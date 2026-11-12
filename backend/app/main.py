from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware

from app.api import admin, auth, chat, courses, lessons, media_auth

app = FastAPI(title="Course Assistant", docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=2000)

for module in (auth, courses, lessons, chat, admin, media_auth):
    app.include_router(module.router, prefix="/api/v1")


@app.get("/api/v1/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}
