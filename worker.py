"""
SwarmAI Worker Node v0.6.0
===========================
Runs on every machine (home PC, cloud server, laptop).

New in v0.6.0 — Auto ngrok tunnel:
    - If SWARM_COORDINATOR is set but SWARM_PUBLIC_URL is NOT set,
      worker automatically starts an ngrok tunnel on port 8100.
    - Gets the public URL from ngrok and registers it with coordinator.
    - No manual setup needed — just set SWARM_NGROK_TOKEN env var.
    - Solves the private IP problem permanently in pure Python.

Environment variables:
    SWARM_COORDINATOR=http://YOUR_VPS_IP:8200   ← coordinator address
    SWARM_API_KEY=your-secret-key               ← must match coordinator
    SWARM_PUBLIC_URL=http://YOUR_PUBLIC_IP:8100 ← optional: set manually
    SWARM_NGROK_TOKEN=your-ngrok-token          ← optional: for auto tunnel

How it works:
    1. Worker starts on port 8100
    2. ngrok opens a tunnel → gives public URL e.g. https://abc.ngrok-free.app
    3. Worker registers that public URL with coordinator
    4. EC2 coordinator can now reach your PC through ngrok tunnel
    5. Heartbeat keeps registration alive

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

app = FastAPI(title="SwarmAI Worker", version="0.6.0")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TIMEOUT = 300
WORKER_PORT = 8100

# ─── Internet Swarm Config ────────────────────────────────────────
COORDINATOR_URL = os.environ.get("SWARM_COORDINATOR", "")
API_KEY = os.environ.get("SWARM_API_KEY", "swarm-dev-key-change-in-production")
PUBLIC_URL = os.environ.get("SWARM_PUBLIC_URL", "")       # manual override
NGROK_TOKEN = os.environ.get("SWARM_NGROK_TOKEN", "")     # ngrok auth token
HEARTBEAT_INTERVAL = 10

# ─── State ───────────────────────────────────────────────────────
_ollama_semaphore = asyncio.Semaphore(1)
_queue_depth: int = 0
_requests_served: int = 0
_public_url: str = ""   # final resolved public URL (manual or ngrok)


# ─── ngrok Auto Tunnel ────────────────────────────────────────────

def _start_ngrok_tunnel() -> str:
    """
    Start ngrok tunnel on WORKER_PORT.
    Returns the public HTTPS URL e.g. https://abc123.ngrok-free.app
    """
    try:
        from pyngrok import ngrok, conf

        # Set auth token if provided
        if NGROK_TOKEN:
            conf.get_default().auth_token = NGROK_TOKEN

        # Open tunnel
        tunnel = ngrok.connect(WORKER_PORT, "http")
        public_url = tunnel.public_url

        # ngrok gives http:// — upgrade to https:// if available
        if public_url.startswith("http://"):
            public_url = public_url.replace("http://", "https://", 1)

        print(f"[+] ngrok tunnel opened: {public_url} → localhost:{WORKER_PORT}")
        return public_url

    except ImportError:
        print("[!] pyngrok not installed. Run: pip install pyngrok")
        print("[!] Falling back to local mode.")
        return ""
    except Exception as e:
        print(f"[!] ngrok failed: {e}")
        print("[!] Set SWARM_NGROK_TOKEN env var with your ngrok auth token.")
        print("[!] Get token free at: https://ngrok.com")
        return ""


# ─── Startup ─────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    global _public_url

    if not COORDINATOR_URL:
        print("[i] No coordinator configured — running in local mode.")
        return

    # Resolve public URL
    if PUBLIC_URL:
        # Manual override — use as-is
        _public_url = PUBLIC_URL
        print(f"[i] Using manual public URL: {_public_url}")
    else:
        # Auto ngrok tunnel
        print("[i] No SWARM_PUBLIC_URL set — starting ngrok tunnel automatically...")
        loop = asyncio.get_event_loop()
        _public_url = await loop.run_in_executor(None, _start_ngrok_tunnel)

    if _public_url:
        await _register_with_coordinator(_public_url)
        asyncio.create_task(_heartbeat_loop(_public_url))
    else:
        print("[!] Could not get public URL — node will NOT register with coordinator.")
        print("[!] Options:")
        print("[!]   1. Set SWARM_NGROK_TOKEN=your-token (get free at ngrok.com)")
        print("[!]   2. Set SWARM_PUBLIC_URL=http://YOUR_PUBLIC_IP:8100 manually")


async def _register_with_coordinator(public_url: str):
    hardware = {
        "os": platform.system(),
        "python": platform.python_version(),
        "node_version": "0.6.0",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{COORDINATOR_URL}/register",
                json={"url": public_url, "hardware": hardware},
                headers={"X-Api-Key": API_KEY},
            )
            if resp.status_code == 200:
                print(f"[+] Registered with coordinator: {COORDINATOR_URL}")
                print(f"[+] Public URL: {public_url}")
            else:
                print(f"[!] Registration failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[!] Could not reach coordinator: {e}")


async def _heartbeat_loop(public_url: str):
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{COORDINATOR_URL}/heartbeat",
                    json={
                        "url": public_url,
                        "queue_depth": _queue_depth,
                        "requests_served": _requests_served,
                    },
                    headers={"X-Api-Key": API_KEY},
                )
        except Exception:
            pass


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "alive",
        "queue_depth": _queue_depth,
        "requests_served": _requests_served,
        "version": "0.6.0",
        "coordinator": COORDINATOR_URL or "local mode",
        "public_url": _public_url or PUBLIC_URL or "not set",
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
