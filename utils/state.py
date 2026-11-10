"""Remembers which steps finished (data/<video>/state.json) so a re-run resumes where it stopped."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class State:
    def __init__(self, folder: Path):
        self.path = folder / "state.json"
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def done(self, key: str) -> bool:
        return self.data.get(key, {}).get("status") == "done"

    def mark(self, key: str, status: str = "done", **info):
        self.data[key] = {"status": status, "at": datetime.now().isoformat(timespec="seconds"), **info}
        self._save()

    def clear(self, prefix: str = ""):
        self.data = {k: v for k, v in self.data.items() if prefix and not k.startswith(prefix)}
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
