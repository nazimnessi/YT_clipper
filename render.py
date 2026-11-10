"""Step 7 - RENDER: one ffmpeg pass per clip.

  per segment layout (single crop / stacked / blurred wide) -> join -> karaoke subtitles + hook title
  -> loudness normalised audio -> 1080x1920 H.264 mp4

Output: clip_N/final.mp4  (+ a copy in data/<video>/output/ with a readable name)
"""
from __future__ import annotations

import re
import shutil

from utils import ffmpeg
from utils import log as logs

log = logs.get("render")
W_OUT, H_OUT = 1080, 1920


# ---------------------------------------------------------------- subtitles (.ass)
def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def _esc(t: str) -> str:
    return t.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def group_words(words, per_line: int, pause: float = 0.6) -> list[list[dict]]:
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if (len(cur) >= per_line or w["w"].endswith((".", "?", "!", ",")) or nxt is None
                or nxt["s"] - w["e"] > pause):
            groups.append(cur)
            cur = []
    return groups


def layout_at(segments, t) -> str:
    for sg in segments:
        if sg["start"] <= t < sg["end"]:
            return sg["layout"]
    return segments[-1]["layout"] if segments else "single"


def build_ass(words, segments, title, s, duration) -> str:
    st = s.subtitles
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W_OUT}
PlayResY: {H_OUT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{st.font},{st.font_size},{st.text_color},{st.text_color},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{st.outline},2,2,60,60,0,1
Style: Hook,{st.font},66,&H00FFFFFF,&H00FFFFFF,&H30000000,&H30000000,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if s.hook_title and title:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(min(s.hook_seconds, duration))},Hook,,0,0,0,,"
                     f"{{\\an8\\pos({W_OUT // 2},170)\\fad(150,250)}}{_esc(title)}")
    groups = group_words(words, st.words_per_line)
    for gi, g in enumerate(groups):
        nxt_start = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else None
        for j, cur in enumerate(g):
            if j + 1 < len(g):
                end = g[j + 1]["s"]
            else:
                end = cur["e"] + 0.25
                if nxt_start is not None:
                    end = min(end, nxt_start)
            end = min(max(end, cur["s"] + 0.05), duration)
            if cur["s"] >= duration:
                continue
            pos = (f"\\an5\\pos({W_OUT // 2},{H_OUT // 2})" if layout_at(segments, cur["s"]) == "stacked"
                   else f"\\an2\\pos({W_OUT // 2},{int(H_OUT * 0.76)})")
            parts = []
            for k, w in enumerate(g):
                txt = _esc(w["w"].upper() if st.uppercase else w["w"])
                parts.append(f"{{\\c{st.highlight_color}\\fscx112\\fscy112}}{txt}{{\\r}}" if k == j else txt)
            lines.append(f"Dialogue: 0,{_ts(cur['s'])},{_ts(end)},Sub,,0,0,0,,{{{pos}}}{' '.join(parts)}")
    return header + "\n".join(lines) + "\n"


# ---------------------------------------------------------------- video filter graph
def _crop(c) -> str:
    x, y, w, h = c
    return f"crop={w}:{h}:{x}:{y}"


def layout_filter(i: int, sg: dict, t0: float) -> str:
    a, b = t0 + sg["start"], t0 + sg["end"]
    head = f"[v{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS"
    composition = sg.get("composition")
    if composition:
        regions = composition["regions"]
        branches = (f"{head},split={len(regions)}" +
                    "".join(f"[r{i}_{j}]" for j in range(len(regions))) + ";")
        base = f"color=c=black:s={W_OUT}x{H_OUT}:r=30:d={b - a:.3f}[canvas{i}]"
        parts = [branches, base]
        current = f"[canvas{i}]"
        for j, region in enumerate(regions):
            x, y, cw, ch = region["crop"]
            rx = round(region["x"] * W_OUT)
            ry = round(region["y"] * H_OUT)
            rw = max(2, round(region["width"] * W_OUT / 2) * 2)
            rh = max(2, round(region["height"] * H_OUT / 2) * 2)
            parts.append(
                f"[r{i}_{j}]crop={cw}:{ch}:{x}:{y},"
                f"scale={rw}:{rh}:force_original_aspect_ratio=increase,"
                f"crop={rw}:{rh},setsar=1[region{i}_{j}]"
            )
            target = f"[composed{i}_{j}]"
            parts.append(
                f"{current}[region{i}_{j}]overlay={rx}:{ry}:shortest=1{target}"
            )
            current = target
        parts.append(f"{current}format=yuv420p[s{i}]")
        return ";".join(parts)
    lay = sg["layout"]
    if lay == "single":
        return f"{head},{_crop(sg['crops'][0])},scale={W_OUT}:{H_OUT},setsar=1,format=yuv420p[s{i}]"
    if lay == "stacked":
        top, bot = sg["crops"]
        half = H_OUT // 2
        return (f"{head},split=2[t{i}][b{i}];"
                f"[t{i}]{_crop(top)},scale={W_OUT}:{half},setsar=1[tt{i}];"
                f"[b{i}]{_crop(bot)},scale={W_OUT}:{half},setsar=1[bb{i}];"
                f"[tt{i}][bb{i}]vstack=inputs=2,format=yuv420p[s{i}]")
    # wide: full frame over blurred, zoomed copy of itself
    return (f"{head},split=2[bg{i}][fg{i}];"
            f"[bg{i}]scale={W_OUT}:{H_OUT}:force_original_aspect_ratio=increase,crop={W_OUT}:{H_OUT},"
            f"gblur=sigma=40,eq=brightness=-0.08[bgb{i}];"
            f"[fg{i}]scale={W_OUT}:{H_OUT}:force_original_aspect_ratio=decrease,setsar=1[fgs{i}];"
            f"[bgb{i}][fgs{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[s{i}]")


def build_filter(segments, t0, t1, has_audio: bool, loudnorm: bool, ass_name: str | None) -> str:
    k = len(segments)
    parts = [f"[0:v]split={k}" + "".join(f"[v{i}]" for i in range(k)) if k > 1 else "[0:v]null[v0]"]
    parts += [layout_filter(i, sg, t0) for i, sg in enumerate(segments)]
    tail = "".join(f"[s{i}]" for i in range(k)) + f"concat=n={k}:v=1:a=0,fps=30"
    if ass_name:
        tail += f",ass={ass_name}"
    parts.append(tail + ",format=yuv420p[vout]")
    if has_audio:
        a = f"[0:a]atrim=start={t0:.3f}:end={t1:.3f},asetpts=PTS-STARTPTS"
        if loudnorm:
            a += ",loudnorm=I=-14:TP=-1.5:LRA=11"
        parts.append(a + ",aresample=48000[aout]")
    return ";".join(parts)


def safe_name(title: str) -> str:
    t = re.sub(r"[^\w\- ]", "", title, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "_", t)[:60] or "clip"


def run(job, clip: dict):
    s, n = job.settings, clip["index"]
    key = f"clip_{n}.render"
    cdir = job.clip_dir(n)
    final = cdir / "final.mp4"
    meta = job.clip_meta(n)
    if (job.should_skip(key) and final.exists()
            and meta.get("render_layout_mode") == s.layout):
        log.info(f"clip {n}: already rendered - skipping")
        with job.pipe.step("render", f"clip {n} (cached)"):
            return
    frame = job.load(f"clip_{n}", "frame.json")
    t0, t1 = meta["trim_start"], meta["trim_end"]
    duration = t1 - t0
    segments = frame["segments"] or [{"start": 0, "end": duration, "layout": "wide", "crops": []}]
    has_audio = ffmpeg.probe(cdir / "source.mp4")["has_audio"]

    (cdir / "subs.ass").write_text(build_ass(meta.get("words", []), segments, clip["title"], s, duration),
                                   encoding="utf-8")
    graph = build_filter(segments, t0, t1, has_audio, s.loudnorm, "subs.ass")
    (cdir / "filter.txt").write_text(graph, encoding="utf-8")   # for debugging

    args = ["-i", (cdir / "source.mp4").resolve(), "-filter_complex", graph, "-map", "[vout]"]
    if has_audio:
        args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", s.crf, "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "final.mp4"]
    with job.pipe.step("render", f"clip {n}") as step:
        ffmpeg.run(args, duration=duration, on_progress=lambda f: step.fraction(f, label=f"{f * 100:.0f}%"),
                   log=log, cwd=cdir)
    out = ffmpeg.probe(final)
    copy_dir = job.path("output")
    copy_dir.mkdir(exist_ok=True)
    nice = copy_dir / f"{n:02d}_{safe_name(clip['title'])}.mp4"
    shutil.copyfile(final, nice)
    job.update_clip_meta(n, final=str(final), output=str(nice), final_duration=round(out["duration"], 2),
                         render_layout_mode=s.layout)
    log.info(f"clip {n}: rendered {out['width']}x{out['height']}, {out['duration']:.1f}s, "
             f"{final.stat().st_size / 1e6:.1f} MB -> {nice}")
    job.state.mark(key)


if __name__ == "__main__":
    from utils.job import standalone
    standalone("render", run, per_clip=True)
