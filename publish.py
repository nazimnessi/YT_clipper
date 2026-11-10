"""Step 8 - PUBLISH (OFF by default, enable with --upload).
AI writes title/description/tags -> upload to YouTube with progress.

Output: clip_N/upload.json {url, title, ...}
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel

from utils import log as logs
from utils import youtube as yt
from utils.ai import AIUnavailable, ask_json

log = logs.get("publish")


class Meta(BaseModel):
    title: str
    description: str
    tags: List[str] = []


PROMPT = """Write YouTube Shorts metadata for this clip.
Original video: "{vtitle}" by {channel}
Clip working title: "{title}"
Clip transcript: "{text}"

Return ONLY JSON: {{"title": "<max 70 chars, hooky, no hashtags>",
"description": "<2-3 short lines in the clip's language, no links>", "tags": ["<5-10 tags>"]}}"""


def make_metadata(job, clip, meta, s) -> dict:
    info = job.load("info.json", default={})
    text = " ".join(w["w"] for w in meta.get("words", []))[:2500]
    try:
        m, provider = ask_json(PROMPT.format(vtitle=info.get("title", ""), channel=info.get("channel", ""),
                                             title=clip["title"], text=text), Meta, s, log, what="write metadata",
                               max_tokens=800)
        title, desc, tags = m.title, m.description, m.tags
    except AIUnavailable:
        title, desc, tags, provider = clip["title"], "", [], "none"
    credit = f"\n\nOriginal video: {info.get('webpage_url') or job.url}\nCredit: {info.get('channel', '')}"
    return {"title": f"{title[:90]} #Shorts", "description": f"{desc}{credit}\n\n#Shorts",
            "tags": ["shorts", *tags, info.get("channel") or ""], "meta_by": provider}


def run(job, clip: dict):
    s, n = job.settings, clip["index"]
    key = f"clip_{n}.publish"
    if not s.upload:
        return
    if job.should_skip(key):
        log.info(f"clip {n}: already uploaded - {job.load(f'clip_{n}', 'upload.json', default={}).get('url')}")
        with job.pipe.step("publish", f"clip {n} (cached)"):
            return
    meta = job.clip_meta(n)
    with job.pipe.step("publish", f"clip {n}", total=1) as step:
        md = make_metadata(job, clip, meta, s)
        step.update(label="uploading")
        url = yt.upload(job.clip_dir(n) / "final.mp4", md["title"], md["description"],
                        [t for t in md["tags"] if t], s, step=step)
    job.save(md | {"url": url, "privacy": s.privacy}, f"clip_{n}", "upload.json")
    job.update_clip_meta(n, url=url)
    log.info(f"clip {n}: uploaded ({s.privacy}) -> {url}")
    job.state.mark(key, url=url)


if __name__ == "__main__":
    from utils.job import standalone
    standalone("publish", run, per_clip=True)
