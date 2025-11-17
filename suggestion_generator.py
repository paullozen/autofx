import os
import sys
from pathlib import Path
from manifesto import ensure_entry, update_stage, load_manifest
from profiles import list_profiles, choose_profiles
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm
import platform
import time
from paths import IMG_SUGGESTIONS_DIR, TXT_PROCESSED_DIR

# ==========================
# ELIGIBILITY
# ==========================
def list_ready_for_suggestions() -> list[str]:
    mf = load_manifest()
    ready = []
    for base, info in mf.items():
        if info.get("txt") == "done" and info.get("suggestions") != 'done':
            ready.append(base)
    return ready


# ==========================
# CONFIG
# ==========================
ROOT         = Path(__file__).resolve().parent
INPUT_DIR    = TXT_PROCESSED_DIR
OUTPUT_DIR   = IMG_SUGGESTIONS_DIR

PROMPT_PATH  = "prompts/Scene_Suggestion.txt"
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

def locate_processed_txt(base: str) -> Path | None:
    """
    Locate the processed TXT for a base.
    Priority is txt_processed/base/base.txt, falling back to txt_processed/base.txt,
    and finally any matching file in the tree.
    """
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    folder_candidate = INPUT_DIR / base / f"{base}.txt"
    if folder_candidate.exists():
        return folder_candidate

    top_level = INPUT_DIR / f"{base}.txt"
    if top_level.exists():
        return top_level

    matches = list(INPUT_DIR.rglob(f"{base}.txt"))
    return matches[0] if matches else None


def read_base_lines(base: str) -> tuple[list[str], Path | None]:
    """Read processed TXT lines for the base, stripping blanks."""
    txt_path = locate_processed_txt(base)
    if txt_path is None:
        return [], None
    with open(txt_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return lines, txt_path

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

def group_lines(lines, group_size: int):
    if group_size <= 1:
        return lines
    chunks = []
    for i in range(0, len(lines), group_size):
        chunk_lines = [line for line in lines[i : i + group_size] if line]
        if not chunk_lines:
            continue
        chunk = "\n".join(chunk_lines).strip()
        if chunk:
            chunks.append(chunk)
    return chunks

def ensure_manifest_for_inbox():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    for txt_file in INPUT_DIR.rglob("*.txt"):
        ensure_entry(txt_file.stem)

# ==========================
# CORE
# ==========================
def process_base(base: str, group_size: int, chosen_profiles: list[str]):
    """
    Gera sugestões a partir do TXT processado, agrupando por group_size e subdividindo entre os perfis.
    Agora o modelo recebe o contexto global completo do roteiro e o pattern junto ao system prompt.
    """
    txt_lines, txt_path = read_base_lines(base)
    base_out_dir = OUTPUT_DIR / base
    base_out_dir.mkdir(parents=True, exist_ok=True)

    if txt_path is None:
        update_stage(base, "suggestions", "error: txt processado não encontrado")
        return

    update_stage(base, "suggestions", "in_progress")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if not txt_lines:
            update_stage(base, "suggestions", "error: arquivo txt vazio")
            return

        prompt_core = load_text(PROMPT_PATH)    # SJ_DRAWS.txt
        full_prompt = (
            f"{prompt_core}\n\n"
            f"--- TEXT ---\n\n"
            f"Generate ONE concise visual suggestion for the following block of text, starting with 'Show...' and strictly adhering to all policies and formatting rules defined above."
            )

        scenes = group_lines(txt_lines, group_size)
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
                        "Original:",
                        scene_text.replace("\n", " "),
                        f"Suggestion: {final_suggestion}",
                        ""
                    ]
                    f_out.write("\n".join(block) + "\n")
                    f_out.flush()

        update_stage(
            base,
            "suggestions",
            "done",
            extra={"scenes": total, "group_size": group_size, "source": str(txt_path)},
        )
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

        # Calcula total estimado de cenas
        total_lines = 0
        for base in selected:
            lines, _ = read_base_lines(base)
            total_lines += len(lines)

        print(f"\n📊 Total de falas nos arquivos selecionados: {total_lines}")

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

