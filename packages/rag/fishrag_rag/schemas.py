from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentChunk:
    index: int
    text: str
    start: int
    end: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)
