from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from dispatch import process
from ingestion import normalise
from models import GatewayResponse, IngestRequest

logger = logging.getLogger("gateway")

router = APIRouter()


@router.post("/ingest", response_model=GatewayResponse)
async def ingest(request: IngestRequest):
    """
    Main ingestion endpoint. Authenticated via X-API-Key header.
    Normalises → classifies → routes → returns structured response.
    ``LOCAL_TOOLS`` classifications are gated: they do not execute installed tools
    or invoke the sandbox from this path; use ``/plans/*`` for proposal, explicit
    approval, and execution. All activity is written to the audit log (GET /logs).
    """
    envelope = await normalise(request)

    logger.info(
        "ingest | modality=%-6s source=%-20s ts=%s",
        envelope.modality,
        envelope.source_device,
        envelope.timestamp.isoformat(),
    )

    try:
        result = await process(envelope)
    except Exception as exc:
        logger.exception("dispatch.process raised an unhandled exception")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Dispatch error: {exc}",
        ) from exc

    return GatewayResponse(
        status="ok",
        routed_to=result.get("routed_to"),
        result=result,
        fail_reason=result.get("fail_reason"),
        timestamp=datetime.now(timezone.utc),
        envelope=envelope,
    )
