from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ApprovalRule:
    tool_name: str
    reason: str
    risk_level: str = "high"
    categories: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovalCheck:
    requires_approval: bool
    tool_name: str
    reason: str | None = None
    risk_level: str = "low"
    categories: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "requires_approval": self.requires_approval,
            "tool_name": self.tool_name,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "categories": list(self.categories),
        }


class ApprovalRequestHandler(Protocol):
    async def request_approval(
        self,
        *,
        session_id: str,
        user_input: str,
        tool_name: str,
        tool_arguments: Mapping[str, Any],
        check: ApprovalCheck,
    ) -> Mapping[str, Any]:
        """Persist or dispatch an approval request and return metadata."""


class ApprovalPolicy:
    def __init__(self, rules: list[ApprovalRule]) -> None:
        self.rules = {rule.tool_name: rule for rule in rules}

    def evaluate(self, *, tool_name: str, arguments: Mapping[str, Any]) -> ApprovalCheck:
        normalized_tool_name = tool_name.strip()
        rule = self.rules.get(normalized_tool_name)
        if rule is not None:
            return ApprovalCheck(
                requires_approval=True,
                tool_name=normalized_tool_name,
                reason=rule.reason,
                risk_level=rule.risk_level,
                categories=rule.categories,
            )

        if _has_explicit_high_risk_flag(arguments):
            return ApprovalCheck(
                requires_approval=True,
                tool_name=normalized_tool_name,
                reason="Tool arguments explicitly mark this action as high risk.",
                risk_level="high",
                categories=("explicit_high_risk",),
            )

        return ApprovalCheck(requires_approval=False, tool_name=normalized_tool_name)


@dataclass(frozen=True)
class MedicalSafetyAssessment:
    high_risk: bool
    blocked: bool
    reasons: tuple[str, ...] = ()
    disclaimer: str = (
        "本回答仅用于知识库资料辅助阅读，不能替代医生诊断、治疗建议或监管要求；"
        "涉及诊疗决策时请由具备资质的专业人员结合完整病情复核。"
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "high_risk": self.high_risk,
            "blocked": self.blocked,
            "reasons": list(self.reasons),
            "disclaimer": self.disclaimer,
        }


@dataclass(frozen=True)
class SafeAnswer:
    answer: str
    is_answered: bool
    assessment: MedicalSafetyAssessment


HIGH_RISK_MEDICAL_KEYWORDS = (
    "诊断",
    "确诊",
    "处方",
    "剂量",
    "用量",
    "停药",
    "换药",
    "手术",
    "急救",
    "禁忌",
    "不良反应",
    "diagnosis",
    "diagnose",
    "prescription",
    "dosage",
    "surgery",
    "emergency",
)


def default_approval_policy() -> ApprovalPolicy:
    return ApprovalPolicy(
        [
            ApprovalRule(
                tool_name="delete_document",
                reason="Deleting knowledge base documents requires human approval.",
                categories=("knowledge_base_mutation",),
            ),
            ApprovalRule(
                tool_name="bulk_import_documents",
                reason="Bulk document import can overwrite or pollute the knowledge base.",
                categories=("knowledge_base_mutation", "bulk_operation"),
            ),
            ApprovalRule(
                tool_name="rebuild_index",
                reason="Rebuilding indexes can affect retrieval quality and availability.",
                categories=("index_mutation", "bulk_operation"),
            ),
            ApprovalRule(
                tool_name="delete_vectors",
                reason="Deleting vectors can make indexed evidence unretrievable.",
                categories=("index_mutation", "destructive_operation"),
            ),
            ApprovalRule(
                tool_name="external_api_call",
                reason="External or paid API calls require review before execution.",
                categories=("external_api", "cost_control"),
            ),
            ApprovalRule(
                tool_name="file_write",
                reason="File writes require review before changing persistent artifacts.",
                categories=("filesystem_mutation",),
            ),
            ApprovalRule(
                tool_name="shell",
                reason="System command execution requires review.",
                risk_level="critical",
                categories=("system_command",),
            ),
            ApprovalRule(
                tool_name="high_risk_medical_answer",
                reason="High-risk medical advice requires reviewer approval.",
                risk_level="critical",
                categories=("medical_safety",),
            ),
        ]
    )


def assess_medical_safety(
    *,
    query: str,
    answer: str,
    citation_count: int,
) -> MedicalSafetyAssessment:
    haystack = f"{query}\n{answer}".lower()
    matched = tuple(
        keyword for keyword in HIGH_RISK_MEDICAL_KEYWORDS if keyword.lower() in haystack
    )
    high_risk = bool(matched)
    blocked = high_risk and citation_count == 0
    reasons: list[str] = []
    if matched:
        reasons.append(f"Matched high-risk medical terms: {', '.join(matched[:8])}.")
    if blocked:
        reasons.append("High-risk medical content has no supporting citations.")
    return MedicalSafetyAssessment(
        high_risk=high_risk,
        blocked=blocked,
        reasons=tuple(reasons),
    )


def apply_medical_safety_guard(
    *,
    query: str,
    answer: str,
    citation_count: int,
) -> SafeAnswer:
    assessment = assess_medical_safety(
        query=query,
        answer=answer,
        citation_count=citation_count,
    )
    if assessment.blocked:
        return SafeAnswer(
            answer=(
                "该问题可能涉及高风险医学决策，且当前知识库回答没有足够引用证据支撑，"
                "因此已拦截直接回答。请补充权威资料或提交人工医学审核。"
            ),
            is_answered=False,
            assessment=assessment,
        )
    if assessment.high_risk and assessment.disclaimer not in answer:
        return SafeAnswer(
            answer=f"{answer}\n\n{assessment.disclaimer}",
            is_answered=True,
            assessment=assessment,
        )
    return SafeAnswer(answer=answer, is_answered=True, assessment=assessment)


def _has_explicit_high_risk_flag(arguments: Mapping[str, Any]) -> bool:
    value = arguments.get("requires_approval") or arguments.get("high_risk")
    return value is True
