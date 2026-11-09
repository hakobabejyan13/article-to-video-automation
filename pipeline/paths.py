"""Every path the pipeline reads or writes, derived from the article file name."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Folder layout from PLAN.md section 3. `doctor` checks that each one exists.
FOLDERS = [
    "source",
    "scenes",
    "audio",
    "render",
    "output",
    "docs",
    "pipeline",
    "assets",
    "assets/fonts",
    "assets/music",
    "assets/icons",
    "tests",
]


def article_id_from(article: Path) -> str:
    """`source/article-XX.md` -> `article-XX`."""
    return article.stem


@dataclass(frozen=True)
class ArticlePaths:
    root: Path
    article: Path
    id: str

    @classmethod
    def for_article(cls, article: Path, root: Path = PROJECT_ROOT) -> "ArticlePaths":
        return cls(root=root, article=article, id=article_id_from(article))

    @property
    def sentences(self) -> Path:
        return self.root / "scenes" / f"{self.id}.sentences.json"

    @property
    def scenes(self) -> Path:
        return self.root / "scenes" / f"{self.id}.scenes.json"

    @property
    def output_dir(self) -> Path:
        return self.root / "output" / self.id

    @property
    def verify_report(self) -> Path:
        return self.output_dir / "verify-report.json"

    @property
    def script(self) -> Path:
        return self.output_dir / "script.md"

    @property
    def factsheet_md(self) -> Path:
        return self.output_dir / "factsheet.md"

    @property
    def factsheet_csv(self) -> Path:
        return self.output_dir / "factsheet.csv"

    @property
    def audio_dir(self) -> Path:
        return self.root / "audio" / self.id

    @property
    def timing(self) -> Path:
        return self.audio_dir / "timing.json"

    @property
    def render_out(self) -> Path:
        return self.root / "render" / "out" / f"{self.id}.mp4"

    @property
    def final_mp4(self) -> Path:
        return self.output_dir / f"{self.id}.mp4"
