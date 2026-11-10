"""Job = one video being processed: settings, folders, saved state, progress, JSON helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from utils.state import State


@dataclass
class Job:
    settings: object
    url: str
    video_id: str
    folder: Path
    state: State = field(init=False)
    pipe: object = None

    def __post_init__(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state = State(self.folder)

    # -------- files
    def path(self, *parts) -> Path:
        return self.folder.joinpath(*parts)

    def clip_dir(self, n: int) -> Path:
        d = self.folder / f"clip_{n}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load(self, *parts, default=None):
        p = self.path(*parts)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    def save(self, data, *parts):
        p = self.path(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    # -------- clips
    def clips(self) -> list[dict]:
        return self.load("highlights.json", default=[])

    def clip_meta(self, n: int) -> dict:
        return self.load(f"clip_{n}", "clip.json", default={})

    def update_clip_meta(self, n: int, **kv) -> dict:
        meta = self.clip_meta(n) | kv
        self.save(meta, f"clip_{n}", "clip.json")
        return meta

    # -------- step bookkeeping
    def should_skip(self, key: str) -> bool:
        return self.state.done(key) and not self.settings.force


def standalone(step_name: str, run_fn, per_clip: bool):
    """Run one step module on its own:  python frame.py --video <id> [--clip N]"""
    from utils import log as logs
    from utils import net
    from utils.config import load_settings
    from utils.log import console
    from utils.progress import Pipeline
    from utils.youtube import watch_url

    s = load_settings(standalone=True)
    logs.setup_logging(s.logs, s.verbose)
    if s.insecure:
        net.enable_insecure()
    job = Job(settings=s, url=watch_url(s.video), video_id=s.video, folder=s.out / s.video)
    clips = [c for c in job.clips() if s.clip is None or c["index"] == s.clip] if per_clip else [None]
    with Pipeline(console, total=len(clips) * 10) as pipe:
        job.pipe = pipe
        for c in clips:
            run_fn(job, c) if per_clip else run_fn(job)
    logs.get(step_name).info("done")
