from __future__ import annotations

from typing import Any

from sqlalchemy.types import UserDefinedType


class VectorType(UserDefinedType[Any]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimensions})"
