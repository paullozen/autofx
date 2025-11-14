"""Centralized filesystem layout for pipeline artifacts."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = ROOT / "output"
SCRIPTS_ROOT = OUTPUT_ROOT  # flattened layout (legacy compat)
LEGACY_SCRIPTS_ROOT = OUTPUT_ROOT / "scripts"

# Ensure the roots exist so downstream mkdir calls only need to
# create their own leaf directories.
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
SCRIPTS_ROOT.mkdir(parents=True, exist_ok=True)

# Shared files
MANIFEST_PATH = ROOT / "manifesto.json"

# Text/script stages
TXT_INBOX_DIR = ROOT / "txt_inbox"
TXT_INBOX_DIR.mkdir(parents=True, exist_ok=True)
TXT_PROCESSED_DIR = SCRIPTS_ROOT / "txt_processed"
TXT_DOWNLOADS_DIR = SCRIPTS_ROOT / "txt_downloads"
SRT_OUTPUT_DIR = SCRIPTS_ROOT / "srt_outputs"
IMG_SUGGESTIONS_DIR = SCRIPTS_ROOT / "img_suggestions"
TIMELINES_DIR = SCRIPTS_ROOT / "timelines"
SCRIPTS_RENDER_DIR = SCRIPTS_ROOT / "render_output"

# Media outputs
IMG_OUTPUT_DIR = OUTPUT_ROOT / "imgs_output"
VIDEO_OUTPUT_DIR = OUTPUT_ROOT / "videos"
RENDER_OUTPUT_DIR = OUTPUT_ROOT / "render_output"
AUDIO_OUTPUT_DIR = OUTPUT_ROOT / "audio"
COMMENTS_OUTPUT_DIR = OUTPUT_ROOT / "comments"


def ensure_dirs(*paths: Iterable[Path] | Path):
    """Create every requested directory (parents included)."""
    for path in paths:
        if isinstance(path, (list, tuple, set)):
            for nested in path:
                ensure_dirs(nested)
        else:
            Path(path).mkdir(parents=True, exist_ok=True)


def _migrate_legacy_scripts_layout():
    """Move historical output/scripts/* folders to the flattened layout."""
    if not LEGACY_SCRIPTS_ROOT.exists():
        return

    legacy_map = {
        LEGACY_SCRIPTS_ROOT / "txt_processed": TXT_PROCESSED_DIR,
        LEGACY_SCRIPTS_ROOT / "txt_downloads": TXT_DOWNLOADS_DIR,
        LEGACY_SCRIPTS_ROOT / "srt_outputs": SRT_OUTPUT_DIR,
        LEGACY_SCRIPTS_ROOT / "img_suggestions": IMG_SUGGESTIONS_DIR,
        LEGACY_SCRIPTS_ROOT / "timelines": TIMELINES_DIR,
        LEGACY_SCRIPTS_ROOT / "render_output": SCRIPTS_RENDER_DIR,
    }

    for legacy_path, new_path in legacy_map.items():
        if not legacy_path.exists():
            continue
        new_path.mkdir(parents=True, exist_ok=True)
        try:
            legacy_path.rename(new_path)
            continue
        except OSError:
            pass
        for item in legacy_path.iterdir():
            target = new_path / item.name
            if target.exists():
                continue
            shutil.move(str(item), str(target))
        try:
            legacy_path.rmdir()
        except OSError:
            pass

    try:
        LEGACY_SCRIPTS_ROOT.rmdir()
    except OSError:
        pass


_migrate_legacy_scripts_layout()
