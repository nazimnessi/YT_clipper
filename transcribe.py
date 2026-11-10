"""Step 5 - TRANSCRIBE: Whisper on each clip -> exact word timings, then tighten start/end onto natural pauses.

Output per clip: clip_N/words.json  and  clip.json {trim_start, trim_end, words}
"""
from __future__ import annotations

from utils import log as logs

log = logs.get("transcribe")
_MODEL = None
PAUSE = 0.35           # gap (s) between words that counts as a natural break
SNAP_WINDOW = 3.0      # how far (s) we may move a clip edge to land on a break


def _load_model(s):
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        device, compute = s.whisper_device, "int8"
        if device == "auto":
            try:
                import ctranslate2
                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:  # noqa: BLE001
                device = "cpu"
        if device == "cuda":
            compute = "float16"
        log.info(f"loading Whisper '{s.whisper_model}' on {device} (first run downloads the model)")
        _MODEL = WhisperModel(s.whisper_model, device=device, compute_type=compute)
    return _MODEL


def transcribe_file(path, s, step=None, language=None) -> tuple[list[dict], str]:
    """Return ([{start,end,text,words:[{w,s,e}]}], language). Times relative to the file."""
    model = _load_model(s)
    segments, info = model.transcribe(str(path), language=language or s.language,
                                      word_timestamps=True, vad_filter=True)
    dur = info.duration or 1
    out = []
    for seg in segments:
        out.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip(),
                    "words": [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)}
                              for w in (seg.words or []) if w.word.strip()]})
        if step:
            step.fraction(seg.end / dur, label=f"{seg.end:.0f}/{dur:.0f}s audio")
    return out, info.language


def flat_words(segments) -> list[dict]:
    return [w for seg in segments for w in seg["words"]]


def _is_break_before(words, i) -> bool:
    """True if a sentence/pause boundary sits right before words[i]."""
    if i == 0:
        return True
    prev = words[i - 1]
    return words[i]["s"] - prev["e"] >= PAUSE or prev["w"].endswith((".", "?", "!"))


def _is_break_after(words, i) -> bool:
    if i == len(words) - 1:
        return True
    return words[i + 1]["s"] - words[i]["e"] >= PAUSE or words[i]["w"].endswith((".", "?", "!"))


def snap_edges(words, target_start, target_end, min_len, max_len) -> tuple[float, float]:
    """Move start/end to the nearest natural break within SNAP_WINDOW, keeping length in range."""
    if not words:
        return target_start, target_end

    def nearest(idx_ok, key, target):
        cands = [words[i][key] for i in range(len(words)) if idx_ok(i) and abs(words[i][key] - target) <= SNAP_WINDOW]
        if not cands:  # no break nearby: nearest word edge
            cands = [w[key] for w in words]
        return min(cands, key=lambda t: abs(t - target))

    start = nearest(lambda i: _is_break_before(words, i), "s", target_start)
    end_cands = sorted({words[i]["e"] for i in range(len(words)) if _is_break_after(words, i)},
                       key=lambda t: abs(t - target_end))
    end = next((e for e in end_cands if min_len <= e - start <= max_len and abs(e - target_end) <= SNAP_WINDOW * 2),
               None)
    if end is None:
        end = nearest(lambda i: True, "e", target_end)
        end = min(max(end, start + min_len), start + max_len)
    return start, end


def run(job, clip: dict):
    s, n = job.settings, clip["index"]
    key = f"clip_{n}.transcribe"
    if job.should_skip(key):
        log.info(f"clip {n}: already transcribed - skipping")
        with job.pipe.step("transcribe", f"clip {n} (cached)"):
            return
    meta = job.clip_meta(n)
    src = job.clip_dir(n) / "source.mp4"
    with job.pipe.step("transcribe", f"clip {n}") as step:
        segs, lang = transcribe_file(src, s, step, language=job.load("info.json", default={}).get("language"))
        words = flat_words(segs)
        job.save(segs, f"clip_{n}", "words.json")

        # clip times relative to the downloaded section file
        t_start = clip["start"] - meta["section_start"]
        t_end = clip["end"] - meta["section_start"]
        start, end = snap_edges(words, t_start, t_end, s.min_sec, s.max_sec)
        start = max(0.0, start - 0.15)
        end = min(meta.get("section_duration", end + 1), end + 0.3)
        clip_words = [{"w": w["w"], "s": round(w["s"] - start, 2), "e": round(w["e"] - start, 2)}
                      for w in words if w["s"] >= start - 0.05 and w["e"] <= end + 0.05]
        job.update_clip_meta(n, trim_start=round(start, 2), trim_end=round(end, 2),
                             duration=round(end - start, 2), language=lang, words=clip_words)
    log.info(f"clip {n}: {len(clip_words)} words, trimmed to {end - start:.1f}s "
             f"(moved start {start - t_start:+.1f}s, end {end - t_end:+.1f}s)")
    job.state.mark(key)


if __name__ == "__main__":
    from utils.job import standalone
    standalone("transcribe", run, per_clip=True)
