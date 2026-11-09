"""LLM adapters (pipeline/llm.py), with recorded responses only: no network.

- tests/fixtures/llm/gemini-503.json and gemini-404.json are real error bodies
  recorded from the Gemini API in the cloud on 2026-11-07.
- tests/fixtures/llm/gemini-stream.sse is a real streamed answer recorded the same day
  (thought summary parts included, which the adapter must skip).
- tests/fixtures/llm/anthropic-stream.sse is written by hand in the documented
  Messages streaming event format (no Anthropic key was available to record one).
  It goes through the real `anthropic` SDK, via an in-memory HTTP transport.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from pipeline import llm

FIX = Path(__file__).resolve().parent / "fixtures" / "llm"
SECRET = "sk-test-not-a-real-key-123456"


def gemini_cfg(**over) -> dict:
    cfg = {"provider": "gemini", "model": "m1", "fallback_models": ["m2"], "api_key_env": "A2V_TEST_KEY",
           "stream": True, "max_retries": 3, "http_attempts": 2, "backoff_s": 0}
    cfg.update(over)
    return cfg


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Opener:
    """Replays one recorded outcome per call and records the requests."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        kind, data = self.outcomes.pop(0)
        if kind == "ok":
            return FakeResp(data)
        if kind == "http":
            status, body = data
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(body))
        raise urllib.error.URLError(data)


def sse(*texts, finish="STOP") -> bytes:
    lines = []
    for i, t in enumerate(texts):
        chunk = {"candidates": [{"content": {"parts": [{"text": t}], "role": "model"}}],
                 "modelVersion": "m1-001"}
        if i == len(texts) - 1:
            chunk["candidates"][0]["finishReason"] = finish
            chunk["usageMetadata"] = {"totalTokenCount": 42}
        lines.append("data: " + json.dumps(chunk) + "\r\n\r\n")
    return "".join(lines).encode()


def test_gemini_recorded_stream_skips_thoughts():
    raw = (FIX / "gemini-stream.sse").read_bytes()
    text, usage, version, finish = llm.parse_sse(raw.splitlines())
    data = json.loads(text)
    assert data["scenes"][0]["voiceover"][0]["text"] == "Thanks for watching."
    assert b'"thought": true' in raw  # the recording has thought parts, and they were skipped
    assert finish == "STOP" and usage.get("totalTokenCount")


def test_gemini_joins_chunks_and_sends_stream_request(monkeypatch):
    monkeypatch.delenv("A2V_TEST_KEY", raising=False)
    op = Opener([("ok", sse('{"scenes"', ": []}"))])
    res = llm.generate("prompt text", gemini_cfg(), schema={"type": "object"}, log=lambda m: None, opener=op)
    assert res.text == '{"scenes": []}' and res.model == "m1" and res.usage == {"totalTokenCount": 42}
    req = op.requests[0]
    assert req.full_url.endswith("/models/m1:streamGenerateContent?alt=sse")
    body = json.loads(req.data)
    assert body["generationConfig"]["responseJsonSchema"] == {"type": "object"}
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["contents"][0]["parts"][0]["text"] == "prompt text"
    # empty key variable: no key header at all (the cloud network adds it)
    assert not any(k.lower() == "x-goog-api-key" for k in req.headers)


def test_gemini_sends_key_header_when_set(monkeypatch):
    monkeypatch.setenv("A2V_TEST_KEY", SECRET)
    op = Opener([("ok", sse("{}"))])
    llm.generate("p", gemini_cfg(), log=lambda m: None, opener=op)
    assert op.requests[0].get_header("X-goog-api-key") == SECRET


def test_gemini_falls_back_on_recorded_503_then_404(monkeypatch):
    monkeypatch.setenv("A2V_TEST_KEY", SECRET)
    b503 = (FIX / "gemini-503.json").read_bytes()
    b404 = (FIX / "gemini-404.json").read_bytes()
    logs = []
    op = Opener([("http", (503, b503)), ("http", (503, b503)), ("http", (404, b404)),
                 ("ok", sse("{}"))])
    cfg = gemini_cfg(fallback_models=["m2", "m3"])
    res = llm.generate("p", cfg, log=logs.append, opener=op, sleep=lambda s: None)
    assert res.model == "m3"
    urls = [r.full_url.split("/models/")[1].split(":")[0] for r in op.requests]
    assert urls == ["m1", "m1", "m2", "m3"]  # 503 retried once on m1; 404 not retried
    assert any("HTTP 503" in line and "high demand" in line for line in logs)
    assert any("HTTP 404" in line for line in logs)
    assert all(SECRET not in line for line in logs + res.events)


def test_gemini_all_models_fail_raises_provider_unavailable(monkeypatch):
    monkeypatch.setenv("A2V_TEST_KEY", SECRET)
    b503 = (FIX / "gemini-503.json").read_bytes()
    op = Opener([("http", (503, b503))] * 4)
    with pytest.raises(llm.ProviderUnavailable) as exc:
        llm.generate("p", gemini_cfg(), log=lambda m: None, opener=op, sleep=lambda s: None)
    assert "m1" in str(exc.value) and "m2" in str(exc.value) and SECRET not in str(exc.value)


def test_gemini_network_error_falls_back():
    op = Opener([("net", "timed out"), ("net", "timed out"), ("ok", sse("{}"))])
    res = llm.generate("p", gemini_cfg(), log=lambda m: None, opener=op, sleep=lambda s: None)
    assert res.model == "m2"


def test_gemini_bad_key_is_a_setup_error(monkeypatch):
    monkeypatch.setenv("A2V_TEST_KEY", SECRET)
    body = json.dumps({"error": {"code": 403, "message": "API key not valid."}}).encode()
    op = Opener([("http", (403, body))])
    with pytest.raises(llm.LLMSetupError) as exc:
        llm.generate("p", gemini_cfg(), log=lambda m: None, opener=op)
    assert "API key not valid" in str(exc.value) and SECRET not in str(exc.value)
    assert len(op.requests) == 1


def test_gemini_400_is_not_retried():
    body = json.dumps({"error": {"code": 400, "message": "Invalid JSON payload"}}).encode()
    op = Opener([("http", (400, body))])
    with pytest.raises(llm.ProviderUnavailable):
        llm.generate("p", gemini_cfg(), log=lambda m: None, opener=op)
    assert len(op.requests) == 1


def test_gemini_cut_answer_moves_on():
    op = Opener([("ok", sse('{"sce', finish="MAX_TOKENS")), ("ok", sse('{"sce', finish="MAX_TOKENS")),
                 ("ok", sse("{}"))])
    res = llm.generate("p", gemini_cfg(), log=lambda m: None, opener=op, sleep=lambda s: None)
    assert res.model == "m2"


def test_gemini_error_inside_stream():
    bad = b'data: {"error": {"code": 503, "message": "overloaded"}}\n\n'
    op = Opener([("ok", bad), ("ok", bad), ("ok", sse("{}"))])
    res = llm.generate("p", gemini_cfg(), log=lambda m: None, opener=op, sleep=lambda s: None)
    assert res.model == "m2"


def test_unknown_provider():
    with pytest.raises(llm.LLMSetupError):
        llm.generate("p", gemini_cfg(provider="other"), log=lambda m: None)


# ---------------------------------------------------------------- Anthropic

def anthropic_cfg(**over) -> dict:
    cfg = {"provider": "anthropic", "model": "claude-haiku-5-5", "fallback_models": [],
           "api_key_env": "A2V_TEST_ANTHROPIC", "stream": True, "max_retries": 3,
           "http_attempts": 1, "backoff_s": 0}
    cfg.update(over)
    return cfg


def mock_client(responses, seen):
    httpx = pytest.importorskip("httpx2")
    import anthropic

    queue = list(responses)

    def handler(request):
        seen.append(request)
        status, body = queue.pop(0)
        headers = {"content-type": "text/event-stream" if status == 200 else "application/json"}
        return httpx.Response(status, content=body, headers=headers)

    return anthropic.DefaultHttpxClient(transport=httpx.MockTransport(handler))


def test_anthropic_recorded_stream_through_sdk(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("A2V_TEST_ANTHROPIC", SECRET)
    seen = []
    client = mock_client([(200, (FIX / "anthropic-stream.sse").read_bytes())], seen)
    schema = {"type": "object", "properties": {"scenes": {"type": "array"}}, "required": ["scenes"],
              "additionalProperties": False}
    res = llm.generate("prompt text", anthropic_cfg(), schema=schema, log=lambda m: None, http_client=client)
    assert json.loads(res.text)["scenes"][0]["voiceover"][0]["text"] == "Thanks for watching."
    assert res.provider == "anthropic" and res.finish_reason == "end_turn"
    assert res.usage["output_tokens"] == 48
    body = json.loads(seen[0].content)
    assert body["model"] == "claude-haiku-5-5" and body["stream"] is True
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": schema}
    assert body["messages"] == [{"role": "user", "content": "prompt text"}]
    auth = seen[0].headers.get("x-api-key") or seen[0].headers.get("authorization", "")
    assert auth.endswith(SECRET)  # the SDK sends the key itself (header name depends on SDK version)


def test_anthropic_overloaded_falls_back_then_fails(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("A2V_TEST_ANTHROPIC", SECRET)
    err = json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}).encode()
    seen = []
    client = mock_client([(529, err), (529, err)], seen)
    logs = []
    with pytest.raises(llm.ProviderUnavailable):
        llm.generate("p", anthropic_cfg(fallback_models=["claude-sonnet-5-5"]), log=logs.append,
                     http_client=client, sleep=lambda s: None)
    assert [json.loads(r.content)["model"] for r in seen] == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert all(SECRET not in line for line in logs)


def test_anthropic_needs_a_key(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.delenv("A2V_TEST_ANTHROPIC", raising=False)
    with pytest.raises(llm.LLMSetupError) as exc:
        llm.generate("p", anthropic_cfg(), log=lambda m: None)
    assert "A2V_TEST_ANTHROPIC" in str(exc.value)


def test_anthropic_rejected_key_is_setup_error(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("A2V_TEST_ANTHROPIC", SECRET)
    err = json.dumps({"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}).encode()
    client = mock_client([(401, err)], [])
    with pytest.raises(llm.LLMSetupError) as exc:
        llm.generate("p", anthropic_cfg(), log=lambda m: None, http_client=client)
    assert SECRET not in str(exc.value)


def test_switching_to_haiku_is_a_config_change():
    """PLAN.md T3 done check: the commented lines in config.yaml are a working block."""
    import re

    from pipeline import config

    text = config.CONFIG_PATH.read_text(encoding="utf-8")
    assert re.search(r"#\s+provider: anthropic", text)
    assert re.search(r"#\s+model: claude-haiku-5-5", text)
    assert re.search(r"#\s+api_key_env: ANTHROPIC_API_KEY", text)
