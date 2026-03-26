# 🐝 SwarmAI

**Open-source runtime that distributes local AI workloads across multiple computers.**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Ollama](https://img.shields.io/badge/Runtime-Ollama-black.svg)](https://ollama.com)

---

## What is SwarmAI?

SwarmAI is a distributed compute runtime for local LLM models. It allows multiple computers on a network to share AI workload — turning idle machines into a powerful inference cluster.

**Instead of one computer struggling with AI tasks, your entire network collaborates.**

```
User sends 10 prompts
    ↓
SwarmAI Scheduler splits tasks
    ↓
┌─────────┐  ┌─────────┐  ┌─────────┐
│  Node 1 │  │  Node 2 │  │  Node 3 │
│ 4 tasks │  │ 3 tasks │  │ 3 tasks │
└─────────┘  └─────────┘  └─────────┘
    ↓              ↓            ↓
Results merged → returned to user
```

### Benchmark Results (real)

| Setup | Time | Avg/prompt |
|-------|------|------------|
| 1 node | 113.3s | 28.3s |
| 2 nodes | 68.3s | 17.1s |

**⚡ 1.66x speedup with just 2 nodes.**

---

## Key Features

- **Distributed batch inference** — split prompts across multiple machines
- **CLI tool** — start nodes, run prompts, benchmark with simple commands
- **Node management** — add/remove/monitor nodes dynamically
- **Health checking** — automatically skips offline nodes
- **Benchmark mode** — measure real speedup with your setup
- **Zero config** — works on any local network with Ollama installed

---

## Architecture

```
┌─────────────────────────────────────────┐
│              SwarmAI CLI                │
│  start | status | run | benchmark      │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│            Scheduler                    │
│  Node registry | Round-robin splitter   │
│  Health check  | Result aggregator      │
└──────┬─────────────────┬────────────────┘
       │                 │
┌──────▼──────┐   ┌──────▼──────┐
│  Worker Node │   │  Worker Node │
│  FastAPI     │   │  FastAPI     │
│  Ollama LLM  │   │  Ollama LLM  │
│  (Machine 1) │   │  (Machine 2) │
└─────────────┘   └─────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed on each machine

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/swarm-ai.git
cd swarm-ai
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Pull a model on each machine

```bash
ollama pull phi3:mini
```

### 4. Start a worker node

```bash
python swarm.py start
```

Run this on every machine you want in the swarm.

### 5. Check node status

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

### 7. Benchmark

```bash
python swarm.py benchmark
```

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `python swarm.py start` | Start a worker node on this machine |
| `python swarm.py start --port 8200` | Start worker on custom port |
| `python swarm.py status` | Check which nodes are online |
| `python swarm.py run "prompt"` | Send a single prompt to the swarm |
| `python swarm.py run --file prompts.txt` | Distribute prompts from a file |
| `python swarm.py benchmark` | Compare 1 node vs full swarm speed |
| `python swarm.py benchmark --count 8` | Benchmark with 8 prompts |
| `python swarm.py nodes --list` | Show configured nodes |
| `python swarm.py nodes --add http://IP:8100` | Add a node |
| `python swarm.py nodes --remove http://IP:8100` | Remove a node |

---

## Configuration

Node list is stored in `swarm_nodes.json`:

```json
{
  "nodes": [
    "http://192.168.86.4:8100",
    "http://192.168.86.6:8100"
  ]
}
```

Edit this file or use `python swarm.py nodes` commands to manage nodes.

---

## Supported Models

Any model supported by Ollama works:

- `phi3:mini` — lightweight, fast on CPU
- `mistral` — good balance of speed and quality
- `llama3.2` — Meta's latest open model
- `deepseek-coder` — optimized for code tasks
- `gemma2` — Google's open model

---

## How It Works

1. **Worker nodes** run on each machine, wrapping Ollama's local LLM behind a FastAPI endpoint
2. **Scheduler** maintains a registry of available nodes and their health status
3. When prompts arrive, the scheduler **distributes them round-robin** across online nodes
4. All nodes process their assigned prompts **simultaneously**
5. Results are **collected, sorted, and returned** to the user

This is **batch parallelism** — independent prompts run on separate machines at the same time. A single prompt still runs on one node, but many prompts complete much faster when distributed.

---

## Roadmap

- [x] **Phase 1** — Distributed batch inference ✅
- [ ] **Phase 2** — Agent task orchestration (split complex tasks into subtasks)
- [ ] **Phase 3** — Multi-agent workflows
- [ ] **Phase 4** — Smart scheduling (weighted distribution by node speed)
- [ ] **Phase 5** — Internet-based swarm (beyond local network)

---

## Use Cases

- **Batch document summarization** — process hundreds of documents in parallel
- **Code generation** — split coding tasks across nodes (models, routes, tests)
- **Data extraction** — analyze multiple files simultaneously
- **Translation** — translate documents in parallel
- **Testing** — generate test cases across multiple nodes

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| LLM Runtime | Ollama |
| API Framework | FastAPI |
| HTTP Client | httpx (async) |
| CLI | Typer |
| Terminal UI | Rich |
| Concurrency | asyncio |

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
