"""bge-m3 on CPU. Internal only: nothing outside the Compose network can reach it."""
from fastapi import FastAPI
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

MAX_TOKENS = 512

app = FastAPI()
model = SentenceTransformer("/models/bge-m3", device="cpu")
model.max_seq_length = MAX_TOKENS


class EmbedRequest(BaseModel):
    texts: list[str] = Field(max_length=64)


@app.post("/embed")
def embed(request: EmbedRequest) -> dict:
    vectors = model.encode(request.texts, normalize_embeddings=True, batch_size=8)
    return {"vectors": vectors.tolist()}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
