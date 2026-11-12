"""The stage DAG. Postgres holds state; this table only says what may run after what."""

MEDIA, AI = "media", "ai"

STAGES: dict[str, tuple[str, list[str]]] = {
    "probe": (MEDIA, []),
    "render_deck": (MEDIA, []),
    "transcode_hls": (MEDIA, ["probe"]),
    "extract_audio": (MEDIA, ["probe"]),
    "sample_frames": (MEDIA, ["probe"]),
    "read_slides": (MEDIA, ["render_deck"]),
    "transcribe": (MEDIA, ["probe", "extract_audio", "render_deck"]),
    "sync_slides": (MEDIA, ["transcribe", "sample_frames", "read_slides"]),
    "build_passages": (AI, ["transcribe", "sync_slides"]),
    "extract_knowledge": (AI, ["build_passages"]),
    "resolve_concepts": (AI, ["extract_knowledge"]),
    "embed": (AI, ["resolve_concepts", "transcode_hls"]),
}

DECK_ONLY = {"render_deck", "read_slides", "sample_frames", "sync_slides"}
NEEDS_LLM = {"extract_knowledge", "resolve_concepts"}
FINISHED = {"done", "skipped"}
