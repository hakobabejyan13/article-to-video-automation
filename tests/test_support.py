"""Config, front matter and the helper scripts."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from pipeline import config, frontmatter
from pipeline.tools import body_hash, docx_text

REPO = Path(__file__).resolve().parent.parent


def test_config_has_every_planned_key():
    cfg = config.load()
    assert config.missing_keys(cfg) == []
    assert cfg["video"]["target_seconds"] == [60, 90]
    assert cfg["render"]["concurrency"] == 1
    assert cfg["llm"]["stream"] is True


def test_config_missing_key_is_reported(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("video: {width: 1920}\n")
    with pytest.raises(config.ConfigError) as exc:
        config.load(f)
    assert "video.fps" in str(exc.value)
    assert "llm" in str(exc.value)


def test_requirements_match_the_approved_list():
    lines = [
        line.split("==")[0].strip()
        for line in (REPO / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert lines == ["kokoro", "soundfile", "PyYAML", "jsonschema", "anthropic", "pytest"]


def test_gitignore_covers_secrets_and_caches():
    ignored = (REPO / ".gitignore").read_text().split()
    for entry in (".env", ".venv/", "node_modules/", "render/out/", ".cache/"):
        assert entry in ignored


def test_front_matter_split_keeps_body_bytes():
    body = b"# Title\r\n\r\nText with \xe2\x80\x9cquotes\xe2\x80\x9d.\n"
    data = b"---\npublisher: X\npromotional: false\n---\n" + body
    block, rest = frontmatter.split_bytes(data)
    assert block == b"publisher: X\npromotional: false\n"
    assert rest == body


def test_no_front_matter_returns_whole_file():
    assert frontmatter.split_bytes(b"# Title\n") == (None, b"# Title\n")


def test_unclosed_front_matter_raises():
    with pytest.raises(frontmatter.FrontMatterError):
        frontmatter.split_bytes(b"---\npublisher: X\n# Title\n")


def test_read_article(tmp_path):
    f = tmp_path / "a.md"
    # bytes, so Windows does not turn \n into \r\n
    f.write_bytes(b"---\npublisher: Some Co\npromotional: true\nurl: https://example.com\n---\n# T\n")
    meta, body = frontmatter.read_article(f)
    assert meta == {"publisher": "Some Co", "promotional": True, "url": "https://example.com"}
    assert body == "# T\n"


def test_promotional_must_be_boolean(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("---\npublisher: Some Co\npromotional: maybe\n---\n# T\n")
    with pytest.raises(frontmatter.FrontMatterError):
        frontmatter.read_article(f)


def test_body_hash_equals_original_file_hash(tmp_path, capsys):
    original = b"# Title\n\nBody.\n"
    f = tmp_path / "a.md"
    f.write_bytes(b"---\npublisher: X\npromotional: true\n---\n" + original)
    expected = hashlib.sha256(original).hexdigest()
    assert body_hash.main([str(f), "--expect", expected]) == 0
    assert body_hash.main([str(f), "--expect", "0" * 64]) == 1


def _make_docx(path: Path, paras: list[str]) -> None:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{p}</w:t></w:r></w:p>" if p else "<w:p/>"
        for p in paras
    )
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def test_docx_convert_and_check(tmp_path):
    docx = tmp_path / "b.docx"
    _make_docx(docx, ["# Heading", "", "First line", "second line"])
    out = tmp_path / "b.md"
    assert docx_text.main(["convert", str(docx), str(out)]) == 0
    assert out.read_text() == "# Heading\n\nFirst line\nsecond line\n"


def test_docx_check_finds_a_changed_word(tmp_path):
    docx = tmp_path / "b.docx"
    _make_docx(docx, ["one two three"])
    md = tmp_path / "b.md"
    md.write_text("one too three\n")
    ok, msg = docx_text.compare(docx, md)
    assert not ok and "word 2" in msg
    md.write_text("one two\n")
    ok, msg = docx_text.compare(docx, md)
    assert not ok and "counts differ" in msg

