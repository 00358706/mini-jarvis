"""
dispatch.py — Pipeline orchestrator (Phase 4).

Flow:
  ingest (audited) → classify (Ollama, temperature=0, validated tokens only)
  → route → branch handler → failure classification → audit → response

Classification uses the local model only (no LoopLM / adapter loops on the hot path).
Installed tool execution from the gateway uses sandbox.run() (subprocess isolation),
but ``LOCAL_TOOLS`` on ``/ingest`` is gated: it does not call ``tools.execute`` by
default; use the plan proposal and ``/plans/*`` approval path for execution.
"""

from __future__ import annotations

import logging
from typing import Any

import audit
from classification import classify
from failure_classifier import annotate_result_dict, classify_failure
from models import NormalisedEnvelope, RoutingTarget
from routing import route_cloud_llm, route_local_llm

logger = logging.getLogger("gateway.dispatch")

_INGEST_LOCAL_TOOLS_GATE_MESSAGE = (
    "Tool-related request detected. POST /ingest does not execute installed tools "
    "directly. Create a pending plan (for example POST /plans/from-message where "
    "supported, or POST /plans/propose with a structured plan), obtain explicit "
    "approval, then POST /plans/{plan_id}/execute."
)


async def process(envelope: NormalisedEnvelope) -> dict[str, Any]:
    """
    Main dispatch pipeline.

    Returns a dict suitable for GatewayResponse.result (includes routed_to,
    branch-specific fields, and optional fail_reason).
    """
    audit_kind = "event" if envelope.modality == "event" else "ingest"
    routing_text = (envelope.text_content or "").strip() or str(envelope.content)[:500]
    input_summary = routing_text[:200]

    await audit.append(
        kind=audit_kind,
        input_summary=input_summary,
        metadata={
            "modality": envelope.modality,
            "source_device": envelope.source_device,
        },
    )

    classifier_result = await classify(envelope)
    target: RoutingTarget = classifier_result.target

    logger.info(
        "dispatch | target=%s confidence=%.2f backend=%s modality=%s source=%s",
        target,
        classifier_result.confidence,
        classifier_result.classifier_backend,
        envelope.modality,
        envelope.source_device,
    )

    base_meta = {
        "classifier_backend": classifier_result.classifier_backend,
        "classifier_confidence": classifier_result.confidence,
    }

    match target:

        case "LOCAL_TOOLS":
            result: dict[str, Any] = {
                "routed_to": "LOCAL_TOOLS",
                "lane": "plan_proposal_required",
                "tool_executed": False,
                "sandbox_worker_invoked": False,
                "approval_required": True,
                "message": _INGEST_LOCAL_TOOLS_GATE_MESSAGE,
            }
            fail = classify_failure(
                routed_to="LOCAL_TOOLS",
                ingest_tool_execution_gated=True,
            )
            result = annotate_result_dict(result, fail)

            await audit.append(
                kind="route",
                input_summary=input_summary,
                decision=target,
                route="LOCAL_TOOLS",
                result_summary="Ingest tool execution gated; plan/approval flow required.",
                metadata={
                    **base_meta,
                    "failure_reason": fail,
                    "gate": "ingest_tool_execution_disabled",
                    "tool_executed": False,
                    "sandbox_worker_invoked": False,
                    "approval_required": True,
                },
            )
            return result

        case "LOCAL_LLM":
            llm_result = await route_local_llm(envelope)
            reply = llm_result.get("reply")
            err = llm_result.get("error")
            result = {"routed_to": "LOCAL_LLM", **llm_result}
            fail = classify_failure(
                routed_to="LOCAL_LLM",
                llm_reply=reply if isinstance(reply, str) else None,
                llm_error=err if isinstance(err, str) else None,
            )
            result = annotate_result_dict(result, fail)

            await audit.append(
                kind="route",
                input_summary=input_summary,
                decision=target,
                route="LOCAL_LLM",
                result_summary=(str(reply)[:200] if reply else None),
                error=err if isinstance(err, str) else None,
                metadata={**base_meta, "failure_reason": fail},
            )
            return result

        case "CLOUD_LLM":
            cloud_result = await route_cloud_llm(envelope)
            blocked = bool(cloud_result.get("blocked"))
            reply = cloud_result.get("reply")
            err = cloud_result.get("error")
            result = {"routed_to": "CLOUD_LLM", **cloud_result}
            fail = classify_failure(
                routed_to="CLOUD_LLM",
                llm_reply=reply if isinstance(reply, str) else None,
                llm_error=err if isinstance(err, str) else None,
                cloud_blocked=blocked,
            )
            result = annotate_result_dict(result, fail)

            await audit.append(
                kind="route",
                input_summary=input_summary,
                decision=target,
                route="CLOUD_LLM",
                result_summary=(str(reply)[:200] if reply else None),
                error=err if isinstance(err, str) else None,
                metadata={
                    **base_meta,
                    "failure_reason": fail,
                    "cloud_blocked": blocked,
                },
            )
            return result

        case "DROP":
            result = {
                "routed_to": "DROP",
                "reason": "Input classified as empty, malformed, or unsafe.",
            }
            fail = classify_failure(routed_to="DROP")
            result = annotate_result_dict(result, fail)
            await audit.append(
                kind="drop",
                input_summary=input_summary,
                decision="DROP",
                route="DROP",
                result_summary="Classified as empty, malformed, or unsafe.",
                metadata={**base_meta, "failure_reason": fail},
            )
            return result

        case _:
            result = {
                "routed_to": "DROP",
                "reason": f"Unexpected routing target {target!r} (internal error).",
            }
            fail = classify_failure(
                routed_to="DROP",
                validation_error="internal routing token mismatch",
            )
            result = annotate_result_dict(result, fail)
            await audit.append(
                kind="error",
                input_summary=input_summary,
                error=f"Unexpected routing target '{target}'.",
                metadata={**base_meta, "failure_reason": fail},
            )
            return result
