"""
dispatch.py — Pipeline orchestrator (Phase 4).

Flow:
  ingest (audited) → classify (Ollama, temperature=0, validated tokens only)
  → route → execute → failure classification → audit → response

Classification uses the local model only (no LoopLM / adapter loops on the hot path).
Tool execution always goes through sandbox.run() (subprocess isolation).
"""

from __future__ import annotations

import logging
from typing import Any

import audit
from classification import classify
from failure_classifier import annotate_result_dict, classify_failure
from models import NormalisedEnvelope, RoutingTarget
from routing import route_cloud_llm, route_local_llm
from tools import execute as tools_execute

logger = logging.getLogger("gateway.dispatch")


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
            tool_result = await tools_execute(envelope)
            no_intent = tool_result.tool_name == "none" or (
                tool_result.error and "No matching tool intent" in tool_result.error
            )
            result: dict[str, Any] = {
                "routed_to": "LOCAL_TOOLS",
                "tool": tool_result.tool_name,
                "success": tool_result.success,
                "data": tool_result.data,
                "error": tool_result.error,
                "sandbox_elapsed": tool_result.sandbox_elapsed,
                "execution_duration_ms": tool_result.execution_duration_ms,
                "executed_in_sandbox_worker": tool_result.executed_in_sandbox_worker,
                "sandbox_timeout": tool_result.sandbox_timeout,
            }
            fail = classify_failure(
                routed_to="LOCAL_TOOLS",
                tool_name=tool_result.tool_name,
                tool_success=tool_result.success,
                tool_error=tool_result.error,
                no_matching_tool_intent=no_intent,
            )
            result = annotate_result_dict(result, fail)

            await audit.append(
                kind="tool",
                input_summary=input_summary,
                decision=target,
                route="LOCAL_TOOLS",
                tool=tool_result.tool_name,
                result_summary=(
                    str(tool_result.data)[:200] if tool_result.success else None
                ),
                error=tool_result.error,
                metadata={
                    **base_meta,
                    "failure_reason": fail,
                    "tool_execution_duration_ms": tool_result.execution_duration_ms,
                    "tool_executed_in_sandbox_worker": tool_result.executed_in_sandbox_worker,
                    "tool_sandbox_timeout": tool_result.sandbox_timeout,
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
