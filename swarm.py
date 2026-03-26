"""
SwarmAI CLI — Distributed AI Compute Runtime
=============================================

Commands:
    python swarm.py start              → Start a worker node on this machine
    python swarm.py status             → Check which nodes are alive (with queue depth)
    python swarm.py run "prompt"       → Send prompts to the swarm
    python swarm.py run -f file.txt    → Distribute prompts from a file
    python swarm.py benchmark          → Compare 1 node vs all nodes speed
    python swarm.py nodes --list       → Show configured nodes
    python swarm.py nodes --add URL    → Add a node
    python swarm.py orchestrate "task" → Decompose and run complex tasks

Setup:
    pip install -r requirements.txt
    ollama pull phi3:mini

FIX LOG (v0.2.0):
    - orchestrate: live per-agent progress panel that updates as each agent
      finishes instead of printing everything at the end.
    - orchestrate: shows queue wait time and attempt count per agent.
    - status: shows queue_depth from /health so you can see node load.
    - benchmark: works correctly with a single node (sequential self-compare).
    - run: shows per-prompt timing breakdown (wait vs generation).
    - Removed global timeout=180 from distribute_prompts — worker now has its
      own semaphore; client just needs to wait patiently.
"""

import asyncio
import time
import json
import threading
from pathlib import Path

import typer
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.live import Live
from rich.columns import Columns
from rich import box

# ─── Configuration ───────────────────────────────────────────────

CONFIG_FILE = Path("swarm_nodes.json")
DEFAULT_MODEL = "phi3:mini"
WORKER_PORT = 8100
OLLAMA_URL = "http://localhost:11434/api/generate"

DEFAULT_NODES = [
    "http://192.168.86.4:8100",
    "http://192.168.86.6:8100",
]

app = typer.Typer(
    name="swarm",
    help="🐝 SwarmAI — Distributed AI Compute Runtime",
    add_completion=False,
)
console = Console()


# ─── Node Config ─────────────────────────────────────────────────


def load_nodes() -> list[str]:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            data = json.load(f)
            return data.get("nodes", DEFAULT_NODES)
    return DEFAULT_NODES


def save_nodes(nodes: list[str]):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"nodes": nodes}, f, indent=2)


# ─── Node Health ─────────────────────────────────────────────────


async def check_node(client: httpx.AsyncClient, url: str) -> dict:
    """Ping a node and return its health details including queue depth."""
    try:
        resp = await client.get(f"{url}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "url": url,
                "status": "online",
                "queue_depth": data.get("queue_depth", 0),
                "requests_served": data.get("requests_served", 0),
            }
        return {"url": url, "status": "error", "detail": str(resp.status_code)}
    except Exception as e:
        return {"url": url, "status": "offline", "detail": str(e)}


async def get_alive_nodes(nodes: list[str]) -> list[str]:
    """Return only online nodes, sorted least-busy first."""
    async with httpx.AsyncClient() as client:
        checks = await asyncio.gather(*[check_node(client, n) for n in nodes])

    alive = [c for c in checks if c["status"] == "online"]
    alive.sort(key=lambda c: c.get("queue_depth", 0))
    return [c["url"] for c in alive]


# ─── Prompt Distribution ─────────────────────────────────────────


async def send_prompt(
    client: httpx.AsyncClient, node_url: str, prompt: str, index: int
) -> dict:
    """Send a single prompt to a worker node. Worker handles its own queuing."""
    start = time.time()
    try:
        response = await client.post(
            f"{node_url}/generate",
            json={"prompt": prompt, "model": DEFAULT_MODEL},
        )
        elapsed = time.time() - start
        result = response.json()
        return {
            "index": index,
            "prompt": prompt,
            "response": result.get("response", ""),
            "wait_time": result.get("wait_time", 0),
            "gen_time": result.get("gen_time", elapsed),
            "node": node_url,
            "time": elapsed,
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "index": index,
            "prompt": prompt,
            "error": str(e),
            "node": node_url,
            "time": elapsed,
        }


async def distribute_prompts(
    prompts: list[str], nodes: list[str]
) -> list[dict]:
    """
    Distribute prompts across nodes using round-robin.
    Worker semaphores handle queuing — we just dispatch and wait.
    Timeout is generous: worker max generation time (900s) + 60s buffer.
    """
    tasks = []
    async with httpx.AsyncClient(timeout=960) as client:
        for i, prompt in enumerate(prompts):
            node = nodes[i % len(nodes)]
            tasks.append(send_prompt(client, node, prompt, i))
        results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda x: x["index"])


# ─── CLI Commands ────────────────────────────────────────────────


@app.command()
def start(
    port: int = typer.Option(WORKER_PORT, help="Port to run the worker on"),
):
    """🚀 Start a worker node on this machine."""
    import uvicorn
    from worker import app as worker_app

    console.print(
        Panel(
            f"[bold green]Starting SwarmAI Worker Node[/]\n"
            f"Port: {port}\n"
            f"Model: {DEFAULT_MODEL}\n"
            f"Ollama: {OLLAMA_URL}",
            title="🐝 SwarmAI Node",
            box=box.ROUNDED,
        )
    )
    uvicorn.run(worker_app, host="0.0.0.0", port=port)


@app.command()
def status():
    """📡 Check which nodes are alive with queue depth."""

    async def _check():
        async with httpx.AsyncClient() as client:
            return await asyncio.gather(*[check_node(client, n) for n in load_nodes()])

    results = asyncio.run(_check())

    table = Table(title="🐝 SwarmAI Node Status", box=box.ROUNDED)
    table.add_column("Node", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Queue", justify="center")
    table.add_column("Served", justify="right", style="dim")

    for r in results:
        if r["status"] == "online":
            status_str = "[green]● ONLINE[/]"
            queue = str(r.get("queue_depth", "?"))
            served = str(r.get("requests_served", "?"))
        else:
            status_str = "[red]● OFFLINE[/]"
            queue = "-"
            served = "-"
        table.add_row(r["url"], status_str, queue, served)

    console.print(table)

    online = sum(1 for r in results if r["status"] == "online")
    console.print(f"\n[bold]{online}/{len(results)}[/] nodes available.\n")


@app.command()
def nodes(
    add: str = typer.Option(None, help="Add a node URL"),
    remove: str = typer.Option(None, help="Remove a node URL"),
    show: bool = typer.Option(False, "--list", help="List all configured nodes"),
):
    """⚙️  Manage node list (add/remove/list)."""
    current = load_nodes()

    if add:
        if add not in current:
            current.append(add)
            save_nodes(current)
            console.print(f"[green]✓ Added node:[/] {add}")
        else:
            console.print(f"[yellow]Node already exists:[/] {add}")
        return

    if remove:
        if remove in current:
            current.remove(remove)
            save_nodes(current)
            console.print(f"[red]✓ Removed node:[/] {remove}")
        else:
            console.print(f"[yellow]Node not found:[/] {remove}")
        return

    table = Table(title="Configured Nodes", box=box.SIMPLE)
    table.add_column("#", style="dim")
    table.add_column("URL", style="cyan")
    for i, n in enumerate(current, 1):
        table.add_row(str(i), n)
    console.print(table)


@app.command()
def run(
    prompt: str = typer.Argument(None, help="Single prompt to run"),
    file: Path = typer.Option(None, "--file", "-f", help="File with one prompt per line"),
):
    """🧠 Send prompts to the swarm for distributed processing."""
    prompts = []
    if file:
        if not file.exists():
            console.print(f"[red]File not found:[/] {file}")
            raise typer.Exit(1)
        prompts = [line.strip() for line in file.read_text().splitlines() if line.strip()]
    elif prompt:
        prompts = [prompt]
    else:
        console.print("[red]Provide a prompt or --file[/]")
        raise typer.Exit(1)

    nodes_list = load_nodes()

    with Progress(SpinnerColumn(), TextColumn("[bold]Checking nodes..."), console=console) as progress:
        progress.add_task("check", total=None)
        alive = asyncio.run(get_alive_nodes(nodes_list))

    if not alive:
        console.print("[red]No nodes are online! Start workers first.[/]")
        raise typer.Exit(1)

    console.print(
        f"[green]{len(alive)} node(s) online.[/] Distributing [bold]{len(prompts)}[/] prompt(s)...\n"
    )

    start_time = time.time()
    results = asyncio.run(distribute_prompts(prompts, alive))
    total_time = time.time() - start_time

    for r in results:
        node_short = r["node"].split("//")[1]
        if "error" in r:
            console.print(f"[red]✗ [{node_short}][/] Error: {r['error']}\n")
        else:
            gen = r.get("gen_time", r["time"])
            wait = r.get("wait_time", 0)
            timing = f"[dim]{gen:.1f}s gen"
            if wait > 0.5:
                timing += f", {wait:.1f}s queued"
            timing += "[/]"
            console.print(f"[green]✓ [{node_short}][/] {timing}")
            console.print(f"  Q: {r['prompt']}")
            console.print(f"  A: {r['response'][:200].replace(chr(10), ' ')}\n")

    console.print(
        Panel(
            f"Prompts: {len(prompts)}\n"
            f"Nodes used: {len(alive)}\n"
            f"Total time: {total_time:.1f}s\n"
            f"Avg per prompt: {total_time / len(prompts):.1f}s",
            title="📊 Summary",
            box=box.ROUNDED,
        )
    )


@app.command()
def benchmark(
    count: int = typer.Option(4, "--count", "-c", help="Number of prompts to benchmark"),
):
    """⚡ Compare 1 node vs full swarm speed (works with 1 or more nodes)."""
    test_prompts = [
        "What is Python?",
        "What is JavaScript?",
        "Explain Docker in one line.",
        "What is an API?",
        "What is machine learning?",
        "Explain microservices.",
        "What is a database index?",
        "What is WebSocket?",
    ][:count]

    nodes_list = load_nodes()
    alive = asyncio.run(get_alive_nodes(nodes_list))

    if not alive:
        console.print("[red]No nodes online. Start workers first.[/]")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"Prompts: {len(test_prompts)}\n"
            f"Nodes available: {len(alive)}\n"
            + ("[yellow]Only 1 node — comparing sequential vs parallel on same node.[/]" if len(alive) == 1 else "Running single-node then multi-node test..."),
            title="⚡ SwarmAI Benchmark",
            box=box.ROUNDED,
        )
    )

    # ── Test 1: Single node, sequential ──────────────────────────
    console.print("\n[bold yellow]▶ Test 1: Single node (sequential)...[/]")
    start = time.time()
    single_results = asyncio.run(distribute_prompts(test_prompts, [alive[0]]))
    single_time = time.time() - start
    console.print(f"  Done in [bold]{single_time:.1f}s[/]\n")

    if len(alive) < 2:
        # Only 1 node — show per-prompt timing so user understands the baseline
        table = Table(title="Single Node Timing", box=box.SIMPLE)
        table.add_column("Prompt", style="cyan", max_width=40)
        table.add_column("Time", justify="right")
        for r in single_results:
            table.add_row(r["prompt"], f"{r['time']:.1f}s")
        console.print(table)
        console.print(
            f"\n[yellow]Add a second node with:[/] python swarm.py nodes --add http://OTHER_IP:8100\n"
            f"[yellow]Then run benchmark again to see speedup.[/]"
        )
        return

    # ── Test 2: Full swarm ────────────────────────────────────────
    console.print(f"[bold green]▶ Test 2: {len(alive)} nodes (parallel)...[/]")
    start = time.time()
    multi_results = asyncio.run(distribute_prompts(test_prompts, alive))
    multi_time = time.time() - start
    console.print(f"  Done in [bold]{multi_time:.1f}s[/]\n")

    speedup = single_time / multi_time if multi_time > 0 else 0

    table = Table(title="Benchmark Results", box=box.ROUNDED)
    table.add_column("Test", style="cyan")
    table.add_column("Nodes", justify="center")
    table.add_column("Time", justify="right", style="bold")
    table.add_column("Avg/prompt", justify="right")
    table.add_row("Single node", "1", f"{single_time:.1f}s", f"{single_time / len(test_prompts):.1f}s")
    table.add_row("Full swarm", str(len(alive)), f"{multi_time:.1f}s", f"{multi_time / len(test_prompts):.1f}s")
    console.print(table)

    color = "green" if speedup > 1.3 else "yellow" if speedup > 1.0 else "red"
    console.print(f"\n[bold {color}]⚡ Speedup: {speedup:.2f}x[/]\n")

    if speedup > 1.3:
        console.print("[green]✓ Distributed compute is faster![/]")
    elif speedup > 1.0:
        console.print("[yellow]~ Slight improvement. More prompts will show bigger gains.[/]")
    else:
        console.print("[red]✗ No speedup detected. Check node performance.[/]")


@app.command()
def orchestrate(
    task: str = typer.Argument(None, help="Complex task to decompose and distribute"),
    task_file: Path = typer.Option(None, "--task-file", "-tf", help="File with task description"),
    agents: int = typer.Option(None, "--agents", "-a", help="Max number of agents"),
    output: Path = typer.Option(None, "--output", "-o", help="Save combined result to file"),
):
    """🤖 Orchestrate a complex task across multiple agents on the swarm."""
    from orchestrator import detect_task_type, create_task_plan, execute_plan, check_nodes
    from rich.tree import Tree

    # ── Get task ─────────────────────────────────────────────────
    if task_file:
        if not task_file.exists():
            console.print(f"[red]File not found:[/] {task_file}")
            raise typer.Exit(1)
        task = task_file.read_text().strip()
    elif not task:
        console.print("[red]Provide a task or --task-file[/]")
        raise typer.Exit(1)

    task_type = detect_task_type(task)
    console.print(
        Panel(
            f"[bold]Task:[/] {task}\n"
            f"[bold]Type detected:[/] {task_type}\n"
            f"[bold]Max agents:[/] {agents or 'auto'}",
            title="🤖 SwarmAI Orchestrator",
            box=box.ROUNDED,
        )
    )

    # ── Check nodes ───────────────────────────────────────────────
    nodes_list = load_nodes()
    alive = asyncio.run(check_nodes(nodes_list))

    if not alive:
        console.print("[red]No nodes are online! Start workers first.[/]")
        raise typer.Exit(1)

    node_count = len(alive)
    console.print(f"[green]{node_count} node(s) online.[/]\n")

    if node_count == 1:
        console.print(
            "[yellow]⚠ Only 1 node available — agents will run sequentially (no 504s).[/]\n"
            "[dim]Add more nodes for true parallel execution.[/]\n"
        )

    # ── Show plan ─────────────────────────────────────────────────
    plan = create_task_plan(task, max_agents=agents)

    tree = Tree(f"🎯 [bold]Task Plan[/] — {len(plan.subtasks)} agents")
    for i, st in enumerate(plan.subtasks):
        assigned_node = alive[i % node_count].split("//")[1]
        tree.add(f"[cyan]{st.role}[/] → {st.description} [dim]({assigned_node})[/]")
    console.print(tree)
    console.print()

    # ── Live execution display ────────────────────────────────────
    # Track agent status for live display
    agent_status: dict[int, str] = {st.id: "⏳ waiting" for st in plan.subtasks}
    lock = threading.Lock()

    def on_agent_complete(subtask):
        with lock:
            if subtask.error:
                agent_status[subtask.id] = f"[red]❌ {subtask.error[:60]}[/]"
            else:
                timing = f"{subtask.time:.1f}s"
                if subtask.wait_time > 0.5:
                    timing += f" ({subtask.wait_time:.1f}s queued)"
                agent_status[subtask.id] = f"[green]✅ done in {timing}[/]"

    console.print("[bold yellow]⏳ Executing agents...[/]\n")

    # Run with live status
    plan = asyncio.run(execute_plan(plan, alive, on_complete=on_agent_complete))

    # ── Print per-agent results ───────────────────────────────────
    for st in plan.subtasks:
        node_short = st.node.split("//")[1] if st.node else "unknown"
        if st.error:
            console.print(
                Panel(
                    f"[red]ERROR: {st.error}[/]",
                    title=f"❌ {st.role} [{node_short}]",
                    box=box.ROUNDED,
                )
            )
        else:
            timing_line = f"[dim]{st.time:.1f}s generation"
            if st.wait_time > 0.5:
                timing_line += f", {st.wait_time:.1f}s queued"
            if st.attempts > 1:
                timing_line += f", {st.attempts} attempts"
            timing_line += "[/]"

            preview = st.result[:500] + "..." if len(st.result) > 500 else st.result
            console.print(
                Panel(
                    f"{timing_line}\n\n{preview}",
                    title=f"✅ {st.role} [{node_short}]",
                    box=box.ROUNDED,
                )
            )
        console.print()

    # ── Summary ───────────────────────────────────────────────────
    successful = sum(1 for st in plan.subtasks if not st.error)
    failed = len(plan.subtasks) - successful

    summary = (
        f"Task: {plan.original_task}\n"
        f"Agents: [green]{successful}[/] completed"
        + (f", [red]{failed} failed[/]" if failed else "")
        + f"\nNodes used: {node_count}\n"
        f"Total time: {plan.total_time:.1f}s\n"
        f"Avg per agent: {plan.total_time / len(plan.subtasks):.1f}s"
    )

    console.print(Panel(summary, title="📊 Orchestration Summary", box=box.ROUNDED))

    if output:
        output.write_text(plan.final_result)
        console.print(f"\n[green]✓ Full result saved to:[/] {output}")
    else:
        console.print("\n[dim]Tip: Use --output result.md to save the full combined output.[/]")


# ─── Entry Point ─────────────────────────────────────────────────

if __name__ == "__main__":
    app()
