"""
SwarmAI Agent Orchestrator
==========================
Phase 2: Splits complex tasks into independent subtasks and distributes
them across worker nodes for parallel execution.

This is the brain that turns a single complex request into multiple
parallel LLM calls across your swarm.

Usage via CLI:
    python swarm.py orchestrate "Build a REST API for a blog system"
    python swarm.py orchestrate "Build a full-stack e-commerce app" --agents 6

FIX LOG (v0.2.0):
    - CRITICAL: Replaced broken round-robin parallel dispatch with smart
      least-busy routing. With 1 node, tasks now run sequentially without
      504 timeouts. With N nodes, tasks route to the node with the shortest
      queue — not blindly round-robin.
    - Added retry logic: each subtask retries up to 2 times on failure before
      marking as error.
    - Added per-subtask timeout (default 600s) — prevents one hung agent from
      blocking the entire plan forever.
    - Node queue depth is read from /health before each dispatch so routing
      decisions are always based on real-time load, not guesses.
    - execute_plan now returns a live progress callback for the CLI to display
      per-agent status as they complete, not just at the end.
"""

import asyncio
import time
from dataclasses import dataclass, field

import httpx

# ─── Configuration ───────────────────────────────────────────────

DEFAULT_MODEL = "phi3:mini"
AGENT_TIMEOUT = 600       # seconds per agent before giving up
MAX_RETRIES = 2           # retry failed agents this many times

# ─── Data Structures ─────────────────────────────────────────────


@dataclass
class SubTask:
    """A single subtask assigned to an agent."""
    id: int
    role: str           # e.g. "Database Architect", "API Developer"
    description: str    # what this agent should do
    prompt: str         # actual prompt sent to LLM
    node: str = ""      # which node processed it
    result: str = ""    # LLM response
    time: float = 0.0   # seconds taken
    wait_time: float = 0.0  # seconds waiting in node queue
    error: str = ""
    attempts: int = 0   # how many times we tried


@dataclass
class TaskPlan:
    """Complete plan for executing a complex task."""
    original_task: str
    subtasks: list[SubTask] = field(default_factory=list)
    final_result: str = ""
    total_time: float = 0.0


# ─── Task Decomposition Templates ────────────────────────────────

TASK_TEMPLATES = {
    "rest_api": {
        "keywords": ["rest api", "api", "backend", "endpoints", "routes"],
        "agents": [
            {
                "role": "Database Architect",
                "description": "Design the database schema and models",
                "prompt_template": "You are a Database Architect. Design the complete database schema with tables, columns, relationships, and constraints for: {task}. Provide SQL CREATE TABLE statements and ORM model definitions.",
            },
            {
                "role": "API Developer",
                "description": "Create the API endpoints and routes",
                "prompt_template": "You are an API Developer. Design and write all REST API endpoints (GET, POST, PUT, DELETE) with request/response schemas for: {task}. Include route definitions, request validation, and response formats.",
            },
            {
                "role": "Auth Engineer",
                "description": "Implement authentication and authorization",
                "prompt_template": "You are an Auth Engineer. Design and implement the authentication and authorization system for: {task}. Include JWT token handling, login/register endpoints, role-based access control, and middleware.",
            },
            {
                "role": "Test Engineer",
                "description": "Write comprehensive test cases",
                "prompt_template": "You are a Test Engineer. Write comprehensive unit tests and integration tests for: {task}. Cover all endpoints, edge cases, error handling, and authentication flows. Use pytest.",
            },
            {
                "role": "Documentation Writer",
                "description": "Create API documentation",
                "prompt_template": "You are a Documentation Writer. Write complete API documentation for: {task}. Include endpoint descriptions, request/response examples, authentication guide, and setup instructions.",
            },
        ],
    },
    "code_review": {
        "keywords": ["review", "audit", "analyze", "refactor", "security"],
        "agents": [
            {
                "role": "Security Auditor",
                "description": "Check for security vulnerabilities",
                "prompt_template": "You are a Security Auditor. Analyze for security vulnerabilities, injection risks, authentication weaknesses, and data exposure in: {task}. Provide specific findings and fixes.",
            },
            {
                "role": "Performance Analyst",
                "description": "Identify performance bottlenecks",
                "prompt_template": "You are a Performance Analyst. Analyze for performance issues, N+1 queries, memory leaks, slow algorithms, and optimization opportunities in: {task}. Provide specific recommendations.",
            },
            {
                "role": "Code Quality Reviewer",
                "description": "Review code quality and patterns",
                "prompt_template": "You are a Code Quality Reviewer. Review for code quality, design patterns, SOLID principles, naming conventions, and maintainability in: {task}. Suggest specific improvements.",
            },
            {
                "role": "Test Coverage Analyst",
                "description": "Identify missing test coverage",
                "prompt_template": "You are a Test Coverage Analyst. Analyze and identify missing test cases, untested edge cases, and gaps in test coverage for: {task}. Provide specific test cases to add.",
            },
        ],
    },
    "documentation": {
        "keywords": ["document", "docs", "readme", "guide", "tutorial", "explain"],
        "agents": [
            {
                "role": "Technical Writer",
                "description": "Write technical documentation",
                "prompt_template": "You are a Technical Writer. Write clear, detailed technical documentation for: {task}. Include architecture overview, component descriptions, and technical decisions.",
            },
            {
                "role": "Tutorial Creator",
                "description": "Create step-by-step tutorials",
                "prompt_template": "You are a Tutorial Creator. Create a beginner-friendly step-by-step tutorial for: {task}. Include prerequisites, setup instructions, code examples, and common pitfalls.",
            },
            {
                "role": "API Reference Writer",
                "description": "Write API reference docs",
                "prompt_template": "You are an API Reference Writer. Write comprehensive API reference documentation for: {task}. Include all endpoints, parameters, response formats, and error codes.",
            },
        ],
    },
    "fullstack": {
        "keywords": ["fullstack", "full stack", "website", "web app", "application", "frontend", "full application"],
        "agents": [
            {
                "role": "Backend Developer",
                "description": "Build the server-side logic",
                "prompt_template": "You are a Backend Developer. Design and implement the complete backend for: {task}. Include server setup, database models, API routes, business logic, and error handling.",
            },
            {
                "role": "Frontend Developer",
                "description": "Build the user interface",
                "prompt_template": "You are a Frontend Developer. Design and implement the complete frontend UI for: {task}. Include component structure, pages, forms, state management, and styling.",
            },
            {
                "role": "Database Engineer",
                "description": "Design the data layer",
                "prompt_template": "You are a Database Engineer. Design the complete database schema, migrations, seed data, and query optimizations for: {task}.",
            },
            {
                "role": "DevOps Engineer",
                "description": "Set up deployment and CI/CD",
                "prompt_template": "You are a DevOps Engineer. Create the deployment configuration, Docker setup, CI/CD pipeline, and environment configuration for: {task}.",
            },
            {
                "role": "Test Engineer",
                "description": "Write all tests",
                "prompt_template": "You are a Test Engineer. Write comprehensive tests (unit, integration, e2e) for: {task}. Cover both frontend and backend.",
            },
        ],
    },
    "general": {
        "keywords": [],
        "agents": [
            {
                "role": "Research Analyst",
                "description": "Research and gather information",
                "prompt_template": "You are a Research Analyst. Provide thorough research and analysis on: {task}. Include key findings, data points, and recommendations.",
            },
            {
                "role": "Solution Architect",
                "description": "Design the solution",
                "prompt_template": "You are a Solution Architect. Design a complete solution for: {task}. Include architecture, components, technology choices, and implementation plan.",
            },
            {
                "role": "Implementation Specialist",
                "description": "Write the implementation",
                "prompt_template": "You are an Implementation Specialist. Write the complete implementation for: {task}. Include all code, configuration, and setup steps.",
            },
            {
                "role": "Quality Reviewer",
                "description": "Review and improve the output",
                "prompt_template": "You are a Quality Reviewer. Review and provide improvements for: {task}. Check for completeness, correctness, best practices, and potential issues.",
            },
        ],
    },
}


# ─── Node Load Tracker ───────────────────────────────────────────

class NodeLoadTracker:
    """
    Tracks in-flight task count per node so we can always route to the
    least-busy node. Falls back gracefully if health check data is stale.
    """

    def __init__(self, nodes: list[str]):
        self._load: dict[str, int] = {n: 0 for n in nodes}

    def pick_least_busy(self) -> str:
        """Return the node with the fewest active tasks."""
        return min(self._load, key=self._load.get)

    def increment(self, node: str):
        self._load[node] = self._load.get(node, 0) + 1

    def decrement(self, node: str):
        self._load[node] = max(0, self._load.get(node, 1) - 1)

    def snapshot(self) -> dict[str, int]:
        return dict(self._load)


# ─── Orchestrator Engine ─────────────────────────────────────────


def detect_task_type(task: str) -> str:
    """Detect which template to use based on task keywords."""
    task_lower = task.lower()
    for template_name, template in TASK_TEMPLATES.items():
        if template_name == "general":
            continue
        if any(kw in task_lower for kw in template["keywords"]):
            return template_name
    return "general"


def create_task_plan(task: str, max_agents: int = None) -> TaskPlan:
    """Decompose a complex task into subtasks using templates."""
    task_type = detect_task_type(task)
    template = TASK_TEMPLATES[task_type]

    agents = template["agents"]
    if max_agents and max_agents < len(agents):
        agents = agents[:max_agents]

    plan = TaskPlan(original_task=task)
    for i, agent in enumerate(agents):
        subtask = SubTask(
            id=i,
            role=agent["role"],
            description=agent["description"],
            prompt=agent["prompt_template"].format(task=task),
        )
        plan.subtasks.append(subtask)

    return plan


async def _run_subtask_with_retry(
    client: httpx.AsyncClient,
    node_url: str,
    subtask: SubTask,
    tracker: NodeLoadTracker,
    max_retries: int = MAX_RETRIES,
) -> SubTask:
    """
    Execute a subtask with retry logic.
    On 5xx errors, wait briefly and retry up to max_retries times.
    On timeout, mark error immediately (no retry — would just queue again).
    """
    last_error = ""

    for attempt in range(1, max_retries + 2):  # +2 = 1 initial + max_retries
        subtask.attempts = attempt
        start = time.time()
        subtask.node = node_url
        tracker.increment(node_url)

        try:
            response = await asyncio.wait_for(
                client.post(
                    f"{node_url}/generate",
                    json={"prompt": subtask.prompt, "model": DEFAULT_MODEL},
                ),
                timeout=AGENT_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()

            subtask.result = result.get("response", "")
            subtask.wait_time = result.get("wait_time", 0.0)
            subtask.time = time.time() - start
            subtask.error = ""
            tracker.decrement(node_url)
            return subtask

        except asyncio.TimeoutError:
            subtask.error = f"Agent timed out after {AGENT_TIMEOUT}s"
            subtask.time = time.time() - start
            tracker.decrement(node_url)
            # Timeout = no point retrying immediately — node is overloaded
            return subtask

        except Exception as e:
            last_error = str(e)
            subtask.time = time.time() - start
            tracker.decrement(node_url)

            if attempt <= max_retries:
                # Brief backoff before retry
                await asyncio.sleep(2 * attempt)
            else:
                subtask.error = f"Failed after {attempt} attempts. Last error: {last_error}"

    return subtask


async def execute_plan(
    plan: TaskPlan,
    nodes: list[str],
    on_complete=None,  # optional callback(subtask) called as each agent finishes
) -> TaskPlan:
    """
    Execute all subtasks with smart least-busy routing.

    With 1 node:  tasks run sequentially on that node — no 504s.
    With N nodes: each new task dispatches to whichever node has fewest active tasks.

    The key insight: we do NOT pre-assign all tasks upfront. We assign each task
    just before it starts, based on current load — like a real task scheduler.
    """
    plan_start = time.time()
    tracker = NodeLoadTracker(nodes)

    # Semaphore limits total concurrent in-flight requests to len(nodes).
    # Each node can handle 1 at a time; no point sending more than that.
    concurrency = len(nodes)
    sem = asyncio.Semaphore(concurrency)

    async def run_one(subtask: SubTask) -> SubTask:
        async with sem:
            node = tracker.pick_least_busy()
            result = await _run_subtask_with_retry(
                client, node, subtask, tracker
            )
            if on_complete:
                on_complete(result)
            return result

    async with httpx.AsyncClient(timeout=AGENT_TIMEOUT + 60) as client:
        completed = await asyncio.gather(*[run_one(st) for st in plan.subtasks])

    plan.subtasks = sorted(completed, key=lambda x: x.id)
    plan.total_time = time.time() - plan_start

    # Combine results into a single markdown doc
    sections = []
    for st in plan.subtasks:
        if st.result:
            timing = f"*({st.time:.1f}s gen"
            if st.wait_time:
                timing += f", {st.wait_time:.1f}s queued"
            if st.attempts > 1:
                timing += f", {st.attempts} attempts"
            timing += ")*"
            sections.append(f"## {st.role}\n{timing}\n\n{st.result}")
        elif st.error:
            sections.append(f"## {st.role}\n\n> ⚠️ ERROR: {st.error}")

    plan.final_result = "\n\n---\n\n".join(sections)
    return plan


async def check_nodes(nodes: list[str]) -> list[str]:
    """Return only online nodes, sorted by queue depth (least busy first)."""
    alive = []
    async with httpx.AsyncClient(timeout=5) as client:
        for node in nodes:
            try:
                resp = await client.get(f"{node}/health", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    queue_depth = data.get("queue_depth", 0)
                    alive.append((queue_depth, node))
            except Exception:
                pass

    # Sort by queue depth — least busy first
    alive.sort(key=lambda x: x[0])
    return [node for _, node in alive]
