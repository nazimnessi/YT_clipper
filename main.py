"""YouTube Clipper - one long video in, vertical Shorts with subtitles out.

    python main.py --url "https://youtu.be/VIDEO_ID"
    python main.py                       # uses the first row of input_video.xlsx
    python main.py --url ... --upload    # also upload (OFF by default)
    python main.py --help                # all options

Steps:  ingest -> highlight -> (per clip) fetch -> transcribe -> frame -> render [-> publish]
Re-running the same command resumes from where it stopped (use --force to redo everything).
"""
from __future__ import annotations

import sys
import time
import traceback
from collections import defaultdict

from rich.panel import Panel
from rich.table import Table

import fetch
import frame
import highlight
import ingest
import publish
import render
import transcribe
from utils import excel, ffmpeg, net
from utils import log as logs
from utils.config import load_settings
from utils.job import Job
from utils.log import console
from utils.progress import WEIGHTS, Pipeline, total_weight
from utils.youtube import video_id, watch_url

log = logs.get("main")
CLIP_STEPS = [("fetch", fetch.run), ("transcribe", transcribe.run), ("frame", frame.run),
              ("render", render.run), ("publish", publish.run)]


def resolve_input(s):
    rows = excel.read_rows(s.excel)
    url = s.url
    if not url:
        if not rows:
            raise SystemExit("No video given. Use --url <youtube link> or fill input_video.xlsx "
                             "(columns: video_url, yt_account).")
        url = rows[0]["video_url"]
        log.info(f"using first row of {s.excel}")
    vid = video_id(url)
    account = s.yt_account or excel.find_account(rows, vid)
    return url, vid, account


def banner(s, vid, account, log_file):
    t = Table.grid(padding=(0, 2))
    t.add_row("Video", watch_url(vid))
    t.add_row("YT account", account or "-")
    t.add_row("Clips", f"{s.clips} x {s.min_sec:.0f}-{s.max_sec:.0f}s, layout {s.layout}")
    t.add_row("AI", f"{s.ai} ({len(s.ai_model_hierarchy)} ranked models)")
    t.add_row("Whisper", f"{s.whisper_model} on {s.whisper_device}")
    t.add_row("Upload", f"ON ({s.privacy})" if s.upload else "OFF (use --upload to enable)")
    t.add_row("Output", str(s.out / vid))
    t.add_row("Log", str(log_file))
    console.print(Panel(t, title="YouTube Clipper", expand=False))


def summary(job, results, timings, started):
    t = Table(title="Result", show_lines=False)
    for col in ("#", "Title", "Length", "Layout", "Picked by", "Status", "File / URL"):
        t.add_column(col, overflow="fold")
    for r in results:
        t.add_row(str(r["index"]), r["title"][:45], f"{r.get('length', 0):.0f}s", r.get("layout", "-"),
                  r.get("picked_by", "-"), r["status"], r.get("url") or r.get("output") or r.get("error", "")[:60])
    console.print(t)
    tt = " | ".join(f"{k} {v:.0f}s" for k, v in timings.items())
    console.print(f"[dim]Time per step: {tt}[/]")
    console.print(f"[bold]Total time: {time.time() - started:.0f}s[/]   results: {job.path('results.json')}")


def main():
    s = load_settings()
    log_file = logs.setup_logging(s.logs, s.verbose)
    if s.insecure:
        net.enable_insecure()
        log.warning("SSL certificate checks are OFF (--insecure)")
    ffmpeg.check_installed()

    url, vid, account = resolve_input(s)
    s.yt_account = account
    banner(s, vid, account, log_file)

    job = Job(settings=s, url=url, video_id=vid, folder=s.out / vid)
    if s.force:
        job.state.clear()
    vlog = logs.add_file_log(job.path("run.log"))
    log.info(f"run started for {vid} (settings: {s.model_dump_json(exclude={'subtitles'})})")
    started = time.time()
    timings = defaultdict(float)
    results = []

    def timed(name, fn, *a):
        t = time.time()
        try:
            return fn(*a)
        finally:
            timings[name] += time.time() - t

    try:
        with Pipeline(console, total_weight(s.clips, s.upload)) as pipe:
            job.pipe = pipe
            timed("ingest", ingest.run, job)
            clips = timed("highlight", highlight.run, job)
            pipe.set_total(total_weight(len(clips), s.upload))

            for clip in clips:
                n = clip["index"]
                rec = {"index": n, "title": clip["title"], "picked_by": clip.get("picked_by"),
                       "start": clip["start"], "end": clip["end"], "status": "ok"}
                for i, (name, fn) in enumerate(CLIP_STEPS):
                    if name == "publish" and not s.upload:
                        continue
                    try:
                        timed(name, fn, job, clip)
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:  # noqa: BLE001 - one bad clip shouldn't stop the others
                        log.error(f"clip {n}: {name} failed: {str(e).splitlines()[0][:300]}")
                        log.debug(traceback.format_exc())
                        job.state.mark(f"clip_{n}.{name}", status="failed", error=str(e)[:500])
                        rec.update(status=f"failed at {name}", error=str(e).splitlines()[0][:200])
                        rest = [x for x, _ in CLIP_STEPS[i + 1:] if x != "publish" or s.upload]
                        pipe.done += sum(WEIGHTS[x] for x in rest)   # keep the ETA honest
                        break
                meta = job.clip_meta(n)
                fr = job.load(f"clip_{n}", "frame.json", default={})
                rec.update(length=meta.get("final_duration") or meta.get("duration") or 0,
                           layout="+".join(sorted({
                               sg.get("composition", {}).get("layout", sg["layout"])
                               for sg in fr.get("segments", [])
                           })) or "-",
                           output=meta.get("output"), url=meta.get("url"))
                if rec["status"] == "ok" and not s.upload:
                    rec["status"] = "ok (not uploaded)"
                results.append(rec)
    except KeyboardInterrupt:
        log.warning("stopped by user - run the same command again to resume")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log.error(f"run failed: {e}")
        log.debug(traceback.format_exc())
        console.print(f"[red]Failed - see log: {log_file}[/]")
        sys.exit(1)
    finally:
        logs.remove_handler(vlog)

    job.save({"video": url, "video_id": vid, "yt_account": account, "upload": s.upload,
              "clips": results, "timings": dict(timings)}, "results.json")
    summary(job, results, timings, started)
    ok = sum(r["status"].startswith("ok") for r in results)
    log.info(f"finished: {ok}/{len(results)} clips ok")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
