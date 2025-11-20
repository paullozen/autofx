import json
import shutil
from pathlib import Path
from paths import (
    MANIFEST_PATH,
    VIDEO_OUTPUT_DIR,
    IMG_OUTPUT_DIR,
    RENDER_OUTPUT_DIR,
    SCRIPTS_RENDER_DIR,
    SRT_OUTPUT_DIR,
    TIMELINES_DIR,
    IMG_SUGGESTIONS_DIR,
    TXT_INBOX_DIR,
    TXT_PROCESSED_DIR,
    AUDIO_OUTPUT_DIR,
    OUTPUT_ROOT,
)

# ========================
# CONFIG
# ========================
ROOT = Path(__file__).resolve().parent
VIDEOS_DIR = VIDEO_OUTPUT_DIR
IMGS_DIR = IMG_OUTPUT_DIR
RENDER_DIR = RENDER_OUTPUT_DIR
SRT_DIR = SRT_OUTPUT_DIR
TIMELINE_DIR = TIMELINES_DIR
TXT_INBOX = TXT_INBOX_DIR
TXT_PROCESSED = TXT_PROCESSED_DIR
AUDIO_DIR = AUDIO_OUTPUT_DIR

# ========================
# HELPERS
# ========================
def delete_path(p: Path):
    """Apaga arquivo ou pasta inteira."""
    try:
        if p.is_file():
            p.unlink()
            print(f"🗑️  Arquivo deletado: {p}")
        elif p.is_dir():
            shutil.rmtree(p)
            print(f"🧹 Pasta deletada: {p}")
    except Exception as e:
        print(f"⚠️ Falha ao deletar {p}: {e}")

def load_manifest():
    """Carrega o manifesto e retorna o dicionário."""
    if not MANIFEST_PATH.exists():
        print("⚠️ Manifesto não encontrado, criando novo vazio.")
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text("{}", encoding="utf-8")
        return {}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ Erro ao ler manifesto: {e}")
        return {}

def save_manifest(data):
    """Salva o manifesto atualizado."""
    try:
        MANIFEST_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        print(f"🧾 Manifesto atualizado: {MANIFEST_PATH}")
    except Exception as e:
        print(f"⚠️ Falha ao salvar manifesto: {e}")

def select_videos(manifest_data):
    """Lista os vídeos 'done' e permite escolher quais limpar."""
    done_items = [k for k, v in manifest_data.items() if v.get("video") == "done"]
    if not done_items:
        print("⚠️ Nenhum vídeo marcado como 'done' no manifesto.")
        return []

    print("\n📜 Vídeos prontos para limpeza:")
    for i, item in enumerate(done_items, start=1):
        print(f"[{i}] {item}")

    selected = input("\nDigite os números dos vídeos que deseja limpar (ex: 1,3,5) ou ENTER para cancelar: ").strip()
    if not selected:
        print("🚫 Nenhum vídeo selecionado. Abortando limpeza.")
        return []

    try:
        indices = [int(x.strip()) for x in selected.split(",")]
        chosen = [done_items[i - 1] for i in indices if 1 <= i <= len(done_items)]
        print(f"\n✅ Selecionados para limpeza: {chosen}")
        return chosen
    except Exception:
        print("⚠️ Entrada inválida. Abortando.")
        return []

def clean_video_files(video_name):
    """Apaga todos os arquivos relacionados ao vídeo e move TXT processado."""
    # Pastas primeiro
    dir_candidates = [
        IMGS_DIR / video_name,
        (IMG_SUGGESTIONS_DIR / video_name),
        VIDEOS_DIR / video_name,
        RENDER_DIR / video_name,
        SCRIPTS_RENDER_DIR / video_name,
    ]
    for path in dir_candidates:
        if path.exists():
            delete_path(path)

    # Arquivos específicos
    file_candidates = [
        VIDEOS_DIR / f"{video_name}.mp4",
        RENDER_DIR / f"{video_name}.mp4",
        SCRIPTS_RENDER_DIR / f"{video_name}.mp4",
        SRT_DIR / f"{video_name}.srt",
        TIMELINE_DIR / f"{video_name}_timeline.json",
        AUDIO_DIR / f"{video_name}.mp3",
    ]
    seen = set()
    for path in file_candidates:
        if path.exists():
            key = str(path.resolve())
            if key in seen:
                continue
            delete_path(path)
            seen.add(key)

    # move_txt_to_processed(video_name)

def purge_output_except_txt_processed():
    """Remove tudo em output/ exceto output/txt_processed."""
    if not OUTPUT_ROOT.exists():
        return

    preserved = TXT_PROCESSED_DIR.resolve()

    print("\n🧨 Limpando conteúdo de output/ (exceto txt_processed)...")
    for child in OUTPUT_ROOT.iterdir():
        resolved = child.resolve()
        if resolved == preserved:
            continue
        delete_path(child)

# ========================
# MAIN
# ========================
def main():
    print("💣 Iniciando verificação do manifesto...\n")
    manifest_data = load_manifest()
    selected_videos = select_videos(manifest_data)

    if not selected_videos:
        print("\n🚫 Nenhuma ação executada.")
        return

    print("\n🔥 Limpando dados selecionados...\n")

    for video_name in selected_videos:
        clean_video_files(video_name)
        if video_name in manifest_data:
            del manifest_data[video_name]

    save_manifest(manifest_data)
    purge_output_except_txt_processed()
    print("\n✅ Faxina concluída com sucesso.")

if __name__ == "__main__":
    main()


def move_txt_to_processed(base_name: str):
    TXT_PROCESSED.mkdir(parents=True, exist_ok=True)
    src = TXT_INBOX / f"{base_name}.txt"
    if not src.exists():
        return
    dest = TXT_PROCESSED / src.name
    try:
        if dest.exists():
            dest.unlink()
        src.replace(dest)
        print(f"📁 TXT movido para {dest}")
    except Exception as exc:
        print(f"⚠️ Falha ao mover {src}: {exc}")
