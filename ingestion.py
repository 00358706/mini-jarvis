"""
ingestion.py — Normalisation + multimodal preprocessing.

Phase 4: non-text modalities (voice, image) are preprocessed here
into a text_content field before entering the pipeline. This means
the classifier and routing layers always see text regardless of
the original input modality.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

import multimodal
from models import IngestRequest, NormalisedEnvelope


async def normalise(request: IngestRequest) -> NormalisedEnvelope:
    """
    Convert an IngestRequest into a NormalisedEnvelope.

    For non-text modalities, calls the multimodal preprocessor to
    extract a text representation. This text is stored in text_content
    and used for routing — the original content is preserved.
    """
    ts = request.timestamp or datetime.now(timezone.utc)

    # Structural validation first
    _validate_content_structure(request)

    # Multimodal preprocessing for non-text modalities
    text_content: str | None = None
    extra_metadata: dict = {}

    if request.modality in ("voice", "image", "event"):
        preprocess_result = await multimodal.preprocess(
            request.modality, request.content
        )
        text_content = preprocess_result["text"]
        extra_metadata = preprocess_result.get("metadata", {})
    elif request.modality == "text":
        text_content = str(request.content)

    return NormalisedEnvelope(
        modality=request.modality,
        content=request.content,
        source_device=request.source_device,
        timestamp=ts,
        metadata={**request.metadata, **extra_metadata},
        text_content=text_content,
    )


def _validate_content_structure(request: IngestRequest) -> None:
    match request.modality:
        case "text":
            if not isinstance(request.content, str) or not request.content.strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="text modality requires a non-empty string in 'content'.",
                )
        case "image":
            if not isinstance(request.content, str) or not request.content.strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="image modality requires a base64 string or URL in 'content'.",
                )
        case "voice":
            if not isinstance(request.content, str) or not request.content.strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="voice modality requires base64-encoded audio in 'content'.",
                )
        case "event":
            if not isinstance(request.content, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="event modality requires a JSON object in 'content'.",
                )
