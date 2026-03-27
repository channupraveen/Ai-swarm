"""
SwarmAI Agent Orchestrator
==========================
Splits complex tasks into subtasks and distributes across worker nodes.

FIX LOG (v0.4.0):
    - Added num_predict: 500 to all Ollama calls — caps output to ~500 tokens.
      Without this, phi3:mini generates 1500-3000 tokens per agent = 3-10 min.
      500 tokens = focused, useful output in 15-40s per agent.
    - Shortened prompt templates — removed verbose instructions that cause
      the model to write essays instead of code.
    - Added temperature: 0.3 for more deterministic, faster outputs.
    - Concurrency semaphore still enforces 1 call per node max.
    - Retry logic retained (2 retries on failure).
"""

import asyncio
import time
from dataclasses import dataclass, field

import httpx

# ─── Configuration ───────────────────────────────────────────────

DEFAULT_MODEL = "phi3:mini"
AGENT_TIMEOUT = 300      # 5 min max per agent (was 600)
MAX_RETRIES = 1          # 1 retry on failure (was 2)
MAX_TOKENS = 500         # ← KEY FIX: cap output tokens per agent

# ─── Data Structures ─────────────────────────────────────────────

@dataclass
class SubTask:
    id: int
    role: str
    description: str
    prompt: str
    node: str = ""
    result: str = ""
    time: float = 0.0
    wait_time: float = 0.0
    error: str = ""
    attempts: int = 0


@dataclass
class TaskPlan:
    original_task: str
    subtasks: list[SubTask] = field(default_factory=list)
    final_result: str = ""
    total_time: float = 0.0


# ─── Task Templates (short, focused prompts) ─────────────────────

TASK_TEMPLATES = {
    "rest_api": {
        "keywords": ["rest api", "api", "backend", "endpoints", "routes"],
        "agents": [
            {
                "role": "Database Architect",
                "description": "Design database schema",
                "prompt_template": "Write SQL CREATE TABLE statements for a {task}. Be concise. Show tables, columns, and foreign keys only.",
            },
            {
                "role": "API Developer",
                "description": "Create API endpoints",
                "prompt_template": "List all REST API endpoints for a {task}. For each: method, path, request body, response. Be concise.",
            },
            {
                "role": "Auth Engineer",
                "description": "Implement authentication",
                "prompt_template": "Write JWT authentication code (login + middleware) for a {task} using Python FastAPI. Be concise.",
            },
            {
                "role": "Test Engineer",
                "description": "Write test cases",
                "prompt_template": "Write 5 pytest test cases for a {task} REST API. Cover: create, read, update, delete, auth. Be concise.",
            },
            {
                "role": "Documentation Writer",
                "description": "Write API docs",
                "prompt_template": "Write a short API documentation for a {task}. Include: overview, endpoints table, auth guide. Be concise.",
            },
        ],
    },
    "code_review": {
        "keywords": ["review", "audit", "analyze", "refactor", "security"],
        "agents": [
            {
                "role": "Security Auditor",
                "description": "Check security vulnerabilities",
                "prompt_template": "List the top 5 security issues to check when reviewing: {task}. Be specific and concise.",
            },
            {
                "role": "Performance Analyst",
                "description": "Identify performance issues",
                "prompt_template": "List the top 5 performance issues to check in: {task}. Be specific and concise.",
            },
            {
                "role": "Code Quality Reviewer",
                "description": "Review code quality",
                "prompt_template": "List the top 5 code quality issues to check in: {task}. Focus on SOLID principles. Be concise.",
            },
            {
                "role": "Test Coverage Analyst",
                "description": "Identify missing tests",
                "prompt_template": "List 5 missing test cases for: {task}. Include edge cases. Be concise.",
            },
        ],
    },
    "documentation": {
        "keywords": ["document", "docs", "readme", "guide", "tutorial", "explain"],
        "agents": [
            {
                "role": "Technical Writer",
                "description": "Write technical documentation",
                "prompt_template": "Write a short technical overview for: {task}. Include: what it is, architecture, key components. Max 300 words.",
            },
            {
                "role": "Tutorial Creator",
                "description": "Create step-by-step tutorial",
                "prompt_template": "Write a 5-step quickstart tutorial for: {task}. Include code snippets. Be concise.",
            },
            {
                "role": "API Reference Writer",
                "description": "Write API reference",
                "prompt_template": "Write a concise API reference table for: {task}. Columns: endpoint, method, description, example.",
            },
        ],
    },
    "fullstack": {
        "keywords": ["fullstack", "full stack", "website", "web app", "application", "frontend", "full application"],
        "agents": [
            {
                "role": "Backend Developer",
                "description": "Build server-side logic",
                "prompt_template": "List the backend components needed for: {task}. Include: routes, models, services. Be concise with code snippets.",
            },
            {
                "role": "Frontend Developer",
                "description": "Build user interface",
                "prompt_template": "List the frontend components and pages needed for: {task}. Include component names and their purpose. Be concise.",
            },
            {
                "role": "Database Engineer",
                "description": "Design data layer",
                "prompt_template": "Write the database schema (SQL) for: {task}. Show tables and key relationships only. Be concise.",
            },
            {
                "role": "DevOps Engineer",
                "description": "Set up deployment",
                "prompt_template": "Write a docker-compose.yml for: {task}. Include: app, db, and any required services. Be concise.",
            },
            {
                "role": "Test Engineer",
                "description": "Write tests",
                "prompt_template": "List 5 critical test cases (unit + integration) for: {task}. Be concise.",
            },
        ],
    },
    "general": {
        "keywords": [],
        "agents": [
            {
                "role": "Research Analyst",
                "description": "Research and analyse",
                "prompt_template": "Give a concise analysis of: {task}. List key points, considerations, and recommendations. Max 300 words.",
            },
            {
                "role": "Solution Architect",
                "description": "Design the solution",
                "prompt_template": "Design a solution for: {task}. List: components, technology stack, and architecture. Be concise.",
            },
            {
                "role": "Implementation Specialist",
                "description": "Write implementation",
                "prompt_template": "Write the core implementation code for: {task}. Focus on the most important part only. Be concise.",
            },
            {
                "role": "Quality Reviewer",
                "description": "Review and improve",
                "prompt_template": "List 5 improvements and potential issues for: {task}. Be specific and concise.",
            },
        ],
    },
}


# ─── Node Load Tracker ───────────────────────────────────────────

class NodeLoadTracker:
    def __init__(self, nodes: list[str]):
        self._load: dict[str, int] = {n: 0 for n in nodes}

    def pick_least_busy(self) -> str:
        return min(self._load, key=self._load.get)

    def increment(self, node: str):
        self._load[node] = self._load.get(node, 0) + 1

    def decrement(self, node: str):
        self._load[node] = max(0, self._load.get(node, 1) - 1)


# ─── Orchestrator Engine ─────────────────────────────────────────

def detect_task_type(task: str) -> str:
    task_lower = task.lower()
    for name, template in TASK_TEMPLATES.items():
        if name == "general":
            continue
        if any(kw in task_lower for kw in template["keywords"]):
            return name
    return "general"


def create_task_plan(task: str, max_agents: int = None) -> TaskPlan:
    task_type = detect_task_type(task)
    template = TASK_TEMPLATES[task_type]
    agents = template["agents"]
    if max_agents and max_agents < len(agents):
        agents = agents[:max_agents]

    plan = TaskPlan(original_task=task)
    for i, agent in enumerate(agents):
        plan.subtasks.append(SubTask(
            id=i,
            role=agent["role"],
            description=agent["description"],
            prompt=agent["prompt_template"].format(task=task),
        ))
    return plan


async def _run_subtask_with_retry(
    client: httpx.AsyncClient,
    node_url: str,
    subtask: SubTask,
    tracker: NodeLoadTracker,
) -> SubTask:
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 2):
        subtask.attempts = attempt
        start = time.time()
        subtask.node = node_url
        tracker.increment(node_url)

        try:
            response = await asyncio.wait_for(
                client.post(
                    f"{node_url}/generate",
                    json={
                        "prompt": subtask.prompt,
                        "model": DEFAULT_MODEL,
                        "num_predict": MAX_TOKENS,   # ← caps output length
                        "temperature": 0.3,          # ← faster, focused output
                    },
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
            subtask.error = f"Timed out after {AGENT_TIMEOUT}s"
            subtask.time = time.time() - start
            tracker.decrement(node_url)
            return subtask

        except Exception as e:
            last_error = str(e)
            subtask.time = time.time() - start
            tracker.decrement(node_url)
            if attempt <= MAX_RETRIES:
                await asyncio.sleep(2 * attempt)
            else:
                subtask.error = f"Failed after {attempt} attempts: {last_error}"

    return subtask


async def execute_plan(
    plan: TaskPlan,
    nodes: list[str],
    on_complete=None,
) -> TaskPlan:
    plan_start = time.time()
    tracker = NodeLoadTracker(nodes)
    sem = asyncio.Semaphore(len(nodes))

    async def run_one(subtask: SubTask) -> SubTask:
        async with sem:
            node = tracker.pick_least_busy()
            result = await _run_subtask_with_retry(client, node, subtask, tracker)
            if on_complete:
                on_complete(result)
            return result

    async with httpx.AsyncClient(timeout=AGENT_TIMEOUT + 60) as client:
        completed = await asyncio.gather(*[run_one(st) for st in plan.subtasks])

    plan.subtasks = sorted(completed, key=lambda x: x.id)
    plan.total_time = time.time() - plan_start

    sections = []
    for st in plan.subtasks:
        if st.result:
            timing = f"*({st.time:.1f}s"
            if st.wait_time > 0.5:
                timing += f", {st.wait_time:.1f}s queued"
            timing += ")*"
            sections.append(f"## {st.role}\n{timing}\n\n{st.result}")
        elif st.error:
            sections.append(f"## {st.role}\n\n> ⚠️ ERROR: {st.error}")

    plan.final_result = "\n\n---\n\n".join(sections)
    return plan


async def check_nodes(nodes: list[str]) -> list[str]:
    alive = []
    async with httpx.AsyncClient(timeout=5) as client:
        for node in nodes:
            try:
                resp = await client.get(f"{node}/health", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    alive.append((data.get("queue_depth", 0), node))
            except Exception:
                pass
    alive.sort(key=lambda x: x[0])
    return [node for _, node in alive]
