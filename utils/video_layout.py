"""Video-type layout templates and same-source region crop selection."""
from __future__ import annotations

import re
import statistics


LAYOUTS = {
    "podcast": {
        "default_layout": "two_person_vertical",
        "layouts": {
            "two_person_vertical": {"regions": [
                {"source": "speaker_1", "x": 0, "y": 0, "width": 1, "height": 0.5},
                {"source": "speaker_2", "x": 0, "y": 0.5, "width": 1, "height": 0.5},
            ]},
            "active_speaker_focus": {"regions": [
                {"source": "active_speaker", "x": 0, "y": 0, "width": 1, "height": 0.7},
                {"source": "other_speaker", "x": 0, "y": 0.7, "width": 1, "height": 0.3},
            ]},
            "single_speaker": {"regions": [
                {"source": "active_speaker", "x": 0, "y": 0, "width": 1, "height": 1},
            ]},
        },
    },
    "gaming": {
        "default_layout": "gameplay_facecam",
        "layouts": {
            "gameplay_facecam": {"regions": [
                {"source": "gameplay", "x": 0, "y": 0, "width": 1, "height": 0.7},
                {"source": "facecam", "x": 0, "y": 0.7, "width": 1, "height": 0.3},
            ]},
            "gameplay_fullscreen": {"regions": [
                {"source": "gameplay", "x": 0, "y": 0, "width": 1, "height": 1},
            ]},
            "gameplay_facecam_overlay": {"regions": [
                {"source": "gameplay", "x": 0, "y": 0, "width": 1, "height": 1},
                {"source": "facecam", "x": 0.65, "y": 0.05, "width": 0.3, "height": 0.25},
            ]},
        },
    },
    "reaction": {
        "default_layout": "reaction_vertical",
        "layouts": {
            "reaction_vertical": {"regions": [
                {"source": "original", "x": 0, "y": 0, "width": 1, "height": 0.5},
                {"source": "reaction", "x": 0, "y": 0.5, "width": 1, "height": 0.5},
            ]},
            "reaction_overlay": {"regions": [
                {"source": "original", "x": 0, "y": 0, "width": 1, "height": 1},
                {"source": "reaction", "x": 0.65, "y": 0.7, "width": 0.3, "height": 0.25},
            ]},
            "reaction_focus": {"regions": [
                {"source": "reaction", "x": 0, "y": 0, "width": 1, "height": 0.7},
                {"source": "original", "x": 0, "y": 0.7, "width": 1, "height": 0.3},
            ]},
        },
    },
    "tutorial": {
        "default_layout": "presenter_screen",
        "layouts": {
            "presenter_screen": {"regions": [
                {"source": "presenter", "x": 0, "y": 0, "width": 1, "height": 0.4},
                {"source": "screen", "x": 0, "y": 0.4, "width": 1, "height": 0.6},
            ]},
            "screen_fullscreen": {"regions": [
                {"source": "screen", "x": 0, "y": 0, "width": 1, "height": 1},
            ]},
            "presenter_overlay": {"regions": [
                {"source": "screen", "x": 0, "y": 0, "width": 1, "height": 1},
                {"source": "presenter", "x": 0.65, "y": 0.7, "width": 0.3, "height": 0.25},
            ]},
        },
    },
    "interview": {
        "default_layout": "interviewer_guest",
        "layouts": {
            "interviewer_guest": {"regions": [
                {"source": "interviewer", "x": 0, "y": 0, "width": 1, "height": 0.5},
                {"source": "guest", "x": 0, "y": 0.5, "width": 1, "height": 0.5},
            ]},
            "active_speaker_focus": {"regions": [
                {"source": "active_speaker", "x": 0, "y": 0, "width": 1, "height": 0.7},
                {"source": "other_speaker", "x": 0, "y": 0.7, "width": 1, "height": 0.3},
            ]},
            "single_speaker": {"regions": [
                {"source": "active_speaker", "x": 0, "y": 0, "width": 1, "height": 1},
            ]},
        },
    },
    "single_person": {
        "default_layout": "smart_portrait",
        "layouts": {
            "smart_portrait": {"regions": [
                {"source": "person", "x": 0, "y": 0, "width": 1, "height": 1},
            ]},
            "center_portrait": {"regions": [
                {"source": "main_video", "x": 0, "y": 0, "width": 1, "height": 1},
            ]},
        },
    },
    "presentation": {
        "default_layout": "presentation_full",
        "layouts": {
            "presentation_full": {"regions": [
                {"source": "slides", "x": 0, "y": 0, "width": 1, "height": 1},
            ]},
        },
    },
    "general": {
        "default_layout": "smart_crop",
        "layouts": {
            "smart_crop": {"regions": [
                {"source": "main_video", "x": 0, "y": 0, "width": 1, "height": 1},
            ]},
        },
    },
}

_TYPE_KEYWORDS = {
    "podcast": ("podcast", "podcasting"),
    "gaming": ("gaming", "gameplay", "gamer", "esports", "let's play"),
    "reaction": ("reaction", "reacts", "reacting"),
    "tutorial": ("tutorial", "how to", "how-to", "lesson", "step by step", "step-by-step"),
    "interview": ("interview", "q&a", "question and answer"),
    "single_person": ("vlog", "monologue", "solo talk"),
    "presentation": ("presentation", "keynote", "webinar", "slides", "slide deck"),
}
_FACE_SOURCES = {
    "speaker_1": 0, "interviewer": 0,
    "speaker_2": 1, "guest": 1,
    "active_speaker": 0, "other_speaker": 1,
    "person": 0, "facecam": 0, "presenter": 0, "reaction": 0,
}


def classify_video(info: dict) -> str:
    """Classify from YouTube text metadata; require a unique keyword match."""
    tags = info.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    text = " ".join(str(value) for value in [
        info.get("title") or "", info.get("description") or "", *tags,
    ]).lower()
    scores = {
        video_type: sum(len(re.findall(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text))
                        for keyword in keywords)
        for video_type, keywords in _TYPE_KEYWORDS.items()
    }
    best = max(scores.values(), default=0)
    winners = [video_type for video_type, score in scores.items() if score == best and score > 0]
    return winners[0] if len(winners) == 1 else "general"


def face_elements(samples: list[list], height: int) -> list[tuple[float, float, float, float]]:
    """Return median face boxes ordered left-to-right across the shot."""
    ordered = []
    for sample in samples:
        faces = [face for face in sample if face[3] >= 0.07 * height and face[4] >= 0.6]
        ordered.append(sorted(faces, key=lambda face: face[0] + face[2] / 2))
    count = max((len(sample) for sample in ordered), default=0)
    elements = []
    for index in range(count):
        boxes = [sample[index] for sample in ordered if len(sample) > index]
        if not boxes:
            continue
        elements.append(tuple(statistics.median(face[i] for face in boxes) for i in range(4)))
    return elements


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def _cover_crop(width: int, height: int, aspect: float) -> list[int]:
    if width / height > aspect:
        crop_width, crop_height = height * aspect, height
    else:
        crop_width, crop_height = width, width / aspect
    x, y = (width - crop_width) / 2, (height - crop_height) / 2
    cw, ch = min(width, _even(crop_width)), min(height, _even(crop_height))
    return [_even(min(max(x, 0), width - cw)), _even(min(max(y, 0), height - ch)), cw, ch]


def _face_crop(face, width: int, height: int, aspect: float) -> list[int]:
    x, y, fw, fh = face
    crop_height = max(fh * 1.2, fw * 1.2 / aspect)
    crop_width = crop_height * aspect
    if crop_width > width:
        crop_width, crop_height = width, width / aspect
    if crop_height > height:
        crop_width, crop_height = height * aspect, height
    cx, cy = x + fw / 2, y + fh / 2
    left = min(max(cx - crop_width / 2, 0), width - crop_width)
    top = min(max(cy - crop_height / 2, 0), height - crop_height)
    cw, ch = min(width, _even(crop_width)), min(height, _even(crop_height))
    return [_even(min(max(left, 0), width - cw)), _even(min(max(top, 0), height - ch)), cw, ch]


def choose_layout(video_type: str, face_count: int) -> str | None:
    if video_type in ("podcast", "interview"):
        if face_count >= 2:
            return LAYOUTS[video_type]["default_layout"]
        return "single_speaker" if face_count == 1 else None
    if video_type == "gaming":
        return "gameplay_facecam" if face_count else "gameplay_fullscreen"
    if video_type == "reaction":
        return "reaction_vertical" if face_count else None
    if video_type == "tutorial":
        return "presenter_screen" if face_count else "screen_fullscreen"
    if video_type == "single_person":
        return "smart_portrait" if face_count else "center_portrait"
    return LAYOUTS[video_type]["default_layout"]


def compose_regions(video_type: str, layout_name: str, faces, width: int, height: int) -> list[dict] | None:
    template = LAYOUTS[video_type]["layouts"][layout_name]["regions"]
    regions = []
    for region in template:
        rendered = dict(region)
        aspect = (region["width"] * 1080) / (region["height"] * 1920)
        face_index = _FACE_SOURCES.get(region["source"])
        if region["source"] == "main_video" and faces:
            rendered["crop"] = _face_crop(faces[0], width, height, aspect)
            rendered["element_id"] = "person" if video_type == "general" else region["source"]
        elif face_index is not None:
            if face_index >= len(faces):
                return None
            rendered["crop"] = _face_crop(faces[face_index], width, height, aspect)
            rendered["element_id"] = region["source"]
        else:
            rendered["crop"] = _cover_crop(width, height, aspect)
            rendered["element_id"] = region["source"]
        regions.append(rendered)
    return regions
