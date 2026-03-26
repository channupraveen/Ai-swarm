"""
SwarmAI CLI — Distributed AI Compute Runtime
=============================================

Commands:
    python swarm.py start           → Start a worker node on this machine
    python swarm.py status          → Check which nodes are alive
    python swarm.py run "prompt"    → Send prompts to the swarm
    python swarm.py run -f file.txt → Distribute prompts from a file
    python swarm.py benchmark       → Compare 1 node vs all nodes speed
    python swarm.py nodes --list    → Show configured nodes
    python swarm.py nodes --add URL → Add a node

Setup:
    pip install -r requirements.txt
    ollama pull phi3:mini
"""

import asyncio
import time
import json
from pathlib import Path

import typer
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

# ─── Configuration ───────────────────────────────────────────────

CONFIG_FILE = Path("swarm_nodes.json")
DEFAULT_MODEL = "phi3:mini"
WORKER_PORT = 8100
OLLAMA_URL = "http://localhost:11434/api/generate"

# Default nodes — override by creating swarm_nodes.json
DEFAULT_NODES = [
    "http://192.168.86.4:8100",
    "http://192.168.86.6:8100",
]

# ─── App Setup ───────────────────────────────────────────────────

app = typer.Typer(
    name="swarm",
    help="🐝 SwarmAI — Distributed AI Compute Runtime",
    add_completion=False,
)
console = Console()


# ─── Helper Functions ────────────────────────────────────────────


def load_nodes() -> list[str]:
    """Load node list from config file, or use defaults."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            data = json.load(f)
            return data.get("nodes", DEFAULT_NODES)
    return DEFAULT_NODES


def save_nodes(nodes: list[str]):
    """Save node list to config file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump({"nodes": nodes}, f, indent=2)


async def check_node(client: httpx.AsyncClient, url: str) -> dict:
    """Check if a node is alive."""
    try:
        resp = await client.get(f"{url}/health", timeout=5)
        if resp.status_code == 200:
            return {"url": url, "status": "online", "detail": resp.json()}
        return {"url": url, "status": "error", "detail": str(resp.status_code)}
    except Exception as e:
        return {"url": url, "status": "offline", "detail": str(e)}


async def send_prompt(
    client: httpx.AsyncClient, node_url: str, prompt: str, index: int
) -> dict:
    """Send a single prompt to a worker node."""
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
    """Distribute prompts across nodes using round-robin."""
    tasks = []
    async with httpx.AsyncClient(timeout=180) as client:
        for i, prompt in enumerate(prompts):
            node = nodes[i % len(nodes)]
            tasks.append(send_prompt(client, node, prompt, i))
        results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda x: x["index"])


async def get_alive_nodes(nodes: list[str]) -> list[str]:
    """Return only nodes that are online."""
    async with httpx.AsyncClient() as client:
        checks = await asyncio.gather(*[check_node(client, n) for n in nodes])
    return [c["url"] for c in checks if c["status"] == "online"]


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
    """📡 Check which nodes are alive."""
    nodes = load_nodes()

    async def _check():
        async with httpx.AsyncClient() as client:
            return await asyncio.gather(*[check_node(client, n) for n in nodes])

    results = asyncio.run(_check())

    table = Table(title="🐝 SwarmAI Node Status", box=box.ROUNDED)
    table.add_column("Node", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Detail")

    for r in results:
        status_str = (
            "[green]● ONLINE[/]" if r["status"] == "online" else "[red]● OFFLINE[/]"
        )
        table.add_row(r["url"], status_str, str(r.get("detail", "")))

    console.print(table)

    online = sum(1 for r in results if r["status"] == "online")
    console.print(f"\n[bold]{online}/{len(nodes)}[/] nodes available.\n")


@app.command()
def nodes(
    add: str = typer.Option(None, help="Add a node URL (e.g. http://192.168.1.10:8100)"),
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

    # Default: show list
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
    # Collect prompts
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

    nodes = load_nodes()

    # Check alive nodes first
    with Progress(
        SpinnerColumn(), TextColumn("[bold]Checking nodes..."), console=console
    ) as progress:
        progress.add_task("check", total=None)
        alive = asyncio.run(get_alive_nodes(nodes))

    if not alive:
        console.print("[red]No nodes are online! Start workers first.[/]")
        raise typer.Exit(1)

    console.print(
        f"[green]{len(alive)} node(s) online.[/] Distributing {len(prompts)} prompt(s)...\n"
    )

    # Distribute
    start_time = time.time()
    results = asyncio.run(distribute_prompts(prompts, alive))
    total_time = time.time() - start_time

    # Display results
    for r in results:
        node_short = r["node"].split("//")[1]
        if "error" in r:
            console.print(f"[red]✗ [{node_short}][/] {r['prompt']}")
            console.print(f"  Error: {r['error']}\n")
        else:
            console.print(f"[green]✓ [{node_short}][/] [dim]{r['time']:.1f}s[/]")
            console.print(f"  Q: {r['prompt']}")
            response_preview = r["response"][:200].replace("\n", " ")
            console.print(f"  A: {response_preview}\n")

    # Summary
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
    """⚡ Compare 1 node vs full swarm speed."""
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

    nodes = load_nodes()

    # Check alive nodes
    alive = asyncio.run(get_alive_nodes(nodes))
    if len(alive) < 2:
        console.print("[red]Need at least 2 online nodes for benchmark.[/]")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"Prompts: {len(test_prompts)}\n"
            f"Nodes available: {len(alive)}\n"
            f"Running single-node then multi-node test...",
            title="⚡ SwarmAI Benchmark",
            box=box.ROUNDED,
        )
    )

    # --- Single node test ---
    console.print("\n[bold yellow]▶ Test 1: Single node...[/]")
    start = time.time()
    single_results = asyncio.run(distribute_prompts(test_prompts, [alive[0]]))
    single_time = time.time() - start
    console.print(f"  Done in [bold]{single_time:.1f}s[/]\n")

    # --- Multi node test ---
    console.print(f"[bold green]▶ Test 2: {len(alive)} nodes...[/]")
    start = time.time()
    multi_results = asyncio.run(distribute_prompts(test_prompts, alive))
    multi_time = time.time() - start
    console.print(f"  Done in [bold]{multi_time:.1f}s[/]\n")

    # --- Results ---
    speedup = single_time / multi_time if multi_time > 0 else 0

    table = Table(title="Benchmark Results", box=box.ROUNDED)
    table.add_column("Test", style="cyan")
    table.add_column("Nodes", justify="center")
    table.add_column("Time", justify="right", style="bold")
    table.add_column("Avg/prompt", justify="right")

    table.add_row(
        "Single node",
        "1",
        f"{single_time:.1f}s",
        f"{single_time / len(test_prompts):.1f}s",
    )
    table.add_row(
        "Full swarm",
        str(len(alive)),
        f"{multi_time:.1f}s",
        f"{multi_time / len(test_prompts):.1f}s",
    )

    console.print(table)

    color = "green" if speedup > 1.3 else "yellow" if speedup > 1.0 else "red"
    console.print(f"\n[bold {color}]⚡ Speedup: {speedup:.2f}x[/]\n")

    if speedup > 1.3:
        console.print("[green]✓ Distributed compute is faster![/]")
    elif speedup > 1.0:
        console.print(
            "[yellow]~ Slight improvement. More prompts will show bigger gains.[/]"
        )
    else:
        console.print("[red]✗ No speedup detected. Check node performance.[/]")


@app.command()
def orchestrate(
    task: str = typer.Argument(None, help="Complex task to decompose and distribute"),
    task_file: Path = typer.Option(None, "--task-file", "-tf", help="File containing the task description"),
    agents: int = typer.Option(None, "--agents", "-a", help="Max number of agents to use"),
    output: Path = typer.Option(None, "--output", "-o", help="Save combined result to file"),
):
    """🤖 Orchestrate a complex task across multiple agents on the swarm."""
    from orchestrator import (
        detect_task_type,
        create_task_plan,
        execute_plan,
        check_nodes,
    )
    from rich.tree import Tree
    from rich.markdown import Markdown

    # Get task
    if task_file:
        if not task_file.exists():
            console.print(f"[red]File not found:[/] {task_file}")
            raise typer.Exit(1)
        task = task_file.read_text().strip()
    elif not task:
        console.print("[red]Provide a task or --task-file[/]")
        raise typer.Exit(1)

    # Detect task type
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

    # Check nodes
    nodes = load_nodes()
    alive = asyncio.run(check_nodes(nodes))

    if not alive:
        console.print("[red]No nodes are online! Start workers first.[/]")
        raise typer.Exit(1)

    console.print(f"[green]{len(alive)} node(s) online.[/]\n")

    # Create plan
    plan = create_task_plan(task, max_agents=agents)

    # Show plan
    tree = Tree(f"🎯 [bold]Task Plan[/] — {len(plan.subtasks)} agents")
    for st in plan.subtasks:
        node = alive[st.id % len(alive)].split("//")[1]
        tree.add(f"[cyan]{st.role}[/] → {st.description} [dim]({node})[/]")
    console.print(tree)
    console.print()

    # Execute
    console.print("[bold yellow]⏳ Executing all agents in parallel...[/]\n")
    plan = asyncio.run(execute_plan(plan, alive))

    # Show results per agent
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
            # Truncate for display
            preview = st.result[:500] + "..." if len(st.result) > 500 else st.result
            console.print(
                Panel(
                    preview,
                    title=f"✅ {st.role} [{node_short}] — {st.time:.1f}s",
                    box=box.ROUNDED,
                )
            )
        console.print()

    # Summary
    successful = sum(1 for st in plan.subtasks if not st.error)
    console.print(
        Panel(
            f"Task: {plan.original_task}\n"
            f"Agents: {successful}/{len(plan.subtasks)} completed\n"
            f"Nodes used: {len(alive)}\n"
            f"Total time: {plan.total_time:.1f}s\n"
            f"Avg per agent: {plan.total_time / len(plan.subtasks):.1f}s",
            title="📊 Orchestration Summary",
            box=box.ROUNDED,
        )
    )

    # Save full output if requested
    if output:
        output.write_text(plan.final_result)
        console.print(f"\n[green]✓ Full result saved to:[/] {output}")
    else:
        console.print(
            "\n[dim]Tip: Use --output result.md to save the full combined output.[/]"
        )


# ─── Entry Point ─────────────────────────────────────────────────

if __name__ == "__main__":
    app()
