"""
SwarmAI — Join Swarm in One Command
=====================================
Run this on ANY computer to join the swarm instantly.

Usage:
    python join_swarm.py --key YOUR_NGROK_TOKEN

That's it. It will:
    1. Install all dependencies automatically
    2. Check Ollama is running
    3. Start ngrok tunnel (gets public URL)
    4. Register with coordinator
    5. Start accepting AI tasks

Requirements:
    - Python 3.10+
    - Ollama installed and running (ollama serve)
"""

import subprocess
import sys
import os
import time

# ─── Config ──────────────────────────────────────────────────────
COORDINATOR_URL = "http://35.173.231.250:8200"
API_KEY_SWARM   = "swarm-secret-key-123"
WORKER_PORT     = 8100

# ─────────────────────────────────────────────────────────────────

def run(cmd: str):
    subprocess.run(cmd, shell=True, check=True)

def check(cmd: str) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Join SwarmAI network")
    parser.add_argument("--key", required=True, help="Your ngrok auth token (get free at ngrok.com)")
    parser.add_argument("--port", default=WORKER_PORT, type=int, help="Worker port (default: 8100)")
    parser.add_argument("--model", default="phi3:mini", help="Ollama model (default: phi3:mini)")
    args = parser.parse_args()

    print("\n🐝 SwarmAI — Joining swarm...\n")

    # ── Step 1: Install dependencies ─────────────────────────────
    print("[1/4] Installing dependencies...")
    run(f"{sys.executable} -m pip install fastapi uvicorn httpx typer rich pyngrok pydantic --quiet")
    print("      ✅ Done\n")

    # ── Step 2: Check Ollama ──────────────────────────────────────
    print("[2/4] Checking Ollama...")
    import httpx
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        if models:
            print(f"      ✅ Ollama running — models: {', '.join(models)}\n")
        else:
            print(f"      ⚠️  Ollama running but no models found.")
            print(f"      Run: ollama pull {args.model}\n")
    except Exception:
        print("      ❌ Ollama not running!")
        print("      Fix: install Ollama from https://ollama.com then run: ollama serve")
        print("      Then run this script again.\n")
        sys.exit(1)

    # ── Step 3: Start ngrok tunnel ────────────────────────────────
    print("[3/4] Starting ngrok tunnel...")
    from pyngrok import ngrok, conf
    conf.get_default().auth_token = args.key
    tunnel = ngrok.connect(args.port, "http")
    public_url = tunnel.public_url.replace("http://", "https://")
    print(f"      ✅ Public URL: {public_url}\n")

    # ── Step 4: Set env vars and start worker ─────────────────────
    print("[4/4] Joining swarm...")
    os.environ["SWARM_COORDINATOR"] = COORDINATOR_URL
    os.environ["SWARM_API_KEY"]     = API_KEY_SWARM
    os.environ["SWARM_PUBLIC_URL"]  = public_url
    os.environ["SWARM_NGROK_TOKEN"] = args.key

    print(f"""
╔══════════════════════════════════════════════════════╗
║           🐝 SwarmAI Node Ready!                     ║
╠══════════════════════════════════════════════════════╣
║  Coordinator : {COORDINATOR_URL}    ║
║  Public URL  : {public_url[:40]}... ║
║  Port        : {args.port}                                   ║
║  Model       : {args.model}                             ║
╚══════════════════════════════════════════════════════╝
    """)

    # Start worker
    import uvicorn
    from worker import app as worker_app
    uvicorn.run(worker_app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
