from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fishrag_rag.evaluation import RagEvaluationReport

RagEvaluationJobStatus = Literal["running", "completed", "failed"]
RagEvaluationJobMode = Literal["scored_dataset", "auto_rag"]


@dataclass(frozen=True)
class RagEvaluationJobRecord:
    id: str
    name: str
    status: RagEvaluationJobStatus
    mode: RagEvaluationJobMode
    ks: tuple[int, ...]
    example_count: int
    created_at: datetime
    updated_at: datetime
    report: RagEvaluationReport | None = None
    error: str | None = None


class InMemoryRagEvaluationJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, RagEvaluationJobRecord] = {}

    def create(
        self,
        *,
        name: str,
        mode: RagEvaluationJobMode,
        ks: tuple[int, ...],
        example_count: int,
    ) -> RagEvaluationJobRecord:
        now = _utc_now()
        job = RagEvaluationJobRecord(
            id=str(uuid4()),
            name=name.strip() or "RAG Evaluation",
            status="running",
            mode=mode,
            ks=ks,
            example_count=example_count,
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.id] = job
        return job

    def complete(
        self,
        job_id: str,
        *,
        report: RagEvaluationReport,
    ) -> RagEvaluationJobRecord:
        job = self.get(job_id)
        updated = RagEvaluationJobRecord(
            id=job.id,
            name=job.name,
            status="completed",
            mode=job.mode,
            ks=job.ks,
            example_count=job.example_count,
            created_at=job.created_at,
            updated_at=_utc_now(),
            report=report,
        )
        self._jobs[job_id] = updated
        return updated

    def fail(self, job_id: str, *, error: str) -> RagEvaluationJobRecord:
        job = self.get(job_id)
        updated = RagEvaluationJobRecord(
            id=job.id,
            name=job.name,
            status="failed",
            mode=job.mode,
            ks=job.ks,
            example_count=job.example_count,
            created_at=job.created_at,
            updated_at=_utc_now(),
            error=error,
        )
        self._jobs[job_id] = updated
        return updated

    def get(self, job_id: str) -> RagEvaluationJobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise ValueError("RAG evaluation job not found.") from exc

    def list(self, *, limit: int = 50) -> list[RagEvaluationJobRecord]:
        jobs = sorted(self._jobs.values(), key=lambda job: job.updated_at, reverse=True)
        return jobs[:limit]

    def clear(self) -> None:
        self._jobs.clear()


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)
