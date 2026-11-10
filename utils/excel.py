"""Read input_video.xlsx  (columns: video_url | yt_account). Excel is optional."""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook


def read_rows(path: Path) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []
    header = [str(h or "").strip().lower().replace(" ", "_") for h in rows[0]]
    out = []
    for r in rows[1:]:
        rec = {header[i]: (str(v).strip() if v is not None else "") for i, v in enumerate(r) if i < len(header)}
        if rec.get("video_url"):
            out.append(rec)
    return out


def find_account(rows: list[dict], video_id: str) -> str | None:
    for r in rows:
        if video_id and video_id in r.get("video_url", ""):
            return r.get("yt_account") or None
    return None
