"""Measures how well GLM citation tags match their sources. Writes nothing.

    docker compose exec -T api python - LESSON_ID < eval/glm_citation_check.py
"""
import sys
from sqlalchemy import select
from app.core.db import session_scope
from app.core.llm import get_llm
from app.core.embeddings import embed, cosine
from app.assistant.citations import split_sections, sentences, _TAG, _plain
from app.assistant.prompt import build_messages
from app.assistant.retrieval import retrieve, visible_revisions
from app.models import Lesson
qs = ["What does relaxation do to the distance?", "Why can't we use this algorithm with negative edge weights?",
      "What will I be asked to do on the exam?", "松弛操作是做什么的？", "How does Bellman-Ford detect negative cycles?"]
llm = get_llm(); rows = []
with session_scope() as s:
    lesson = s.get(Lesson, int(sys.argv[1]))
    revs = visible_revisions(s, lesson.course_id, None)
    for q in qs:
        v = embed([q])[0]
        src = retrieve(s, lesson.course_id, lesson, revs, q, v, 20000)
        kinds = [x.kind for x in src]
        reply = llm.chat(build_messages(src, [], q), max_tokens=1024)
        cls, _ = split_sections(reply)
        parts = sentences(cls); n = bad = 0
        for p in parts:
            tags = [int(t) for t in _TAG.findall(p)]
            for t in dict.fromkeys(tags):
                if not 1 <= t <= len(src):
                    print("   INVENTED", t); bad += 1; continue
                a, b = embed([_plain(p), src[t-1].text]); c = cosine(a, b); rows.append(c); n += 1
                if c < .5: print(f"   low {c:.2f} | {_plain(p)[:70]!r} <- {src[t-1].text[:70]!r}")
        print(f"Q {q[:45]!r}: sources={len(src)} distinct_starts={len({x.start_ms for x in src})} kinds={sorted(set(map(str,kinds)))} tags={n} invented={bad}")
rows.sort()
print("pairs", len(rows), "min %.2f p10 %.2f median %.2f max %.2f" % (rows[0], rows[len(rows)//10], rows[len(rows)//2], rows[-1]), "below .5:", sum(r<.5 for r in rows))
