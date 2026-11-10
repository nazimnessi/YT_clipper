"""Step 6 - FRAME: decide how each shot is framed in 9:16.

  split clip into shots (scene cuts) -> detect faces ~2x per second -> per shot pick a layout:
    1 face                         -> single  : 9:16 crop centred on the face
    2 faces far apart (left/right) -> stacked : left person on top, right person below
    2 faces close together         -> single  : crop centred on both
    0 or 3+ faces                  -> wide    : whole frame over a blurred background

Output: clip_N/frame.json {width, height, segments:[{start, end, layout, crops:[[x,y,w,h],...]}]}
        (times relative to the trimmed clip, i.e. 0 = clip start)
"""
from __future__ import annotations

import statistics
from collections import Counter

import cv2

from utils import log as logs
from utils.faces import FaceDetector

log = logs.get("frame")
SAMPLE_FPS = 4          # frames per second examined for scene cuts
FACE_EVERY = 2          # run face detection on every 2nd sample (=2 fps)
CUT_THRESHOLD = 0.45    # histogram distance that counts as a shot change
MIN_SHOT = 1.2          # shots shorter than this inherit the previous layout
MIN_FACE_H = 0.07       # ignore faces smaller than 7% of frame height
STACK_ASPECT = 1080 / 960


def _even(v) -> int:
    return int(round(v / 2)) * 2


def _clamp(v, lo, hi):
    return max(lo, min(v, hi))


# ---------------------------------------------------------------- layout maths (pure functions)
def single_crop(cx, W, H) -> list[int]:
    cw = min(_even(H * 9 / 16), _even(W))
    x = _clamp(cx - cw / 2, 0, W - cw)
    return [_even(x), 0, cw, _even(H)]


def stacked_crops(left, right, W, H) -> list[list[int]]:
    """left/right = (cx, cy, face_h). Returns [top_crop, bottom_crop] each with 1080:960 aspect."""
    split = (left[0] + right[0]) / 2
    cw = min(split, W - split, H * STACK_ASPECT)
    ch = cw / STACK_ASPECT
    crops = []
    for (cx, cy, fh), lo, hi in ((left, 0, split), (right, split, W)):
        x = _clamp(cx - cw / 2, lo, hi - cw)
        y = _clamp(cy + 0.10 * ch - ch / 2, 0, H - ch)   # face slightly above centre
        crops.append([_even(x), _even(y), _even(cw), _even(ch)])
    return crops


def _centre(f):
    x, y, w, h = f[:4]
    return x + w / 2, y + h / 2, h


def decide(samples: list[list], W: int, H: int, forced: str = "auto", detector_ok: bool = True) -> dict:
    """samples: list of face lists [(x,y,w,h,score),...] for one shot. Returns {layout, crops}."""
    faces = [[f for f in s if f[3] >= MIN_FACE_H * H and f[4] >= 0.6] for s in samples]
    counts = Counter(min(len(f), 3) for f in faces)
    n = counts.most_common(1)[0][0] if counts else 0
    vertical_source = W / H <= 9 / 16 + 0.02

    def two_people():
        pairs = [sorted(f, key=lambda z: z[0])[:2] if len(f) >= 2 else None for f in faces]
        pairs = [p for p in pairs if p]
        if not pairs:
            return None
        L = [_centre(p[0]) for p in pairs]
        R = [_centre(p[1]) for p in pairs]
        left = tuple(statistics.median(v[i] for v in L) for i in range(3))
        right = tuple(statistics.median(v[i] for v in R) for i in range(3))
        span = statistics.median(p[1][0] + p[1][2] - p[0][0] for p in pairs)
        return left, right, span

    def one_person_cx():
        cs = [_centre(max(f, key=lambda z: z[2] * z[3]))[0] for f in faces if f]
        return statistics.median(cs) if cs else W / 2

    if forced == "wide" or vertical_source:
        return {"layout": "wide", "crops": []}

    if forced == "stacked":
        tp = two_people()
        if tp:
            return {"layout": "stacked", "crops": stacked_crops(tp[0], tp[1], W, H)}
        # no 2 faces found: assume a left/right split screen
        return {"layout": "stacked", "crops": stacked_crops((W / 4, H / 2, 0), (3 * W / 4, H / 2, 0), W, H)}

    if forced == "single":
        return {"layout": "single", "crops": [single_crop(one_person_cx(), W, H)]}

    # auto
    if not detector_ok or n == 0 or n >= 3:
        return {"layout": "wide", "crops": []}
    if n == 1:
        return {"layout": "single", "crops": [single_crop(one_person_cx(), W, H)]}
    left, right, span = two_people()
    if span <= H * 9 / 16 * 0.9:  # both fit in one vertical crop
        return {"layout": "single", "crops": [single_crop((left[0] + right[0]) / 2, W, H)]}
    return {"layout": "stacked", "crops": stacked_crops(left, right, W, H)}


def _similar(a, b, W) -> bool:
    if a["layout"] != b["layout"] or len(a["crops"]) != len(b["crops"]):
        return False
    return all(abs(p[0] - q[0]) < 0.04 * W and abs(p[1] - q[1]) < 0.04 * W for p, q in zip(a["crops"], b["crops"]))


def build_segments(shots, W, H, forced, detector_ok) -> list[dict]:
    """shots: [(start, end, samples)] -> merged segment list."""
    segs = []
    for start, end, samples in shots:
        d = decide(samples, W, H, forced, detector_ok)
        if segs and end - start < MIN_SHOT:          # too short to judge: keep previous framing
            d = {k: segs[-1][k] for k in ("layout", "crops")}
        if segs and _similar(segs[-1], d, W):
            segs[-1]["end"] = end
        else:
            segs.append({"start": start, "end": end, **d})
    return segs


# ---------------------------------------------------------------- video analysis
def analyse(path, t0, t1, detector: FaceDetector, step=None):
    """Return (W, H, shots) where shots = [(start, end, [faces per sample])], times relative to t0."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000)
    next_t, prev_hist, i = t0, None, 0
    cuts, samples = [0.0], []           # samples: (t_rel, faces or None)
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if t > t1:
            break
        if t + 1e-3 < next_t:
            continue
        next_t += 1 / SAMPLE_FPS
        rel = max(0.0, t - t0)
        small = cv2.resize(frame, (160, max(1, int(160 * H / W))))
        hist = cv2.calcHist([cv2.cvtColor(small, cv2.COLOR_BGR2HSV)], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        if prev_hist is not None and cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA) > CUT_THRESHOLD:
            if rel - cuts[-1] >= 0.5:
                cuts.append(rel)
        prev_hist = hist
        faces = detector.detect(frame) if (detector.available and i % FACE_EVERY == 0) else None
        samples.append((rel, faces))
        i += 1
        if step:
            step.fraction(rel / max(t1 - t0, 0.1), label=f"{rel:.0f}/{t1 - t0:.0f}s, {len(cuts) - 1} cuts")
    cap.release()
    dur = t1 - t0
    bounds = cuts + [dur]
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a <= 0:
            continue
        shots.append((round(a, 2), round(b, 2), [f for t, f in samples if a <= t < b and f is not None]))
    return W, H, shots


def run(job, clip: dict):
    s, n = job.settings, clip["index"]
    key = f"clip_{n}.frame"
    if job.should_skip(key):
        log.info(f"clip {n}: framing already decided - skipping")
        with job.pipe.step("frame", f"clip {n} (cached)"):
            return
    meta = job.clip_meta(n)
    with job.pipe.step("frame", f"clip {n}") as step:
        detector = FaceDetector(s.models_dir)
        W, H, shots = analyse(job.clip_dir(n) / "source.mp4", meta["trim_start"], meta["trim_end"], detector, step)
        segs = build_segments(shots, W, H, s.layout, detector.available)
        if segs:
            segs[-1]["end"] = round(meta["trim_end"] - meta["trim_start"], 2)
    job.save({"width": W, "height": H, "segments": segs}, f"clip_{n}", "frame.json")
    summary = Counter(sg["layout"] for sg in segs)
    log.info(f"clip {n}: {len(shots)} shots -> {len(segs)} segments " +
             ", ".join(f"{k}x{v}" for k, v in summary.items()))
    for sg in segs:
        log.debug(f"  {sg['start']:6.2f}-{sg['end']:6.2f}s {sg['layout']:<8} {sg['crops']}")
    job.state.mark(key, layouts=dict(summary))


if __name__ == "__main__":
    from utils.job import standalone
    standalone("frame", run, per_clip=True)
