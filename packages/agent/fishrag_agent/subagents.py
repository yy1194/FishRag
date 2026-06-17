from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    description: str
    system_prompt: str
    tools: tuple[str, ...] = ()


@dataclass
class SubAgentRegistry:
    specs: dict[str, SubAgentSpec] = field(default_factory=dict)

    def register(self, spec: SubAgentSpec) -> None:
        if not spec.name.strip():
            raise ValueError("Sub-agent name cannot be empty.")
        self.specs[spec.name] = spec

    def get(self, name: str) -> SubAgentSpec:
        try:
            return self.specs[name]
        except KeyError as exc:
            raise KeyError(f"Unknown sub-agent: {name}") from exc

    def list_names(self) -> Sequence[str]:
        return tuple(sorted(self.specs))
