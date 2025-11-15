# auto_srt_notion.py
import re
import shutil
import textwrap
from pathlib import Path
from manifesto import ensure_entry, update_stage
from paths import TXT_INBOX_DIR, SRT_OUTPUT_DIR, TXT_PROCESSED_DIR

# ==========================
# CONFIG
# ==========================
INBOX_DIR = TXT_INBOX_DIR
OUTPUT_DIR = SRT_OUTPUT_DIR
PROCESSED_DIR = TXT_PROCESSED_DIR

WPM = 180
BASE_MIN_DUR = 1.0
BASE_MAX_DUR = 6.0
BASE_MAX_CHARS_LINE = 42
BASE_MAX_LINES = 2
MIN_DUR = BASE_MIN_DUR
MAX_DUR = BASE_MAX_DUR
MAX_CHARS_LINE = BASE_MAX_CHARS_LINE
MAX_LINES = BASE_MAX_LINES
LINES_PER_TIMESTAMP = BASE_MAX_LINES
GAP = 10
EXTRA_PAUSE = 0.3


def configure_caption_settings(lines_per_timestamp: int):
    """Scale SRT timing + wrapping constraints based on desired lines per entry."""
    global MIN_DUR, MAX_DUR, MAX_CHARS_LINE, MAX_LINES, LINES_PER_TIMESTAMP
    lines = max(1, lines_per_timestamp)
    factor = lines / BASE_MAX_LINES
    MIN_DUR = round(BASE_MIN_DUR * factor, 2)
    MAX_DUR = round(BASE_MAX_DUR * factor, 2)
    # Allow wider lines but keep them somewhat readable.
    scaled_chars = int(BASE_MAX_CHARS_LINE * min(factor, 4))
    MAX_CHARS_LINE = min(200, max(BASE_MAX_CHARS_LINE, scaled_chars))
    MAX_LINES = lines
    LINES_PER_TIMESTAMP = lines

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


def chunk_sentences(sentences: list[str], per_timestamp: int) -> list[str]:
    chunk_size = max(1, per_timestamp)
    block, grouped = [], []
    for sentence in sentences:
        if not sentence:
            continue
        block.append(sentence)
        if len(block) >= chunk_size:
            grouped.append(" ".join(block).strip())
            block = []
    if block:
        grouped.append(" ".join(block).strip())
    return grouped


def build_srt(sentences):
    srt_lines, current_time = [], 0.0
    grouped_sentences = chunk_sentences(sentences, LINES_PER_TIMESTAMP)
    for idx, chunk_text in enumerate(grouped_sentences, start=1):
        duration = estimate_duration(chunk_text)
        start_time = current_time if idx == 1 else current_time + GAP
        end_time = start_time + duration

        srt_lines.append(f"{idx}")
        srt_lines.append(f"{seconds_to_timestamp(start_time)} --> {seconds_to_timestamp(end_time)}")
        srt_lines.append(wrap_text(chunk_text))
        srt_lines.append("")

        current_time = end_time
    return "\n".join(srt_lines)

# ==========================
# LOCAL INBOX HELPERS
# ==========================
# Notion calls disabled for now; scripts are pulled from txt_inbox/ at the repo root instead.
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


def count_sentences_for_base(base: str) -> tuple[int | None, Path]:
    raw, txt_path = read_script(base)
    if raw is None:
        return None, txt_path
    sentences = split_into_sentences(raw)
    return len(sentences), txt_path


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
        selected = entries
    else:
        try:
            idx = int(choice)
            if idx < 1 or idx > len(entries):
                print("Número inválido.")
                return
        except ValueError:
            print("Entrada inválida.")
            return
        selected = [entries[idx - 1]]

    print("\n🧮 Contagem de frases por script selecionado:")
    for name in selected:
        count, txt_path = count_sentences_for_base(name)
        if count is None:
            print(f" - {name}: arquivo não encontrado ({txt_path})")
        else:
            print(f" - {name}: {count} frases detectadas")

    try:
        lines_raw = input("➡️ Quantas linhas o SRT deve agrupar por timestamp? (ENTER = 2): ").strip()
        lines_per_timestamp = int(lines_raw) if lines_raw else BASE_MAX_LINES
    except ValueError:
        lines_per_timestamp = BASE_MAX_LINES
    configure_caption_settings(lines_per_timestamp)
    print(f"⚙️ Configurado: {LINES_PER_TIMESTAMP} linhas/timestamp, {MAX_CHARS_LINE} chars/linha, duração {MIN_DUR}-{MAX_DUR}s.")

    print("\n🎬 Processando seleção...\n")
    for name in selected:
        process_base(name)


def archive_txt(txt_path: Path):
    """Move txt processado para output/txt_processed."""
    if not txt_path.exists():
        return
    channel_folder: Path
    stem = txt_path.stem
    if " - " in stem:
        channel_name = stem.split(" - ", 1)[0].strip() or "unknown"
        channel_folder = PROCESSED_DIR / channel_name
    else:
        channel_folder = PROCESSED_DIR
    channel_folder.mkdir(parents=True, exist_ok=True)
    dest = channel_folder / txt_path.name
    try:
        shutil.move(str(txt_path), str(dest))
        print(f"📁 TXT movido para {dest}")
    except Exception as exc:
        print(f"⚠️ Falha ao mover {txt_path} para {dest}: {exc}")


if __name__ == "__main__":
    main()
