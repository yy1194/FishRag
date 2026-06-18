from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fishrag_agent.planning import utc_now


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    description: str
    system_prompt: str
    tools: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": list(self.tools),
        }


@dataclass(frozen=True)
class SubAgentTask:
    subagent: str
    description: str
    input: str = ""


@dataclass(frozen=True)
class SubAgentResult:
    subagent: str
    description: str
    input: str
    status: str
    output: str
    tools: tuple[str, ...]
    started_at: datetime
    completed_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "subagent": self.subagent,
            "description": self.description,
            "input": self.input,
            "status": self.status,
            "output": self.output,
            "tools": list(self.tools),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


@dataclass
class SubAgentRegistry:
    specs: dict[str, SubAgentSpec] = field(default_factory=dict)

    def register(self, spec: SubAgentSpec) -> None:
        name = spec.name.strip()
        if not name:
            raise ValueError("Sub-agent name cannot be empty.")
        self.specs[name] = SubAgentSpec(
            name=name,
            description=spec.description.strip(),
            system_prompt=spec.system_prompt.strip(),
            tools=tuple(tool.strip() for tool in spec.tools if tool.strip()),
        )

    def get(self, name: str) -> SubAgentSpec:
        normalized_name = name.strip()
        try:
            return self.specs[normalized_name]
        except KeyError as exc:
            raise KeyError(f"Unknown sub-agent: {normalized_name}") from exc

    def list_names(self) -> Sequence[str]:
        return tuple(sorted(self.specs))

    def list_specs(self) -> tuple[SubAgentSpec, ...]:
        return tuple(self.specs[name] for name in sorted(self.specs))


class SubAgentRunner:
    def __init__(self, registry: SubAgentRegistry) -> None:
        self.registry = registry

    async def delegate(self, task: SubAgentTask) -> SubAgentResult:
        if not task.description.strip():
            raise ValueError("Sub-agent task description cannot be empty.")
        spec = self.registry.get(task.subagent)
        started_at = utc_now()
        await asyncio.sleep(0)
        completed_at = utc_now()
        return SubAgentResult(
            subagent=spec.name,
            description=task.description.strip(),
            input=task.input.strip(),
            status="completed",
            output=(
                f"{spec.name} accepted the task and prepared a focused result scaffold. "
                f"Task: {task.description.strip()}"
            ),
            tools=spec.tools,
            started_at=started_at,
            completed_at=completed_at,
        )

    async def delegate_many(self, tasks: Sequence[SubAgentTask]) -> list[SubAgentResult]:
        return list(await asyncio.gather(*(self.delegate(task) for task in tasks)))


def default_subagent_registry() -> SubAgentRegistry:
    registry = SubAgentRegistry()
    registry.register(
        SubAgentSpec(
            name="rag_researcher",
            description="Search the knowledge base and organize evidence with citations.",
            system_prompt=(
                "Focus on retrieval quality, evidence coverage, and citation traceability."
            ),
            tools=("rag_search", "load_skill"),
        )
    )
    registry.register(
        SubAgentSpec(
            name="document_processor",
            description=(
                "Inspect document ingestion, parsing, chunking, embedding, and indexing steps."
            ),
            system_prompt="Focus on document processing correctness and recoverable failures.",
            tools=("load_skill", "write_todos"),
        )
    )
    registry.register(
        SubAgentSpec(
            name="medical_reviewer",
            description="Review medical safety, unsupported claims, and evidence sufficiency.",
            system_prompt="Focus on medical risk, uncertainty, and evidence-grounded phrasing.",
            tools=("load_skill",),
        )
    )
    registry.register(
        SubAgentSpec(
            name="code_reviewer",
            description="Review implementation risk, regressions, and missing tests.",
            system_prompt="Focus on bugs, behavior changes, and verification gaps.",
            tools=("write_todos",),
        )
    )
    return registry
