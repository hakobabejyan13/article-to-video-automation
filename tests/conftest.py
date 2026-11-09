import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline.paths import FOLDERS  # noqa: E402


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A throwaway project folder with the real config and a test article."""
    for folder in FOLDERS:
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "pipeline" / "config.yaml", tmp_path / "pipeline" / "config.yaml")
    shutil.copy(REPO / "tests" / "fixtures" / "article-test.md", tmp_path / "source" / "article-test.md")
    return tmp_path


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never call a real LLM: the Gemini adapter's default opener fails loudly.
    Tests that need responses pass their own `opener` / `http_client`."""
    import urllib.request

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
