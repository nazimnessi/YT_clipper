"""Step 3 - FETCH: download only each clip's time range (+ padding), not the whole video.

Output: clip_N/source.mp4 and clip.json {section_start, section_end, section_duration}
"""
from __future__ import annotations

from utils import ffmpeg
from utils import log as logs
from utils import youtube as yt
from utils.retry import retry

log = logs.get("fetch")


def run(job, clip: dict):
    s, n = job.settings, clip["index"]
    key = f"clip_{n}.fetch"
    out = job.clip_dir(n) / "source.mp4"
    if job.should_skip(key) and out.exists():
        log.info(f"clip {n}: already downloaded - skipping")
        with job.pipe.step("fetch", f"clip {n} (cached)"):
            return
    duration = job.load("info.json", default={}).get("duration") or clip["end"] + s.pad_sec
    a = max(0.0, clip["start"] - s.pad_sec)
    b = min(duration, clip["end"] + s.pad_sec)
    with job.pipe.step("fetch", f"clip {n}") as step:
        log.info(f"clip {n}: downloading {a:.1f}-{b:.1f}s")
        retry(lambda: yt.download_section(job.url, a, b, out, s, log, step=step), attempts=3, log=log,
              what=f"download clip {n}")
        info = ffmpeg.probe(out)
    if info["duration"] < (b - a) * 0.5:
        raise RuntimeError(f"downloaded clip is too short ({info['duration']:.1f}s, expected {b - a:.1f}s)")
    job.update_clip_meta(n, index=n, title=clip["title"], start=clip["start"], end=clip["end"],
                         section_start=round(a, 2), section_end=round(b, 2),
                         section_duration=round(info["duration"], 2),
                         width=info["width"], height=info["height"], fps=info["fps"])
    log.info(f"clip {n}: {info['width']}x{info['height']} @ {info['fps']:.0f}fps, {info['duration']:.1f}s, "
             f"{out.stat().st_size / 1e6:.1f} MB")
    job.state.mark(key)


if __name__ == "__main__":
    from utils.job import standalone
    standalone("fetch", run, per_clip=True)
