"""ffmpeg / ffprobe helpers with live progress."""
from __future__ import annotations

import json
import shutil
import subprocess
from collections import deque


class FFmpegError(RuntimeError):
    pass


def check_installed():
    missing = [b for b in ("ffmpeg", "ffprobe") if not shutil.which(b)]
    if missing:
        raise SystemExit(f"{', '.join(missing)} not found on PATH. Install ffmpeg first (see README).")


def probe(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path}: {r.stderr.strip()[-500:]}")
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    fps = 30.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, dnm = v["avg_frame_rate"].split("/")
        fps = float(n) / float(dnm) if float(dnm) else 30.0
    return {
        "duration": float(d["format"].get("duration", 0) or 0),
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "fps": fps,
        "has_audio": a is not None,
    }


def run(args: list, duration: float | None = None, on_progress=None, log=None, cwd=None):
    """Run ffmpeg; calls on_progress(fraction 0..1) while encoding. Raises FFmpegError with stderr tail."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error", "-progress", "pipe:1", *map(str, args)]
    if log:
        log.debug("ffmpeg " + " ".join(f'"{a}"' if " " in str(a) else str(a) for a in cmd[1:]))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", cwd=cwd)
    err_tail = deque(maxlen=40)

    import threading
    t = threading.Thread(target=lambda: [err_tail.append(l) for l in proc.stderr], daemon=True)
    t.start()
    for line in proc.stdout:
        if on_progress and duration and line.startswith("out_time_us="):
            try:
                on_progress(min(int(line.split("=")[1]) / 1e6 / duration, 1.0))
            except ValueError:
                pass
    proc.wait()
    t.join(timeout=2)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg exited with {proc.returncode}:\n" + "".join(err_tail)[-2000:])
