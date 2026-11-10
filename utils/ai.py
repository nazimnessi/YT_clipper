"""AI chain: Claude -> Gemini. Returns validated JSON or raises AIUnavailable (caller then uses heuristics)."""
from __future__ import annotations

import json
import os
import re

from pydantic import TypeAdapter, ValidationError

from utils import net
from utils.retry import retry


class AIUnavailable(Exception):
    pass


def _claude(prompt: str, s, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(timeout=180, max_retries=0, **net.anthropic_kwargs())
    msg = client.messages.create(model=s.claude_model, max_tokens=max_tokens,
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


PROVIDERS = {
    "claude": (_claude, lambda: bool(os.environ.get("ANTHROPIC_API_KEY"))),
    "gemini": (_gemini, lambda: bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))),
}


def chain(s) -> list[str]:
    return {"auto": ["claude", "gemini"], "claude": ["claude"], "gemini": ["gemini"], "heuristic": []}[s.ai]


def extract_json(text: str):
    """Pull the first JSON array/object out of a model reply (handles ```json fences and prose)."""
    text = re.sub(r"```(?:json)?", "", text)
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        raise ValueError("no JSON found in reply")
    obj, _ = json.JSONDecoder().raw_decode(text[min(starts):])
    return obj


def _gemini_models(s) -> list[str]:
    return list(dict.fromkeys(model for model in [s.gemini_model, *s.gemini_fallback_models] if model))


def ask_json(prompt: str, schema, s, log, what: str = "AI request", max_tokens: int = 4096):
    """Try providers and configured Gemini models. Returns (parsed, provider_name)."""
    adapter = TypeAdapter(schema)
    for name in chain(s):
        fn, has_key = PROVIDERS[name]
        if not has_key():
            log.info(f"{name}: no API key set, skipping")
            continue

        models = _gemini_models(s) if name == "gemini" else [None]
        for index, model in enumerate(models):
            if model:
                log.info(f"{what}: trying Gemini model {model} ({index + 1}/{len(models)})")

            def call():
                if model:
                    text = fn(prompt, max_tokens, model=model)
                else:
                    text = fn(prompt, s, max_tokens)
                log.debug(f"{name} raw reply ({len(text)} chars): {text[:1500]}")
                return adapter.validate_python(extract_json(text))

            try:
                result = retry(
                    call, attempts=3, log=log,
                    what=f"{what} via {name}" + (f" ({model})" if model else ""),
                    retry_if=(lambda e: getattr(e, "code", None) != 404) if model else None,
                )
                if model:
                    log.info(f"{what}: answered by Gemini model {model}")
                else:
                    log.info(f"{what}: answered by {name}")
                return result, name
            except ImportError as e:
                log.warning(f"{name}: library not installed ({e})")
                break
            except (ValidationError, ValueError) as e:
                log.warning(f"{name}" + (f" model {model}" if model else "") +
                            f": reply was not valid JSON for this request: {str(e)[:300]}")
            except Exception as e:  # noqa: BLE001
                log.warning(f"{name}" + (f" model {model}" if model else "") +
                            f": failed after retries: {str(e)[:300]}")

            if model and index + 1 < len(models):
                log.info(f"Gemini model switch: {model} -> {models[index + 1]}")
        if name == "gemini":
            log.warning("all configured Gemini models failed; continuing to the next provider or heuristic fallback")
    raise AIUnavailable(f"no AI provider could answer ({what})")
