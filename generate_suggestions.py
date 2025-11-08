# generate_suggestions.py (versão SRT + subdivisão por perfis)
import os
import sys
from pathlib import Path
from manifesto import ensure_entry, update_stage, load_manifest
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm
import platform
import time

# ==========================
# ELIGIBILITY
# ==========================
def list_ready_for_suggestions() -> list[str]:
    mf = load_manifest()
    ready = []
    for base, info in mf.items():
        if info.get("srt") == "done" and info.get("suggestions") != 'done':
            ready.append(base)
    return ready


# ==========================
# CONFIG
# ==========================
ROOT         = Path(__file__).resolve().parent
PROFILE_DIR  = ROOT / "chrome_profiles"  # para listar perfis criados
INPUT_DIR    = "scripts/srt_outputs"
OUTPUT_DIR   = "scripts/img_suggestions"
# PATTERN_PATH = "prompts/MOT_PATTERN.txt"
# PROMPT_PATH  = "prompts/MOT_DRAWS.txt"
PATTERN_PATH = "prompts/SJ_PATTERN_chalk.txt"
PROMPT_PATH  = "prompts/SJ_DRAWS_2.txt"

# ==========================
# ENV
# ==========================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
print("Model set to:", OPENAI_MODEL)

if not OPENAI_API_KEY:
    raise RuntimeError("Faltando OPENAI_API_KEY no .env")
client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
# HELPERS
# ==========================
def load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

def read_srt_lines(srt_path: str):
    """Extrai falas de um arquivo .srt (ignora índices e timestamps)."""
    lines = []
    with open(srt_path, "r", encoding="utf-8") as f:
        block = []
        for raw in f:
            line = raw.strip()
            if not line:
                if block:
                    lines.append(" ".join(block))
                    block = []
                continue
            if line.isdigit():
                continue
            if "-->" in line:
                continue
            block.append(line)
        if block:
            lines.append(" ".join(block))
    return lines

def ask_model(full_prompt, scene_text):
    """Envia o prompt completo ao modelo e retorna a resposta limpa."""
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": full_prompt},
            {"role": "user", "content": scene_text},
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

def detect_completed_scenes(out_path):
    """Conta quantas linhas 'Scene ' já existem no arquivo (para retomar)."""
    if not os.path.exists(out_path):
        return 0
    count = 0
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Scene "):
                count += 1
    return count

def group_lines(lines, group_size:int):
    if group_size <= 1:
        return lines
    chunks = []
    for i in range(0, len(lines), group_size):
        chunk = " ".join(lines[i:i+group_size]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks

def ensure_manifest_for_inbox():
    for f in os.listdir(INPUT_DIR):
        if f.endswith(".srt"):
            base = Path(f).stem
            ensure_entry(base)

def list_profiles():
    """Lista nomes de pastas dentro de chrome_profiles (perfis)."""
    if not PROFILE_DIR.exists():
        return []
    return [p.name for p in PROFILE_DIR.iterdir() if p.is_dir()]

def choose_profiles(profiles: list[str]) -> list[str]:
    """
    Mostra os perfis e permite escolher vários por número ou '0' para todos.
    Retorna a lista de nomes escolhidos.
    """
    if not profiles:
        print("⚠️ Nenhum perfil encontrado em chrome_profiles/. Seguindo com 1 'default'.")
        return ["default"]

    print("\n👤 Perfis disponíveis:")
    for i, name in enumerate(profiles, 1):
        print(f"{i}. {name}")
    print("0. TODOS")

    raw = input("➡️ Selecione perfis (ex: 1 3 4 ou '0' p/ todos): ").strip().lower()
    if raw == "0" or raw == "todos":
        return profiles
    try:
        idxs = [int(x) for x in raw.replace(",", " ").split()]
        chosen = [profiles[i-1] for i in idxs if 1 <= i <= len(profiles)]
        if not chosen:
            raise ValueError
        return chosen
    except Exception:
        print("❌ Entrada inválida. Usando apenas o primeiro perfil.")
        return [profiles[0]]

# ==========================
# CORE
# ==========================
def process_base(base: str, group_size: int, chosen_profiles: list[str]):
    """
    Gera sugestões a partir do SRT, agrupando por group_size e subdividindo entre os perfis.
    Agora o modelo recebe o contexto global completo do roteiro e o pattern junto ao system prompt.
    """
    srt_path = os.path.join(INPUT_DIR, f"{base}.srt")
    base_out_dir = Path(OUTPUT_DIR) / base
    base_out_dir.mkdir(parents=True, exist_ok=True)

    if not os.path.exists(srt_path):
        update_stage(base, "suggestions", "error: srt não encontrado")
        return

    update_stage(base, "suggestions", "in_progress")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        lines = read_srt_lines(srt_path)
        if not lines:
            update_stage(base, "suggestions", "error: arquivo srt vazio")
            return

        prompt_core = load_text(PROMPT_PATH)    # SJ_DRAWS.txt
        pattern     = load_text(PATTERN_PATH)   # SJ_PATTERN 2.txt
        # full_script = "\n".join(lines).strip()

        # --- cria o prompt global com contexto e estilo ---
        # full_prompt = (
        #     f"{prompt_core}\n\n"
        #     f"The following is the full script context (for emotional and narrative consistency):\n"
        #     f"{full_script}\n\n"
        #     f"---\n\n"
        #     f"Apply this understanding to each individual line below, generating visually accurate suggestions "
        #     f"aligned with the following visual pattern:\n{pattern}\n\n"
        #     f"Do not repeat stylistic descriptions — just describe what should be shown visually, starting with 'Show...'"
        # )
        full_prompt = (
            f"{prompt_core}\n\n"
            f"Use the following visual pattern:\n{pattern}\n\n"
            f"Generate one simple visual suggestion for each line below. "
            f"Keep it concise and literal, starting with 'Show...'"
        )

        scenes = group_lines(lines, group_size)
        total = len(scenes)
        if total == 0:
            update_stage(base, "suggestions", "error: sem cenas após agrupamento")
            return

        # --- divisão contígua por perfis ---
        P = max(1, len(chosen_profiles))
        base_chunk = total // P
        remainder = total % P

        ranges = []
        if P == 1:
            ranges.append((1, total))
        else:
            first_count = base_chunk + remainder
            start = 1
            end = first_count
            ranges.append((start, end))
            for k in range(1, P):
                start = end + 1
                end = start + base_chunk - 1
                ranges.append((start, end))

        # --- processamento principal ---
        for prof_name, (start_idx, end_idx) in zip(chosen_profiles, ranges):
            if start_idx > end_idx:
                continue

            out_path = base_out_dir / f"{base}__{prof_name}.txt"
            done_sub = detect_completed_scenes(out_path)
            mode = "a" if done_sub > 0 else "w"

            with open(out_path, mode, encoding="utf-8") as f_out:
                for j, scene_idx in enumerate(
                    tqdm(range(start_idx, end_idx + 1),
                         desc=f"{base}__{prof_name} ({start_idx}-{end_idx})",
                         initial=done_sub,
                         total=(end_idx - start_idx + 1)),
                    start=1
                ):
                    if j <= done_sub:
                        continue

                    scene_text = scenes[scene_idx - 1]
                    max_retries = 3
                    for attempt in range(1, max_retries + 1):
                        try:
                            suggestion = ask_model(full_prompt, scene_text)
                            if "[ERRO AO GERAR" in suggestion or "Request timed out"  in suggestion:
                                raise RuntimeError("Modelo retornou erro interno")
                            final_suggestion = suggestion.strip()
                            break
                        except Exception as e:
                            if attempt < max_retries:
                                print(f"⚠️ Cena {scene_idx}: tentativa {attempt}/{max_retries} falhou ({e}), repetindo...")
                                continue
                            else:
                                print(f"❌ Cena {scene_idx}: erro persistente ({e})")
                                final_suggestion = f"[ERRO AO GERAR: {e}]"

                    block = [
                        f"Scene {scene_idx}",
                        f"Original: {scene_text}",
                        f"Suggestion: {final_suggestion}",
                        ""
                    ]
                    f_out.write("\n".join(block) + "\n")
                    f_out.flush()

        update_stage(base, "suggestions", "done", extra={"scenes": total, "group_size": group_size})
        print(f"[OK] {base} → dividido entre {len(chosen_profiles)} perfil(is) (cenas: {total}, group={group_size})")

    except Exception as e:
        update_stage(base, "suggestions", f"error: {str(e)}")
        print(f"[ERRO] {base}: {e}")

# ==========================
# MAIN
# ==========================
def main():
    ensure_manifest_for_inbox()

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    # Lista candidatos do manifesto
    candidates = list_ready_for_suggestions()
    if not candidates:
        print("Nenhum arquivo pendente para sugestões.")
        return

    # Escolha de bases
    if args:
        if "todos" in [a.lower() for a in args]:
            selected = candidates
        else:
            selected = args
    else:
        print("\n📂 Arquivos disponíveis:")
        for i, base in enumerate(candidates, 1):
            print(f"{i}. {base}")
        print("0. TODOS")

        choice = input("➡️ Digite número(s) separados por vírgula ou 0 para TODOS: ").strip()
        if not choice:
            print("❌ Nenhuma escolha feita.")
            return

        if choice == "0":
            selected = candidates
        else:
            try:
                idxs = [int(x) for x in choice.split(",")]
                selected = [candidates[i-1] for i in idxs if 1 <= i <= len(candidates)]
            except Exception:
                print("❌ Entrada inválida.")
                return

    # Pergunta group_size DEPOIS da escolha dos arquivos
    try:
        g = input("➡️ Quantas falas por cena? (ENTER = 1): ").strip()
        group_size = int(g) if g else 1
    except ValueError:
        group_size = 1

    # Escolha dos perfis (0 = todos)
    profiles = list_profiles()
    chosen_profiles = choose_profiles(profiles)

    # Processa cada base com a mesma seleção de perfis
    for base in selected:
        process_base(base, group_size, chosen_profiles)

    def beep():
            system = platform.system().lower()
            try:
                if system == "windows":
                    import winsound
                    for _ in range(3):
                        winsound.Beep(1000, 200)
                        time.sleep(0.1)
                else:
                    sys.stdout.write("\a" * 3)
                    sys.stdout.flush()
            except Exception:
                pass
    
    print("\n" + "-" * 60)
    print("🔔")
    beep()
    print("✅ Finalizado processamento das bases selecionadas.")

if __name__ == "__main__":
    main()

