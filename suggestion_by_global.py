"""Generate visual suggestions for processed TXT scripts."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

from alerts import ring_bell
from manifesto import ensure_entry, load_manifest, update_stage
from paths import IMG_SUGGESTIONS_DIR, TXT_PROCESSED_DIR
from profiles import choose_profiles, list_profiles

# ==========================
# CONFIG
# ==========================
ROOT = Path(__file__).resolve().parent
INPUT_DIR = TXT_PROCESSED_DIR
OUTPUT_DIR = IMG_SUGGESTIONS_DIR
PROMPT_PATH = "prompts/Scene_Suggestion.txt"

# ==========================
# ENV
# ==========================
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
print("Model set to:", OPENAI_MODEL)

if not OPENAI_API_KEY:
    raise RuntimeError("Faltando OPENAI_API_KEY no .env")
client = OpenAI(api_key=OPENAI_API_KEY)


def load_text(path: str | Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def split_into_sentences(text: str) -> list[str]:
    if not text:
        return []
    cleaned = re.sub(r"\s+", " ", text.strip())
    sentences = re.split(r"(?<=[.?!])\s+", cleaned)
    result = [s.strip() for s in sentences if s.strip()]
    if not result and cleaned:
        result = [cleaned]
    return result


def ask_model(full_prompt: str, scene_text: str) -> str:
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": full_prompt},
            {"role": "user", "content": scene_text},
        ],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()


def detect_completed_scenes(out_path: Path) -> int:
    if not out_path.exists():
        return 0
    count = 0
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Scene "):
                count += 1
    return count


def group_lines(lines: list[str], group_size: int) -> list[str]:
    if group_size <= 1:
        return lines
    chunks = []
    for i in range(0, len(lines), group_size):
        chunk = " ".join(lines[i : i + group_size]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def locate_processed_txt(base: str) -> Path | None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    pattern = f"{base}.txt"
    for txt_file in INPUT_DIR.rglob(pattern):
        return txt_file
    return None


def read_processed_sentences(base: str) -> tuple[list[str], Path | None]:
    txt_path = locate_processed_txt(base)
    if txt_path is None:
        return [], None
    raw_text = txt_path.read_text(encoding="utf-8").strip()
    return split_into_sentences(raw_text), txt_path


def count_sentences_for_base(base: str) -> tuple[int | None, Path | None]:
    sentences, txt_path = read_processed_sentences(base)
    if txt_path is None:
        return None, None
    return len(sentences), txt_path


def ensure_manifest_for_inbox() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    for txt_file in INPUT_DIR.rglob("*.txt"):
        ensure_entry(txt_file.stem)


def parse_json_suggestions(raw: str) -> list[str]:
    cleaned = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    suggestions: list[str] = []
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            data = data.get("suggestions")
        if isinstance(data, list):
            suggestions = [str(item).strip() for item in data if str(item).strip()]
            suggestions = [s if s.lower().startswith("show") else f"Show {s}" for s in suggestions]
            return suggestions
    except Exception:
        pass
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        if line[0] in {"-", "•", "*"}:
            line = line[1:].strip()
        m = re.match(r"^(?:\d+[.)-]?\s*)(.*)$", line)
        if m:
            line = m.group(1).strip()
        if not line:
            continue
        if not line.lower().startswith("show"):
            line = f"Show {line}"
        suggestions.append(line.strip())
    return suggestions


def list_ready_for_suggestions() -> list[str]:
    mf = load_manifest()
    return [
        base
        for base, info in mf.items()
        if info.get("srt") == "done" and info.get("suggestions") != "done"
    ]


# ==========================
# GLOBAL MODE
# ==========================
def process_base_full_script(base: str, suggestion_count: int, chosen_profiles: list[str]) -> None:
    ensure_entry(base)
    base_out_dir = OUTPUT_DIR / base
    base_out_dir.mkdir(parents=True, exist_ok=True)

    update_stage(base, "suggestions", "in_progress")

    try:
        sentences, txt_path = read_processed_sentences(base)
        if txt_path is None:
            update_stage(base, "suggestions", "error: txt processado não encontrado")
            return
        full_script = txt_path.read_text(encoding="utf-8").strip()
        if not full_script:
            update_stage(base, "suggestions", "error: txt processado vazio")
            return

        prompt_core = load_text(PROMPT_PATH)
        full_prompt = (
            f"{prompt_core}\n\n"
            f"You receive the entire processed script. Craft {suggestion_count} distinct visual suggestions "
            f"inspired by the whole narrative. Respond ONLY with JSON using the schema: "
            f'{{"suggestions": ["Show ...", ...]}}. Keep them concise and literal.'
        )
        scene_text = (
            f"Base: {base}\n\n"
            f"FULL SCRIPT:\n{full_script}\n\n"
            f"Generate {suggestion_count} numbered image ideas capturing different striking moments or moods. "
            f"Each suggestion must start with 'Show...'."
        )
        response = ask_model(full_prompt, scene_text)
        suggestions = parse_json_suggestions(response)
        if not suggestions:
            update_stage(base, "suggestions", "error: modelo não retornou sugestões")
            return
        if len(suggestions) < suggestion_count:
            buffered = suggestions.copy()
            while len(suggestions) < suggestion_count:
                suggestions.extend(buffered)
            suggestions = suggestions[:suggestion_count]
        else:
            suggestions = suggestions[:suggestion_count]

        total = len(suggestions)
        P = max(1, len(chosen_profiles))
        base_chunk = total // P
        remainder = total % P
        scene_offset = 0

        for idx, prof_name in enumerate(chosen_profiles):
            share = base_chunk + (1 if idx < remainder else 0)
            if share <= 0:
                continue
            subset = suggestions[scene_offset : scene_offset + share]
            start_scene = scene_offset + 1
            end_scene = start_scene + len(subset) - 1
            desc = f"{base}__{prof_name} ({start_scene}-{end_scene})"
            out_path = base_out_dir / f"{base}__{prof_name}.txt"
            with open(out_path, "w", encoding="utf-8") as f_out:
                for offset, suggestion in enumerate(
                    tqdm(subset, desc=desc, total=len(subset), leave=False),
                    start=0,
                ):
                    scene_number = start_scene + offset
                    block = [
                        f"Scene {scene_number}",
                        f"Suggestion: {suggestion.strip()}",
                        "",
                    ]
                    f_out.write("\n".join(block) + "\n")
            scene_offset += share

        update_stage(
            base,
            "suggestions",
            "done",
            extra={
                "mode": "full_script",
                "total_suggestions": total,
                "requested_suggestions": suggestion_count,
                "scenes": total,
                "group_size": 1,
            },
        )
        print(f"[OK] {base} → {total} sugestões globais concluídas.")

    except Exception as err:  # pragma: no cover - defensive
        update_stage(base, "suggestions", f"error: {err}")
        print(f"[ERRO] {base}: {err}")


# ==========================
# PER-LINE MODE
# ==========================
def process_base(
    base: str,
    group_size: int,
    chosen_profiles: list[str],
    target_suggestions: int | None = None,
) -> None:
    ensure_entry(base)
    base_out_dir = OUTPUT_DIR / base
    base_out_dir.mkdir(parents=True, exist_ok=True)

    update_stage(base, "suggestions", "in_progress")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        sentences, txt_path = read_processed_sentences(base)
        if txt_path is None:
            update_stage(base, "suggestions", "error: txt processado não encontrado")
            return
        if not sentences:
            update_stage(base, "suggestions", "error: txt processado vazio")
            return

        prompt_core = load_text(PROMPT_PATH)
        full_prompt = (
            f"{prompt_core}\n\n"
            f"Generate one simple visual suggestion for each line below. "
            f"Keep it concise and literal, starting with 'Show...'"
        )

        scenes = group_lines(sentences, group_size)
        total_available = len(scenes)
        if total_available == 0:
            update_stage(base, "suggestions", "error: sem cenas após agrupamento")
            return
        if target_suggestions and target_suggestions > 0:
            target = target_suggestions
        else:
            target = total_available
        if target <= total_available:
            scenes = scenes[:target]
        else:
            repeated: list[str] = []
            while len(repeated) < target:
                repeated.extend(scenes)
            scenes = repeated[:target]
        total = len(scenes)

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
            for _ in range(1, P):
                start = end + 1
                end = start + base_chunk - 1
                ranges.append((start, end))

        for prof_name, (start_idx, end_idx) in zip(chosen_profiles, ranges):
            if start_idx > end_idx:
                continue

            out_path = base_out_dir / f"{base}__{prof_name}.txt"
            done_sub = detect_completed_scenes(out_path)
            mode = "a" if done_sub > 0 else "w"

            with open(out_path, mode, encoding="utf-8") as f_out:
                for j, scene_idx in enumerate(
                    tqdm(
                        range(start_idx, end_idx + 1),
                        desc=f"{base}__{prof_name} ({start_idx}-{end_idx})",
                        initial=done_sub,
                        total=(end_idx - start_idx + 1),
                    ),
                    start=1,
                ):
                    if j <= done_sub:
                        continue

                    scene_text = scenes[scene_idx - 1]
                    max_retries = 3
                    for attempt in range(1, max_retries + 1):
                        try:
                            suggestion = ask_model(full_prompt, scene_text)
                            if "[ERRO AO GERAR" in suggestion or "Request timed out" in suggestion:
                                raise RuntimeError("Modelo retornou erro interno")
                            final_suggestion = suggestion.strip()
                            break
                        except Exception as err:
                            if attempt < max_retries:
                                print(
                                    f"⚠️ Cena {scene_idx}: tentativa {attempt}/{max_retries} falhou ({err}), repetindo..."
                                )
                                continue
                            else:
                                print(f"❌ Cena {scene_idx}: erro persistente ({err})")
                                final_suggestion = f"[ERRO AO GERAR: {err}]"

                    block = [
                        f"Scene {scene_idx}",
                        f"Suggestion: {final_suggestion}",
                        "",
                    ]
                    f_out.write("\n".join(block) + "\n")
                    f_out.flush()

        extra_info = {"scenes": total, "group_size": group_size}
        if target_suggestions and target_suggestions > 0:
            extra_info["requested_suggestions"] = target_suggestions
        update_stage(base, "suggestions", "done", extra=extra_info)
        print(f"[OK] {base} → dividido entre {len(chosen_profiles)} perfil(is) (cenas: {total}, group={group_size})")

    except Exception as err:  # pragma: no cover - defensive
        update_stage(base, "suggestions", f"error: {err}")
        print(f"[ERRO] {base}: {err}")


# ==========================
# MAIN
# ==========================
def main() -> None:
    try:
        ensure_manifest_for_inbox()

        args = [a for a in sys.argv[1:] if not a.startswith("-")]
        candidates = list_ready_for_suggestions()
        if not candidates:
            print("Nenhum arquivo pendente para sugestões.")
            return

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
                    selected = [candidates[i - 1] for i in idxs if 1 <= i <= len(candidates)]
                except Exception:
                    print("❌ Entrada inválida.")
                    return

        sentence_counts: dict[str, int | None] = {}
        total_sentences = 0
        print("\n📊 Sentenças por arquivo:")
        for base in selected:
            count, _ = count_sentences_for_base(base)
            sentence_counts[base] = count
            if count is None:
                print(f" - {base}: TXT processado não localizado")
            else:
                print(f" - {base}: {count} sentenças")
                total_sentences += count
        if total_sentences == 0:
            print("⚠️ Não consegui contar sentenças em nenhum arquivo válido.")

        mode_raw = input("➡️ Modo? (1 = sugestões globais, 2 = padrão por falas | ENTER = 2): ").strip()
        use_global_mode = mode_raw == "1"
        group_size = 1
        global_suggestions = 5
        target_suggestions = None

        if use_global_mode:
            try:
                raw = input("➡️ Quantas imagens globais por base? (ENTER = 5): ").strip()
                global_suggestions = max(1, int(raw) if raw else 5)
            except ValueError:
                global_suggestions = 5
            print(f"\n🎯 Cada base receberá {global_suggestions} sugestões inspiradas no texto completo.")
        else:
            try:
                g = input("➡️ Quantas falas por cena? (ENTER = 1): ").strip()
                group_size = max(1, int(g) if g else 1)
            except ValueError:
                group_size = 1

            print("\n🎯 Cenas a processar (por arquivo):")
            for base in selected:
                count = sentence_counts.get(base)
                if not count:
                    print(f" - {base}: não será processado (sem sentenças)")
                    continue
                total_scenes = (count + group_size - 1) // group_size
                print(f" - {base}: {total_scenes} cenas (group={group_size})")
            raw_target = input("➡️ Total de sugestões por base? (ENTER = usar todas as cenas): ").strip()
            if raw_target:
                try:
                    target_suggestions = max(1, int(raw_target))
                except ValueError:
                    target_suggestions = None

        profiles = list_profiles()
        chosen_profiles = choose_profiles(profiles)

        for base in selected:
            if use_global_mode:
                process_base_full_script(base, global_suggestions, chosen_profiles)
            else:
                process_base(base, group_size, chosen_profiles, target_suggestions)
    finally:
        ring_bell("✅ Finalizado processamento das bases selecionadas.")


if __name__ == "__main__":
    main()
