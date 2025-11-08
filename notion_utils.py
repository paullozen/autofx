"""Utility helpers shared between scripts that talk to Notion."""
from __future__ import annotations


def normalize_notion_id(value: str | None) -> str | None:
    """Ensure database/page IDs always have hyphenated 8-4-4-4-12 format."""
    if not value:
        return value
    raw = value.replace("-", "").strip()
    if len(raw) == 32:
        return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return value.strip()
