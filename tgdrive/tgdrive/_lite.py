"""FastAPI's routing surface, as TG Drive uses it, on plain Starlette (see webapp.py for why).

Only imported where FastAPI isn't available (the Android app) or TGDRIVE_WEB=lite asks for it.
"""
from __future__ import annotations

import copy
import dataclasses
import datetime as _dt
import enum
import inspect
import json
import typing
from pathlib import PurePath
from typing import Any, Callable, Optional

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

_REQUIRED = ...


class Body:
    """Marks the argument that receives the JSON request body (FastAPI's `Body(...)`)."""

    def __init__(self, default: Any = _REQUIRED, **_: Any):
        self.default = default


# ------------------------------------------------------------------ encoding
def _encode(o: Any) -> Any:
    """What json can't write on its own, written the way FastAPI's jsonable_encoder does."""
    if isinstance(o, PurePath):
        return str(o)
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if isinstance(o, (_dt.datetime, _dt.date, _dt.time)):
        return o.isoformat()
    if isinstance(o, enum.Enum):
        return o.value
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return dataclasses.asdict(o)
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


class _JSON(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":"),
                          default=_encode).encode("utf-8")


def _invalid(loc: list, msg: str, kind: str = "value_error") -> Response:
    return _JSON({"detail": [{"type": kind, "loc": loc, "msg": msg}]}, status_code=422)


# ------------------------------------------------------------ parameter parsing
_TRUE = {"1", "true", "t", "on", "y", "yes"}
_FALSE = {"0", "false", "f", "off", "n", "no"}


def _unwrap_optional(tp: Any) -> tuple[Any, bool]:
    origin = typing.get_origin(tp)
    if origin is typing.Union or (origin is not None and getattr(origin, "__name__", "") == "UnionType"):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return tp, False


def _converter(tp: Any) -> Callable[[str], Any]:
    base, _ = _unwrap_optional(tp)
    if base is int:
        def conv(v: str) -> int:
            v = v.strip()
            if not v or not (v.isdigit() or (v[0] in "+-" and v[1:].isdigit())):
                raise ValueError("Input should be a valid integer")
            return int(v)
        return conv
    if base is float:
        return float
    if base is bool:
        def conv_b(v: str) -> bool:
            s = v.strip().lower()
            if s in _TRUE:
                return True
            if s in _FALSE:
                return False
            raise ValueError("Input should be a valid boolean")
        return conv_b
    return str


class _Param:
    __slots__ = ("name", "source", "convert", "default", "required", "is_dict")

    def __init__(self, name: str, source: str, convert=None, default: Any = None, required: bool = False,
                 is_dict: bool = False):
        self.name, self.source, self.convert = name, source, convert
        self.default, self.required, self.is_dict = default, required, is_dict


def _plan(endpoint: Callable, path: str) -> list[_Param]:
    sig = inspect.signature(endpoint)
    try:
        hints = typing.get_type_hints(endpoint)
    except Exception:
        hints = {}
    in_path = {seg.split(":", 1)[0] for seg in _path_names(path)}
    plan = []
    for name, p in sig.parameters.items():
        tp = hints.get(name, p.annotation)
        if tp is Request or (isinstance(tp, type) and issubclass(tp, Request)):
            plan.append(_Param(name, "request"))
        elif isinstance(p.default, Body):
            plan.append(_Param(name, "body", default=p.default.default, required=p.default.default is _REQUIRED,
                               is_dict=_unwrap_optional(tp)[0] is dict))
        elif name in in_path:
            plan.append(_Param(name, "path", _converter(tp)))
        else:
            required = p.default is inspect.Parameter.empty
            plan.append(_Param(name, "query", _converter(tp), None if required else p.default, required))
    return plan


def _path_names(path: str) -> list[str]:
    out, i = [], 0
    while True:
        a = path.find("{", i)
        if a < 0:
            return out
        b = path.find("}", a)
        out.append(path[a + 1:b])
        i = b + 1


def _endpoint(func: Callable, path: str) -> Callable[[Request], Any]:
    plan = _plan(func, path)
    is_async = inspect.iscoroutinefunction(func)

    async def handler(request: Request) -> Response:
        kwargs: dict[str, Any] = {}
        for p in plan:
            if p.source == "request":
                kwargs[p.name] = request
            elif p.source == "path":
                raw = request.path_params.get(p.name, "")
                try:
                    kwargs[p.name] = p.convert(str(raw))
                except ValueError as exc:
                    return _invalid(["path", p.name], str(exc))
            elif p.source == "query":
                raw = request.query_params.get(p.name)
                if raw is None:
                    if p.required:
                        return _invalid(["query", p.name], "Field required", "missing")
                    kwargs[p.name] = p.default
                else:
                    try:
                        kwargs[p.name] = p.convert(raw)
                    except ValueError as exc:
                        return _invalid(["query", p.name], str(exc))
            else:   # body
                data = await request.body()
                if not data:
                    if p.required:
                        return _invalid(["body"], "Field required", "missing")
                    kwargs[p.name] = copy.deepcopy(p.default)
                    continue
                try:
                    value = json.loads(data)
                except ValueError as exc:
                    return _invalid(["body"], f"JSON decode error: {exc}", "json_invalid")
                if p.is_dict and not isinstance(value, dict):
                    return _invalid(["body"], "Input should be a valid dictionary", "dict_type")
                kwargs[p.name] = value
        result = await func(**kwargs) if is_async else await run_in_threadpool(func, **kwargs)
        if isinstance(result, Response):
            return result
        return _JSON(result)

    handler.__name__ = getattr(func, "__name__", "endpoint")
    return handler


# ------------------------------------------------------------------- routers
class APIRouter:
    def __init__(self) -> None:
        self._routes: list[Any] = []

    def api_route(self, path: str, methods: Optional[list[str]] = None, **_: Any):
        def deco(func: Callable) -> Callable:
            self._routes.append(Route(path, _endpoint(func, path), methods=list(methods or ["GET"])))
            return func
        return deco

    def get(self, path: str, **kw: Any):
        return self.api_route(path, ["GET"], **kw)

    def post(self, path: str, **kw: Any):
        return self.api_route(path, ["POST"], **kw)

    def put(self, path: str, **kw: Any):
        return self.api_route(path, ["PUT"], **kw)

    def patch(self, path: str, **kw: Any):
        return self.api_route(path, ["PATCH"], **kw)

    def delete(self, path: str, **kw: Any):
        return self.api_route(path, ["DELETE"], **kw)

    @property
    def routes(self) -> list[Any]:
        return list(self._routes)


async def _http_exception(_: Request, exc: HTTPException) -> Response:
    return _JSON({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


class FastAPI(APIRouter):
    """Collects routes like FastAPI does and builds one Starlette app on the first request."""

    def __init__(self, title: str = "", lifespan: Optional[Callable] = None, **_: Any):
        super().__init__()
        self.title = title
        self._lifespan = lifespan
        self._handlers: dict[Any, Callable] = {HTTPException: _http_exception}
        self._middleware: list[Middleware] = []
        self._app: Optional[Starlette] = None

    def exception_handler(self, exc_class: Any):
        def deco(func: Callable) -> Callable:
            self._handlers[exc_class] = func
            return func
        return deco

    def middleware(self, kind: str):
        if kind != "http":
            raise ValueError("only http middleware is supported")

        def deco(func: Callable) -> Callable:
            self._middleware.insert(0, Middleware(BaseHTTPMiddleware, dispatch=func))
            return func
        return deco

    def include_router(self, router: APIRouter, **_: Any) -> None:
        self._routes.extend(router.routes)

    def mount(self, path: str, app: Any, name: Optional[str] = None) -> None:
        self._routes.append(Mount(path, app=app, name=name))

    def _build(self) -> Starlette:
        if self._app is None:
            user = self._lifespan
            self._app = Starlette(routes=self._routes, middleware=self._middleware,
                                  exception_handlers=self._handlers,
                                  lifespan=(lambda _app: user(self)) if user else None)
        return self._app

    async def __call__(self, scope, receive, send) -> None:
        await self._build()(scope, receive, send)
