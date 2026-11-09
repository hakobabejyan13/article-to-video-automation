"""LLM adapters for the `scenes` stage (PLAN.md section 2).

Two providers, chosen by `llm.provider` in config.yaml:

- `gemini`: Google's REST API, called with the standard library only. Always
  streamed (`streamGenerateContent?alt=sse`), because long non-streamed calls were
  cut at 30 s in the cloud. On HTTP 429/5xx (and 404, a retired model name) the next
  model in `llm.fallback_models` is tried.
- `anthropic`: the official `anthropic` SDK (Claude Haiku 5.5 is the planned paid
  fallback), streamed with `messages.stream(...).get_final_message()`.

API keys are read from the environment variable named in `llm.api_key_env`. For
Gemini an empty variable means "send no key header" (in the cloud the network adds
the key). Keys are never logged or put into error messages: errors carry only the
HTTP status and the API's own message.

`generate()` is the one entry point. It returns an `LLMResult`, or raises
`ProviderUnavailable` (every model failed: exit code 3) or `LLMSetupError`
(a setup problem such as a missing key or package: exit code 2).
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# HTTP statuses worth retrying on the same model (after a pause) and then falling
# back to the next model. 404 is not retried, but does fall back: it means the
# model name is retired or unknown to this key.
RETRY_STATUS = {408, 429, 500, 502, 503, 504}
FALLBACK_STATUS = RETRY_STATUS | {404}

DEFAULTS = {
    "http_attempts": 2,        # tries per model before moving to the next one
    "backoff_s": 5,            # pause before a retry on the same model (doubles)
    "timeout_s": 300,          # socket timeout for one request
    "max_output_tokens": 32000,
    "temperature": None,       # provider default
}

Log = Callable[[str], None]


class LLMError(RuntimeError):
    pass


class ProviderUnavailable(LLMError):
    """Every configured model failed (rate limits, overload, network)."""


class LLMSetupError(LLMError):
    """Something on this machine is not set up (key, package, unknown provider)."""


class ModelError(LLMError):
    """One model call failed. `fallback` says whether the next model may help."""

    def __init__(self, message: str, fallback: bool, status: int | None = None):
        super().__init__(message)
        self.fallback = fallback
        self.status = status


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    seconds: float
    usage: dict = field(default_factory=dict)
    model_version: str | None = None
    finish_reason: str | None = None
    events: list[str] = field(default_factory=list)  # what happened, for the run log


def _setting(cfg_llm: dict, key: str):
    v = cfg_llm.get(key)
    return DEFAULTS[key] if v is None else v


def models_in_order(cfg_llm: dict) -> list[str]:
    out = [cfg_llm["model"]]
    for m in cfg_llm.get("fallback_models") or []:
        if m not in out:
            out.append(m)
    return out


# ------------------------------------------------------------------ Gemini

def _gemini_body(prompt: str, schema: dict | None, cfg_llm: dict) -> dict:
    gen: dict = {"responseMimeType": "application/json",
                 "maxOutputTokens": int(_setting(cfg_llm, "max_output_tokens")),
                 # Thought summaries are streamed (and skipped by parse_sse) so bytes keep
                 # flowing while the model thinks; a silent stream was cut with HTTP 502
                 # "upstream request failed" after 30 s in the cloud.
                 "thinkingConfig": {"includeThoughts": True}}
    if schema is not None:
        gen["responseJsonSchema"] = schema
    temp = _setting(cfg_llm, "temperature")
    if temp is not None:
        gen["temperature"] = float(temp)
    return {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}


def _api_message(raw: bytes) -> str:
    """The API's own error message (never request headers, so never the key)."""
    text = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(text)
        if isinstance(data, list) and data:
            data = data[0]
        err = data.get("error", data) if isinstance(data, dict) else {}
        msg = err.get("message") if isinstance(err, dict) else None
        if msg:
            return " ".join(str(msg).split())[:300]
    except (json.JSONDecodeError, AttributeError):
        pass
    return " ".join(text.split())[:300] or "(no message)"


def parse_sse(lines) -> tuple[str, dict, str | None, str | None]:
    """Join the answer text from Gemini SSE lines. Thought parts are skipped.

    Returns (text, usage, model_version, finish_reason).
    """
    text: list[str] = []
    usage: dict = {}
    version = finish = None
    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            d = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ModelError(f"stream sent a line that is not JSON: {exc}", fallback=True) from None
        if "error" in d:
            err = d["error"] if isinstance(d["error"], dict) else {"message": str(d["error"])}
            code = err.get("code")
            raise ModelError(f"stream error {code}: {str(err.get('message', ''))[:300]}",
                             fallback=code in FALLBACK_STATUS or code is None, status=code)
        for cand in d.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                if not part.get("thought") and "text" in part:
                    text.append(part["text"])
            finish = cand.get("finishReason", finish)
        usage = d.get("usageMetadata", usage) or usage
        version = d.get("modelVersion", version)
    return "".join(text), usage, version, finish


def _gemini_once(model: str, prompt: str, schema: dict | None, cfg_llm: dict, opener) -> LLMResult:
    url = f"{GEMINI_BASE}/{model}:streamGenerateContent?alt=sse"
    headers = {"Content-Type": "application/json"}
    key = os.environ.get(cfg_llm["api_key_env"], "").strip()
    if key:
        headers["x-goog-api-key"] = key
    body = json.dumps(_gemini_body(prompt, schema, cfg_llm)).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    t0 = time.monotonic()
    try:
        with opener(req, timeout=float(_setting(cfg_llm, "timeout_s"))) as resp:
            text, usage, version, finish = parse_sse(resp)
    except urllib.error.HTTPError as exc:
        status = exc.code
        msg = _api_message(exc.read() if exc.fp else b"")
        raise ModelError(f"HTTP {status}: {msg}", fallback=status in FALLBACK_STATUS,
                         status=status) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ModelError(f"network error: {reason}", fallback=True) from None
    secs = time.monotonic() - t0
    if not text.strip():
        raise ModelError(f"empty answer (finish reason {finish})", fallback=True)
    if finish not in (None, "STOP"):
        # MAX_TOKENS, SAFETY, ...: the JSON is cut or missing; another model may do better
        raise ModelError(f"answer stopped early (finish reason {finish})", fallback=True)
    return LLMResult(text=text, provider="gemini", model=model, seconds=secs, usage=usage,
                     model_version=version, finish_reason=finish)


# ------------------------------------------------------------------ Anthropic

def _anthropic_client(cfg_llm: dict, http_client=None):
    try:
        import anthropic
    except ImportError:
        raise LLMSetupError("the 'anthropic' package is not installed; run "
                            "pip install -r requirements.txt") from None
    key = os.environ.get(cfg_llm["api_key_env"], "").strip()
    if not key:
        raise LLMSetupError(f"{cfg_llm['api_key_env']} is not set; put the Anthropic key in .env")
    kwargs = {"api_key": key, "max_retries": 0, "timeout": float(_setting(cfg_llm, "timeout_s"))}
    if http_client is not None:
        kwargs["http_client"] = http_client
    return anthropic, anthropic.Anthropic(**kwargs)


def _anthropic_once(model: str, prompt: str, schema: dict | None, cfg_llm: dict,
                    http_client=None) -> LLMResult:
    anthropic, client = _anthropic_client(cfg_llm, http_client)
    params: dict = {
        "model": model,
        "max_tokens": int(_setting(cfg_llm, "max_output_tokens")),
        "messages": [{"role": "user", "content": prompt}],
    }
    if schema is not None:
        params["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    t0 = time.monotonic()
    try:
        with client.messages.stream(**params) as stream:
            msg = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise LLMSetupError(f"the key in {cfg_llm['api_key_env']} was rejected (HTTP 401)") from None
    except anthropic.APIStatusError as exc:
        status = exc.status_code
        raise ModelError(f"HTTP {status}: {str(getattr(exc, 'message', exc))[:300]}",
                         fallback=status in FALLBACK_STATUS or status == 529, status=status) from None
    except anthropic.APIConnectionError as exc:
        raise ModelError(f"network error: {type(exc).__name__}", fallback=True) from None
    secs = time.monotonic() - t0
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    usage = msg.usage.model_dump(exclude_none=True) if getattr(msg, "usage", None) else {}
    if msg.stop_reason == "refusal":
        raise ModelError("the model declined the request (stop_reason refusal)", fallback=True)
    if msg.stop_reason == "max_tokens":
        raise ModelError("answer stopped early (max_tokens)", fallback=True)
    if not text.strip():
        raise ModelError(f"empty answer (stop_reason {msg.stop_reason})", fallback=True)
    return LLMResult(text=text, provider="anthropic", model=model, seconds=secs, usage=usage,
                     model_version=getattr(msg, "model", None), finish_reason=msg.stop_reason)


# ------------------------------------------------------------------ entry point

def generate(prompt: str, cfg_llm: dict, schema: dict | None = None, log: Log = print,
             opener=None, http_client=None, sleep=time.sleep) -> LLMResult:
    """Send one prompt; try each configured model in order. See the module docstring.

    `opener` (Gemini) and `http_client` (Anthropic) exist so tests can replay
    recorded responses without network access.
    """
    provider = cfg_llm.get("provider")
    if provider not in ("gemini", "anthropic"):
        raise LLMSetupError(f"llm.provider must be gemini or anthropic, not {provider!r}")
    attempts = max(1, int(_setting(cfg_llm, "http_attempts")))
    backoff = float(_setting(cfg_llm, "backoff_s"))
    failures: list[str] = []
    events: list[str] = []
    for model in models_in_order(cfg_llm):
        for i in range(attempts):
            try:
                if provider == "gemini":
                    res = _gemini_once(model, prompt, schema, cfg_llm,
                                       opener or urllib.request.urlopen)
                else:
                    res = _anthropic_once(model, prompt, schema, cfg_llm, http_client)
                res.events = events + [f"{model}: ok in {res.seconds:.0f} s"]
                return res
            except ModelError as exc:
                line = f"{model}: {exc} (try {i + 1} of {attempts})"
                log("  " + line)
                events.append(line)
                if exc.status in (401, 403):
                    raise LLMSetupError(f"{provider} {model}: {exc}. Check the key in "
                                        f"{cfg_llm['api_key_env']}") from None
                if not exc.fallback:
                    raise ProviderUnavailable(f"{provider} {model}: {exc}") from None
                if exc.status in RETRY_STATUS or exc.status is None:
                    if i + 1 < attempts:
                        sleep(backoff * (2 ** i))
                        continue
                failures.append(f"{model}: {exc}")
                break
    raise ProviderUnavailable(f"every {provider} model failed: " + "; ".join(failures))
