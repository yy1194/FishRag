from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DocumentChunk:
    index: int
    text: str
    start: int
    end: int
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)
