from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

import audit
import registry as reg
from models import ToolApprovalRequest, ToolProposal

logger = logging.getLogger("gateway")

router = APIRouter()


@router.get("/tools")
async def list_tools():
    """List all tools in the registry (all lifecycle states)."""
    tools = reg.all_tools()
    return {
        "count": len(tools),
        "tools": [t.model_dump(mode="json") for t in tools],
    }


@router.get("/tools/{name}/{version}")
async def get_tool(name: str, version: str):
    """Inspect a specific tool definition by name and version."""
    entry = reg.get(name, version)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{name}:{version}' not found in registry.",
        )
    return entry.model_dump(mode="json")


@router.post("/tools/propose", status_code=status.HTTP_201_CREATED)
async def propose_tool(proposal: ToolProposal):
    """
    Submit a new tool proposal. Status starts as 'proposed'.
    The tool cannot execute until it is approved and installed.
    Spec §7 lifecycle: propose → review → approve → install → register.
    """
    try:
        entry = reg.propose(proposal)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    await audit.append(
        kind="lifecycle",
        input_summary=f"Tool proposed: {proposal.name}:{proposal.version}",
        tool=proposal.name,
        result_summary="status=proposed",
    )
    logger.info("tool lifecycle | proposed | %s:%s", proposal.name, proposal.version)
    return {"status": "proposed", "tool": entry.model_dump(mode="json")}


@router.post("/tools/approve")
async def approve_tool(req: ToolApprovalRequest):
    """
    Approve a proposed tool. Status moves proposed → approved.
    Approved tools still cannot execute until installed.
    """
    try:
        entry = reg.approve(req.name, req.version)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit.append(
        kind="lifecycle",
        input_summary=f"Tool approved: {req.name}:{req.version}",
        tool=req.name,
        result_summary=f"status=approved reason={req.reason or 'n/a'}",
    )
    logger.info("tool lifecycle | approved | %s:%s", req.name, req.version)
    return {"status": "approved", "tool": entry.model_dump(mode="json")}


@router.post("/tools/install")
async def install_tool(req: ToolApprovalRequest):
    """
    Mark an approved tool as installed (registered and callable).
    Status moves approved → installed. After this, the tool can execute.
    """
    try:
        entry = reg.install(req.name, req.version)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit.append(
        kind="lifecycle",
        input_summary=f"Tool installed: {req.name}:{req.version}",
        tool=req.name,
        result_summary="status=installed",
    )
    logger.info("tool lifecycle | installed | %s:%s", req.name, req.version)
    return {"status": "installed", "tool": entry.model_dump(mode="json")}


@router.post("/tools/reject")
async def reject_tool(req: ToolApprovalRequest):
    """
    Reject a proposed tool. Terminal state — the tool cannot be re-proposed
    under the same name:version key. Submit a new proposal with an updated
    version string if rework is needed.
    """
    try:
        entry = reg.reject(req.name, req.version, reason=req.reason)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    await audit.append(
        kind="lifecycle",
        input_summary=f"Tool rejected: {req.name}:{req.version}",
        tool=req.name,
        result_summary=f"status=rejected reason={req.reason or 'n/a'}",
    )
    logger.info(
        "tool lifecycle | rejected | %s:%s | reason=%s",
        req.name,
        req.version,
        req.reason,
    )
    return {"status": "rejected", "tool": entry.model_dump(mode="json")}
