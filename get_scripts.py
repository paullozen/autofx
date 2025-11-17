"""Download Notion scripts whose Step is marked as 'Roteiro'."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from notion_client import Client

from manifesto import ensure_entry, update_stage
from notion_utils import normalize_notion_id
from paths import TXT_INBOX_DIR

# ==========================
# CONFIG
# ==========================
load_dotenv()
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = normalize_notion_id(os.getenv("NOTION_DATABASE_ID"))
DATA_SOURCE_ID = normalize_notion_id(os.getenv("NOTION_DATA_SOURCE_ID"))

if not NOTION_TOKEN or not DATABASE_ID:
    raise RuntimeError("Missing NOTION_TOKEN or NOTION_DATABASE_ID in environment.")

notion = Client(auth=NOTION_TOKEN, notion_version="2025-09-03")
_resolved_data_source_id: str | None = DATA_SOURCE_ID


def resolve_data_source_id() -> str:
    """Fetch and cache the data source id required by the 2025-09-03 API."""
    global _resolved_data_source_id
    if _resolved_data_source_id:
        return _resolved_data_source_id

    response = notion.databases.retrieve(database_id=DATABASE_ID)
    data_sources = response.get("data_sources") or []
    if not data_sources:
        raise RuntimeError(
            "Unable to resolve data source for the database. "
            "Grant the integration access or set NOTION_DATA_SOURCE_ID."
        )
    _resolved_data_source_id = data_sources[0]["id"]
    return _resolved_data_source_id


def query_data_source(data_source_id: str, **kwargs):
    """Hit the new query endpoint scoped to a data source."""
    return notion.request(
        path=f"data_sources/{data_source_id}/query",
        method="POST",
        body=kwargs,
    )


# ==========================
# HELPERS
# ==========================
def sanitize_filename(value: str) -> str:
    """Remove characters forbidden by common filesystems."""
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, "", value)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    if not sanitized:
        return "untitled"
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if sanitized.upper() in reserved:
        sanitized = f"_{sanitized}"
    return sanitized


def iter_database_entries(filter_payload: dict) -> Iterator[dict]:
    """Yield every page that matches the provided filter."""
    data_source_id = resolve_data_source_id()
    cursor = None
    while True:
        payload = {"filter": filter_payload, "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        response = query_data_source(data_source_id, **payload)
        for row in response.get("results", []):
            yield row
        if not response.get("has_more"):
            break
        cursor = response.get("next_cursor")


def extract_plain_text(prop: dict, key: str) -> str:
    """Collects plain text fragments from title or rich_text properties."""
    fragments = prop.get(key, [])
    return "".join(fragment.get("plain_text", "") for fragment in fragments).strip()


def get_page_title(page: dict) -> str:
    prop = page["properties"].get("Title", {})
    title = extract_plain_text(prop, "title")
    return title or f"page_{page['id'][:6]}"


def get_script_body(page: dict) -> str:
    prop = page["properties"].get("Script", {})
    if "rich_text" in prop:
        return extract_plain_text(prop, "rich_text")
    # Some workspaces store scripts as plain text instead of rich text.
    if "title" in prop:
        return extract_plain_text(prop, "title")
    return ""


def split_sentences_per_line(text: str) -> str:
    """
    Normalize whitespace and place each detected sentence on its own line.
    Fallback: if punctuation-based splitting yields nothing, return the cleaned text.
    """
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[.?!])\s+", cleaned)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        sentences = [cleaned]
    return "\n".join(sentences)


def unique_txt_path(base_name: str) -> Path:
    """Return a txt_inbox path that will not overwrite existing files."""
    TXT_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    candidate = TXT_INBOX_DIR / f"{base_name}.txt"
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        candidate = TXT_INBOX_DIR / f"{base_name}_{counter}.txt"
        if not candidate.exists():
            return candidate
        counter += 1


def get_select_value(prop: dict) -> str:
    selection = prop.get("select")
    if selection:
        return selection.get("name", "").strip()
    multi = prop.get("multi_select")
    if multi:
        names = [item.get("name", "").strip() for item in multi if item.get("name")]
        return ", ".join(filter(None, names))
    return ""


def get_channel_name(page: dict) -> str:
    props = page.get("properties", {})
    channel_prop = props.get("Channel") or props.get("Canal")
    if not channel_prop:
        return ""
    ptype = channel_prop.get("type")
    if ptype in ("title", "rich_text"):
        return extract_plain_text(channel_prop, ptype)
    if ptype in ("select", "multi_select"):
        return get_select_value(channel_prop)
    return ""


def build_display_label(channel: str, title: str) -> str:
    channel = channel.strip()
    title = title.strip()
    if channel:
        return f"{channel} - {title}" if title else channel
    return title or "Sem título"


def fetch_script_body(page_id: str) -> str:
    page = notion.pages.retrieve(page_id=page_id)
    return get_script_body(page)


def mark_download_completed(page_id: str):
    """Mark the Download checkbox as completed on the page."""
    try:
        notion.pages.update(
            page_id=page_id,
            properties={"Download": {"checkbox": True}},
        )
    except Exception as exc:
        print(f"⚠️  Falha ao marcar 'Download' para {page_id}: {exc}")


def resolve_selection(raw: str, options: list[dict]) -> list[dict]:
    """Return selected options based on 1-indexed user input."""
    if not options:
        return []
    if not raw or raw.strip() in ("", "0"):
        return options

    tokens = raw.replace(",", " ").split()
    if not tokens:
        return options

    indices: list[int] = []
    for token in tokens:
        try:
            idx = int(token)
        except ValueError:
            raise ValueError(f"Entrada inválida: '{token}'")
        if idx < 1 or idx > len(options):
            raise ValueError(f"Número fora do intervalo: {idx}")
        if idx - 1 not in indices:
            indices.append(idx - 1)

    return [options[i] for i in indices]


# ==========================
# MAIN LOGIC
# ==========================
def download_roteiro_scripts():
    filter_payload = {
        "and": [
            {"property": "Step", "select": {"equals": "2. Roteiro"}},
            {"property": "RTD", "formula": {"string": {"equals": "READY"}}},
            {"property": "Download", "checkbox": {"equals": False}},
        ]
    }

    print("🔎 Procurando scripts com Step = 'Roteiro'...")
    entries: list[dict] = []

    for page in iter_database_entries(filter_payload):
        title = get_page_title(page)
        channel = get_channel_name(page)
        label = build_display_label(channel, title)
        entries.append({
            "id": page["id"],
            "title": title,
            "channel": channel,
            "label": label,
        })

    if not entries:
        print("📭 Nada encontrado com Step = 'Roteiro'.")
        return

    print("\nDisponíveis:")
    for idx, entry in enumerate(entries, start=1):
        print(f"{idx}. {entry['label']}")

    raw = input("\n➡️ Digite os números desejados (ex: 1 3) ou ENTER para todos: ").strip()
    try:
        selected = resolve_selection(raw, entries)
    except ValueError as exc:
        print(f"❌ {exc}")
        return

    if not selected:
        print("⚠️ Nenhum item selecionado.")
        return

    total = 0
    for entry in selected:
        body = split_sentences_per_line(fetch_script_body(entry["id"]))
        if not body:
            print(f"⚠️  '{entry['label']}' não possui conteúdo na coluna 'Script' — pulando.")
            continue

        safe_label = sanitize_filename(entry["label"])
        output_path = unique_txt_path(safe_label)
        output_path.write_text(body, encoding="utf-8")
        base_name = output_path.stem
        ensure_entry(base_name)
        update_stage(base_name, "txt", "done", extra={"txt_file": str(output_path.resolve())})
        mark_download_completed(entry["id"])
        total += 1
        rel_path = output_path.relative_to(TXT_INBOX_DIR.parent)
        print(f"✅ {rel_path}")

    if total == 0:
        print("📭 Nada para salvar.")
    else:
        print(f"\n📥 {total} arquivo(s) salvos em {TXT_INBOX_DIR.resolve()}")


if __name__ == "__main__":
    download_roteiro_scripts()
