"""
SwarmAI Worker Node
===================
Turns any machine into an AI compute node.
Wraps local Ollama LLM behind a FastAPI endpoint.

Run standalone:
    uvicorn worker:app --host 0.0.0.0 --port 8100

Or via CLI:
    python swarm.py start
"""

import httpx
from fastapi import FastAPI, HTTPException

app = FastAPI(
    title="SwarmAI Worker",
    description="Distributed AI compute worker node",
    version="0.1.0",
)

OLLAMA_URL = "http://localhost:11434/api/generate"


@app.get("/health")
async def health():
    """Health check endpoint — used by scheduler to detect online nodes."""
    return {"status": "alive"}


@app.post("/generate")
async def generate(request: dict):
    """
    Generate a response from the local LLM.

    Body:
        prompt (str): The prompt to send to the model.
        model (str): Ollama model name. Default: phi3:mini

    Returns:
        response (str): LLM generated text.
        model (str): Model used.
    """
    prompt = request.get("prompt", "")
    model = request.get("model", "phi3:mini")

    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                OLLAMA_URL,
                json={"model": model, "prompt": prompt, "stream": False},
            )
            response.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Ollama is not running. Start it with: ollama serve",
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Ollama request timed out.")

    result = response.json()
    return {"response": result.get("response", ""), "model": model}
