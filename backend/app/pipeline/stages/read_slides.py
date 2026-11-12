from datetime import UTC, datetime

from sqlalchemy import select

from app.core import storage
from app.core.db import session_scope
from app.models import DeckAsset, Slide
from app.pipeline.context import StageContext
from app.pipeline.ocr import read_text


def run(context: StageContext) -> None:
    with session_scope() as session:
        slides = session.scalars(
            select(Slide).where(Slide.deck_asset_id == context.deck_id).order_by(Slide.number)
        ).all()
        keys = [(s.id, s.image_key) for s in slides]
    texts = {slide_id: read_text(storage.read_bytes(key)) for slide_id, key in keys}
    with session_scope() as session:
        for slide_id, text in texts.items():
            session.get(Slide, slide_id).ocr_text = text
        session.get(DeckAsset, context.deck_id).ocr_at = datetime.now(UTC)
