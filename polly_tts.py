# generate_audio.py
import os
import time
import boto3
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm
import re

# ==========================
# IMPORTA MANIFESTO
# ==========================
from manifesto import ensure_entry, update_stage, load_manifest

# ==========================
# CONFIG
# ==========================
ROOT = Path(__file__).resolve().parent
INBOX_DIR = ROOT / "scripts" / "txt_inbox"
AUDIO_DIR = ROOT / "audio"
MAX_CHARS = 2800  # margem segura (< 3000 do Polly)

# Configs de voz

# INGLES (MOT)
VOICE = "Matthew"
ENGINE = "generative"
IDIOM = "en-US"

# INGLES (SEED)
# VOICE = "Joey"
# ENGINE = "neural"
# IDIOM = "en-US"

# ESPANHOL (SEMILLA)
# VOICE = "Andres"
# ENGINE = "neural"
# IDIOM = "es-MX"

# Carrega credenciais AWS
load_dotenv()
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# ==========================
# SETUP
# ==========================
AUDIO_DIR.mkdir(exist_ok=True)
polly = boto3.client(
    "polly",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION,
)

# ==========================
# TEXT HELPERS
# ==========================
def _hard_cut(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    out, buf = [], ""
    for w in text.split():
        if not buf:
            buf = w
        elif len(buf) + 1 + len(w) <= limit:
            buf += " " + w
        else:
            out.append(buf)
            buf = w
    if buf:
        out.append(buf)
    return out

def split_text_smart(text: str, limit: int = MAX_CHARS) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text.strip())
    text = re.sub(r"\u200b|\u200c|\u200d|\ufeff", "", text)
    paragraphs = re.split(r"\n\s*\n+", text)
    chunks, buf = [], ""
    sent_split = re.compile(r"(?<=[.!?…])\s+")

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) <= limit:
            if buf and len(buf) + 2 + len(para) <= limit:
                buf += "\n\n" + para
            else:
                if buf:
                    chunks.append(buf)
                    buf = ""
                buf = para
            continue

        sentences = sent_split.split(para)
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if not buf:
                if len(s) <= limit:
                    buf = s
                else:
                    parts = _hard_cut(s, limit)
                    chunks.extend(parts[:-1])
                    buf = parts[-1]
            else:
                if len(buf) + 1 + len(s) <= limit:
                    buf += " " + s
                else:
                    chunks.append(buf)
                    if len(s) <= limit:
                        buf = s
                    else:
                        parts = _hard_cut(s, limit)
                        chunks.extend(parts[:-1])
                        buf = parts[-1]
        if buf:
            chunks.append(buf)
            buf = ""

    if buf:
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]


# ==========================
# AWS POLLY
# ==========================
def synthesize_with_progress(text: str, output_path: Path, base: str):
    ensure_entry(base)
    try:
        chunks = split_text_smart(text, MAX_CHARS)
        if not chunks:
            print("⚠️ Nenhum conteúdo válido para sintetizar.")
            update_stage(base, "audio", "error: texto vazio")
            return

        update_stage(base, "audio", "in_progress")

        with open(output_path, "wb") as out_f, tqdm(
            total=len(chunks),
            desc=f"🎙️ Gerando áudio ({output_path.stem})",
            ncols=80,
            bar_format="{l_bar}{bar} | {n_fmt}/{total_fmt}"
        ) as pbar:
            for chunk in chunks:
                try:
                    resp = polly.synthesize_speech(
                        Text=chunk,
                        OutputFormat="mp3",
                        VoiceId=VOICE,
                        Engine=ENGINE,
                        LanguageCode=IDIOM,
                    )
                except polly.exceptions.TextLengthExceededException:
                    safe = chunk[: int(len(chunk) * 0.95)]
                    resp = polly.synthesize_speech(
                        Text=safe,
                        OutputFormat="mp3",
                        VoiceId=VOICE,
                        Engine=ENGINE,
                        LanguageCode=IDIOM,
                    )
                out_f.write(resp["AudioStream"].read())
                pbar.update(1)
                time.sleep(0.15)

        # Marca áudio como concluído
        update_stage(base, "audio", "done", extra={"audio_file": str(output_path.resolve())})
        # E garante que o SRT também fique como concluído
        update_stage(base, "srt", "done")

        print(f"✅ Áudio e SRT marcados como 'done' para {base}")

    except Exception as e:
        update_stage(base, "audio", f"error: {e}")
        print(f"❌ Erro ao gerar áudio: {e}")


# ==========================
# MAIN
# ==========================
def main():
    mf = load_manifest()
    txt_files = sorted(INBOX_DIR.glob("*.txt"))
    if not txt_files:
        print("📭 Nenhum arquivo encontrado em txt_inbox/")
        return

    candidates = []
    for txt in txt_files:
        base = txt.stem
        ensure_entry(base)
        status = mf.get(base, {}).get("audio", "pending")
        if status != "done":
            candidates.append(txt)

    if not candidates:
        print("📭 Nenhuma base pendente para gerar áudio (tudo 'done').")
        return

    print("\n🗂️ Bases disponíveis para gerar áudio:")
    for i, txt in enumerate(candidates, 1):
        base = txt.stem
        current_status = mf.get(base, {}).get("audio", "pending")
        print(f"{i}. {base} (status: {current_status})")
    print("0. Cancelar")

    try:
        choice = int(input("\n➡️ Escolha a base (ex: 2): ").strip())
    except ValueError:
        print("❌ Entrada inválida.")
        return

    if choice == 0:
        print("🚫 Cancelado.")
        return

    if not (1 <= choice <= len(candidates)):
        print("❌ Opção fora do intervalo.")
        return

    txt_file = candidates[choice - 1]
    base_name = txt_file.stem
    output_file = AUDIO_DIR / f"{base_name}.mp3"

    text = txt_file.read_text(encoding="utf-8").strip()
    if not text:
        print("⚠️ Arquivo vazio.")
        update_stage(base_name, "audio", "error: arquivo vazio")
        return

    print(f"\n🚀 Iniciando geração do áudio para '{base_name}'...\n")
    synthesize_with_progress(text, output_file, base_name)
    print("\n🔔 Áudio finalizado com sucesso.")


if __name__ == "__main__":
    main()
