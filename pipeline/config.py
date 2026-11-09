"""Load pipeline/config.yaml (PLAN.md sections 2 and 5)."""

from __future__ import annotations

from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

# Every key the plan names. `doctor` and the tests check config.yaml has them all.
REQUIRED_KEYS = {
    "video": ["target_seconds", "width", "height", "fps"],
    "render": ["concurrency"],
    "speech": ["words_per_minute"],
    "llm": ["provider", "model", "fallback_models", "api_key_env", "stream", "max_retries"],
    "tts": ["provider", "voice", "lang_code", "speed"],
    "music": ["file", "duck_db"],
    "source_tag": ["publisher", "company"],
    "attribution_phrases": [],
    "disclosure_words": ["publish", "rank"],
    "rank_headers": [],
    "review_warnings": ["inference_words", "judging_words", "min_sections"],
}


class ConfigError(ValueError):
    pass


def missing_keys(cfg: dict) -> list[str]:
    missing = []
    for section, keys in REQUIRED_KEYS.items():
        if section not in cfg:
            missing.append(section)
            continue
        for key in keys:
            if not isinstance(cfg[section], dict) or key not in cfg[section]:
                missing.append(f"{section}.{key}")
    return missing


def load(path: Path = CONFIG_PATH) -> dict:
    import yaml

    try:
        cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {exc}") from None
    missing = missing_keys(cfg)
    if missing:
        raise ConfigError("config is missing: " + ", ".join(missing))
    return cfg
