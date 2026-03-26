"""
SwarmAI Agent Orchestrator
==========================
Phase 2: Splits complex tasks into independent subtasks and distributes
them across worker nodes for parallel execution.

This is the brain that turns a single complex request into multiple
parallel LLM calls across your swarm.

Usage via CLI:
    python swarm.py orchestrate "Build a REST API for a blog system"
    python swarm.py orchestrate "Refactor this code for NABH compliance" --agents 6
"""

import asyncio
import time
import json
from dataclasses import dataclass, field

import httpx

# ─── Configuration ───────────────────────────────────────────────

DEFAULT_MODEL = "phi3:mini"

# ─── Data Structures ─────────────────────────────────────────────


@dataclass
class SubTask:
    """A single subtask assigned to an agent."""
    id: int
    role: str          # e.g. "Database Architect", "API Developer"
    description: str   # what this agent should do
    prompt: str        # actual prompt sent to LLM
    node: str = ""     # which node processed it
    result: str = ""   # LLM response
    time: float = 0.0  # seconds taken
    error: str = ""


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
                "prompt_template": "You are a Database Architect. Design the complete database schema with tables, columns, relationships, and constraints for: {task}. Provide the SQL CREATE TABLE statements or ORM model definitions.",
            },
            {
                "role": "API Developer",
                "description": "Create the API endpoints and routes",
                "prompt_template": "You are an API Developer. Design and write all the REST API endpoints (GET, POST, PUT, DELETE) with request/response schemas for: {task}. Include route definitions, request validation, and response formats.",
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
                "prompt_template": "You are a Documentation Writer. Write complete API documentation for: {task}. Include endpoint descriptions, request/response examples, authentication guide, setup instructions, and a README.",
            },
        ],
    },
    "code_review": {
        "keywords": ["review", "audit", "analyze", "refactor", "security"],
        "agents": [
            {
                "role": "Security Auditor",
                "description": "Check for security vulnerabilities",
                "prompt_template": "You are a Security Auditor. Analyze the following for security vulnerabilities, injection risks, authentication weaknesses, and data exposure: {task}. Provide specific findings and fixes.",
            },
            {
                "role": "Performance Analyst",
                "description": "Identify performance bottlenecks",
                "prompt_template": "You are a Performance Analyst. Analyze the following for performance issues, N+1 queries, memory leaks, slow algorithms, and optimization opportunities: {task}. Provide specific recommendations.",
            },
            {
                "role": "Code Quality Reviewer",
                "description": "Review code quality and patterns",
                "prompt_template": "You are a Code Quality Reviewer. Review the following for code quality, design patterns, SOLID principles, naming conventions, and maintainability: {task}. Suggest specific improvements.",
            },
            {
                "role": "Test Coverage Analyst",
                "description": "Identify missing test coverage",
                "prompt_template": "You are a Test Coverage Analyst. Analyze the following and identify missing test cases, untested edge cases, and gaps in test coverage: {task}. Provide specific test cases to add.",
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
                "prompt_template": "You are a Research Analyst. Provide thorough research and analysis on: {task}. Include key findings, data points, and sources.",
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


async def execute_subtask(
    client: httpx.AsyncClient, node_url: str, subtask: SubTask
) -> SubTask:
    """Execute a single subtask on a worker node."""
    start = time.time()
    subtask.node = node_url

    try:
        response = await client.post(
            f"{node_url}/generate",
            json={"prompt": subtask.prompt, "model": DEFAULT_MODEL},
        )
        response.raise_for_status()
        result = response.json()
        subtask.result = result.get("response", "")
        subtask.time = time.time() - start
    except Exception as e:
        subtask.error = str(e)
        subtask.time = time.time() - start

    return subtask


async def execute_plan(plan: TaskPlan, nodes: list[str]) -> TaskPlan:
    """Execute all subtasks in parallel across available nodes."""
    start = time.time()

    tasks = []
    async with httpx.AsyncClient(timeout=300) as client:
        for i, subtask in enumerate(plan.subtasks):
            node = nodes[i % len(nodes)]
            tasks.append(execute_subtask(client, node, subtask))

        completed = await asyncio.gather(*tasks)

    plan.subtasks = sorted(completed, key=lambda x: x.id)
    plan.total_time = time.time() - start

    # Combine results
    sections = []
    for st in plan.subtasks:
        if st.result:
            sections.append(f"## {st.role}\n\n{st.result}")
        elif st.error:
            sections.append(f"## {st.role}\n\n[ERROR: {st.error}]")

    plan.final_result = "\n\n---\n\n".join(sections)

    return plan


async def check_nodes(nodes: list[str]) -> list[str]:
    """Return only online nodes."""
    alive = []
    async with httpx.AsyncClient(timeout=5) as client:
        for node in nodes:
            try:
                resp = await client.get(f"{node}/health")
                if resp.status_code == 200:
                    alive.append(node)
            except Exception:
                pass
    return alive
