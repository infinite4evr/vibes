"""Folders with rules.

* Smart folders ("smart") show every file that matches their rule; nothing is moved,
  so a file can appear in any number of smart folders.
* Auto-filing folders ("auto") move matching files that aren't in any folder yet into
  themselves: right after you save the rule, whenever indexing catches up, and every
  few minutes for files that arrive live. Files you file by hand are never moved.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Optional

from .tasks import spawn

if TYPE_CHECKING:
    from .accounts import Account

log = logging.getLogger("tgdrive.autofile")

PER_RUN = 5000
INTERVAL = 600


def folder_rules(folder: dict) -> Optional[dict]:
    raw = folder.get("rules")
    if not raw:
        return None
    try:
        r = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return None
    return r if isinstance(r, dict) else None


def rule_params(rules: dict) -> dict:
    p = {str(k): str(v) for k, v in (rules.get("params") or {}).items()}
    if rules.get("q"):
        p["q"] = rules["q"]
    return p


class AutoFiler:
    def __init__(self, account: "Account"):
        self.acc = account
        self.task: Optional[asyncio.Task] = None
        self._wake = asyncio.Event()
        self.last_run = 0.0
        self.last_filed: dict[str, int] = {}
        self.running = False

    def start(self) -> None:
        if not self.task or self.task.done():
            self.task = spawn(self._loop(), "auto-filing")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass

    def poke(self) -> None:
        self._wake.set()

    async def _loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                if self.acc.status == "online" and self.acc.drive.loaded:
                    await self.run_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("auto-filing failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), INTERVAL)
                await asyncio.sleep(3)  # let a burst of changes settle
            except asyncio.TimeoutError:
                pass

    def auto_folders(self) -> list[dict]:
        return [f for f in self.acc.db.q("SELECT id, name, rules, kind FROM folders WHERE kind='auto'")
                if folder_rules(f)]

    async def run_all(self) -> dict[str, int]:
        if self.running:
            return {}
        self.running = True
        try:
            out = {}
            for f in self.auto_folders():
                out[f["id"]] = await self.run_folder(f)
            self.last_run = time.time()
            return out
        finally:
            self.running = False

    async def run_folder(self, folder: dict, limit: int = PER_RUN) -> int:
        rules = folder_rules(folder)
        if not rules:
            return 0
        p = {**rule_params(rules), "filed": "0", "limit": "500", "sort": "date", "order": "desc"}
        items: list[tuple[int, int]] = []
        cursor = None
        while len(items) < limit:
            if cursor:
                p["cursor"] = cursor
            res = await self.acc.search.files(p)
            # "related by meaning" results are too loose to move files automatically
            items += [(r["chat_id"], r["msg_id"]) for r in res["items"] if r.get("match") != "related"]
            cursor = res.get("next")
            if not cursor:
                break
        items = items[:limit]
        if items:
            if not self.acc.db.get_folder(folder["id"]):
                return 0
            for i in range(0, len(items), 500):
                await self.acc.drive.place(items[i:i + 500], folder["id"], undo=False)
            self.acc.db.log_activity("auto-file", f"Filed {len(items)} files into “{folder['name']}” by its rule")
        self.last_filed[folder["id"]] = len(items)
        return len(items)
