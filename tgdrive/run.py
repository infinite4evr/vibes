"""Start the TG Drive server:  python run.py   then open http://127.0.0.1:8765

The desktop app (python -m desktop) starts the same server inside its window.
"""
import logging
import socket
import sys
import threading
from typing import Callable, Optional

import uvicorn

from tgdrive import config


def bind(host: str, port: int, fallback: bool = True) -> socket.socket:
    """Bind a listening socket; with fallback, pick a free port if `port` is taken (0 = any)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for candidate in ([port] if port else []) + ([0] if fallback or not port else []):
        s = socket.socket(family, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, candidate))
        except OSError:
            s.close()
            if not fallback:
                raise
            continue
        s.listen(128)
        s.set_inheritable(True)
        return s
    raise OSError(f"No free port on {host}")


def make_server(host: str = config.HOST, port: int = config.PORT, media_port: Optional[int] = None,
                token: str = "", desktop: bool = False, fallback: bool = True):
    """Create (server, sockets). Media (thumbnails, streams) gets its own port."""
    from tgdrive import api
    if token:
        config.ACCESS_TOKEN = token
    main = bind(host, port, fallback=fallback)
    media = bind(host, media_port if media_port is not None else (main.getsockname()[1] + 1), fallback=True)
    api.RUNTIME.update(port=main.getsockname()[1], media_port=media.getsockname()[1], desktop=desktop)
    cfg = uvicorn.Config(api.app, log_level="warning", lifespan="on", timeout_keep_alive=30,
                         access_log=False, proxy_headers=False)
    return uvicorn.Server(cfg), [main, media]


def serve_in_thread(on_ready: Optional[Callable[[int, int], None]] = None, **kw):
    server, socks = make_server(**kw)
    port, media = socks[0].getsockname()[1], socks[1].getsockname()[1]

    def run():
        server.run(sockets=socks)

    t = threading.Thread(target=run, name="tgdrive-server", daemon=True)
    t.start()
    if on_ready:
        on_ready(port, media)
    return server, t, port, media


def main() -> None:
    from tgdrive import maintenance
    log_path = maintenance.setup_logging()
    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.INFO)
    logging.getLogger().addHandler(err)
    if config.HOST not in ("127.0.0.1", "localhost", "::1") and not config.PASSWORD:
        print("\n  Refusing to listen on a public interface without TGDRIVE_PASSWORD.\n"
              "  Anyone who can reach this port would get full access to your Telegram account.\n")
        sys.exit(2)
    server, socks = make_server(fallback="--strict-port" not in sys.argv)
    port = socks[0].getsockname()[1]
    print(f"\n  TG Drive {config.VERSION} → http://{config.HOST}:{port}\n  Data: {config.DATA_DIR}\n  Log:  {log_path}\n")
    if not config.api_configured():
        print("  First run: open the address above and enter your Telegram API ID and hash.\n")
    server.run(sockets=socks)


if __name__ == "__main__":
    main()
