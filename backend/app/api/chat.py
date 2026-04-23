"""Chat endpoints: message ingest + question answering."""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas.all import (
    ChatMessageIn,
    ChatRespondIn,
    FactActionOut,
    GuardedAnswerOut,
    IngestReportOut,
    ProvenanceOut,
)
from app.services import ingest_service, response_guard, retrieval_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/message", response_model=IngestReportOut)
def post_message(body: ChatMessageIn) -> IngestReportOut:
    report = ingest_service.ingest(
        project_id=body.project_id,
        text=body.text,
        speaker=body.speaker,
        tags=body.tags,
    )
    return IngestReportOut(
        project_id=report.project_id,
        chunk_ids=report.chunk_ids,
        candidates=report.candidates,
        accepted=report.accepted,
        rejected=report.rejected,
        facts=[
            FactActionOut(
                key=f.key, value=f.value, action=f.action,
                reason=f.reason, fact_id=f.fact_id, version=f.version,
            )
            for f in report.facts
        ],
    )


@router.post("/respond", response_model=GuardedAnswerOut)
def post_respond(body: ChatRespondIn) -> GuardedAnswerOut:
    result = retrieval_service.retrieve(body.project_id, body.query)
    guarded = response_guard.compose(result)
    return GuardedAnswerOut(
        mode=guarded.mode,
        answer=guarded.answer,
        provenance=[ProvenanceOut(**p.__dict__) for p in guarded.provenance],
        supporting_chunks=guarded.supporting_chunks,
        matched_keys=guarded.matched_keys,
    )
