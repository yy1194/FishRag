from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fishrag_api.db.models import Approval


async def create_approval_record(
    session: AsyncSession,
    *,
    requested_by_user_id: str | None,
    tool_name: str,
    tool_input: dict[str, Any],
) -> Approval:
    approval = Approval(
        requested_by_user_id=requested_by_user_id,
        tool_name=tool_name,
        tool_input=tool_input,
        status="pending",
    )
    session.add(approval)
    await session.commit()
    await session.refresh(approval)
    return approval
