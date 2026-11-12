import shutil
import time
import uuid
from pathlib import Path

from pptx import Presentation
from sqlalchemy import delete

from app.core import storage
from app.core.config import get_settings
from app.core.db import session_scope
from app.models import DeckAsset, Slide
from app.pipeline.context import StageContext
from app.pipeline.errors import PermanentError
from app.pipeline.media import run as sh
from app.pipeline.media import work_dir

CONVERT_TIMEOUT_S = 600
IMAGE_WIDTH = 1600


def convert(source: Path, target_format: str) -> Path:
    """Hands the file to the converter container, which has no network and no secrets."""
    job = Path(get_settings().convert_dir) / uuid.uuid4().hex
    job.mkdir(parents=True)
    try:
        shutil.copy(source, job / f"input{source.suffix}")
        (job / "format").write_text(target_format)
        (job / "ready").touch()
        deadline = time.monotonic() + CONVERT_TIMEOUT_S
        while time.monotonic() < deadline:
            if (job / "error").exists():
                raise PermanentError(f"Could not read this deck: {(job / 'error').read_text()}")
            if (job / "done").exists():
                result = source.with_suffix(f".converted.{target_format}")
                shutil.copy(job / f"input.{target_format}", result)
                return result
            time.sleep(1)
        raise TimeoutError("The slide converter did not finish in time")
    finally:
        shutil.rmtree(job, ignore_errors=True)


def _shape_text(shape) -> list[str]:
    if shape.shape_type == 6:  # group
        return [text for child in shape.shapes for text in _shape_text(child)]
    if getattr(shape, "has_table", False) and shape.has_table:
        return [cell.text for row in shape.table.rows for cell in row.cells if cell.text.strip()]
    if shape.has_text_frame and shape.text_frame.text.strip():
        return [shape.text_frame.text]
    return []


def read_pptx(path: Path) -> list[dict]:
    """Reads slide text, then un-hides every slide so PDF pages line up with slide numbers."""
    deck = Presentation(str(path))
    slides = []
    for slide in deck.slides:
        element = slide._element
        hidden = element.get("show") == "0"
        if hidden:
            del element.attrib["show"]
        notes = slide.notes_slide.notes_text_frame if slide.has_notes_slide else None
        slides.append(
            {
                "text": "\n".join(t for shape in slide.shapes for t in _shape_text(shape)),
                "notes": notes.text if notes is not None else "",
                "hidden": hidden,
            }
        )
    deck.save(str(path))
    return slides


def read_pdf(path: Path) -> list[dict]:
    pages = sh(["pdftotext", "-layout", str(path), "-"]).split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return [{"text": page.strip(), "notes": "", "hidden": False} for page in pages]


def page_images(pdf: Path, directory: Path) -> list[Path]:
    directory.mkdir()
    sh(["pdftoppm", "-png", "-scale-to-x", str(IMAGE_WIDTH), "-scale-to-y", "-1", str(pdf),
        str(directory / "s")])
    return sorted(directory.glob("*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))


def run(context: StageContext) -> None:
    with session_scope() as session:
        deck = session.get(DeckAsset, context.deck_id)
        key, filename = deck.storage_key, deck.filename
    suffix = Path(filename).suffix.lower()

    with work_dir() as out:
        source = storage.download(key, out / f"deck{suffix}")
        if suffix == ".ppt":
            source = convert(source, "pptx")
            suffix = ".pptx"
        if suffix == ".pptx":
            try:
                slides = read_pptx(source)
            except Exception as exc:
                raise PermanentError(f"Could not read this deck: {exc}") from exc
            pdf = convert(source, "pdf")
        else:
            pdf = source
            slides = read_pdf(pdf)

        images = page_images(pdf, out / "pages")
        if len(images) != len(slides):
            raise PermanentError(
                f"The deck has {len(slides)} slides but rendered to {len(images)} pages."
            )

        rows = []
        for number, (image, slide) in enumerate(zip(images, slides, strict=True), start=1):
            image_key = f"decks/{context.deck_id}/slides/{number:04d}.png"
            storage.upload_file(image, image_key)
            rows.append(
                Slide(deck_asset_id=context.deck_id, number=number, image_key=image_key, **slide)
            )

    with session_scope() as session:
        session.execute(delete(Slide).where(Slide.deck_asset_id == context.deck_id))
        session.add_all(rows)
        session.get(DeckAsset, context.deck_id).slide_count = len(rows)
