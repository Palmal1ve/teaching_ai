"""Runs stages. A stage finishing calls advance(), which enqueues whatever became unblocked.

Celery only delivers work. A task is acknowledged on receipt, and a worker heartbeat in Postgres
is what detects a crash, so a 90-minute Whisper job cannot be redelivered mid-run by Redis.
"""
import importlib
import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from app.core.db import session_scope
from app.core.embeddings import EmbedderUnavailable
from app.core.llm import LLMUnavailable
from app.models import (
    Concept,
    ConceptEdge,
    EdgeEvidence,
    LessonRevision,
    PipelineStage,
    Statement,
    StatementConcept,
)
from app.pipeline.celery_app import celery
from app.pipeline.context import load_context
from app.pipeline.errors import PermanentError
from app.pipeline.graph import FINISHED, NEEDS_LLM, STAGES
from app.pipeline.revisions import stage_already_produced, sync_lesson_status

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_S = 30
LLM_RETRY_S = 300
HEARTBEAT_S = 30
HEARTBEAT_STALE = timedelta(seconds=HEARTBEAT_S * 5)
QUEUED_STALE = timedelta(minutes=30)


def now() -> datetime:
    return datetime.now(UTC)


def enqueue(stage_id: int, name: str) -> None:
    run_stage.apply_async(args=[stage_id], queue=STAGES[name][0])


def advance(revision_id: int) -> None:
    to_enqueue: list[tuple[int, str]] = []
    with session_scope() as session:
        revision = session.scalars(
            select(LessonRevision).where(LessonRevision.id == revision_id).with_for_update()
        ).first()
        if revision is None or revision.status not in ("processing", "failed"):
            return
        stages = {
            s.name: s
            for s in session.scalars(
                select(PipelineStage).where(PipelineStage.revision_id == revision_id)
            )
        }
        for name, stage in stages.items():
            blocked = any(stages[dep].status not in FINISHED for dep in STAGES[name][1])
            waiting = stage.retry_at is not None and stage.retry_at > now()
            if stage.status == "pending" and not blocked and not waiting:
                stage.status = "queued"
                stage.queued_at = now()
                to_enqueue.append((stage.id, name))
        if all(s.status in FINISHED for s in stages.values()):
            revision.status = "needs_review"
            sync_lesson_status(session, revision)
    for stage_id, name in to_enqueue:
        enqueue(stage_id, name)


def _claim(stage_id: int) -> tuple[int, str] | None:
    with session_scope() as session:
        stage = session.scalars(
            select(PipelineStage).where(PipelineStage.id == stage_id).with_for_update()
        ).first()
        if stage is None or stage.status != "queued":
            return None
        stage.status = "running"
        stage.started_at = stage.heartbeat_at = now()
        stage.error = None
        return stage.revision_id, stage.name


def _heartbeat(stage_id: int, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_S):
        with session_scope() as session:
            session.execute(
                update(PipelineStage)
                .where(PipelineStage.id == stage_id)
                .values(heartbeat_at=now())
            )


def _finish(stage_id: int) -> None:
    with session_scope() as session:
        stage = session.get(PipelineStage, stage_id)
        stage.status = "done"
        stage.finished_at = now()
        stage.retry_at = None


def _wait_for_llm(stage_id: int, reason: str) -> None:
    with session_scope() as session:
        stage = session.get(PipelineStage, stage_id)
        stage.status = "waiting_for_llm"
        stage.error = f"Waiting for the LLM: {reason}"
        stage.retry_at = now() + timedelta(seconds=LLM_RETRY_S)


def _record_failure(stage_id: int, message: str, permanent: bool) -> None:
    with session_scope() as session:
        stage = session.get(PipelineStage, stage_id)
        stage.attempts += 1
        stage.error = message[:2000]
        if permanent or stage.attempts >= MAX_ATTEMPTS:
            stage.status = "failed"
            stage.finished_at = now()
            revision = session.get(LessonRevision, stage.revision_id)
            if revision.status == "processing":
                revision.status = "failed"
                sync_lesson_status(session, revision)
        else:
            stage.status = "pending"
            stage.retry_at = now() + timedelta(seconds=BACKOFF_S * 2**stage.attempts)


@celery.task(name="run_stage")
def run_stage(stage_id: int) -> None:
    claimed = _claim(stage_id)
    if claimed is None:
        return
    revision_id, name = claimed
    stop = threading.Event()
    threading.Thread(target=_heartbeat, args=(stage_id, stop), daemon=True).start()
    try:
        with session_scope() as session:
            context = load_context(session, revision_id)
            produced = stage_already_produced(session, session.get(PipelineStage, stage_id))
        if not produced:
            importlib.import_module(f"app.pipeline.stages.{name}").run(context)
        _finish(stage_id)
    except LLMUnavailable as exc:
        if name in NEEDS_LLM:
            _wait_for_llm(stage_id, str(exc))
        else:
            _record_failure(stage_id, f"LLM unavailable: {exc}", permanent=False)
    except PermanentError as exc:
        _record_failure(stage_id, str(exc), permanent=True)
    except EmbedderUnavailable as exc:
        _record_failure(stage_id, f"Embedder unavailable: {exc}", permanent=False)
    except Exception as exc:
        log.exception("Stage %s failed for revision %s", name, revision_id)
        _record_failure(stage_id, f"{type(exc).__name__}: {exc}", permanent=False)
    finally:
        stop.set()
    advance(revision_id)


def retry_stage(session, stage: PipelineStage) -> None:
    stage.status = "pending"
    stage.attempts = 0
    stage.retry_at = None
    stage.error = None
    revision = session.get(LessonRevision, stage.revision_id)
    if revision.status == "failed":
        revision.status = "processing"
        sync_lesson_status(session, revision)


@celery.task(name="sweep")
def sweep() -> None:
    """Recovers from crashes and lost Redis messages, and wakes stages whose wait is over."""
    moment = now()
    to_advance: set[int] = set()
    to_requeue: list[tuple[int, str]] = []
    with session_scope() as session:
        crashed = session.scalars(
            select(PipelineStage).where(
                PipelineStage.status == "running",
                PipelineStage.heartbeat_at < moment - HEARTBEAT_STALE,
            )
        ).all()
        for stage in crashed:
            stage.status = "pending"
            stage.error = "Worker stopped during this stage, restarting it"
            to_advance.add(stage.revision_id)

        due = session.scalars(
            select(PipelineStage).where(
                PipelineStage.status.in_(("pending", "waiting_for_llm")),
                PipelineStage.retry_at <= moment,
            )
        ).all()
        for stage in due:
            stage.status = "pending"
            stage.retry_at = None
            to_advance.add(stage.revision_id)

        lost = session.scalars(
            select(PipelineStage).where(
                PipelineStage.status == "queued",
                PipelineStage.queued_at < moment - QUEUED_STALE,
            )
        ).all()
        for stage in lost:
            stage.queued_at = moment
            to_requeue.append((stage.id, stage.name))

    for stage_id, name in to_requeue:
        enqueue(stage_id, name)
    for revision_id in to_advance:
        advance(revision_id)


@celery.task(name="sweep_graph")
def sweep_graph() -> None:
    """Removes graph rows no statement supports. Retrieval already hides them; this is tidying."""
    with session_scope() as session:
        session.execute(
            delete(ConceptEdge).where(
                ~select(EdgeEvidence.id).where(EdgeEvidence.edge_id == ConceptEdge.id).exists()
            )
        )
        session.execute(
            delete(Concept).where(
                ~select(StatementConcept.id)
                .join(Statement, Statement.id == StatementConcept.statement_id)
                .where(StatementConcept.concept_id == Concept.id)
                .exists()
            )
        )


@celery.task(name="reembed_passages")
def reembed_passages(revision_id: int) -> None:
    from app.pipeline.stages.embed import embed_missing

    embed_missing(revision_id)


@celery.task(name="purge_storage")
def purge_storage(prefixes: list[str]) -> None:
    from app.core import storage

    for prefix in prefixes:
        storage.delete_prefix(prefix)
