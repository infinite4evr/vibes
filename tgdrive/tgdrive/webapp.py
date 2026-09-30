"""The web framework TG Drive's HTTP API is written against.

On computers this is FastAPI. FastAPI needs pydantic, whose core is compiled Rust that has no
Android build, so the Android app runs the same routes on Starlette (the framework FastAPI is
itself built on) through the small adapter below. It covers exactly what TG Drive's routes use:

  * path parameters converted by annotation (int, str, and `{name:path}`); negative numbers work
    (chat ids are negative), a value that doesn't convert answers 422 like FastAPI;
  * query parameters from the remaining arguments (str, int, float, bool, Optional[...]);
  * `body: dict = Body(...)` / `Body(default=...)` for JSON bodies;
  * `request: Request`, plain return values as JSON, Response objects as they are;
  * exception handlers, one `@app.middleware("http")`, routers, mounts and a lifespan.

The whole test suite runs against both (TGDRIVE_WEB=lite forces the adapter where FastAPI is
installed), so the two can't drift apart unnoticed.
"""
from __future__ import annotations

import os

ENGINE = "fastapi"
try:
    if os.environ.get("TGDRIVE_WEB") == "lite":
        raise ImportError("adapter requested")
    from fastapi import APIRouter, Body, FastAPI, Request  # noqa: F401
    from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,  # noqa: F401
                                   RedirectResponse, Response, StreamingResponse)
    from fastapi.staticfiles import StaticFiles  # noqa: F401
except ImportError:
    ENGINE = "starlette"
    from ._lite import APIRouter, Body, FastAPI  # noqa: F401
    from starlette.requests import Request  # noqa: F401
    from starlette.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse,  # noqa: F401
                                     RedirectResponse, Response, StreamingResponse)
    from starlette.staticfiles import StaticFiles  # noqa: F401
