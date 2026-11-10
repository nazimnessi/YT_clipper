"""Ranked Claude, Gemini, and Groq models; returns validated JSON or raises AIUnavailable."""
from __future__ import annotations

import json
import os
import re

from pydantic import TypeAdapter, ValidationError

from utils import net
from utils.retry import retry


class AIUnavailable(Exception):
    pass


def _claude(prompt: str, max_tokens: int, model: str) -> str:
    import anthropic
    client = anthropic.Anthropic(timeout=180, max_retries=0, **net.anthropic_kwargs())
    msg = client.messages.create(model=model, max_tokens=max_tokens,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(getattr(b, "text", "") for b in msg.content)


def _gemini(prompt: str, max_tokens: int, model: str) -> str:
    from google import genai
    from google.genai import types
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=key, **net.genai_kwargs())
    resp = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json",
                                           temperature=0.4, max_output_tokens=max_tokens * 2))
    return resp.text or ""


def _groq(prompt: str, max_tokens: int, model: str) -> str:
    from groq import Groq
    with Groq(timeout=180, max_retries=0, **net.groq_kwargs()) as client:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=max_tokens,
        )
    return resp.choices[0].message.content or ""


PROVIDERS = {
    "claude": (_claude, lambda: bool(os.environ.get("ANTHROPIC_API_KEY"))),
    "gemini": (_gemini, lambda: bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))),
    "groq": (_groq, lambda: bool(os.environ.get("GROQ_API_KEY"))),
}


def model_chain(s) -> list[tuple[str, str]]:
    allowed = {"claude", "gemini", "groq"} if s.ai == "auto" else {s.ai}
    models = []
    seen = set()
    for entry in s.ai_model_hierarchy:
        provider, separator, model = entry.partition(":")
        if not separator or provider not in PROVIDERS or not model:
            raise ValueError(f"invalid AI model hierarchy entry: {entry!r}")
        candidate = (provider, model)
        if provider in allowed and candidate not in seen:
            models.append(candidate)
            seen.add(candidate)
    return models


def extract_json(text: str):
    """Pull the first JSON array/object out of a model reply (handles ```json fences and prose)."""
    text = re.sub(r"```(?:json)?", "", text)
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in reply")
    obj, _ = json.JSONDecoder().raw_decode(text[min(starts):])
    return obj


def ask_json(prompt: str, schema, s, log, what: str = "AI request", max_tokens: int = 4096):
    """Try configured models in ranked order. Returns (parsed, provider:model)."""
    adapter = TypeAdapter(schema)
    models = model_chain(s)
    missing_keys = set()
    for index, (name, model) in enumerate(models):
        fn, has_key = PROVIDERS[name]
        if not has_key():
            if name not in missing_keys:
                log.info(f"{name}: no API key set, skipping its models")
                missing_keys.add(name)
            continue

        label = f"{name}:{model}"
        log.info(f"{what}: trying {label} ({index + 1}/{len(models)})")

        def call():
            text = fn(prompt, max_tokens, model)
            log.debug(f"{label} raw reply ({len(text)} chars): {text[:1500]}")
            return adapter.validate_python(extract_json(text))

        def retryable(error):
            if isinstance(error, (ValidationError, ValueError)):
                return False
            status = getattr(error, "status_code", getattr(error, "code", None))
            return status not in (400, 401, 403, 404, 422, "model_not_found")

        try:
            result = retry(call, attempts=3, log=log, what=f"{what} via {label}", retry_if=retryable)
            log.info(f"{what}: answered by {label}")
            return result, label
        except ImportError as e:
            log.warning(f"{label}: library not installed ({e})")
        except (ValidationError, ValueError) as e:
            log.warning(f"{label}: reply was not valid JSON for this request: {str(e)[:300]}")
        except Exception as e:  # noqa: BLE001
            log.warning(f"{label}: failed after retries: {str(e)[:300]}")
    raise AIUnavailable(f"no AI provider could answer ({what})")
