"""
SwarmAI Worker Node v0.5.0
===========================
Runs on every machine (home PC, cloud server, laptop).

New in v0.5.0 — Internet Swarm:
    - AUTO REGISTER: on startup, if SWARM_COORDINATOR is set,
      posts to /register so coordinator knows this node exists.
    - HEARTBEAT: background task pings coordinator every 10s
      so coordinator knows this node is still alive.
    - PUBLIC URL: node must know its own public URL to register.
      Set via env var: SWARM_PUBLIC_URL=http://YOUR_PUBLIC_IP:8100

Environment variables:
    SWARM_COORDINATOR=http://YOUR_VPS_IP:8200   ← coordinator address
    SWARM_API_KEY=your-secret-key               ← must match coordinator
    SWARM_PUBLIC_URL=http://YOUR_PUBLIC_IP:8100 ← this node's public URL

Local usage (no coordinator):
    Just run as before — env vars are optional.
    python swarm.py start
"""

import asyncio
import os
import time
import json
import platform

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="SwarmAI Worker", version="0.5.0")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TIMEOUT = 300

# ─── Internet Swarm Config (optional) ────────────────────────────
COORDINATOR_URL = os.environ.get("SWARM_COORDINATOR", "")    # e.g. http://1.2.3.4:8200
API_KEY = os.environ.get("SWARM_API_KEY", "swarm-dev-key-change-in-production")
PUBLIC_URL = os.environ.get("SWARM_PUBLIC_URL", "")          # e.g. http://MY_IP:8100
HEARTBEAT_INTERVAL = 10   # seconds between heartbeat pings

# ─── State ───────────────────────────────────────────────────────
_ollama_semaphore = asyncio.Semaphore(1)
_queue_depth: int = 0
_requests_served: int = 0


# ─── Startup: Register + Heartbeat ───────────────────────────────

@app.on_event("startup")
async def on_startup():
    """On startup: register with coordinator if configured, then start heartbeat."""
    if COORDINATOR_URL and PUBLIC_URL:
        await _register_with_coordinator()
        asyncio.create_task(_heartbeat_loop())
    elif COORDINATOR_URL and not PUBLIC_URL:
        print("[!] SWARM_COORDINATOR set but SWARM_PUBLIC_URL missing.")
        print("[!] Set SWARM_PUBLIC_URL=http://YOUR_PUBLIC_IP:8100")
    else:
        print("[i] No coordinator configured — running in local mode.")


async def _register_with_coordinator():
    """POST /register to coordinator so it knows this node exists."""
    hardware = {
        "os": platform.system(),
        "python": platform.python_version(),
        "node_version": "0.5.0",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{COORDINATOR_URL}/register",
                json={"url": PUBLIC_URL, "hardware": hardware},
                headers={"X-Api-Key": API_KEY},
            )
            if resp.status_code == 200:
                print(f"[+] Registered with coordinator: {COORDINATOR_URL}")
                print(f"[+] This node's public URL: {PUBLIC_URL}")
            else:
                print(f"[!] Registration failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[!] Could not reach coordinator: {e}")


async def _heartbeat_loop():
    """Ping coordinator every 10s so it knows we're alive."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{COORDINATOR_URL}/heartbeat",
                    json={
                        "url": PUBLIC_URL,
                        "queue_depth": _queue_depth,
                        "requests_served": _requests_served,
                    },
                    headers={"X-Api-Key": API_KEY},
                )
        except Exception:
            pass  # silent — don't crash the worker if coordinator is down


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "alive",
        "queue_depth": _queue_depth,
        "requests_served": _requests_served,
        "version": "0.5.0",
        "coordinator": COORDINATOR_URL or "local mode",
        "public_url": PUBLIC_URL or "not set",
    }


@app.get("/test")
async def test_ollama():
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            full_response = ""
            async with client.stream(
                "POST", OLLAMA_URL,
                json={"model": "phi3:mini", "prompt": "Say OK", "stream": True, "num_predict": 5},
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            full_response += chunk.get("response", "")
                            if chunk.get("done"):
                                break
                        except Exception:
                            pass
        return {"status": "ok", "ollama_response": full_response.strip()}
    except httpx.ConnectError:
        return {"status": "error", "detail": "Ollama not running. Run: ollama serve"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.post("/generate")
async def generate(request: dict):
    global _queue_depth, _requests_served

    prompt = request.get("prompt", "")
    model = request.get("model", "phi3:mini")
    num_predict = request.get("num_predict", 500)
    temperature = request.get("temperature", 0.3)

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    _queue_depth += 1
    queue_entry_time = time.time()

    try:
        async with _ollama_semaphore:
            wait_time = time.time() - queue_entry_time
            gen_start = time.time()
            full_response = ""

            try:
                async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                    async with client.stream(
                        "POST", OLLAMA_URL,
                        json={
                            "model": model,
                            "prompt": prompt,
                            "stream": True,
                            "keep_alive": "10m",
                            "options": {
                                "temperature": temperature,
                                "num_predict": num_predict,
                            },
                        },
                    ) as resp:
                        if resp.status_code != 200:
                            raise HTTPException(status_code=502, detail=f"Ollama HTTP {resp.status_code}")
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                chunk = json.loads(line)
                                full_response += chunk.get("response", "")
                                if chunk.get("done"):
                                    break
                            except json.JSONDecodeError:
                                pass

            except httpx.ConnectError:
                raise HTTPException(status_code=503, detail="Ollama not running. Run: ollama serve")
            except httpx.TimeoutException:
                raise HTTPException(status_code=504, detail=f"Ollama timed out after {OLLAMA_TIMEOUT}s")

            gen_time = time.time() - gen_start
            _requests_served += 1

            return JSONResponse(
                content={
                    "response": full_response,
                    "model": model,
                    "wait_time": round(wait_time, 2),
                    "gen_time": round(gen_time, 2),
                },
                headers={"X-Queue-Depth": str(max(0, _queue_depth - 1))},
            )
    finally:
        _queue_depth -= 1
