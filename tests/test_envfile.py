import os

import pytest

from pipeline.envfile import EnvFileError, load_env, parse_env


def test_basic_pairs():
    assert parse_env("A=1\nB=two\n") == {"A": "1", "B": "two"}


def test_blank_lines_and_comments_ignored():
    text = "\n# a comment\n   \n  # indented comment\nA=1\n"
    assert parse_env(text) == {"A": "1"}


def test_empty_value():
    assert parse_env("GEMINI_API_KEY=\n") == {"GEMINI_API_KEY": ""}


def test_export_prefix():
    assert parse_env("export A=1") == {"A": "1"}


def test_spaces_around_equals_and_value():
    assert parse_env("  A =  hello world  ") == {"A": "hello world"}


def test_inline_comment_unquoted():
    assert parse_env("A=value # note") == {"A": "value"}


def test_hash_inside_unquoted_value_is_kept():
    assert parse_env("A=abc#def") == {"A": "abc#def"}


def test_double_quotes_with_escapes():
    assert parse_env(r'A="line1\nline2 \"q\" \\ end"') == {"A": 'line1\nline2 "q" \\ end'}


def test_double_quotes_keep_hash_and_spaces():
    assert parse_env('A="  x # y  "  # comment') == {"A": "  x # y  "}


def test_single_quotes_are_literal():
    assert parse_env(r"A='a\nb # c'") == {"A": r"a\nb # c"}


def test_value_may_contain_equals():
    assert parse_env("A=x=y=z") == {"A": "x=y=z"}


def test_crlf_line_endings():
    assert parse_env("A=1\r\nB=2\r\n") == {"A": "1", "B": "2"}


def test_last_duplicate_wins():
    assert parse_env("A=1\nA=2") == {"A": "2"}


@pytest.mark.parametrize("line", ["JUSTTEXT", "1A=x", "A-B=x", "=x"])
def test_bad_lines_raise(line):
    with pytest.raises(EnvFileError):
        parse_env(line)


def test_unclosed_quote_raises():
    with pytest.raises(EnvFileError):
        parse_env('A="open')


def test_error_never_contains_the_value():
    with pytest.raises(EnvFileError) as exc:
        parse_env('KEY="super-secret-value')
    assert "super-secret-value" not in str(exc.value)
    assert "line 1" in str(exc.value)


def test_load_sets_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("A2V_T1", raising=False)
    f = tmp_path / ".env"
    f.write_text("A2V_T1=hello\n")
    assert load_env(f) == {"A2V_T1": "hello"}
    assert os.environ["A2V_T1"] == "hello"


def test_existing_environment_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("A2V_T1", "from-env")
    f = tmp_path / ".env"
    f.write_text("A2V_T1=from-file\n")
    assert load_env(f) == {}
    assert os.environ["A2V_T1"] == "from-env"


def test_override(tmp_path, monkeypatch):
    monkeypatch.setenv("A2V_T1", "from-env")
    f = tmp_path / ".env"
    f.write_text("A2V_T1=from-file\n")
    load_env(f, override=True)
    assert os.environ["A2V_T1"] == "from-file"


def test_missing_file_is_fine(tmp_path):
    assert load_env(tmp_path / "nope.env") == {}


def test_utf8_bom_from_notepad(tmp_path, monkeypatch):
    monkeypatch.delenv("A2V_T1", raising=False)
    f = tmp_path / ".env"
    f.write_bytes(b"\xef\xbb\xbfA2V_T1=bom\r\n")
    load_env(f)
    assert os.environ["A2V_T1"] == "bom"


def test_env_example_parses():
    from pathlib import Path

    example = Path(__file__).resolve().parent.parent / ".env.example"
    values = parse_env(example.read_text(encoding="utf-8"))
    assert values == {"GEMINI_API_KEY": "", "ANTHROPIC_API_KEY": ""}
