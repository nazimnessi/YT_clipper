"""YouTube helpers: yt-dlp (info, captions, section download) and Data API upload (OAuth)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from utils import net

ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([\w-]{11})")


def video_id(url: str) -> str:
    m = ID_RE.search(url or "")
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{11}", url or ""):
        return url
    raise ValueError(f"Could not find a YouTube video id in: {url!r}")


def watch_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


# ---------------------------------------------------------------- yt-dlp
class _YdlLogger:
    def __init__(self, log):
        self.log = log

    def debug(self, msg):
        self.log.debug(f"yt-dlp: {msg}")

    info = debug

    def warning(self, msg):
        self.log.warning(f"yt-dlp: {msg}")

    def error(self, msg):
        self.log.error(f"yt-dlp: {msg}")


def _base_opts(s, log) -> dict:
    o = {"quiet": True, "no_warnings": False, "noprogress": True, "logger": _YdlLogger(log),
         "nocheckcertificate": net.insecure(), "retries": 5, "fragment_retries": 5}
    if s.cookies_from_browser:
        o["cookiesfrombrowser"] = (s.cookies_from_browser,)
    return o


def extract_info(url: str, s, log, comments: bool = True) -> dict:
    import yt_dlp
    o = _base_opts(s, log) | {"skip_download": True}
    if comments:
        o["getcomments"] = True
        o["extractor_args"] = {"youtube": {"max_comments": ["100", "100", "0", "0"], "comment_sort": ["top"]}}
    with yt_dlp.YoutubeDL(o) as ydl:
        return ydl.sanitize_info(ydl.extract_info(url, download=False))


def fetch_captions(info: dict, s, log) -> tuple[list[dict], str | None]:
    """Return ([{start,end,text}], lang) from YouTube captions (manual first, then auto)."""
    import yt_dlp
    lang = s.language or info.get("language") or "en"
    for kind in ("subtitles", "automatic_captions"):
        tracks = info.get(kind) or {}
        keys = [k for k in (lang, f"{lang}-orig") if k in tracks]
        keys += [k for k in tracks if k.split("-")[0] == lang and k not in keys]
        if not keys and kind == "subtitles" and not s.language and len(tracks) == 1:
            keys = list(tracks)  # only one manual track: use it
        for k in keys:
            fmt = next((f for f in tracks[k] if f.get("ext") == "json3"), None)
            if not fmt:
                continue
            with yt_dlp.YoutubeDL(_base_opts(s, log)) as ydl:
                raw = ydl.urlopen(fmt["url"]).read().decode("utf-8", "replace")
            segs = parse_json3(json.loads(raw))
            if segs:
                log.info(f"captions: {kind.replace('_', ' ')} '{k}' ({len(segs)} lines)")
                return segs, k.split("-")[0]
    return [], None


def parse_json3(data: dict) -> list[dict]:
    out = []
    for ev in data.get("events", []):
        if "segs" not in ev or "tStartMs" not in ev:
            continue
        text = "".join(sg.get("utf8", "") for sg in ev["segs"]).replace("\n", " ").strip()
        if not text:
            continue
        st = ev["tStartMs"] / 1000
        out.append({"start": round(st, 2), "end": round(st + ev.get("dDurationMs", 0) / 1000, 2), "text": text})
    # auto-captions overlap (rolling lines): end each line at the next line's start
    for a, b in zip(out, out[1:]):
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    return out


def _hook(step):
    def hook(d):
        if d.get("status") != "downloading" or step is None:
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        got = d.get("downloaded_bytes") or 0
        name = Path(d.get("filename", "")).suffix
        if total:
            step.fraction(got / total, label=f"{got / 1e6:.1f}/{total / 1e6:.1f} MB {name}")
        else:
            step.update(label=f"{got / 1e6:.1f} MB {name}")
    return hook


def download_section(url: str, start: float, end: float, out: Path, s, log, step=None) -> Path:
    """Download only [start, end] seconds of the video to `out` (.mp4)."""
    import yt_dlp
    from yt_dlp.utils import download_range_func
    out.parent.mkdir(parents=True, exist_ok=True)
    o = _base_opts(s, log) | {
        "format": "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out.with_suffix("")) + ".%(ext)s",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "progress_hooks": [_hook(step)],
        "overwrites": True,
    }
    with yt_dlp.YoutubeDL(o) as ydl:
        ydl.download([url])
    if not out.exists():
        cand = sorted(out.parent.glob(out.stem + ".*"))
        cand = [c for c in cand if c.suffix not in (".part", ".ytdl", ".json")]
        if not cand:
            raise RuntimeError("download finished but no output file was found")
        cand[0].rename(out)
    return out


def download_audio(url: str, out_dir: Path, s, log, step=None) -> Path:
    import yt_dlp
    out_dir.mkdir(parents=True, exist_ok=True)
    o = _base_opts(s, log) | {"format": "ba[ext=m4a]/ba/b", "outtmpl": str(out_dir / "audio.%(ext)s"),
                              "progress_hooks": [_hook(step)]}
    with yt_dlp.YoutubeDL(o) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))


# ---------------------------------------------------------------- upload (YouTube Data API)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service(s):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if Path(s.token).exists():
        creds = Credentials.from_authorized_user_file(str(s.token), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(s.client_secret).exists():
                raise SystemExit(f"{s.client_secret} not found - needed for upload (see README 'Upload setup')")
            flow = InstalledAppFlow.from_client_secrets_file(str(s.client_secret), SCOPES)
            creds = flow.run_local_server(port=0)
        Path(s.token).write_text(creds.to_json(), encoding="utf-8")
    http = net.google_http()
    if http is not None:
        from google_auth_httplib2 import AuthorizedHttp
        return build("youtube", "v3", http=AuthorizedHttp(creds, http=http))
    return build("youtube", "v3", credentials=creds)


def upload(path: Path, title: str, description: str, tags: list[str], s, step=None) -> str:
    from googleapiclient.http import MediaFileUpload
    yt = _service(s)
    body = {"snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:30],
                        "categoryId": s.category_id},
            "status": {"privacyStatus": s.privacy, "selfDeclaredMadeForKids": False}}
    media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=4 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status and step:
            step.fraction(status.progress(), label=f"{status.progress() * 100:.0f}%")
    return f"https://youtube.com/shorts/{resp['id']}"
