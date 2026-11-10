"""Two-level progress bar: overall pipeline (weighted, with ETA) + the current step."""
from __future__ import annotations

from contextlib import contextmanager

from rich.progress import (BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn,
                           TimeElapsedColumn, TimeRemainingColumn)

# rough relative cost of each step (per call). Transcribe/render dominate.
WEIGHTS = {"ingest": 3, "highlight": 4, "fetch": 6, "transcribe": 10, "frame": 4, "render": 10, "publish": 6}
PER_CLIP = ["fetch", "transcribe", "frame", "render"]


def total_weight(n_clips: int, upload: bool) -> float:
    per_clip = sum(WEIGHTS[s] for s in PER_CLIP) + (WEIGHTS["publish"] if upload else 0)
    return WEIGHTS["ingest"] + WEIGHTS["highlight"] + n_clips * per_clip


class Pipeline:
    def __init__(self, console, total: float):
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description:<34}"),
            BarColumn(bar_width=36),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("ETA"),
            TimeRemainingColumn(),
            console=console,
        )
        self.overall = self.progress.add_task("[bold]Overall", total=total)
        self.current = self.progress.add_task("", total=1, visible=False)
        self.done = 0.0

    def __enter__(self):
        self.progress.start()
        return self

    def __exit__(self, *exc):
        self.progress.update(self.current, visible=False)
        self.progress.stop()

    def set_total(self, total: float):
        self.progress.update(self.overall, total=max(total, self.done))

    @contextmanager
    def step(self, name: str, label: str = "", total: float | None = None):
        h = StepHandle(self, name, WEIGHTS.get(name, 1), label, total)
        try:
            yield h
        finally:
            h.finish()


class StepHandle:
    def __init__(self, pipe: Pipeline, name: str, weight: float, label: str, total):
        self.p, self.name, self.w = pipe, name, weight
        self.total = total or 1.0
        self.completed = 0.0
        self.label = label
        pipe.progress.reset(pipe.current, total=self.total, completed=0, visible=True,
                            description=self._desc())

    def _desc(self):
        return f"  [cyan]{self.name}[/] {self.label}"[:60]

    def update(self, completed: float | None = None, advance: float | None = None,
               total: float | None = None, label: str | None = None):
        if total:
            self.total = total
        if completed is not None:
            self.completed = completed
        if advance:
            self.completed += advance
        if label is not None:
            self.label = label
        self.completed = min(self.completed, self.total)
        prog = self.p.progress
        prog.update(self.p.current, total=self.total, completed=self.completed, description=self._desc())
        prog.update(self.p.overall, completed=self.p.done + self.w * self.completed / self.total)

    def fraction(self, f: float, label: str | None = None):
        self.update(completed=max(0.0, min(f, 1.0)) * self.total, label=label)

    def finish(self):
        self.p.done += self.w
        self.p.progress.update(self.p.overall, completed=self.p.done)
