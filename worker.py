"""
SwarmAI Worker Node
===================
Turns any machine into an AI compute node.
Wraps local Ollama LLM behind a FastAPI endpoint.

Run standalone:
    uvicorn worker:app --host 0.0.0.0 --port 8100

Or via CLI:
    python swarm.py start

FIX LOG (v0.3.0):
    - ROOT FIX: Switched Ollama from stream=False to stream=True and manually
      collect chunks. stream=False holds a single HTTP connection open for the
      entire generation duration — on slow hardware this causes Ollama's own
      internal timeout to fire and return 504 back to us. stream=True sends
      incremental chunks so the TCP connection stays alive throughout.
    - Added /test endpoint: hit http://NODE:8100/test to verify Ollama is
      responding correctly before running agents.
    - Semaphore retained — only 1 Ollama call at a time per node.
    - Timeout bumped to 1200s (20 min) for very slow hardware.
    - Added OLLAMA_KEEP_ALIVE param to prevent Ollama from unloading the model
      mid-generation on low-RAM machines.
"""

import asyncio
import time
import json

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(
    title="SwarmAI Worker",
    description="Distributed AI compute worker node",
    version="0.3.0",
)

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TIMEOUT = 1200  # 20 minutes — covers very slow CPU inference

# ─── Concurrency Guard ───────────────────────────────────────────
_ollama_semaphore = asyncio.Semaphore(1)
_queue_depth: int = 0
_requests_served: int = 0


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "alive",
        "queue_depth": _queue_depth,
        "requests_served": _requests_served,
        "ollama_url": OLLAMA_URL,
        "version": "0.3.0",
    }


@app.get("/test")
async def test_ollama():
    """
    Quick test: sends a tiny prompt to Ollama to verify it's working.
    Hit this before running agents: http://192.168.86.4:8100/test
    """
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            full_response = ""
            async with client.stream(
                "POST",
                OLLAMA_URL,
                json={
                    "model": "phi3:mini",
                    "prompt": "Say OK",
                    "stream": True,
                    "keep_alive": "10m",
                },
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
    """
    Generate a response from the local LLM using streaming mode.

    Streaming keeps the TCP connection alive during generation,
    preventing Ollama's internal timeout from firing on slow hardware.

    Body:
        prompt (str): The prompt to send to the model.
        model  (str): Ollama model name. Default: phi3:mini

    Returns:
        response  (str):   LLM generated text.
        model     (str):   Model used.
        wait_time (float): Seconds waiting in queue.
        gen_time  (float): Seconds spent generating.
    """
    global _queue_depth, _requests_served

    prompt = request.get("prompt", "")
    model = request.get("model", "phi3:mini")

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    _queue_depth += 1
    queue_entry_time = time.time()

    try:
        async with _ollama_semaphore:
            wait_time = time.time() - queue_entry_time
            gen_start = time.time()

            full_response = ""
            error_detail = None

            try:
                async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                    # ── KEY FIX: stream=True ──────────────────────────────
                    # Each chunk resets the TCP idle timer.
                    # stream=False holds one silent connection for the full
                    # generation duration — routers/proxies kill it as idle.
                    async with client.stream(
                        "POST",
                        OLLAMA_URL,
                        json={
                            "model": model,
                            "prompt": prompt,
                            "stream": True,
                            "keep_alive": "10m",  # prevent model unload mid-gen
                        },
                    ) as resp:
                        if resp.status_code != 200:
                            error_detail = f"Ollama returned HTTP {resp.status_code}"
                        else:
                            async for line in resp.aiter_lines():
                                if not line.strip():
                                    continue
                                try:
                                    chunk = json.loads(line)
                                    full_response += chunk.get("response", "")
                                    if chunk.get("done"):
                                        break
                                except json.JSONDecodeError:
                                    pass  # skip malformed lines

            except httpx.ConnectError:
                raise HTTPException(
                    status_code=503,
                    detail="Ollama is not running. Start it with: ollama serve",
                )
            except httpx.TimeoutException:
                raise HTTPException(
                    status_code=504,
                    detail=f"Ollama timed out after {OLLAMA_TIMEOUT}s. Try a smaller model.",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Ollama error: {str(e)}")

            if error_detail:
                raise HTTPException(status_code=502, detail=error_detail)

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
