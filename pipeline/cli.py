"""Command line: `python -m pipeline run <article> [--review] [--from <stage>]` and `doctor`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline import exitcodes, stages
from pipeline.paths import PROJECT_ROOT, ArticlePaths


def _stage_table() -> str:
    lines = ["stages, in run order:"]
    for i, name in enumerate(stages.STAGE_NAMES, start=1):
        lines.append(f"  {i}. {name:<10} {stages.DESCRIPTIONS[name]}")
    lines += [
        "",
        "With --review the run stops after the first 'docs' (exit 0); read the",
        "fact sheet, then run again with --from tts.",
        "",
        "exit codes: 0 success or review stop, 1 checker or length failure,",
        "2 missing setup or input, 3 provider unavailable after retries",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Turn one article file into a 1920x1080 explainer MP4 with an AI voiceover.",
        epilog=_stage_table(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="{run,doctor}")
    sub.required = True

    run = sub.add_parser(
        "run",
        help="run the pipeline on one article",
        description="Run every stage on one article, or start at --from <stage>.",
        epilog=_stage_table(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run.add_argument("article", type=Path, help="article file, for example source/article-XX.md")
    run.add_argument(
        "--review",
        action="store_true",
        help="stop after the fact sheet is written so a person can review it",
    )
    run.add_argument(
        "--from",
        dest="from_stage",
        metavar="STAGE",
        choices=stages.STAGE_NAMES,
        help="start at this stage: " + ", ".join(stages.STAGE_NAMES),
    )

    sub.add_parser(
        "doctor",
        help="check Python, Node, FFmpeg, folders, config and the LLM key",
        description="Check that this machine is set up to run the pipeline.",
    )
    return parser


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def cmd_run(args: argparse.Namespace, root: Path) -> int:
    from pipeline import config as config_mod
    from pipeline import envfile
    from pipeline.frontmatter import FrontMatterError, read_article

    article = args.article
    if not article.is_absolute():
        article = Path.cwd() / article
    if not article.is_file():
        _err(f"article file not found: {args.article}")
        return exitcodes.SETUP
    if article.suffix.lower() != ".md":
        _err(f"article must be a Markdown file (.md): {args.article}")
        return exitcodes.SETUP

    try:
        envfile.load_env(root / ".env")
    except envfile.EnvFileError as exc:
        _err(str(exc))
        return exitcodes.SETUP
    try:
        cfg = config_mod.load(root / "pipeline" / "config.yaml")
    except config_mod.ConfigError as exc:
        _err(str(exc))
        return exitcodes.SETUP
    try:
        meta, body = read_article(article)
    except FrontMatterError as exc:
        _err(f"{args.article}: {exc}")
        return exitcodes.SETUP

    paths = ArticlePaths.for_article(article, root=root)

    if args.from_stage:
        missing = [p for p in stages.required_inputs(args.from_stage, paths) if not p.exists()]
        if missing:
            _err(
                f"--from {args.from_stage} needs files that do not exist yet:\n"
                + "\n".join(f"  {_rel(p, root)}" for p in missing)
                + "\nRun the earlier stages first (or run without --from)."
            )
            return exitcodes.SETUP

    ctx = stages.RunContext(paths=paths, config=cfg, meta=meta, body=body, review=args.review)
    print(f"Article {paths.id} (publisher: {meta['publisher']}, promotional: {meta['promotional']})")
    for step in stages.plan_from(args.from_stage):
        if step == stages.REVIEW:
            if args.review:
                print(
                    f"Stopped for review. Read {_rel(paths.factsheet_md, root)}, then run:\n"
                    f"  python -m pipeline run {args.article.as_posix()} --from tts"
                )
                return exitcodes.OK
            continue
        print(f"== {step}")
        code = stages.STAGES[step](ctx)
        if code != exitcodes.OK:
            return code
    print("Done.")
    return exitcodes.OK


def _safe_console() -> None:
    """Article text can hold characters a Windows console code page cannot print
    (for example curly quotes or currency signs); print a '?' instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None, root: Path = PROJECT_ROOT) -> int:
    _safe_console()
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return cmd_run(args, root)
    if args.command == "doctor":
        from pipeline import doctor

        return doctor.run(root)
    return exitcodes.SETUP  # unreachable: argparse requires a command
