from pathlib import Path
from typing import Literal, TypedDict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from vestor_domain.ani import calculate_ani
from vestor_domain.m2 import calculate_m2
from vestor_domain.primitives import InputError
from vestor_wire import decode_input, decode_m2_input, encode_m2_result, error_field
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


@app.post("/api/v2/calculate")
def calculate_v2(payload: dict[str, Any]) -> Any:
    try:
        decoded = decode_m2_input(payload)
    except InputError as exc:
        return JSONResponse(status_code=422, content={"errors": [{"field": exc.field, "message": str(exc)}]})
    try:
        result = calculate_m2(decoded)
        warnings = (
            *result.ani.warnings, *result.ledger.evidence.warnings, *result.share_gains.warnings,
            *(warning for row in result.acquisitions for warning in row.warnings),
            *result.annual_cgt.warnings, *result.settlement.payroll_warnings, *result.settlement.cash_warnings,
        )
        errors = [{"field": error_field(warning.field, payload), "message": warning.message}
                  for warning in dict.fromkeys(warnings) if warning.status == "input_error"]
        if errors:
            return JSONResponse(status_code=422, content={"errors": errors})
        return encode_m2_result(result)
    except InputError as exc:
        return JSONResponse(status_code=422, content={"errors": [{"field": error_field(exc.field, payload), "message": str(exc)}]})
