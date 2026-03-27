# 🐝 SwarmAI

**Open-source distributed AI compute runtime — run LLMs across unlimited machines on your local network or over the internet.**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Ollama](https://img.shields.io/badge/Runtime-Ollama-black.svg)](https://ollama.com)
[![Version](https://img.shields.io/badge/Version-0.5.0-orange.svg)]()

---

> **No API keys. No cloud costs. Full privacy. Your machines, your models, your swarm.**

---

## What is SwarmAI?

SwarmAI turns any group of computers into a distributed AI inference cluster. Each machine runs a local LLM via Ollama. SwarmAI splits tasks intelligently across all of them — in parallel.

**Instead of one computer struggling with AI tasks, your entire network collaborates.**

```
You type one command
        ↓
SwarmAI splits into agents
        ↓
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│  Node 1 │  │  Node 2 │  │  Node 3 │  │  Node N │
│ Agent 1 │  │ Agent 2 │  │ Agent 3 │  │ Agent N │
│ phi3mini│  │ phi3mini│  │ phi3mini│  │ phi3mini│
└─────────┘  └─────────┘  └─────────┘  └─────────┘
        ↓
Results merged → saved to result.md
```

---

## Key Features

- 🔀 **Distributed batch inference** — split prompts across unlimited machines
- 🤖 **Agent orchestration** — decompose complex tasks (API, fullstack, docs) into parallel agents
- 🌐 **Internet swarm** — connect nodes across different networks via coordinator server
- 🔒 **Secure** — API key auth between nodes and coordinator
- 💓 **Heartbeat system** — dead nodes removed automatically
- ⚡ **Smart routing** — least-busy node gets the next task
- 🔁 **Retry logic** — failed agents retry automatically
- 📊 **Benchmark mode** — measure real speedup with your setup
- 🩺 **Diagnostics** — built-in tool to debug node issues
- ♾️ **Unlimited nodes** — add as many machines as you want

---

## Architecture

### Local Swarm

```
┌──────────────────────────────────────┐
│           swarm.py (CLI)             │
│  start│status│run│benchmark│orchestrate│
└──────────────┬───────────────────────┘
               │
┌──────────────▼───────────────────────┐
│          orchestrator.py             │
│  Task decomposition                  │
│  NodeLoadTracker (least-busy router) │
│  Retry logic + timeout per agent     │
└──────┬───────────────────┬───────────┘
       │                   │
┌──────▼──────┐     ┌──────▼──────┐
│  worker.py  │     │  worker.py  │  ← runs on each machine
│  FastAPI    │     │  FastAPI    │
│  Semaphore  │     │  Semaphore  │  ← 1 Ollama call at a time
│  stream=True│     │  stream=True│  ← no TCP timeout
│  Ollama LLM │     │  Ollama LLM │
└─────────────┘     └─────────────┘
```

### Internet Swarm

```
[Home PC]    ──register+heartbeat──►  [coordinator.py on VPS :8200]
[Office PC]  ──register+heartbeat──►  [coordinator.py on VPS :8200]
[Cloud VM]   ──register+heartbeat──►  [coordinator.py on VPS :8200]
                                               │
                                    You orchestrate from anywhere
                                    Tasks routed to least-busy node
```

---

## Quick Start — Local Swarm

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed on each machine

### 1. Clone and install

```bash
git clone https://github.com/channupraveen/Ai-swarm.git
cd Ai-swarm
pip install -r requirements.txt
```

### 2. Pull a model on each machine

```bash
ollama pull phi3:mini
```

### 3. Start a worker on each machine

```bash
python swarm.py start
```

Run this on **every machine** you want in the swarm.

### 4. Add nodes to your config

```bash
python swarm.py nodes --add http://192.168.1.10:8100
python swarm.py nodes --add http://192.168.1.11:8100
# Add as many as you want — unlimited
```

### 5. Check status

```bash
python swarm.py status
```

### 6. Run prompts

```bash
# Single prompt
python swarm.py run "What is Python?"

# Multiple prompts from file
python swarm.py run --file prompts.txt
```

### 7. Orchestrate a complex task

```bash
python swarm.py orchestrate "Build a REST API for a blog system" --agents 4 --output result.md
```

---

## Quick Start — Internet Swarm

### Step 1 — Deploy coordinator on a VPS

```bash
# On your VPS (AWS EC2 / DigitalOcean / any Ubuntu server)
git clone https://github.com/channupraveen/Ai-swarm.git
cd Ai-swarm
pip install -r requirements.txt

export SWARM_API_KEY=your-secret-key-here
python swarm.py coordinator-start
# Coordinator now running at http://YOUR_VPS_IP:8200
```

Or use the setup script:
```bash
bash setup_vps.sh
```

### Step 2 — Start nodes anywhere in the world

```bash
# On each machine (home, office, cloud — anywhere)
set SWARM_COORDINATOR=http://YOUR_VPS_IP:8200
set SWARM_API_KEY=your-secret-key-here
set SWARM_PUBLIC_URL=http://THIS_MACHINE_PUBLIC_IP:8100

python swarm.py start
# Node auto-registers with coordinator on startup
# Heartbeat keeps it alive in the registry
```

### Step 3 — Check internet swarm status

```bash
python swarm.py coordinator-status http://YOUR_VPS_IP:8200 --key your-secret-key-here
```

### Step 4 — Send tasks via coordinator

```bash
python swarm.py coordinator-run "Explain machine learning" \
  --coordinator http://YOUR_VPS_IP:8200 \
  --key your-secret-key-here
```

---

## CLI Reference

### Local Commands

| Command | Description |
|---------|-------------|
| `python swarm.py start` | Start a worker node on this machine |
| `python swarm.py start --port 8200` | Start on custom port |
| `python swarm.py status` | Check all nodes — online/offline + queue depth |
| `python swarm.py run "prompt"` | Send a single prompt to the swarm |
| `python swarm.py run --file prompts.txt` | Distribute prompts from a file |
| `python swarm.py benchmark` | Compare 1 node vs full swarm speed |
| `python swarm.py benchmark --count 8` | Benchmark with 8 prompts |
| `python swarm.py nodes --list` | Show configured nodes |
| `python swarm.py nodes --add http://IP:8100` | Add a node |
| `python swarm.py nodes --remove http://IP:8100` | Remove a node |
| `python swarm.py orchestrate "task"` | Run multi-agent task orchestration |
| `python swarm.py orchestrate "task" --agents 4` | Limit to 4 agents |
| `python swarm.py orchestrate "task" --output out.md` | Save result to file |

### Internet Swarm Commands

| Command | Description |
|---------|-------------|
| `python swarm.py coordinator-start` | Start coordinator server (run on VPS) |
| `python swarm.py coordinator-status URL --key KEY` | Check internet swarm + list nodes |
| `python swarm.py coordinator-run "prompt" --coordinator URL --key KEY` | Route prompt via coordinator |

### Diagnostic Tool

```bash
python diagnose.py
```
Tests every configured node: worker health → Ollama status → full generation timing.

---

## Agent Orchestration

SwarmAI can decompose complex tasks into parallel agents. Each agent runs on a different node simultaneously.

### Supported task types

| Type | Detected by | Agents created |
|------|-------------|----------------|
| `rest_api` | "api", "endpoints", "backend" | DB Architect, API Dev, Auth Engineer, Test Engineer, Docs Writer |
| `fullstack` | "fullstack", "web app", "frontend" | Backend Dev, Frontend Dev, DB Engineer, DevOps, Test Engineer |
| `code_review` | "review", "audit", "security" | Security Auditor, Performance Analyst, Code Reviewer, Test Analyst |
| `documentation` | "docs", "readme", "tutorial" | Technical Writer, Tutorial Creator, API Reference Writer |
| `general` | anything else | Research Analyst, Solution Architect, Implementation Specialist, Reviewer |

### Example

```bash
python swarm.py orchestrate "Build a REST API for a blog system" --agents 4 --output result.md
```

```
🎯 Task Plan — 4 agents
├── Database Architect → Design the database schema       (node 1)
├── API Developer      → Create the API endpoints         (node 2)
├── Auth Engineer      → Implement authentication         (node 1)
└── Test Engineer      → Write comprehensive test cases   (node 2)

⏳ Executing agents...
  Database Architect: ✅ 38.2s
  API Developer:      ✅ 41.7s
  Auth Engineer:      ✅ 35.1s
  Test Engineer:      ✅ 39.4s

📊 Agents: 4/4 completed | Nodes: 2 | Total: 79.3s
✓ Saved to: result.md
```

---

## How the 504 Bug Was Fixed

Early versions had a critical bug: running 4 agents on 1 node caused 3 of 4 to fail with `504 Gateway Timeout`.

**Root cause:** `stream=False` holds one silent HTTP connection open for 60-90s during generation. Routers kill idle connections → 504.

**Fix applied in v0.3.0:**
- `stream=True` in worker.py — tokens flow continuously, TCP stays alive
- `asyncio.Semaphore(1)` — only 1 Ollama call at a time per node, extras wait in Python memory
- `NodeLoadTracker` — routes new tasks to least-busy node, not blindly round-robin
- `num_predict=500` — caps output tokens so agents finish in 30-60s, not 10 minutes

---

## Node Configuration

Nodes are stored in `swarm_nodes.json`:

```json
{
  "nodes": [
    "http://192.168.1.10:8100",
    "http://192.168.1.11:8100",
    "http://192.168.1.12:8100"
  ]
}
```

**No limit on number of nodes.** Add as many machines as you want. The scheduler automatically uses all online nodes and skips offline ones.

---

## Internet Swarm — How It Works

```
1. Coordinator runs on VPS — public IP, port 8200
2. Each node starts with env vars set → auto-registers via POST /register
3. Node sends heartbeat every 10s via POST /heartbeat
4. Coordinator removes nodes silent for >30s
5. You call /route → coordinator picks least-busy alive node → forwards prompt
```

### Coordinator API endpoints

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /` | None | Public status — nodes online count |
| `POST /register` | API key | Node registers itself |
| `POST /heartbeat` | API key | Node signals it's alive |
| `GET /nodes` | API key | List all nodes with status |
| `GET /nodes/alive` | API key | List only alive nodes |
| `POST /route` | API key | Route a prompt to best node |

---

## Environment Variables

| Variable | Used by | Description |
|----------|---------|-------------|
| `SWARM_API_KEY` | worker + coordinator | Shared secret for auth |
| `SWARM_COORDINATOR` | worker | Coordinator URL to register with |
| `SWARM_PUBLIC_URL` | worker | This node's public URL for coordinator |

---

## Supported Models

Any model supported by Ollama works with SwarmAI:

| Model | Size | Best for |
|-------|------|----------|
| `phi3:mini` | 2.3GB | Fast on CPU, good quality |
| `tinyllama` | 637MB | Fastest, lightweight tasks |
| `mistral` | 4.1GB | Better quality, needs more RAM |
| `llama3.2` | 2GB | Meta's latest, well balanced |
| `deepseek-coder` | 776MB | Code generation tasks |
| `gemma2` | 5.4GB | Google's open model |

---

## Benchmark Results

Real numbers from 2-node local swarm:

| Setup | Prompts | Time | Avg/prompt |
|-------|---------|------|------------|
| 1 node | 4 | 113.3s | 28.3s |
| 2 nodes | 4 | 68.3s | 17.1s |

**⚡ 1.66x speedup with 2 nodes. Scales linearly with more nodes.**

---

## Project Structure

```
Ai-swarm/
├── swarm.py          ← CLI entrypoint (all commands)
├── worker.py         ← FastAPI worker node (runs on each machine)
├── orchestrator.py   ← Agent task decomposition + smart routing
├── coordinator.py    ← Internet swarm coordinator (runs on VPS)
├── diagnose.py       ← Debug tool — tests every node
├── setup_vps.sh      ← One-command VPS setup script
├── prompts.txt       ← Sample prompts for testing
├── requirements.txt  ← Python dependencies
└── README.md
```

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
| Concurrency | asyncio + Semaphore |

---

## Roadmap

- [x] **Phase 1** — Distributed batch inference ✅
- [x] **Phase 2** — Agent task orchestration ✅
- [x] **Phase 3** — Smart least-busy routing ✅
- [x] **Phase 4** — Internet swarm + coordinator ✅
- [x] **Phase 5** — Heartbeat + auto node removal ✅
- [ ] **Phase 6** — Desktop UI dashboard
- [ ] **Phase 7** — AI coding assistant on top of swarm
- [ ] **Phase 8** — Model-aware routing (send code tasks to deepseek-coder, etc.)

---

## Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Acknowledgments

- [Ollama](https://ollama.com) — local LLM runtime
- [FastAPI](https://fastapi.tiangolo.com) — async API framework
- [Typer](https://typer.tiangolo.com) — CLI framework
- [Rich](https://rich.readthedocs.io) — terminal formatting

---

**Built with ❤️ for the open-source AI community.**
