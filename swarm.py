"""
SwarmAI CLI — Distributed AI Compute Runtime
=============================================

LOCAL commands:
    python swarm.py start              → Start a worker node on this machine
    python swarm.py status             → Check local nodes alive
    python swarm.py run "prompt"       → Send prompt to local swarm
    python swarm.py benchmark          → Speed comparison
    python swarm.py orchestrate "task" → Multi-agent task

INTERNET SWARM commands:
    python swarm.py coordinator-start          → Start coordinator (on VPS)
    python swarm.py coordinator-status URL KEY → Check coordinator + nodes
    python swarm.py coordinator-run URL KEY    → Send prompt via coordinator
"""

import asyncio
import time
import json
import os
import threading
from pathlib import Path

import typer
import httpx
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

CONFIG_FILE = Path("swarm_nodes.json")
DEFAULT_MODEL = "phi3:mini"
WORKER_PORT = 8100
OLLAMA_URL = "http://localhost:11434/api/generate"

DEFAULT_NODES = [
    "http://192.168.86.4:8100",
    "http://192.168.86.6:8100",
]

app = typer.Typer(name="swarm", help="🐝 SwarmAI — Distributed AI Compute Runtime", add_completion=False)
console = Console()


# ─── Node Config ─────────────────────────────────────────────────

def load_nodes() -> list[str]:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f).get("nodes", DEFAULT_NODES)
    return DEFAULT_NODES


def save_nodes(nodes: list[str]):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"nodes": nodes}, f, indent=2)


# ─── Node Health ─────────────────────────────────────────────────

async def check_node(client: httpx.AsyncClient, url: str) -> dict:
    try:
        resp = await client.get(f"{url}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return {"url": url, "status": "online", "queue_depth": data.get("queue_depth", 0), "requests_served": data.get("requests_served", 0)}
        return {"url": url, "status": "error"}
    except Exception as e:
        return {"url": url, "status": "offline", "detail": str(e)}


async def get_alive_nodes(nodes: list[str]) -> list[str]:
    async with httpx.AsyncClient() as client:
        checks = await asyncio.gather(*[check_node(client, n) for n in nodes])
    alive = [c for c in checks if c["status"] == "online"]
    alive.sort(key=lambda c: c.get("queue_depth", 0))
    return [c["url"] for c in alive]


# ─── Prompt Distribution ─────────────────────────────────────────

async def send_prompt(client: httpx.AsyncClient, node_url: str, prompt: str, index: int) -> dict:
    start = time.time()
    try:
        response = await client.post(f"{node_url}/generate", json={"prompt": prompt, "model": DEFAULT_MODEL})
        elapsed = time.time() - start
        result = response.json()
        return {"index": index, "prompt": prompt, "response": result.get("response", ""), "wait_time": result.get("wait_time", 0), "gen_time": result.get("gen_time", elapsed), "node": node_url, "time": elapsed}
    except Exception as e:
        return {"index": index, "prompt": prompt, "error": str(e), "node": node_url, "time": time.time() - start}


async def distribute_prompts(prompts: list[str], nodes: list[str]) -> list[dict]:
    tasks = []
    async with httpx.AsyncClient(timeout=960) as client:
        for i, prompt in enumerate(prompts):
            tasks.append(send_prompt(client, nodes[i % len(nodes)], prompt, i))
        results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda x: x["index"])


# ─── LOCAL CLI Commands ───────────────────────────────────────────

@app.command()
def start(port: int = typer.Option(WORKER_PORT, help="Port to run the worker on")):
    """🚀 Start a worker node on this machine."""
    import uvicorn
    from worker import app as worker_app
    console.print(Panel(f"[bold green]Starting SwarmAI Worker Node[/]\nPort: {port}\nModel: {DEFAULT_MODEL}", title="🐝 SwarmAI Node", box=box.ROUNDED))
    uvicorn.run(worker_app, host="0.0.0.0", port=port)


@app.command()
def status():
    """📡 Check which local nodes are alive."""
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
            table.add_row(r["url"], "[green]● ONLINE[/]", str(r.get("queue_depth","?")), str(r.get("requests_served","?")))
        else:
            table.add_row(r["url"], "[red]● OFFLINE[/]", "-", "-")
    console.print(table)
    online = sum(1 for r in results if r["status"] == "online")
    console.print(f"\n[bold]{online}/{len(results)}[/] nodes available.\n")


@app.command()
def nodes(
    add: str = typer.Option(None, help="Add a node URL"),
    remove: str = typer.Option(None, help="Remove a node URL"),
    show: bool = typer.Option(False, "--list", help="List nodes"),
):
    """⚙️  Manage node list."""
    current = load_nodes()
    if add:
        if add not in current:
            current.append(add)
            save_nodes(current)
            console.print(f"[green]✓ Added:[/] {add}")
        else:
            console.print(f"[yellow]Already exists:[/] {add}")
        return
    if remove:
        if remove in current:
            current.remove(remove)
            save_nodes(current)
            console.print(f"[red]✓ Removed:[/] {remove}")
        return
    table = Table(title="Configured Nodes", box=box.SIMPLE)
    table.add_column("#", style="dim")
    table.add_column("URL", style="cyan")
    for i, n in enumerate(current, 1):
        table.add_row(str(i), n)
    console.print(table)


@app.command()
def run(
    prompt: str = typer.Argument(None),
    file: Path = typer.Option(None, "--file", "-f"),
):
    """🧠 Send prompts to local swarm."""
    prompts = []
    if file:
        prompts = [l.strip() for l in file.read_text().splitlines() if l.strip()]
    elif prompt:
        prompts = [prompt]
    else:
        console.print("[red]Provide a prompt or --file[/]")
        raise typer.Exit(1)

    nodes_list = load_nodes()
    with Progress(SpinnerColumn(), TextColumn("[bold]Checking nodes..."), console=console) as p:
        p.add_task("check", total=None)
        alive = asyncio.run(get_alive_nodes(nodes_list))

    if not alive:
        console.print("[red]No nodes online.[/]")
        raise typer.Exit(1)

    start_time = time.time()
    results = asyncio.run(distribute_prompts(prompts, alive))
    total_time = time.time() - start_time

    for r in results:
        node_short = r["node"].split("//")[1]
        if "error" in r:
            console.print(f"[red]✗ [{node_short}][/] {r['error']}\n")
        else:
            console.print(f"[green]✓ [{node_short}][/] [dim]{r.get('gen_time',r['time']):.1f}s[/]")
            console.print(f"  Q: {r['prompt']}")
            console.print(f"  A: {r['response'][:200]}\n")

    console.print(Panel(f"Prompts: {len(prompts)}\nNodes: {len(alive)}\nTotal: {total_time:.1f}s", title="📊 Summary", box=box.ROUNDED))


@app.command()
def benchmark(count: int = typer.Option(4, "--count", "-c")):
    """⚡ Compare 1-node vs full swarm speed."""
    test_prompts = ["What is Python?", "What is Docker?", "What is an API?", "What is ML?"][:count]
    alive = asyncio.run(get_alive_nodes(load_nodes()))
    if not alive:
        console.print("[red]No nodes online.[/]")
        raise typer.Exit(1)

    console.print(f"\n[bold yellow]▶ Single node...[/]")
    start = time.time()
    asyncio.run(distribute_prompts(test_prompts, [alive[0]]))
    single_time = time.time() - start

    if len(alive) < 2:
        console.print(f"  Done in {single_time:.1f}s\n[yellow]Add more nodes to compare.[/]")
        return

    console.print(f"[bold green]▶ Full swarm ({len(alive)} nodes)...[/]")
    start = time.time()
    asyncio.run(distribute_prompts(test_prompts, alive))
    multi_time = time.time() - start

    speedup = single_time / multi_time if multi_time > 0 else 0
    table = Table(box=box.ROUNDED)
    table.add_column("Test", style="cyan")
    table.add_column("Time", justify="right", style="bold")
    table.add_column("Speedup", justify="right")
    table.add_row("Single node", f"{single_time:.1f}s", "1.0x")
    table.add_row(f"Full swarm ({len(alive)})", f"{multi_time:.1f}s", f"[green]{speedup:.2f}x[/]")
    console.print(table)


@app.command()
def orchestrate(
    task: str = typer.Argument(None),
    task_file: Path = typer.Option(None, "--task-file", "-tf"),
    agents: int = typer.Option(None, "--agents", "-a"),
    output: Path = typer.Option(None, "--output", "-o"),
):
    """🤖 Decompose and run a complex task across agents."""
    from orchestrator import detect_task_type, create_task_plan, execute_plan, check_nodes
    from rich.tree import Tree

    if task_file:
        task = task_file.read_text().strip()
    elif not task:
        console.print("[red]Provide a task.[/]")
        raise typer.Exit(1)

    task_type = detect_task_type(task)
    console.print(Panel(f"[bold]Task:[/] {task}\n[bold]Type:[/] {task_type}\n[bold]Agents:[/] {agents or 'auto'}", title="🤖 SwarmAI Orchestrator", box=box.ROUNDED))

    alive = asyncio.run(check_nodes(load_nodes()))
    if not alive:
        console.print("[red]No nodes online.[/]")
        raise typer.Exit(1)

    node_count = len(alive)
    console.print(f"[green]{node_count} node(s) online.[/]\n")
    if node_count == 1:
        console.print("[yellow]⚠ 1 node — agents run sequentially.[/]\n")

    plan = create_task_plan(task, max_agents=agents)
    tree = Tree(f"🎯 [bold]Task Plan[/] — {len(plan.subtasks)} agents")
    for i, st in enumerate(plan.subtasks):
        tree.add(f"[cyan]{st.role}[/] → {st.description} [dim]({alive[i % node_count].split('//')[1]})[/]")
    console.print(tree)
    console.print()

    lock = threading.Lock()
    def on_complete(subtask):
        with lock:
            status = f"[green]✅ {subtask.time:.1f}s[/]" if not subtask.error else f"[red]❌ {subtask.error[:50]}[/]"
            console.print(f"  {subtask.role}: {status}")

    console.print("[bold yellow]⏳ Executing agents...[/]\n")
    plan = asyncio.run(execute_plan(plan, alive, on_complete=on_complete))
    console.print()

    for st in plan.subtasks:
        node_short = st.node.split("//")[1] if st.node else "?"
        if st.error:
            console.print(Panel(f"[red]{st.error}[/]", title=f"❌ {st.role} [{node_short}]", box=box.ROUNDED))
        else:
            preview = st.result[:500] + "..." if len(st.result) > 500 else st.result
            console.print(Panel(f"[dim]{st.time:.1f}s gen[/]\n\n{preview}", title=f"✅ {st.role} [{node_short}]", box=box.ROUNDED))
        console.print()

    successful = sum(1 for st in plan.subtasks if not st.error)
    console.print(Panel(
        f"Agents: [green]{successful}[/]/{len(plan.subtasks)} completed\n"
        f"Nodes: {node_count} | Total: {plan.total_time:.1f}s",
        title="📊 Summary", box=box.ROUNDED
    ))

    if output:
        output.write_text(plan.final_result)
        console.print(f"\n[green]✓ Saved to:[/] {output}")


# ─── INTERNET SWARM Commands ──────────────────────────────────────

@app.command()
def coordinator_start(
    port: int = typer.Option(8200, help="Port for coordinator"),
):
    """🌐 Start the coordinator server (run this on your VPS)."""
    import uvicorn
    from coordinator import app as coord_app
    api_key = os.environ.get("SWARM_API_KEY", "swarm-dev-key-change-in-production")
    console.print(Panel(
        f"[bold green]Starting SwarmAI Coordinator[/]\n"
        f"Port: {port}\n"
        f"API Key: {api_key}\n\n"
        f"[yellow]Set SWARM_API_KEY env var before running in production![/]",
        title="🌐 SwarmAI Coordinator", box=box.ROUNDED
    ))
    uvicorn.run(coord_app, host="0.0.0.0", port=port)


@app.command()
def coordinator_status(
    coordinator_url: str = typer.Argument(..., help="Coordinator URL e.g. http://VPS_IP:8200"),
    api_key: str = typer.Option(..., "--key", "-k", help="API key"),
):
    """📡 Check coordinator status and list registered internet nodes."""
    async def _check():
        async with httpx.AsyncClient(timeout=10) as client:
            # Root (public)
            root = await client.get(coordinator_url)
            root_data = root.json()

            # Nodes (auth required)
            nodes_resp = await client.get(f"{coordinator_url}/nodes", headers={"X-Api-Key": api_key})
            nodes_data = nodes_resp.json()
            return root_data, nodes_data

    try:
        root_data, nodes_data = asyncio.run(_check())
    except Exception as e:
        console.print(f"[red]Cannot reach coordinator: {e}[/]")
        raise typer.Exit(1)

    console.print(Panel(
        f"Nodes online: [green]{root_data.get('nodes_online', 0)}[/]\n"
        f"Nodes total: {root_data.get('nodes_total', 0)}\n"
        f"Version: {root_data.get('version','?')}",
        title=f"🌐 Coordinator: {coordinator_url}", box=box.ROUNDED
    ))

    table = Table(title="Registered Internet Nodes", box=box.ROUNDED)
    table.add_column("Node URL", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Queue", justify="center")
    table.add_column("Served", justify="right")
    table.add_column("Last Heartbeat", justify="right", style="dim")

    for node in nodes_data.get("nodes", []):
        alive = node.get("alive", False)
        table.add_row(
            node["url"],
            "[green]● ALIVE[/]" if alive else "[red]● DEAD[/]",
            str(node.get("queue_depth", 0)),
            str(node.get("requests_served", 0)),
            f"{node.get('last_heartbeat', '?')}s ago",
        )
    console.print(table)


@app.command()
def coordinator_run(
    prompt: str = typer.Argument(..., help="Prompt to send"),
    coordinator_url: str = typer.Option(..., "--coordinator", "-c", help="Coordinator URL"),
    api_key: str = typer.Option(..., "--key", "-k", help="API key"),
):
    """🧠 Send a prompt via coordinator (routes to best internet node)."""
    async def _run():
        async with httpx.AsyncClient(timeout=360) as client:
            resp = await client.post(
                f"{coordinator_url}/route",
                json={"prompt": prompt, "model": DEFAULT_MODEL},
                headers={"X-Api-Key": api_key},
            )
            return resp.json()

    console.print(f"[yellow]Routing via coordinator...[/]")
    try:
        result = asyncio.run(_run())
        console.print(Panel(
            f"[dim]Node used: {result.get('node_used','?')} | Time: {result.get('gen_time',0):.1f}s[/]\n\n"
            f"{result.get('response','')}",
            title="🧠 Response", box=box.ROUNDED
        ))
    except Exception as e:
        console.print(f"[red]Error: {e}[/]")


# ─── Entry Point ─────────────────────────────────────────────────

if __name__ == "__main__":
    app()
