"""Reruns extraction on a revision and reports rejected quotes. Writes nothing.

    docker compose exec -T worker-ai python - REVISION_ID < eval/glm_extraction_check.py
"""
import sys
import time
from app.core.db import session_scope
from app.core.llm import get_llm
from app.core.config import get_settings
from app.pipeline.context import load_context
from app.pipeline.stages import extract_knowledge as ek
from app.knowledge.extraction import SYSTEM, build_prompt, Extraction, verify, normalise, _proven
with session_scope() as s:
    ctx = load_context(s, int(sys.argv[1]))
ek_units = ek._load_units(ctx)[0]
llm = get_llm(); mt = get_settings().extraction_max_tokens
print("units", len(ek_units), "max_tokens", mt)
tot = rej = corrections = 0
for u in ek_units:
    t = time.monotonic()
    r = llm.complete_json(SYSTEM, build_prompt(u), Extraction, max_tokens=mt)
    dt = time.monotonic() - t
    if r is None:
        print(u.index, "INVALID", round(dt, 1)); continue
    res, n = verify(r, u)
    tot += len(r.statements); rej += n
    print(f"unit {u.index}: {dt:.1f}s statements={len(r.statements)} rejected={n} relations={len(r.relations)} concepts={len(r.concepts)}")
    for st in r.statements:
        if not _proven(st, u):
            print("   REJECTED", st.kind, repr(st.quote[:90]), st.segment_ids)
    for st in res["statements"]:
        corrections += st["kind"] == "correction"
        print(f"   {st['kind']:<11} {st['text']}")
    for rel in res["relations"]:
        print(f"   RELATION {rel['source']} {rel['type']} {rel['target']}")
print(f"total {tot} rejected {rej} corrections {corrections}")
print("normalise:", repr(normalise("Bellman-Ford algorithm")), repr(normalise("Bellman Ford")))
