"""Start the TG Drive server:  python run.py   then open http://127.0.0.1:8765

The desktop app (python -m desktop) starts the same server as a separate process
(`run.py --child`), so the window stays responsive whatever the server is doing and a
server crash doesn't take the window down (the app restarts it).
"""
import json
import logging
import os
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
                         access_log=False, proxy_headers=False,
                         timeout_graceful_shutdown=2)   # open streams must not hold up quitting
    server = Server(cfg)
    api.RUNTIME["server"] = server
    return server, [main, media]


class Server(uvicorn.Server):
    """uvicorn's server, plus: the live-update streams end as soon as quitting starts (instead of
    holding the connection open until the graceful-shutdown timeout)."""

    def handle_exit(self, sig, frame) -> None:
        from tgdrive import api
        api.RUNTIME["stopping"] = True
        super().handle_exit(sig, frame)


# However stuck something is, the service process is gone this many seconds after it was told to stop.
HARD_STOP_AFTER = 25.0


def exit_guard(server, log, name: str = "service") -> None:
    """Start a thread that ends the process if stopping takes longer than HARD_STOP_AFTER seconds
    (a thread stuck in a long computation or a network call must never leave TG Drive running)."""
    import time as _t

    def guard():
        while not server.should_exit:
            _t.sleep(0.2)
        started = _t.monotonic()
        while _t.monotonic() - started < HARD_STOP_AFTER:
            _t.sleep(0.5)
        log.warning("%s: stopping took over %.0f s; ending the process now", name, HARD_STOP_AFTER)
        try:
            logging.shutdown()
        finally:
            os._exit(0)

    threading.Thread(target=guard, name="tgdrive-exit-guard", daemon=True).start()


def die_with_parent() -> None:
    """Linux: ask the kernel to send us SIGTERM when the process that started us dies (even if it is
    killed with SIGKILL), so the service can never outlive the window."""
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        import signal
        libc = ctypes.CDLL(None, use_errno=True)
        PR_SET_PDEATHSIG = 1
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    except Exception:
        pass


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


def child_main(argv: list[str]) -> None:
    """The desktop app's service process. Reads its secrets from the environment (never the command line,
    which other users can see), prints one JSON line with the ports once it listens, then serves until
    it gets SIGTERM (or the app that started it goes away)."""
    import argparse
    import threading

    from tgdrive import diagnostics, maintenance
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", action="store_true")
    ap.add_argument("--port", type=int, default=config.PORT)
    ap.add_argument("--media-port", type=int, default=None)
    ap.add_argument("--parent-pid", type=int, default=0)
    a = ap.parse_args(argv)
    die_with_parent()
    if a.parent_pid and os.getppid() != a.parent_pid:
        return   # the window already went away while we were starting
    maintenance.setup_logging()
    diagnostics.install_hooks()
    diagnostics.enable_faulthandler("service")
    log = logging.getLogger("tgdrive.service")
    token = os.environ.get("TGDRIVE_TOKEN", "")
    server, socks = make_server(port=a.port, media_port=a.media_port, token=token, desktop=True)
    port, media = socks[0].getsockname()[1], socks[1].getsockname()[1]
    log.info("service %s starting on ports %s/%s (pid %s)", config.VERSION, port, media, os.getpid())

    def announce():
        import time as _t
        while not server.started and not server.should_exit:
            _t.sleep(0.05)
        if server.started:
            sys.stdout.write(json.dumps({"ready": True, "port": port, "media": media, "pid": os.getpid()}) + "\n")
            sys.stdout.flush()

    def watch_parent():
        # If the window process dies without stopping us (killed, crashed), don't linger as an orphan.
        import time as _t
        while a.parent_pid and not server.should_exit:
            _t.sleep(2)
            if os.getppid() != a.parent_pid:
                log.warning("the app that started the service is gone; stopping")
                server.should_exit = True

    threading.Thread(target=announce, name="tgdrive-announce", daemon=True).start()
    threading.Thread(target=watch_parent, name="tgdrive-parent-watch", daemon=True).start()
    exit_guard(server, log)
    server.run(sockets=socks)
    log.info("service stopped")
    # Don't wait at exit for helper threads (a batch that ignores cancelling, a pending network call):
    # everything that matters was saved during the shutdown above.
    logging.shutdown()
    os._exit(0)


def main() -> None:
    if "--child" in sys.argv[1:]:
        return child_main(sys.argv[1:])
    from tgdrive import diagnostics, maintenance
    log_path = maintenance.setup_logging()
    diagnostics.install_hooks()
    diagnostics.enable_faulthandler("server")
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
    exit_guard(server, logging.getLogger("tgdrive.server"), "server")
    server.run(sockets=socks)
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
