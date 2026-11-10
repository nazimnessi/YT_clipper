"""Settings: built-in defaults  <  config.yaml  <  command-line arguments.  API keys come from .env."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator


class SubtitleStyle(BaseModel):
    font: str = "Arial"
    font_size: int = 80
    words_per_line: int = 3
    uppercase: bool = True
    text_color: str = "&H00FFFFFF"        # ASS colour, &HAABBGGRR -> white
    highlight_color: str = "&H0000FFFF"   # yellow
    outline: int = 6


class Settings(BaseModel):
    # input
    url: Optional[str] = None
    excel: Path = Path("input_video.xlsx")
    yt_account: Optional[str] = None       # read from Excel, for reference only

    # clips
    clips: int = Field(3, ge=1, le=10)
    min_sec: float = Field(20, ge=5)
    max_sec: float = Field(59, le=180)
    layout: Literal["auto", "single", "stacked", "wide"] = "auto"
    pad_sec: float = 3.0                   # extra seconds downloaded around each clip

    # AI
    ai: Literal["auto", "claude", "gemini", "groq", "heuristic"] = "auto"
    ai_model_hierarchy: list[str] = Field(default_factory=lambda: [
        "claude:claude-fable-5-2",
        "gemini:gemini-4-carbon",
        "claude:claude-opus-5-5",
        "groq:openai/gpt-oss-120b",
        "gemini:gemini-4-argon",
        "groq:moonshotai/kimi-k2-instruct-0905",
        "claude:claude-sonnet-5-5",
        "gemini:gemini-3.8-flash",
        "groq:qwen/qwen3.8-27b",
        "gemini:gemini-3.6-flash",
        "groq:llama-3.3-70b-versatile",
        "claude:claude-haiku-5-5",
        "gemini:gemini-3.5-flash-lite",
    ])

    # transcription
    whisper_model: str = "small"
    whisper_device: Literal["auto", "cpu", "cuda"] = "auto"
    language: Optional[str] = None         # e.g. "en", "hi"; None = auto

    # render
    hook_title: bool = True
    hook_seconds: float = 2.5
    loudnorm: bool = True
    crf: int = 20
    subtitles: SubtitleStyle = SubtitleStyle()

    # upload (OFF by default)
    upload: bool = False
    privacy: Literal["private", "unlisted", "public"] = "private"
    category_id: str = "22"
    client_secret: Path = Path("client_secret.json")
    token: Path = Path("token.json")

    # misc
    out: Path = Path("data")
    logs: Path = Path("logs")
    models_dir: Path = Path("models")
    cookies_from_browser: Optional[str] = None   # chrome | edge | firefox ... (helps with YouTube bot checks)
    force: bool = False
    insecure: bool = False
    verbose: bool = False

    # standalone module runs
    video: Optional[str] = None
    clip: Optional[int] = None

    @model_validator(mode="after")
    def _check(self):
        if self.max_sec <= self.min_sec:
            raise ValueError(f"max_sec ({self.max_sec}) must be greater than min_sec ({self.min_sec})")
        return self

    @field_validator("ai_model_hierarchy")
    @classmethod
    def _check_ai_model_hierarchy(cls, models):
        providers = {"claude", "gemini", "groq"}
        for entry in models:
            provider, separator, model = entry.partition(":")
            if not separator or provider not in providers or not model.strip():
                raise ValueError(f"invalid AI model hierarchy entry: {entry!r}")
        return models


def build_parser(standalone: bool = False) -> argparse.ArgumentParser:
    S = argparse.SUPPRESS  # only arguments actually given override config.yaml
    p = argparse.ArgumentParser(
        description="YouTube clipper: long video -> vertical Shorts with subtitles.",
        argument_default=S)
    p.add_argument("--url", help="YouTube video URL")
    p.add_argument("--excel", type=Path, help="input Excel (default input_video.xlsx)")
    p.add_argument("--config", type=Path, default=Path("config.yaml"), help="settings file")
    p.add_argument("--clips", type=int, help="number of clips to make (default 3)")
    p.add_argument("--min-sec", dest="min_sec", type=float, help="min clip length (default 20)")
    p.add_argument("--max-sec", dest="max_sec", type=float, help="max clip length (default 59)")
    p.add_argument("--layout", choices=["auto", "single", "stacked", "wide"], help="framing (default auto)")
    p.add_argument("--ai", choices=["auto", "claude", "gemini", "groq", "heuristic"],
                   help="highlight AI (default auto)")
    p.add_argument("--whisper-model", dest="whisper_model", help="tiny|base|small|medium|large-v3")
    p.add_argument("--whisper-device", dest="whisper_device", choices=["auto", "cpu", "cuda"])
    p.add_argument("--language", help="spoken language code, e.g. en, hi (default auto)")
    p.add_argument("--upload", action="store_true", help="upload clips to YouTube (default OFF)")
    p.add_argument("--privacy", choices=["private", "unlisted", "public"], help="upload privacy")
    p.add_argument("--out", type=Path, help="output folder (default data/)")
    p.add_argument("--cookies-from-browser", dest="cookies_from_browser",
                   help="use this browser's YouTube login for yt-dlp (chrome, edge, firefox)")
    p.add_argument("--force", action="store_true", help="redo all steps (ignore saved progress)")
    p.add_argument("--insecure", action="store_true", help="skip SSL certificate checks")
    p.add_argument("--verbose", action="store_true", help="debug logs in console")
    if standalone:
        p.add_argument("--video", required=True, help="video id (folder in data/) to run this step on")
        p.add_argument("--clip", type=int, help="only this clip number")
    return p


def _flatten_yaml(d: dict) -> dict:
    """config.yaml is grouped into sections for readability; Settings is flat (except 'subtitles')."""
    flat = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict) and k != "subtitles":
            flat.update(v)
        else:
            flat[k] = v
    return flat


def load_settings(argv=None, standalone: bool = False) -> Settings:
    load_dotenv()
    args = vars(build_parser(standalone).parse_args(argv))
    cfg_path = Path(args.pop("config", "config.yaml"))
    data = {}
    if cfg_path.exists():
        data = _flatten_yaml(yaml.safe_load(cfg_path.read_text(encoding="utf-8")))
    data = {k: v for k, v in data.items() if v is not None}
    data.update(args)
    return Settings(**data)
