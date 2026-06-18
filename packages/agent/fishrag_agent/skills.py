from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    triggers: tuple[str, ...] = ()
    version: str = "0.1.0"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "version": self.version,
        }


@dataclass(frozen=True)
class SkillPackage:
    metadata: SkillMetadata
    instructions: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.as_dict(),
            "instructions": self.instructions,
        }


@dataclass(frozen=True)
class SkillSpec:
    metadata: SkillMetadata
    instructions: str


class SkillRegistry:
    def __init__(self, specs: list[SkillSpec] | None = None) -> None:
        self._lock = RLock()
        self._specs_by_name: dict[str, SkillSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: SkillSpec) -> None:
        if not spec.metadata.name.strip():
            raise ValueError("Skill name cannot be empty.")
        if not spec.instructions.strip():
            raise ValueError(f"Skill instructions cannot be empty: {spec.metadata.name}")
        with self._lock:
            self._specs_by_name[spec.metadata.name] = spec

    def list_metadata(self) -> tuple[SkillMetadata, ...]:
        with self._lock:
            specs = tuple(self._specs_by_name.values())
        return tuple(spec.metadata for spec in sorted(specs, key=lambda item: item.metadata.name))

    def load(self, name: str) -> SkillPackage:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Skill name cannot be empty.")
        with self._lock:
            spec = self._specs_by_name.get(normalized_name)
        if spec is None:
            raise KeyError(f"Unknown skill: {normalized_name}")
        return SkillPackage(metadata=spec.metadata, instructions=spec.instructions)


def default_skill_registry() -> SkillRegistry:
    return SkillRegistry(
        [
            SkillSpec(
                metadata=SkillMetadata(
                    name="rag_answering",
                    description=(
                        "Use retrieved evidence to answer with citations and uncertainty handling."
                    ),
                    triggers=("RAG", "knowledge_base", "citations"),
                ),
                instructions=(
                    "Always search the knowledge base before answering factual medical questions. "
                    "Use citation IDs in the answer and state uncertainty when evidence is missing."
                ),
            ),
            SkillSpec(
                metadata=SkillMetadata(
                    name="document_ingestion",
                    description=(
                        "Guide document parsing, chunking, embedding, and keyword indexing."
                    ),
                    triggers=("upload", "parse", "index"),
                ),
                instructions=(
                    "Follow the ingestion sequence: upload, parse, chunk, embed, keyword-index. "
                    "Record failures in document status metadata and keep chunk provenance intact."
                ),
            ),
            SkillSpec(
                metadata=SkillMetadata(
                    name="medical_review",
                    description=(
                        "Review answers for medical safety, evidence coverage, and disclaimers."
                    ),
                    triggers=("medical", "safety", "review"),
                ),
                instructions=(
                    "Flag unsupported diagnosis or treatment claims. "
                    "Require citations for clinical facts "
                    "and keep the assistant framed as a knowledge support tool."
                ),
            ),
            SkillSpec(
                metadata=SkillMetadata(
                    name="task_planning",
                    description=(
                        "Break complex work into tracked todos and update progress as work changes."
                    ),
                    triggers=("plan", "todo", "stage"),
                ),
                instructions=(
                    "Create short actionable todos. "
                    "Keep at most one item in progress and update statuses "
                    "after each meaningful step."
                ),
            ),
        ]
    )
