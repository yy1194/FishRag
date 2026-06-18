from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.db.models import RagEvaluationJob, utc_now

RagEvaluationJobStatus = Literal["queued", "running", "completed", "failed"]
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
    owner_user_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parameters: dict[str, Any] | None = None
    examples: list[dict[str, Any]] | None = None
    report: dict[str, Any] | None = None
    error: str | None = None


class SqlAlchemyRagEvaluationJobStore:
    async def create_queued(
        self,
        session: AsyncSession,
        *,
        name: str,
        mode: RagEvaluationJobMode,
        ks: tuple[int, ...],
        example_count: int,
        parameters: dict[str, Any],
        examples: list[dict[str, Any]],
        owner_user_id: str | None = None,
    ) -> RagEvaluationJobRecord:
        now = utc_now()
        job = RagEvaluationJob(
            id=str(uuid4()),
            owner_user_id=owner_user_id,
            name=name.strip() or "RAG Evaluation",
            status="queued",
            mode=mode,
            ks=list(ks),
            example_count=example_count,
            parameters=dict(parameters),
            examples=list(examples),
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return _to_record(job)

    async def mark_running(
        self,
        session: AsyncSession,
        job_id: str,
    ) -> RagEvaluationJobRecord:
        job = await _get_job(session, job_id)
        now = utc_now()
        job.status = "running"
        job.started_at = now
        job.completed_at = None
        job.updated_at = now
        job.error = None
        await session.commit()
        await session.refresh(job)
        return _to_record(job)

    async def complete(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        report: dict[str, Any],
    ) -> RagEvaluationJobRecord:
        job = await _get_job(session, job_id)
        now = utc_now()
        job.status = "completed"
        job.report = dict(report)
        job.error = None
        job.completed_at = now
        job.updated_at = now
        await session.commit()
        await session.refresh(job)
        return _to_record(job)

    async def fail(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        error: str,
    ) -> RagEvaluationJobRecord:
        job = await _get_job(session, job_id)
        now = utc_now()
        job.status = "failed"
        job.error = error
        job.completed_at = now
        job.updated_at = now
        await session.commit()
        await session.refresh(job)
        return _to_record(job)

    async def get(self, session: AsyncSession, job_id: str) -> RagEvaluationJobRecord:
        return _to_record(await _get_job(session, job_id))

    async def list(self, session: AsyncSession, *, limit: int = 50) -> list[RagEvaluationJobRecord]:
        result = await session.execute(
            select(RagEvaluationJob).order_by(RagEvaluationJob.updated_at.desc()).limit(limit)
        )
        jobs = list(result.scalars().all())
        return [_to_record(job) for job in jobs]


async def _get_job(session: AsyncSession, job_id: str) -> RagEvaluationJob:
    job = await session.get(RagEvaluationJob, job_id)
    if job is None:
        raise ValueError("RAG evaluation job not found.")
    return job


def _to_record(job: RagEvaluationJob) -> RagEvaluationJobRecord:
    return RagEvaluationJobRecord(
        id=job.id,
        name=job.name,
        status=_job_status(job.status),
        mode=_job_mode(job.mode),
        ks=tuple(int(k) for k in job.ks),
        example_count=job.example_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        owner_user_id=job.owner_user_id,
        started_at=job.started_at,
        completed_at=job.completed_at,
        parameters=dict(job.parameters or {}),
        examples=list(job.examples or []),
        report=dict(job.report) if job.report is not None else None,
        error=job.error,
    )


def _job_status(value: str) -> RagEvaluationJobStatus:
    if value == "running":
        return "running"
    if value == "completed":
        return "completed"
    if value == "failed":
        return "failed"
    return "queued"


def _job_mode(value: str) -> RagEvaluationJobMode:
    if value == "auto_rag":
        return "auto_rag"
    return "scored_dataset"
