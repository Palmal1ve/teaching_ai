"""An OpenAI-compatible stand-in for GLM, for end-to-end runs while the real endpoint is offline.

It proves the plumbing, not answer quality: replies are built mechanically from the prompt.

    uv run uvicorn tests.fake_glm:app --port 9100
"""
import json
import re

from fastapi import FastAPI, Request

app = FastAPI()
_LINE = re.compile(r"^\[(\d+)\] (.+)$", re.M)
_SOURCE = re.compile(r"^\[S(\d+)\] .*\n(.+)$", re.M)


def _reply(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _extract(prompt: str) -> str:
    slide = re.search(r"<slide>\n(.*?)\n", prompt, re.S)
    title = slide.group(1).strip() if slide else "Lecture topic"
    title = "Lecture topic" if title.startswith("(") else title
    lines = _LINE.findall(prompt)
    statements = []
    for seq, text in lines[:3]:
        quote = " ".join(text.split()[:6])
        kind = "exam_hint" if "exam" in text.lower() else "explanation"
        statements.append(
            {
                "kind": kind,
                "text": text,
                "concepts": [title],
                "segment_ids": [int(seq)],
                "quote": quote,
            }
        )
    statements.append(
        {
            "kind": "example",
            "text": "Invented claim that must be rejected",
            "concepts": [title],
            "segment_ids": [int(lines[0][0])] if lines else [0],
            "quote": "this sentence was never said in the lecture",
        }
    )
    return json.dumps(
        {
            "concepts": [{"name": title, "aliases": [], "summary": f"Taught as {title}."}],
            "statements": statements,
            "relations": [],
            "term_fixes": [],
        }
    )


def _answer(prompt: str) -> str:
    if "OUT_OF_SCOPE" in prompt:
        return "The class did not cover this.\n\nBeyond the class material\nHere is general help."
    sources = _SOURCE.findall(prompt)
    if not sources:
        return "The class did not cover this."
    tag, text = sources[1] if len(sources) > 1 else sources[0]
    claim = " ".join(text.split()[:18])
    return f"{claim}. [S{tag}] [S999]"


@app.get("/v1/models")
def models() -> dict:
    return {"data": [{"id": "GLM-5.2"}]}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> dict:
    body = await request.json()
    prompt = body["messages"][-1]["content"]
    schema = body.get("response_format", {}).get("json_schema", {}).get("name")
    if schema == "Extraction":
        return _reply(_extract(prompt))
    if schema == "MergeDecision":
        return _reply('{"merge_with": null}')
    return _reply(_answer(prompt))
