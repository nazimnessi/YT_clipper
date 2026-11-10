"""Step 1 - INGEST: video details, captions, most-replayed heatmap, chapters and top comments.
No video download here.

Output: info.json, captions.json, heatmap.json, comments.json
"""
from __future__ import annotations

from utils import log as logs
from utils import youtube as yt
from utils.retry import retry

log = logs.get("ingest")
INFO_KEYS = ["id", "title", "channel", "channel_url", "uploader", "duration", "language", "upload_date",
             "view_count", "like_count", "tags", "chapters", "webpage_url"]


def run(job):
    s = job.settings
    if job.should_skip("ingest"):
        log.info("already ingested - skipping")
        with job.pipe.step("ingest", "(cached)"):
            return
    with job.pipe.step("ingest", "video details", total=4) as step:
        try:
            info = retry(lambda: yt.extract_info(job.url, s, log, comments=True), attempts=2, log=log,
                         what="video info + comments")
        except Exception as e:  # noqa: BLE001 - comments are optional, try without
            log.warning(f"could not get comments ({str(e)[:150]}); retrying without them")
            info = retry(lambda: yt.extract_info(job.url, s, log, comments=False), attempts=3, log=log,
                         what="video info")
        step.update(completed=1, label="saving details")

        meta = {k: info.get(k) for k in INFO_KEYS}
        meta["description"] = (info.get("description") or "")[:3000]
        meta["yt_account"] = s.yt_account
        job.save(meta, "info.json")
        job.save(info.get("heatmap") or [], "heatmap.json")
        comments = [{"text": c.get("text", ""), "likes": c.get("like_count") or 0}
                    for c in (info.get("comments") or [])]
        job.save(comments, "comments.json")
        log.info(f"'{meta['title']}' by {meta['channel']} - {(meta['duration'] or 0) / 60:.1f} min, "
                 f"heatmap: {'yes' if info.get('heatmap') else 'no'}, comments: {len(comments)}, "
                 f"chapters: {len(meta['chapters'] or [])}")

        step.update(completed=2, label="captions")
        segs, lang = [], None
        try:
            segs, lang = retry(lambda: yt.fetch_captions(info, s, log), attempts=2, log=log, what="captions")
        except Exception as e:  # noqa: BLE001
            log.warning(f"caption download failed: {str(e)[:200]}")

        if not segs:
            log.warning("no YouTube captions - downloading audio and transcribing the full video "
                        "with Whisper (slow)")
            from transcribe import transcribe_file
            audio = yt.download_audio(job.url, job.folder, s, log, step=step)
            step.update(completed=0, total=1, label="transcribing full audio")
            full, lang = transcribe_file(audio, s, step=step)
            segs = [{"start": x["start"], "end": x["end"], "text": x["text"]} for x in full]
        if lang:
            meta["language"] = meta.get("language") or lang
            job.save(meta, "info.json")
        job.save(segs, "captions.json")
        step.update(completed=step.total)

    log.info(f"transcript ready: {len(segs)} lines")
    job.state.mark("ingest", title=meta["title"])


if __name__ == "__main__":
    from utils.job import standalone
    standalone("ingest", run, per_clip=False)
