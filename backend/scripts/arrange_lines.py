"""Normalize processed TXT files so each sentence occupies its own line."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable

from paths import TXT_PROCESSED_DIR


def split_sentences_per_line(text: str) -> str:
    """Normalize whitespace and split on sentence-ending punctuation."""
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[.?!])\s+", cleaned)
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    if not sentences:
        sentences = [cleaned]
    return "\n".join(sentences).strip()


def gather_txt_files(root: Path, filters: Iterable[str] | None = None) -> list[Path]:
    """Collect .txt files in txt_processed, optionally filtering by substring."""
    if not root.exists():
        return []
    filters = [f.lower() for f in (filters or []) if f.strip()]
    files = sorted(root.rglob("*.txt"))
    if not filters:
        return files
    filtered: list[Path] = []
    for path in files:
        rel_str = str(path.relative_to(root)).lower()
        if any(token in rel_str for token in filters):
            filtered.append(path)
    return filtered


def process_file(path: Path, dry_run: bool = False, verbose: bool = False) -> bool:
    """Rewrite the file with sentence-per-line formatting. Returns True if changed."""
    original = path.read_text(encoding="utf-8")
    formatted = split_sentences_per_line(original)
    if formatted.strip() == original.strip():
        if verbose:
            print(f"↔️  {path} (no change)")
        return False
    if dry_run:
        print(f"📝 [dry-run] Would normalize {path}")
        return True
    path.write_text(formatted + "\n", encoding="utf-8")
    if verbose:
        print(f"✅ Normalized {path}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Arrange sentences line-by-line for files in txt_processed."
    )
    parser.add_argument(
        "--filter",
        "-f",
        action="append",
        help="Substring filter applied to relative file paths (can repeat).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show actions without writing.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print per-file details.")
    args = parser.parse_args()

    root = TXT_PROCESSED_DIR
    targets = gather_txt_files(root, args.filter)
    if not targets:
        print(f"📭 Nenhum arquivo encontrado em {root}")
        return

    changed = 0
    for path in targets:
        if process_file(path, dry_run=args.dry_run, verbose=args.verbose):
            changed += 1

    suffix = " (dry-run)" if args.dry_run else ""
    print(f"♻️  Processados {len(targets)} arquivo(s); alterados {changed}{suffix}.")


if __name__ == "__main__":
    main()
