from __future__ import annotations

from fastapi import FastAPI
import uvicorn

from .config import get_settings
from .memory.r2_store import R2Store
from .memory.repository import MemoryRepository

app = FastAPI(title="The Daddy Dashboard", version="1.0.0")


@app.get("/health")
def health():
    settings = get_settings()
    return {
        "ok": True,
        "target_root": str(settings.target_root),
        "has_openai": settings.has_openai,
        "has_r2": settings.has_r2,
    }


@app.get("/memory")
def memory():
    repo = MemoryRepository(R2Store(get_settings()))
    return repo.state.model_dump(mode="json")


@app.get("/latest-review")
def latest_review():
    repo = MemoryRepository(R2Store(get_settings()))
    review = repo.latest_review()
    return review.model_dump(mode="json") if review else {}


def main() -> None:
    uvicorn.run("the_daddy.dashboard:app", host="0.0.0.0", port=8787, reload=False)
