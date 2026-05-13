"""
Workspace mirror helpers for plan proposal / policy state (readable evidence only).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from agent_loader import load_agent
from plans import Plan
from workspace import (
    create_workspace,
    write_agent,
    write_context,
    write_plan,
    write_policy_decision,
    write_request,
    write_route,
    workspace_path,
)

logger = logging.getLogger("gateway")


def workspace_exists_active(task_id: str) -> bool:
    return workspace_path(task_id, state="active").is_dir()


def route_metadata_for_plan(plan: Plan) -> dict:
    return {
        "plan_id": plan.plan_id,
        "agent": plan.agent,
        "risk": plan.risk,
        "requires_approval": plan.requires_approval,
        "status": plan.status,
        "source": "plans_api",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": "/plans/propose",
    }


def ensure_workspace_for_plan(plan: Plan) -> None:
    route_meta = route_metadata_for_plan(plan)
    if not workspace_exists_active(plan.plan_id):
        create_workspace(
            task_id=plan.plan_id,
            request_text="# Request\n\nPlan proposed via /plans/propose.\n",
            metadata=route_meta,
        )
    else:
        write_request(plan.plan_id, "# Request\n\nPlan proposed via /plans/propose.\n")
        write_route(plan.plan_id, route_meta, state="active")


def write_workspace_policy_state(plan: Plan, decision: dict) -> None:
    ensure_workspace_for_plan(plan)
    write_plan(plan.plan_id, plan)
    write_policy_decision(plan.plan_id, decision)


def write_workspace_agent_context(plan: Plan, agent_tool_policy_note: str | None = None) -> None:
    source_endpoint = "/plans/propose"
    agent_id = (plan.agent or "").strip() or "unknown_agent"
    try:
        cfg = load_agent(agent_id)
        agent_md = (
            f"# Agent context\n\n"
            f"- agent id: `{cfg.agent_id}`\n"
            f"- display name: `{cfg.display_name or 'n/a'}`\n"
            f"- version: `{cfg.version or 'n/a'}`\n"
            f"- purpose: {cfg.purpose or 'n/a'}\n"
            f"- parsed_with_yaml_library: `{cfg.parsed_with_yaml_library}`\n\n"
            f"## agent.yaml summary\n\n"
            f"```json\n{json.dumps(cfg.agent_yaml_data, indent=2, default=str)}\n```\n\n"
            f"## prompt.md\n\n{cfg.prompt_md or '_missing_'}\n\n"
            f"## tools.yaml\n\n```yaml\n{cfg.tools_yaml or '# missing'}\n```\n\n"
            f"## policy.yaml\n\n```yaml\n{cfg.policy_yaml or '# missing'}\n```\n\n"
            f"## examples.md\n\n{cfg.examples_md or '_missing_'}\n"
        )
    except FileNotFoundError:
        agent_md = (
            "# Agent context\n\n"
            f"Agent folder was not found for `{agent_id}`.\n\n"
            "Policy and registry still decide whether a plan is allowed.\n"
        )

    context_md = (
        "# Context\n\n"
        "This is the readable context used for planning/review.\n\n"
        f"- Plan id: `{plan.plan_id}`\n"
        f"- Agent id: `{agent_id}`\n"
        f"- Risk level: `{plan.risk}`\n"
        f"- Requires approval: `{plan.requires_approval}`\n"
        f"- Source endpoint: `{source_endpoint}`\n\n"
        + (f"- Agent tool policy: {agent_tool_policy_note}\n\n" if agent_tool_policy_note else "")
        + "This workspace is readable state only. Policy, registry, approval state, "
        "and sandbox execution remain authoritative.\n"
    )
    write_agent(plan.plan_id, agent_md, state="active")
    write_context(plan.plan_id, context_md, state="active")
