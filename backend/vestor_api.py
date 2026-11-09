from pathlib import Path
from typing import Literal, TypedDict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from vestor_domain.ani import calculate_ani
from vestor_domain.primitives import InputError
from vestor_wire import decode_input, error_field
from typing import Any
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


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Never echo rejected values (FastAPI's default includes the request input).
    return JSONResponse(status_code=422, content={"errors": [{"field": "inputs", "message": "Supply a valid JSON input object."}]})


@app.post("/api/calculate")
def calculate(payload: dict[str, Any]) -> Any:
    try:
        result = calculate_ani(decode_input(payload))
        if result.status == "input_error":
            return JSONResponse(status_code=422, content={"errors": [{"field": error_field(w.field, payload), "message": w.message} for w in result.warnings]})
        return result.to_wire()
    except InputError as exc:
        return JSONResponse(status_code=422, content={"errors": [{"field": error_field(exc.field, payload), "message": str(exc)}]})
