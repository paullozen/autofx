# auto_srt_notion.py
import re
import shutil
import textwrap
from pathlib import Path
from manifesto import ensure_entry, update_stage

# ==========================
# CONFIG
# ==========================
INBOX_DIR = Path("scripts/txt_inbox")
OUTPUT_DIR = Path("scripts/srt_outputs")
PROCESSED_DIR = Path("scripts/txt_processed")

WPM = 180
MIN_DUR = 1.0
MAX_DUR = 6.0
MAX_CHARS_LINE = 42
MAX_LINES = 2
GAP = 0.8
EXTRA_PAUSE = 0.3

# ==========================
# HELPERS
# ==========================
def seconds_to_timestamp(seconds: float) -> str:
    ms = int((seconds % 1) * 1000)
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def estimate_duration(text: str) -> float:
    words = len(text.split())
    secs = words / (WPM / 60)
    if text.strip().endswith((".", "?", "!", ":")):
        secs += EXTRA_PAUSE
    return max(MIN_DUR, min(MAX_DUR, secs))


def wrap_text(text: str) -> str:
    wrapped = textwrap.wrap(text, width=MAX_CHARS_LINE)
    if len(wrapped) > MAX_LINES:
        merged = wrapped[:MAX_LINES - 1]
        merged.append(" ".join(wrapped[MAX_LINES - 1:]))
        return "\n".join(merged)
    return "\n".join(wrapped)


def split_into_sentences(text: str):
    sentences = re.split(r'(?<=[.?!])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]


def build_srt(sentences):
    srt_lines, current_time = [], 0.0
    for idx, sentence in enumerate(sentences, start=1):
        duration = estimate_duration(sentence)
        start_time = current_time if idx == 1 else current_time + GAP
        end_time = start_time + duration

        srt_lines.append(f"{idx}")
        srt_lines.append(f"{seconds_to_timestamp(start_time)} --> {seconds_to_timestamp(end_time)}")
        srt_lines.append(wrap_text(sentence))
        srt_lines.append("")

        current_time = end_time
    return "\n".join(srt_lines)

# ==========================
# LOCAL INBOX HELPERS
# ==========================
# Notion calls disabled for now; scripts are pulled from scripts/txt_inbox instead.
def list_inbox_files() -> list[Path]:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(INBOX_DIR.glob("*.txt"))


def read_script(base: str) -> tuple[str | None, Path]:
    txt_path = INBOX_DIR / f"{base}.txt"
    if not txt_path.exists():
        return None, txt_path
    return txt_path.read_text(encoding="utf-8"), txt_path

# ==========================
# CORE
# ==========================
def ensure_manifest_for_inbox():
    for txt in list_inbox_files():
        ensure_entry(txt.stem)


def process_base(base: str):
    raw, txt_path = read_script(base)
    if raw is None:
        update_stage(base, "srt", "error: txt não encontrado")
        return

    if not raw.strip():
        update_stage(base, "srt", "error: arquivo txt vazio")
        return

    update_stage(base, "srt", "in_progress")

    sentences = split_into_sentences(raw)
    if not sentences:
        update_stage(base, "srt", "error: sem frases detectadas")
        return

    srt_content = build_srt(sentences)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    srt_path = OUTPUT_DIR / f"{base}.srt"

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    update_stage(
        base,
        "srt",
        "done",
        extra={"sentences": len(sentences), "srt_file": str(srt_path.resolve())}
    )
    print(f"[OK] {base} → {srt_path} ({len(sentences)} frases, origem {txt_path})")
    archive_txt(txt_path)

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    ensure_manifest_for_inbox()

    files = list_inbox_files()
    entries = [f.stem for f in files]
    if not entries:
        print(f"Nenhum .txt encontrado em {INBOX_DIR}.")
        return

    print("\n📜 Arquivos na inbox local:")
    for i, name in enumerate(entries, start=1):
        print(f"{i}. {name}")

    choice = input("\nDigite o número do script que deseja processar (ou 0 para todos): ").strip()
    if not choice:
        print("Operação cancelada.")
        return

    if choice == "0":
        print("\n🔁 Processando todos os arquivos da inbox...")
        for name in entries:
            process_base(name)
        return

    try:
        idx = int(choice)
        if idx < 1 or idx > len(entries):
            print("Número inválido.")
            return
    except ValueError:
        print("Entrada inválida.")
        return

    selected = entries[idx - 1]
    print(f"\n🎬 Processando: {selected}\n")
    process_base(selected)


def archive_txt(txt_path: Path):
    """Move txt processado para scripts/txt_processed."""
    if not txt_path.exists():
        return
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    dest = PROCESSED_DIR / txt_path.name
    try:
        shutil.move(str(txt_path), str(dest))
        print(f"📁 TXT movido para {dest}")
    except Exception as exc:
        print(f"⚠️ Falha ao mover {txt_path} para {dest}: {exc}")


if __name__ == "__main__":
    main()
