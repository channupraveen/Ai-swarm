"""
SwarmAI Diagnostic Tool
========================
Run this BEFORE orchestrate to check exactly what's wrong.

Usage:
    python diagnose.py

It will test:
1. Is worker reachable?
2. Is Ollama running on each node?
3. Can Ollama actually generate a response?
4. How long does 1 generation take?
"""

import asyncio
import time
import json
import httpx

NODES = [
    "http://192.168.86.4:8100",
    "http://192.168.86.6:8100",
]

TEST_PROMPT = "Reply with just the word OK and nothing else."


async def test_node(node: str):
    print(f"\n{'='*55}")
    print(f"  TESTING NODE: {node}")
    print(f"{'='*55}")

    async with httpx.AsyncClient(timeout=30) as client:

        # ── Step 1: Worker health ─────────────────────────────────
        print(f"\n[1] Pinging worker /health ...")
        try:
            r = await client.get(f"{node}/health", timeout=5)
            data = r.json()
            print(f"    ✅ Worker ONLINE — queue={data.get('queue_depth',0)}, served={data.get('requests_served',0)}, version={data.get('version','?')}")
        except Exception as e:
            print(f"    ❌ Worker OFFLINE — {e}")
            print(f"    → Run: python swarm.py start   on that machine")
            return

        # ── Step 2: Ollama test via /test endpoint ────────────────
        print(f"\n[2] Testing Ollama via /test ...")
        try:
            r = await client.get(f"{node}/test", timeout=90)
            data = r.json()
            if data.get("status") == "ok":
                print(f"    ✅ Ollama responding — reply: '{data.get('ollama_response','')}'")
            else:
                print(f"    ❌ Ollama error — {data.get('detail','unknown')}")
                print(f"    → On that machine run: ollama serve")
                return
        except httpx.TimeoutException:
            print(f"    ❌ /test TIMED OUT after 90s")
            print(f"    → Ollama is too slow or not running. Try: ollama serve")
            return
        except Exception as e:
            print(f"    ❌ /test failed — {e}")
            return

        # ── Step 3: Full generate timing ─────────────────────────
        print(f"\n[3] Full /generate timing test ...")
        print(f"    Prompt: '{TEST_PROMPT}'")
        print(f"    Sending... (may take 30-120s on CPU)")

        start = time.time()
        try:
            r = await client.post(
                f"{node}/generate",
                json={"prompt": TEST_PROMPT, "model": "phi3:mini"},
                timeout=300,
            )
            elapsed = time.time() - start
            data = r.json()

            if r.status_code == 200:
                print(f"    ✅ SUCCESS in {elapsed:.1f}s")
                print(f"    Response: '{data.get('response','').strip()[:80]}'")
                print(f"    Wait time: {data.get('wait_time',0):.1f}s | Gen time: {data.get('gen_time',0):.1f}s")

                if elapsed > 120:
                    print(f"\n    ⚠️  WARNING: {elapsed:.0f}s is very slow.")
                    print(f"    → Consider switching to tinyllama:")
                    print(f"       ollama pull tinyllama   (on that machine)")
                    print(f"       Then edit orchestrator.py: DEFAULT_MODEL = 'tinyllama'")
                elif elapsed > 60:
                    print(f"\n    ℹ️  {elapsed:.0f}s per agent is normal on CPU.")
                    print(f"    → 2 agents on 2 nodes = ~{elapsed:.0f}s total (parallel)")
                else:
                    print(f"\n    🚀 Fast! {elapsed:.0f}s per agent.")
            else:
                print(f"    ❌ HTTP {r.status_code} — {data}")

        except httpx.TimeoutException:
            elapsed = time.time() - start
            print(f"    ❌ TIMED OUT after {elapsed:.0f}s")
            print(f"    → This is the 504 bug source.")
            print(f"    → Make sure you restarted worker.py after the v0.3 update")
            print(f"    → Or switch to tinyllama (faster model)")
        except Exception as e:
            print(f"    ❌ Error: {e}")


async def main():
    print("\n🔍 SwarmAI Diagnostic Tool v0.3")
    print("Testing all nodes...\n")

    for node in NODES:
        await test_node(node)

    print(f"\n{'='*55}")
    print("  DIAGNOSIS COMPLETE")
    print(f"{'='*55}")
    print("\nIf all nodes show ✅ — run your orchestrate command.")
    print("If any node shows ❌ — fix that node first.\n")


if __name__ == "__main__":
    asyncio.run(main())
