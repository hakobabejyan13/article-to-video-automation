"""Print the SHA-256 of an article's body (everything below the front matter).

    python -m pipeline.tools.body_hash source/article-XX.md [--expect <sha256>]

Use it to confirm that adding front matter left the article text unchanged:
the body hash after editing must equal the hash of the original file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.frontmatter import body_sha256


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline.tools.body_hash")
    ap.add_argument("article", type=Path)
    ap.add_argument("--expect", help="expected SHA-256; exit 1 if it differs")
    args = ap.parse_args(argv)
    digest = body_sha256(args.article)
    print(f"{digest}  {args.article.as_posix()} (body)")
    if args.expect:
        if digest != args.expect.lower():
            print(f"MISMATCH: expected {args.expect}")
            return 1
        print("body unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
