"""
SwarmAI Coordinator Server
===========================
Runs on a public VPS (AWS EC2 / DigitalOcean / Railway).
This is the central brain for internet-wide swarm coordination.

Responsibilities:
    1. Node registry  — tracks all nodes that register themselves
    2. Heartbeat      — removes nodes that go silent
    3. Task routing   — distributes prompts to alive nodes
    4. Auth           — rejects requests without valid API key

Deploy on VPS:
    pip install -r requirements.txt
    uvicorn coordinator:app --host 0.0.0.0 --port 8200

Environment variables (set on VPS):
    SWARM_API_KEY=your-secret-key-here   ← nodes must send this to register

Architecture:
    [Home PC]  ──register──►  [Coordinator VPS :8200]  ◄──orchestrate──  [You]
    [Cloud PC] ──register──►  [Coordinator VPS :8200]
                               heartbeat removes dead nodes
"""

import asyncio
import os
import time
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ─── Config ──────────────────────────────────────────────────────

# Set this as environment variable on your VPS:
#   export SWARM_API_KEY=mysecretkey123
API_KEY = os.environ.get("SWARM_API_KEY", "swarm-dev-key-change-in-production")

HEARTBEAT_TIMEOUT = 30   # seconds — remove node if silent for this long
COORDINATOR_VERSION = "1.0.0"

app = FastAPI(
    title="SwarmAI Coordinator",
    description="Central coordinator for internet-wide AI swarm",
    version=COORDINATOR_VERSION,
)

# ─── Node Registry ────────────────────────────────────────────────
# In-memory store. Nodes re-register on restart so no DB needed.

class NodeInfo:
    def __init__(self, url: str, hardware: dict):
        self.url = url
        self.hardware = hardware          # cpu, ram, model info from node
        self.registered_at = time.time()
        self.last_heartbeat = time.time()
        self.requests_served = 0
        self.queue_depth = 0

    def is_alive(self) -> bool:
        return (time.time() - self.last_heartbeat) < HEARTBEAT_TIMEOUT

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "hardware": self.hardware,
            "queue_depth": self.queue_depth,
            "requests_served": self.requests_served,
            "last_heartbeat": round(time.time() - self.last_heartbeat, 1),
            "alive": self.is_alive(),
        }


# Global registry: {node_url: NodeInfo}
_registry: dict[str, NodeInfo] = {}


# ─── Auth Helper ─────────────────────────────────────────────────

def require_auth(x_api_key: Optional[str] = Header(None)):
    """Dependency: reject requests without valid API key."""
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Set X-Api-Key header.",
        )


# ─── Request Models ───────────────────────────────────────────────

class RegisterRequest(BaseModel):
    url: str                    # public URL of this node e.g. http://1.2.3.4:8100
    hardware: dict = {}         # optional: {"cpu": "i7", "ram": "16GB", "model": "phi3:mini"}

class HeartbeatRequest(BaseModel):
    url: str
    queue_depth: int = 0
    requests_served: int = 0

class RouteRequest(BaseModel):
    prompt: str
    model: str = "phi3:mini"
    num_predict: int = 500
    temperature: float = 0.3


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/")
async def root():
    """Public endpoint — no auth needed. Shows coordinator status."""
    alive = [n for n in _registry.values() if n.is_alive()]
    return {
        "service": "SwarmAI Coordinator",
        "version": COORDINATOR_VERSION,
        "nodes_online": len(alive),
        "nodes_total": len(_registry),
    }


@app.post("/register")
async def register(req: RegisterRequest, x_api_key: Optional[str] = Header(None)):
    """
    Node calls this on startup to join the swarm.
    Requires valid API key in X-Api-Key header.
    """
    require_auth(x_api_key)

    if not req.url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    _registry[req.url] = NodeInfo(url=req.url, hardware=req.hardware)

    print(f"[+] Node registered: {req.url} | hardware={req.hardware}")
    return {
        "status": "registered",
        "node": req.url,
        "total_nodes": len(_registry),
    }


@app.post("/heartbeat")
async def heartbeat(req: HeartbeatRequest, x_api_key: Optional[str] = Header(None)):
    """
    Node calls this every 10 seconds to stay in the registry.
    Coordinator removes nodes that miss heartbeats for >30s.
    """
    require_auth(x_api_key)

    if req.url not in _registry:
        # Node was evicted (coordinator restart) — auto re-register
        _registry[req.url] = NodeInfo(url=req.url, hardware={})

    node = _registry[req.url]
    node.last_heartbeat = time.time()
    node.queue_depth = req.queue_depth
    node.requests_served = req.requests_served

    return {"status": "ok", "nodes_online": sum(1 for n in _registry.values() if n.is_alive())}


@app.get("/nodes")
async def list_nodes(x_api_key: Optional[str] = Header(None)):
    """List all registered nodes with their status."""
    require_auth(x_api_key)

    # Clean up dead nodes
    dead = [url for url, node in _registry.items() if not node.is_alive()]
    for url in dead:
        print(f"[-] Removing dead node: {url}")
        del _registry[url]

    return {
        "nodes": [n.to_dict() for n in _registry.values()],
        "total": len(_registry),
    }


@app.get("/nodes/alive")
async def alive_nodes(x_api_key: Optional[str] = Header(None)):
    """Return only alive nodes sorted by queue depth (least busy first)."""
    require_auth(x_api_key)

    alive = [n for n in _registry.values() if n.is_alive()]
    alive.sort(key=lambda n: n.queue_depth)
    return {"nodes": [n.url for n in alive], "count": len(alive)}


@app.post("/route")
async def route_task(req: RouteRequest, x_api_key: Optional[str] = Header(None)):
    """
    Route a single prompt to the least-busy alive node.
    Coordinator picks the node — caller just sends the prompt.
    """
    require_auth(x_api_key)

    alive = [n for n in _registry.values() if n.is_alive()]
    if not alive:
        raise HTTPException(status_code=503, detail="No nodes available in swarm.")

    # Pick least busy
    node = min(alive, key=lambda n: n.queue_depth)

    try:
        async with httpx.AsyncClient(timeout=360) as client:
            resp = await client.post(
                f"{node.url}/generate",
                json={
                    "prompt": req.prompt,
                    "model": req.model,
                    "num_predict": req.num_predict,
                    "temperature": req.temperature,
                },
            )
            resp.raise_for_status()
            result = resp.json()
            node.requests_served += 1
            return {
                "response": result.get("response", ""),
                "node_used": node.url,
                "gen_time": result.get("gen_time", 0),
            }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Node {node.url} failed: {str(e)}")


# ─── Background: Heartbeat Cleanup ───────────────────────────────

@app.on_event("startup")
async def start_cleanup_task():
    """Background task: remove dead nodes every 15 seconds."""
    async def cleanup_loop():
        while True:
            await asyncio.sleep(15)
            dead = [url for url, node in _registry.items() if not node.is_alive()]
            for url in dead:
                print(f"[-] Heartbeat timeout — removing: {url}")
                del _registry[url]

    asyncio.create_task(cleanup_loop())


# ─── Entry Point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8200))
    print(f"SwarmAI Coordinator starting on port {port}")
    print(f"API Key: {API_KEY}")
    uvicorn.run(app, host="0.0.0.0", port=port)
