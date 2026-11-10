"""Step 2 - HIGHLIGHT: pick the best moments.

  signals (most-replayed heatmap, timestamps in comments, chapters) + transcript
  -> pass 1: AI proposes ~12 candidates
  -> pass 2: AI scores each (hook, payoff, standalone, emotion) and writes a title
  -> keep the top N, non-overlapping
  AI chain: Claude -> Gemini -> heuristic (heatmap + comments + speech density)

Output: highlights.json  [{index, start, end, title, score, reason, picked_by}]
"""
from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel, Field

from utils import log as logs
from utils.ai import AIUnavailable, ask_json

log = logs.get("highlight")
N_CANDIDATES = 12


class Candidate(BaseModel):
    start: float
    end: float
    title: str = ""
    reason: str = ""


class Score(BaseModel):
    id: int
    hook: float = Field(ge=0, le=10)
    payoff: float = Field(ge=0, le=10)
    standalone: float = Field(ge=0, le=10)
    emotion: float = Field(ge=0, le=10)
    title: str = ""


PASS1 = """You are an expert short-form video editor who finds viral YouTube Shorts inside long videos.

Video: "{title}" by {channel} ({minutes:.0f} min)
{signals}
Below is the transcript. Each line starts with its start time in seconds.

Find the {n} best moments for standalone Shorts. Each moment must:
- be between {min_s:.0f} and {max_s:.0f} seconds long
- open with a strong hook in the first 3 seconds (bold claim, surprising fact, question, conflict, punchline setup)
- end on a complete thought or payoff (never mid-sentence)
- make sense to someone who has NOT seen the rest of the video
- not overlap with other moments
Favour moments viewers rewatched or mentioned in comments (see signals), but only if they also work as a clip.

Return ONLY a JSON array, no other text:
[{{"start": <seconds>, "end": <seconds>, "title": "<catchy title, max 70 chars>", "reason": "<one short sentence>"}}]

TRANSCRIPT:
{transcript}"""

PASS2 = """You are judging candidate YouTube Shorts cut from the video "{title}".
Score each candidate 0-10 on:
- hook: do the first 3 seconds grab attention?
- payoff: is there a satisfying ending / insight / punchline?
- standalone: does it make sense without the rest of the video?
- emotion: is it funny, surprising, inspiring, controversial or useful?
Also write the best possible Shorts title for it (max 70 chars, no hashtags, same language as the clip).

Return ONLY a JSON array, one entry per candidate:
[{{"id": <id>, "hook": <0-10>, "payoff": <0-10>, "standalone": <0-10>, "emotion": <0-10>, "title": "<title>"}}]

CANDIDATES:
{candidates}"""


# ---------------------------------------------------------------- signals
TS_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?(\d{1,2}):([0-5]\d)(?![\d:])")


def comment_times(comments, duration) -> list[tuple[float, int]]:
    out = []
    for c in comments:
        for h, m, sec in TS_RE.findall(c.get("text", "")):
            t = int(h or 0) * 3600 + int(m) * 60 + int(sec)
            if 0 < t < duration:
                out.append((t, 1 + int(c.get("likes") or 0)))
    return out


def heat_peaks(heatmap, k=8, min_gap=45) -> list[dict]:
    bins = sorted(heatmap, key=lambda b: -b.get("value", 0))
    peaks = []
    for b in bins:
        if b.get("value", 0) < 0.3:
            break
        if all(abs(b["start_time"] - p["start_time"]) >= min_gap for p in peaks):
            peaks.append(b)
        if len(peaks) == k:
            break
    return sorted(peaks, key=lambda b: b["start_time"])


def heat_avg(heatmap, a, b) -> float:
    tot = wsum = 0.0
    for x in heatmap:
        ov = min(b, x["end_time"]) - max(a, x["start_time"])
        if ov > 0:
            tot += x.get("value", 0) * ov
            wsum += ov
    return tot / wsum if wsum else 0.0


def signals_text(heatmap, ctimes, chapters) -> str:
    lines = []
    peaks = heat_peaks(heatmap)
    if peaks:
        lines.append("MOST REPLAYED (YouTube heatmap, value 0-1): " +
                     ", ".join(f"{p['start_time']:.0f}-{p['end_time']:.0f}s ({p['value']:.2f})" for p in peaks))
    if ctimes:
        agg = {}
        for t, w in ctimes:
            agg[int(t // 15) * 15] = agg.get(int(t // 15) * 15, 0) + w
        top = sorted(agg.items(), key=lambda kv: -kv[1])[:10]
        lines.append("TIMESTAMPS MENTIONED IN COMMENTS (weight = likes+1): " +
                     ", ".join(f"~{t}s ({w})" for t, w in sorted(top)))
    if chapters:
        lines.append("CHAPTERS: " + "; ".join(f"{c.get('start_time', 0):.0f}s {c.get('title', '')}"
                                              for c in chapters[:40]))
    return ("\nSIGNALS:\n" + "\n".join(lines) + "\n") if lines else ""


# ---------------------------------------------------------------- transcript
def merge_lines(segs, max_len=8.0) -> list[dict]:
    out, cur = [], None
    for sg in segs:
        if cur and (sg["end"] - cur["start"] > max_len or cur["text"].endswith((".", "?", "!"))):
            out.append(cur)
            cur = None
        if cur is None:
            cur = dict(sg)
        else:
            cur["end"] = sg["end"]
            cur["text"] += " " + sg["text"]
    if cur:
        out.append(cur)
    return out


def transcript_text(segs, max_chars=350_000) -> str:
    for chunk in (8, 15, 30, 60):
        lines = merge_lines(segs, chunk)
        text = "\n".join(f"[{x['start']:.1f}] {x['text']}" for x in lines)
        if len(text) <= max_chars:
            return text
    return text[:max_chars]


def text_between(segs, a, b) -> str:
    return " ".join(x["text"] for x in segs if x["end"] > a and x["start"] < b)


# ---------------------------------------------------------------- clean-up
def fit_and_dedupe(cands, segs, duration, s, n) -> list[dict]:
    starts = [x["start"] for x in segs] or [0.0]
    ends = [x["end"] for x in segs] or [duration]
    fixed = []
    for c in cands:
        a = max(0.0, min(c["start"], duration))
        nearest = min(starts, key=lambda t: abs(t - a))
        if abs(nearest - a) < 3:          # snap to the start of a caption line
            a = nearest
        b = min(c["end"], duration)
        if b - a < s.min_sec:
            b = a + s.min_sec
        if b - a > s.max_sec:
            b = a + s.max_sec
        near = [e for e in ends if s.min_sec <= e - a <= s.max_sec]
        if near:
            b = min(near, key=lambda e: abs(e - b))
        b = min(b, duration)
        if b - a >= s.min_sec * 0.8:
            fixed.append(c | {"start": round(a, 2), "end": round(b, 2)})
    fixed.sort(key=lambda c: -c.get("score", 0))
    chosen = []
    for c in fixed:
        if all(c["end"] <= o["start"] or c["start"] >= o["end"] for o in chosen):
            chosen.append(c)
        if len(chosen) == n:
            break
    chosen.sort(key=lambda c: c["start"])
    return [c | {"index": i} for i, c in enumerate(chosen, 1)]


# ---------------------------------------------------------------- pickers
def ai_pick(info, segs, heatmap, ctimes, s) -> list[dict]:
    duration = info.get("duration") or (segs[-1]["end"] if segs else 0)
    prompt = PASS1.format(title=info.get("title", ""), channel=info.get("channel", ""), minutes=duration / 60,
                          signals=signals_text(heatmap, ctimes, info.get("chapters")), n=N_CANDIDATES,
                          min_s=s.min_sec, max_s=s.max_sec, transcript=transcript_text(segs))
    log.debug(f"pass 1 prompt: {len(prompt)} chars")
    cands, provider = ask_json(prompt, List[Candidate], s, log, what="find candidates")
    cands = [c.model_dump() for c in cands if c.end > c.start]
    log.info(f"pass 1 ({provider}): {len(cands)} candidates")

    listing = "\n\n".join(f"id {i}: {c['start']:.0f}-{c['end']:.0f}s\n\"{text_between(segs, c['start'], c['end'])[:1500]}\""
                          for i, c in enumerate(cands))
    try:
        scores, p2 = ask_json(PASS2.format(title=info.get("title", ""), candidates=listing),
                              List[Score], s, log, what="score candidates")
        by_id = {x.id: x for x in scores}
        for i, c in enumerate(cands):
            sc = by_id.get(i)
            if sc:
                c["score"] = round(0.35 * sc.hook + 0.25 * sc.payoff + 0.25 * sc.standalone + 0.15 * sc.emotion
                                   + 2 * heat_avg(heatmap, c["start"], c["end"]), 2)
                c["title"] = sc.title or c["title"]
                c["detail"] = sc.model_dump(exclude={"id", "title"})
            else:
                c["score"] = 0
        provider = provider if p2 == provider else f"{provider}+{p2}"
        log.info(f"pass 2 ({p2}): scored {len(scores)} candidates")
    except AIUnavailable:
        log.warning("scoring pass failed - keeping pass-1 order")
        for i, c in enumerate(cands):
            c["score"] = round(10 - i * 0.5 + 2 * heat_avg(heatmap, c["start"], c["end"]), 2)
    for c in cands:
        c["picked_by"] = provider
    return cands


def heuristic_pick(segs, heatmap, ctimes, s) -> list[dict]:
    """Free fallback: most-replayed heatmap + comment timestamps + speech density."""
    target = (s.min_sec + s.max_sec) / 2
    cands = []
    max_c = max([w for _, w in ctimes], default=1)
    for i, sg in enumerate(segs):
        a, b = sg["start"], sg["start"] + target
        words = sum(len(x["text"].split()) for x in segs if a <= x["start"] < b)
        mentions = sum(w for t, w in ctimes if a - 5 <= t <= b)
        score = (6 * heat_avg(heatmap, a, b) + 3 * min(mentions / max_c, 1) + 1 * min(words / (target * 3), 1))
        cands.append({"start": a, "end": b, "title": sg["text"][:70], "score": round(score, 3),
                      "reason": "heatmap/comments/speech density", "picked_by": "heuristic"})
    return cands


def run(job) -> list[dict]:
    s = job.settings
    if job.should_skip("highlight") and job.clips():
        log.info("highlights already chosen - skipping")
        with job.pipe.step("highlight", "(cached)"):
            return job.clips()
    info = job.load("info.json")
    segs = job.load("captions.json", default=[])
    heatmap = job.load("heatmap.json", default=[])
    comments = job.load("comments.json", default=[])
    if not segs:
        raise RuntimeError("no transcript available - cannot pick highlights")
    duration = info.get("duration") or segs[-1]["end"]
    ctimes = comment_times(comments, duration)

    with job.pipe.step("highlight", "asking AI", total=3) as step:
        cands = []
        if s.ai != "heuristic":
            try:
                cands = ai_pick(info, segs, heatmap, ctimes, s)
            except AIUnavailable as e:
                log.warning(f"{e} - using heuristic picker")
        step.update(completed=2, label="selecting")
        clips = fit_and_dedupe(cands, segs, duration, s, s.clips) if cands else []
        if len(clips) < s.clips:
            if cands:
                log.warning(f"AI gave only {len(clips)} usable clips - filling the rest with the heuristic")
            extra = fit_and_dedupe(heuristic_pick(segs, heatmap, ctimes, s), segs, duration, s, s.clips * 3)
            for c in extra:
                if len(clips) >= s.clips:
                    break
                if all(c["end"] <= o["start"] or c["start"] >= o["end"] for o in clips):
                    clips.append(c)
            clips = [c | {"index": i} for i, c in enumerate(sorted(clips, key=lambda c: c["start"]), 1)]
        step.update(completed=3)

    if not clips:
        raise RuntimeError("no usable clips found (video too short for the min/max clip length?)")
    for c in clips:
        log.info(f"clip {c['index']}: {c['start']:.1f}-{c['end']:.1f}s ({c['end'] - c['start']:.0f}s) "
                 f"score {c.get('score', 0)} [{c['picked_by']}] \"{c['title']}\"")
    job.save(clips, "highlights.json")
    job.state.mark("highlight", clips=len(clips))
    return clips


if __name__ == "__main__":
    from utils.job import standalone
    standalone("highlight", run, per_clip=False)
