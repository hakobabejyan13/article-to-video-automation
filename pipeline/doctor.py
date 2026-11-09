"""`python -m pipeline doctor`: report whether this machine can run the pipeline.

Output is plain ASCII so it prints cleanly in a Windows console.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from pipeline import exitcodes
from pipeline.paths import FOLDERS

PYTHON_VERSION = (3, 12)
NODE_MAJOR = 24

OK, WARN, FAIL, LATER = "OK", "WARN", "FAIL", "LATER"


def _version_of(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, *cmd[1:]], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr or "").strip()
    return text.splitlines()[0] if text else ""


def check_python() -> tuple[str, str, str]:
    v = sys.version_info
    found = f"{v.major}.{v.minor}.{v.micro}"
    want = ".".join(map(str, PYTHON_VERSION))
    if (v.major, v.minor) == PYTHON_VERSION:
        return OK, "Python", found
    return FAIL, "Python", f"{found} found, {want} needed (Kokoro supports 3.10-3.12)"


def check_node() -> tuple[str, str, str]:
    line = _version_of(["node", "--version"])
    if line is None:
        return FAIL, "Node", f"not found; install Node {NODE_MAJOR}"
    m = re.match(r"v?(\d+)\.", line)
    if not m:
        return FAIL, "Node", f"cannot read version from {line!r}"
    if int(m.group(1)) != NODE_MAJOR:
        return FAIL, "Node", f"{line} found, major version {NODE_MAJOR} needed"
    return OK, "Node", line


def check_ffmpeg() -> list[tuple[str, str, str]]:
    rows = []
    for tool in ("ffmpeg", "ffprobe"):
        line = _version_of([tool, "-version"])
        if line is None:
            rows.append((FAIL, tool, "not found on PATH"))
        else:
            m = re.match(rf"{tool} version (\S+)", line)
            rows.append((OK, tool, m.group(1) if m else line))
    return rows


def check_folders(root: Path) -> tuple[str, str, str]:
    missing = [f for f in FOLDERS if not (root / f).is_dir()]
    if missing:
        return FAIL, "Folders", "missing: " + ", ".join(missing)
    return OK, "Folders", f"{len(FOLDERS)} folders present"


def check_packages() -> tuple[str, str, str]:
    missing = []
    for module, package in (("yaml", "PyYAML"), ("jsonschema", "jsonschema")):
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        return FAIL, "Python packages", "missing: " + ", ".join(missing) + " (pip install -r requirements.txt)"
    return OK, "Python packages", "PyYAML, jsonschema"


def check_config(root: Path) -> tuple[tuple[str, str, str], dict | None]:
    from pipeline import config as config_mod

    try:
        cfg = config_mod.load(root / "pipeline" / "config.yaml")
    except ImportError:
        return (FAIL, "Config", "cannot read it without PyYAML"), None
    except config_mod.ConfigError as exc:
        return (FAIL, "Config", str(exc)), None
    return (OK, "Config", "pipeline/config.yaml has every key"), cfg


def check_env_file(root: Path) -> tuple[str, str, str]:
    from pipeline import envfile

    path = root / ".env"
    if not path.is_file():
        return OK, ".env", "none (fine in the cloud; on the laptop copy .env.example to .env)"
    try:
        loaded = envfile.load_env(path)
    except envfile.EnvFileError as exc:
        return FAIL, ".env", str(exc)
    return OK, ".env", f"loaded {len(loaded)} new variable(s)"


def check_llm_key(cfg: dict | None) -> tuple[str, str, str]:
    if cfg is None:
        return FAIL, "LLM key", "config not loaded"
    llm = cfg["llm"]
    var = llm["api_key_env"]
    label = f"LLM key ({llm['provider']}, {var})"
    if os.environ.get(var, "").strip():
        return OK, label, "set (value not shown)"
    return (
        WARN,
        label,
        "not set. Fine in the cloud, where the network adds the key; "
        "on the laptop put it in .env",
    )


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def check_tts_packages() -> tuple[str, str, str]:
    # find_spec only: importing kokoro loads torch, which takes seconds.
    missing = [m for m in ("kokoro", "torch", "soundfile", "numpy") if not _has_module(m)]
    if missing:
        return FAIL, "TTS packages", "missing: " + ", ".join(missing) + " (pip install -r requirements.txt)"
    return OK, "TTS packages", "kokoro, torch, soundfile, numpy"


def check_kokoro_model(cfg: dict | None) -> tuple[str, str, str]:
    """Model weights and the configured voice in the Hugging Face cache."""
    if cfg is None:
        return FAIL, "Kokoro model", "config not loaded"
    tts = cfg["tts"]
    if tts["provider"] != "kokoro":
        return OK, "Kokoro model", f"not used (tts.provider is {tts['provider']})"
    if not _has_module("huggingface_hub"):
        return FAIL, "Kokoro model", "huggingface_hub missing (pip install -r requirements.txt)"
    from huggingface_hub import try_to_load_from_cache

    repo = tts.get("repo_id", "hexgrad/Kokoro-82M")
    files = ["kokoro-v1_0.pth", "config.json", f"voices/{tts['voice']}.pt"]
    missing = [f for f in files if not isinstance(try_to_load_from_cache(repo, f), str)]
    if missing:
        return (WARN, "Kokoro model",
                f"not downloaded yet ({', '.join(missing)}); the first tts run downloads about 330 MB from "
                f"huggingface.co")
    return OK, "Kokoro model", f"{repo}, voice {tts['voice']}, in the local cache"


def check_spacy_model() -> tuple[str, str, str]:
    if _has_module("en_core_web_sm"):
        return OK, "spaCy model en_core_web_sm", "installed"
    return WARN, "spaCy model en_core_web_sm", "not installed yet; the first tts run installs it from github.com"


def check_remotion(root: Path) -> tuple[str, str, str]:
    """The render project's packages (installed with `npm ci` in render/)."""
    import json

    pkg = root / "render" / "node_modules" / "remotion" / "package.json"
    if not (root / "render" / "package.json").exists():
        return FAIL, "Remotion", "render/package.json missing"
    if not pkg.exists():
        return WARN, "Remotion", "not installed yet; run `npm ci` in render/ (the first render downloads Chrome)"
    version = json.loads(pkg.read_text(encoding="utf-8")).get("version", "?")
    return OK, "Remotion", f"{version} in render/node_modules"


def check_music(root: Path, cfg: dict | None) -> tuple[str, str, str]:
    """The music bed the mux stage mixes under the voice (music.file)."""
    name = ((cfg or {}).get("music") or {}).get("file")
    if not name:
        return FAIL, "Music", "music.file is not set in pipeline/config.yaml"
    path = Path(name) if Path(name).is_absolute() else root / name
    if not path.exists():
        return FAIL, "Music", f"{name} not found (download it, see docs/licenses.md)"
    return OK, "Music", name


def run(root: Path) -> int:
    rows: list[tuple[str, str, str]] = [check_python(), check_node(), *check_ffmpeg()]
    rows.append(check_folders(root))
    rows.append(check_packages())
    rows.append(check_env_file(root))  # before the key check, so .env is loaded
    cfg_row, cfg = check_config(root)
    rows.append(cfg_row)
    rows.append(check_llm_key(cfg))
    rows.append(check_tts_packages())
    rows.append(check_kokoro_model(cfg))
    rows.append(check_spacy_model())
    rows.append(check_remotion(root))
    rows.append(check_music(root, cfg))

    print(f"Project folder: {root.name}")
    for status, name, detail in rows:
        print(f"[{status:<5}] {name}: {detail}")
    failed = [r for r in rows if r[0] == FAIL]
    if failed:
        print(f"\n{len(failed)} problem(s) to fix.")
        return exitcodes.SETUP
    print("\nAll checks passed (WARN and LATER items are not errors).")
    return exitcodes.OK
