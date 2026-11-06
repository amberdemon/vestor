from pathlib import Path
from typing import Literal, TypedDict

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(openapi_url=None)
frontend = Path(__file__).with_name("static")


class Health(TypedDict):
    status: Literal["ok"]


@app.get("/api/health")
def health() -> Health:
    return {"status": "ok"}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(frontend / "index.html")


app.mount("/assets", StaticFiles(directory=frontend / "assets", check_dir=False))
