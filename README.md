# 🐝 SwarmAI

**Open-source distributed AI compute runtime — run LLMs across unlimited machines on your local network or over the internet.**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Ollama](https://img.shields.io/badge/Runtime-Ollama-black.svg)](https://ollama.com)
[![Version](https://img.shields.io/badge/Version-0.6.0-orange.svg)]()

---

> **No API keys. No cloud costs. Full privacy. Your machines, your models, your swarm.**

---

## What is SwarmAI?

SwarmAI turns any group of computers into a distributed AI inference cluster. Each machine runs a local LLM via Ollama. SwarmAI splits tasks intelligently across all of them — in parallel.

**Instead of paying $$ for ChatGPT/Claude API — use your own PCs for free.**

```
You type one command
        ↓
SwarmAI splits into agents
        ↓
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│  PC 1   │  │  PC 2   │  │  PC 3   │  │  PC N   │
│ Agent 1 │  │ Agent 2 │  │ Agent 3 │  │ Agent N │
│ Ollama  │  │ Ollama  │  │ Ollama  │  │ Ollama  │
└─────────┘  └─────────┘  └─────────┘  └─────────┘
        ↓
Results merged → saved to result.md
```

---

## Key Features

- 🔀 **Distributed batch inference** — split prompts across unlimited machines
- 🤖 **Agent orchestration** — decompose complex tasks into parallel agents
- 🌐 **Internet swarm** — connect nodes across different networks via coordinator
- 🔒 **Secure** — API key auth between nodes and coordinator
- 💓 **Heartbeat system** — dead nodes removed automatically
- ⚡ **Smart routing** — least-busy node gets the next task
- 🔁 **Retry logic** — failed agents retry automatically
- 🚇 **Auto ngrok tunnel** — join from any network, no port forwarding needed
- 🚀 **One command join** — any PC joins swarm with single command
- ♾️ **Unlimited nodes** — add as many machines as you want

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│              Your PC (sends commands)            │
│         python swarm.py orchestrate "task"       │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│         coordinator.py on AWS EC2               │
│         (central brain — free tier)             │
│  node registry │ heartbeat │ least-busy routing │
└──────┬──────────────────────────┬───────────────┘
       │                          │
┌──────▼──────┐            ┌──────▼──────┐
│  worker.py  │            │  worker.py  │  ← any PC anywhere
│  + ngrok    │            │  + ngrok    │  ← auto public URL
│  Ollama LLM │            │  Ollama LLM │  ← runs locally
└─────────────┘            └─────────────┘
```

---

## Quick Start

### Option A — Join existing swarm (easiest)

Any computer can join with ONE command:

```bash
# 1. Install Ollama from https://ollama.com then:
ollama serve
ollama pull phi3:mini

# 2. Clone repo
git clone https://github.com/channupraveen/Ai-swarm.git
cd Ai-swarm

# 3. Join swarm (get free ngrok token at ngrok.com)
python join_swarm.py --key YOUR_NGROK_TOKEN
```

That's it. The script automatically:
- Installs all Python dependencies
- Checks Ollama is running
- Opens ngrok tunnel → gets public URL
- Registers with coordinator
- Starts accepting AI tasks

---

### Option B — Full local swarm setup

**Step 1 — Clone and install:**
```bash
git clone https://github.com/channupraveen/Ai-swarm.git
cd Ai-swarm
pip install -r requirements.txt
```

**Step 2 — Pull model on each machine:**
```bash
ollama pull phi3:mini
```

**Step 3 — Start worker on each machine:**
```bash
python swarm.py start
```

**Step 4 — Add nodes:**
```bash
python swarm.py nodes --add http://192.168.1.10:8100
python swarm.py nodes --add http://192.168.1.11:8100
```

**Step 5 — Run tasks:**
```bash
python swarm.py orchestrate "Build a REST API for a blog system" --agents 4 --output result.md
```

---

## Internet Swarm Setup

### Deploy coordinator on VPS (one time):

```bash
# On AWS EC2 / DigitalOcean (Ubuntu)
git clone https://github.com/channupraveen/Ai-swarm.git
cd Ai-swarm
pip install -r requirements.txt --break-system-packages
export SWARM_API_KEY=your-secret-key
nohup uvicorn coordinator:app --host 0.0.0.0 --port 8200 > coordinator.log 2>&1 &
```

### Connect any PC from anywhere:

```bash
# Windows PowerShell
$env:SWARM_COORDINATOR="http://YOUR_EC2_IP:8200"
$env:SWARM_API_KEY="your-secret-key"
$env:SWARM_NGROK_TOKEN="your-ngrok-token"
python swarm.py start

# Linux/Mac
export SWARM_COORDINATOR="http://YOUR_EC2_IP:8200"
export SWARM_API_KEY="your-secret-key"
export SWARM_NGROK_TOKEN="your-ngrok-token"
python swarm.py start
```

Node auto-registers via ngrok — works from any network, anywhere.

---

## CLI Reference

### Local Commands

| Command | Description |
|---------|-------------|
| `python swarm.py start` | Start worker node |
| `python swarm.py status` | Check all nodes + queue depth |
| `python swarm.py run "prompt"` | Send single prompt |
| `python swarm.py run --file prompts.txt` | Distribute prompts from file |
| `python swarm.py benchmark` | Compare 1 node vs full swarm |
| `python swarm.py nodes --list` | Show configured nodes |
| `python swarm.py nodes --add http://IP:8100` | Add a node |
| `python swarm.py orchestrate "task"` | Multi-agent task |
| `python swarm.py orchestrate "task" --agents 4 --output result.md` | Full orchestration |

### Internet Swarm Commands

| Command | Description |
|---------|-------------|
| `python swarm.py coordinator-start` | Start coordinator (on VPS) |
| `python swarm.py coordinator-status URL --key KEY` | Check internet swarm |
| `python swarm.py coordinator-run "prompt" --coordinator URL --key KEY` | Route via internet |

### One Command Join

| Command | Description |
|---------|-------------|
| `python join_swarm.py --key NGROK_TOKEN` | Join swarm from any PC |
| `python join_swarm.py --key TOKEN --model mistral` | Join with different model |
| `python join_swarm.py --key TOKEN --port 8101` | Join on custom port |

### Diagnostic Tool

```bash
python diagnose.py
```

---

## Agent Orchestration

SwarmAI decomposes complex tasks into parallel agents running on different nodes.

### Supported task types

| Type | Keywords | Agents |
|------|----------|--------|
| `rest_api` | "api", "endpoints", "backend" | DB Architect, API Dev, Auth Engineer, Test Engineer, Docs Writer |
| `fullstack` | "fullstack", "web app" | Backend Dev, Frontend Dev, DB Engineer, DevOps, Test Engineer |
| `code_review` | "review", "audit", "security" | Security Auditor, Performance Analyst, Code Reviewer, Test Analyst |
| `documentation` | "docs", "readme", "tutorial" | Technical Writer, Tutorial Creator, API Reference Writer |
| `general` | anything else | Research Analyst, Solution Architect, Implementation Specialist, Reviewer |

### Example output

```
🎯 Task Plan — 4 agents
├── Database Architect  → node 1  (192.168.86.4)
├── API Developer       → node 2  (192.168.86.6)
├── Auth Engineer       → node 1  (192.168.86.4)
└── Test Engineer       → node 2  (192.168.86.6)

  Database Architect: ✅ 38.2s
  API Developer:      ✅ 41.7s
  Auth Engineer:      ✅ 35.1s
  Test Engineer:      ✅ 39.4s

📊 Agents: 4/4 | Nodes: 2 | Total: 79.3s
✓ Saved to: result.md
```

---

## How the Private IP Problem Was Solved

Home PCs have private IPs (`192.168.x.x`) — the internet can't reach them directly.

**Solution: Auto ngrok tunnel built into worker.py**

```
WITHOUT ngrok:
EC2 → 192.168.86.4:8100 ❌ unreachable

WITH ngrok (automatic):
EC2 → https://abc.ngrok-free.app ✅ public URL
              ↓
         your PC:8100 (Ollama)
```

Just set `SWARM_NGROK_TOKEN` — worker auto-creates the tunnel on startup. No manual setup, no port forwarding, no static IP needed.

---

## Project Structure

```
Ai-swarm/
├── swarm.py          ← CLI (all commands)
├── worker.py         ← FastAPI worker node + ngrok auto-tunnel
├── orchestrator.py   ← Agent task decomposition + smart routing
├── coordinator.py    ← Internet coordinator (runs on VPS/EC2)
├── join_swarm.py     ← One command: join swarm from any PC
├── diagnose.py       ← Debug tool
├── setup_vps.sh      ← VPS setup script
├── prompts.txt       ← Sample prompts
└── requirements.txt
```

---

## Environment Variables

| Variable | Used by | Description |
|----------|---------|-------------|
| `SWARM_COORDINATOR` | worker | Coordinator URL |
| `SWARM_API_KEY` | worker + coordinator | Shared secret |
| `SWARM_PUBLIC_URL` | worker | Manual public URL override |
| `SWARM_NGROK_TOKEN` | worker | ngrok token for auto tunnel |

---

## Supported Models

| Model | Size | Speed |
|-------|------|-------|
| `phi3:mini` | 2.3GB | Fast on CPU |
| `tinyllama` | 637MB | Fastest |
| `mistral` | 4.1GB | Better quality |
| `llama3.2` | 2GB | Well balanced |
| `deepseek-coder` | 776MB | Code tasks |

---

## Benchmark Results

| Setup | Time | Speedup |
|-------|------|---------|
| 1 node, 4 prompts | 113.3s | 1.0x |
| 2 nodes, 4 prompts | 68.3s | 1.66x |

Scales linearly — more nodes = faster.

---

## Roadmap

- [x] Phase 1 — Local swarm ✅
- [x] Phase 2 — Agent orchestration ✅
- [x] Phase 3 — Smart least-busy routing ✅
- [x] Phase 4 — Internet coordinator on EC2 ✅
- [x] Phase 5 — Heartbeat + auto cleanup ✅
- [x] Phase 6 — Auto ngrok tunnel ✅
- [x] Phase 7 — One command join ✅
- [ ] Phase 8 — Desktop UI dashboard
- [ ] Phase 9 — AI coding assistant on swarm
- [ ] Phase 10 — Model-aware routing

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| LLM Runtime | Ollama |
| API Framework | FastAPI |
| HTTP Client | httpx (async) |
| CLI | Typer |
| Terminal UI | Rich |
| Tunnel | pyngrok |
| Concurrency | asyncio + Semaphore |

---

## Contributing

Contributions welcome! Open an issue first to discuss changes.

---

## License

MIT — see [LICENSE](LICENSE)

---

**Built with ❤️ for the open-source AI community.**
