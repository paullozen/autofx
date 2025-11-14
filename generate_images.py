# generate_images_pw.py — auto-perfis pelos arquivos de sugestão
from tqdm import tqdm
import platform
import sys
import json
import asyncio
import base64
import random
import time
from pathlib import Path
from typing import List, Dict
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from collections import defaultdict
from profiles import list_profiles, resolve_user_data_dir
from paths import MANIFEST_PATH, IMG_SUGGESTIONS_DIR, IMG_OUTPUT_DIR

# ====== PASTAS / CONSTANTES ======
ROOT = Path(__file__).resolve().parent
PROFILE_FOLDER = ROOT / "chrome_profiles"
SUGGESTIONS_DIR = IMG_SUGGESTIONS_DIR
IMG_OUT_DIR = IMG_OUTPUT_DIR
# PATTERN_PATH = "prompts/SJ_PATTERN_chalk.txt"
PATTERN_PATH = "prompts/PSYCHO_PATTERN.txt"
# PATTERN_PATH = "prompts/JS_PATTERN.txt"
# PATTERN_PATH = "prompts/MOT_PATTERN.txt"

IMAGEFX_URL = "https://labs.google/fx/tools/image-fx"
SUFFIXES = ["_01"]  # salvar apenas _01

def load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

ALL_ERRORS = defaultdict(lambda: {"total": 0, "cenas": []})
# pattern = load_text(PATTERN_PATH)
# pattern='An off-white stick figure with a solid off-white head, drawn with clean lines. The main character has facial experession and wears a black cap and a black jacket layered over a white hoodie, with realistic folds and subtle shading.'
pattern=''

def report_errors(base: str):
    total = sum(data["total"] for data in ALL_ERRORS.values())
    if total == 0:
        return
    print(f"\n⚠️ {base}: {total} falha(s) ao gerar imagens.")
    for profile, data in ALL_ERRORS.items():
        if data["total"]:
            sample = ", ".join(data["cenas"][:5])
            suffix = "..." if len(data["cenas"]) > 5 else ""
            print(f"   • Perfil {profile}: {data['total']} cenas (ex.: {sample}{suffix})")
    ALL_ERRORS.clear()


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def save_manifest(mf: dict):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(mf, indent=2, ensure_ascii=False), encoding="utf-8")


def set_images_status(mf: dict, base: str, status: str, images_saved: int | None = None):
    entry = mf.setdefault(base, {})
    entry["images"] = status
    if images_saved is not None:
        entry["images_saved"] = images_saved
    entry["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_manifest(mf)

# ==========================
# PROMPTS / SUGESTÕES
# ==========================


def parse_profile_suggestions(base: str) -> Dict[str, Dict[int, str]]:
    base_dir = SUGGESTIONS_DIR / base
    if not base_dir.exists():
        return {}

    result: Dict[str, Dict[int, str]] = {}
    for txt in sorted(base_dir.glob(f"{base}__*.txt")):
        name = txt.stem
        if "__" not in name:
            continue
        perfil = name.split("__", 1)[1]
        scene_map: Dict[int, str] = {}
        lines = txt.read_text(encoding="utf-8").splitlines()
        current_scene = None
        for line in lines:
            if line.startswith("Scene "):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    current_scene = int(parts[1])
                else:
                    current_scene = None
            elif line.startswith("Suggestion:"):
                if current_scene is not None:
                    prompt = line.split("Suggestion:", 1)[1].strip()
                    scene_map[current_scene] = prompt
                    current_scene = None
        if scene_map:
            result[perfil] = scene_map
    return result


def list_pending_bases_from_manifest() -> List[str]:
    mf = load_manifest()
    pending_bases = [b for b, info in mf.items() if info.get("suggestions") == 'done' and info.get("images") != 'done']

    for subdir in SUGGESTIONS_DIR.iterdir():
        if subdir.is_dir() and subdir.name not in mf:
            pending_bases.append(subdir.name)

    seen, unique = set(), []
    for b in pending_bases:
        if b not in seen:
            seen.add(b)
            unique.append(b)
    return unique

# ==========================
# DISCO (imagens salvas)
# ==========================


def expected_scene_paths(base: str, idx: int) -> list[Path]:
    scene = f"{idx:03}"
    root = IMG_OUT_DIR / base
    return [(root / suffix / f"{scene}.jpg") for suffix in SUFFIXES]


def is_scene_complete(base: str, idx: int) -> bool:
    return all(p.exists() for p in expected_scene_paths(base, idx))


def save_scene_images(base: str, scene_idx: int, b64_list: List[str]) -> int:
    scene = f"{scene_idx:03}"
    out_root = IMG_OUT_DIR / base
    out_root.mkdir(parents=True, exist_ok=True)
    saved = 0
    odd_positions = [i for i in range(1, len(b64_list) + 1, 2)]
    for pos_idx, pos in enumerate(odd_positions[:len(SUFFIXES)], start=0):
        suffix = SUFFIXES[pos_idx]
        folder = out_root / suffix
        folder.mkdir(parents=True, exist_ok=True)
        b64 = b64_list[pos - 1]
        try:
            (folder / f"{scene}.jpg").write_bytes(base64.b64decode(b64))
            saved += 1
        except Exception as e:
            print(f"⚠️ Falha ao salvar {scene}.jpg em {suffix}: {e}")
    return saved

# ==========================
# PLAYWRIGHT HELPERS
# ==========================


async def ensure_editor_ready(page):
    try:
        container = page.locator("div.sc-1004f4bc-4.fZKmcZ").first
        await container.wait_for(timeout=10000)
        await container.click()
        await container.click()
    except PWTimeout:
        pass
    textbox = page.locator("div[role='textbox'][contenteditable='true']").first
    await textbox.wait_for(timeout=15000)
    await textbox.click()
    await asyncio.sleep(0.25)
    await textbox.click()
    await asyncio.sleep(0.15)
    return textbox


async def move_caret_to_end(page):
    try:
        await page.keyboard.press("Control+End")
        await asyncio.sleep(0.05)
    except Exception:
        pass


async def send_prompt_and_collect(page, prompt_text: str, timeout_ms=90000) -> List[str]:
    await move_caret_to_end(page)
    await page.keyboard.insert_text(pattern + prompt_text)
    await asyncio.sleep(random.uniform(0.6, 1.6))
    await page.keyboard.press("Enter")

    imgs = page.locator("img[src^='data:image']")
    await imgs.first.wait_for(timeout=timeout_ms)
    b64_list = []
    count = await imgs.count()
    for i in range(count):
        src = await imgs.nth(i).get_attribute("src")
        if src and "," in src:
            b64_list.append(src.split(",", 1)[1])

    await page.keyboard.press("Control+A")
    await asyncio.sleep(0.15)
    await page.keyboard.press("Backspace")
    await asyncio.sleep(0.15)

    return b64_list

# ==========================
# WORKER
# ==========================


async def worker_task(worker_id: int, context, base: str, profile: str,
                      scene_map: Dict[int, str], q: asyncio.Queue, pbar):
    page = await context.new_page()
    await page.goto(IMAGEFX_URL, wait_until="domcontentloaded")
    await ensure_editor_ready(page)

    while True:
        idx = await q.get()
        if idx is None:
            q.task_done()
            break
        try:
            prompt = scene_map[idx]
            b64_list = await send_prompt_and_collect(page, prompt, timeout_ms=90000)
            if b64_list:
                save_scene_images(base, idx, b64_list)
                # atualização direta do manifesto — sem lock
                mf = load_manifest()
                current = int(mf.get(base, {}).get("images_saved") or 0)
                set_images_status(mf, base, "in_progress", images_saved=max(current, idx))
            pbar.update(1)
        except Exception as e:
            ALL_ERRORS[profile]["total"] += 1
            ALL_ERRORS[profile]["cenas"].append(f"{idx:03}")
        finally:
            q.task_done()
    await page.close()

async def process_profile(base: str,
                          profile: str,
                          ctx,
                          scene_map: Dict[int, str],
                          pendentes: list[int],
                          workers_per_profile: int,
                          position: int):
    # Fila por perfil
    q: asyncio.Queue = asyncio.Queue()
    for sid in pendentes:
        q.put_nowait(sid)

    # Barra por perfil
    pbar = tqdm(
        total=len(pendentes),
        desc=f"{base} / {profile}",
        position=position,
        leave=False,
        dynamic_ncols=True,
        ncols=100,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%]"
    )

    # Workers do perfil
    workers = [
        asyncio.create_task(
            worker_task(wid, ctx, base, profile, scene_map, q, pbar)
        )
        for wid in range(1, max(1, workers_per_profile) + 1)
    ]

    # Espera a fila esvaziar
    await q.join()

    # Manda sentinela para cada worker
    for _ in workers:
        q.put_nowait(None)

    # Aguarda workers
    await asyncio.gather(*workers, return_exceptions=True)

    # Fecha barra e browser DESTE perfil (libera RAM aqui)
    try:
        pbar.close()
    except Exception:
        pass
    await ctx.close()


# ==========================
# EXECUÇÃO POR BASE
# ==========================

async def run_for_base_with_profiles(pw, base: str, workers_per_profile: int):
    try:
        per_profile_scenes = parse_profile_suggestions(base)
        if not per_profile_scenes:
            print(f"⚠️ {base}: não encontrei arquivos '<base>__<perfil>.txt' em {SUGGESTIONS_DIR/base}")
            return

        available_profiles = set(list_profiles())
        chosen = [(p, scene_map) for p, scene_map in per_profile_scenes.items() if p in available_profiles]
        missing = [p for p in per_profile_scenes.keys() if p not in available_profiles]
        if missing:
            print(f"⚠️ Perfis inexistentes (ignorando): {missing}")
        if not chosen:
            print(f"❌ Nenhum perfil válido encontrado para {base}.")
            return

        pending_chosen = []
        for profile, scene_map in chosen:
            scene_ids = sorted(scene_map.keys())
            tem_pendencia = any(not is_scene_complete(base, sid) for sid in scene_ids)
            if tem_pendencia:
                pending_chosen.append((profile, scene_map))
            else:
                print(f"✅ {base} / perfil '{profile}': já concluído, não será aberto.")

        if not pending_chosen:
            mf_final = load_manifest()
            all_scene_ids = sorted({sid for _, m in chosen for sid in m.keys()})
            total = max(all_scene_ids) if all_scene_ids else 0
            set_images_status(mf_final, base, "done", images_saved=total)
            print(f"🏁 {base}: nada pendente em nenhum perfil. Marcado como done.")
            return

        mf = load_manifest()
        if base not in mf:
            mf[base] = {"images": "in_progress", "images_saved": 0}
            save_manifest(mf)
        elif mf[base].get("images") not in ("pending", "in_progress"):
            mf[base]["images"] = "in_progress"
            save_manifest(mf)

        # === ETAPA 1: abrir apenas perfis com pendências ===
        contexts = []
        for idx, (profile, _) in enumerate(pending_chosen):
            user_data_dir = resolve_user_data_dir(profile)
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=True,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-infobars",
                ],
            )
            await ctx.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                if (!window.chrome) window.chrome = { runtime: {} };
            """)
            contexts.append((profile, ctx))
            if idx < len(pending_chosen) - 1:
                await asyncio.sleep(1.0)

        # === ETAPA 2: imprimir pendências ===
        print("\n")
        print("=" * 60)
        print(f"🎬 RESUMO DE CENAS PENDENTES\n")
        all_pendentes = {}

        for (profile, ctx), (_, scene_map) in zip(contexts, pending_chosen):
            scene_ids = sorted(scene_map.keys())
            pendentes = [sid for sid in scene_ids if not is_scene_complete(base, sid)]
            if pendentes:
                all_pendentes[profile] = pendentes
                print(f"🎯 {base} / perfil '{profile}': {len(pendentes)} cenas pendentes "
                      f"(ex.: {pendentes[:10]}{' ...' if len(pendentes)>10 else ''})")

        if not all_pendentes:
            print(f"✅ {base}: nenhum perfil com pendências.")
            return

        # === ETAPA 3: criar progresso ===
        print("\n## PROGRESS:")
        print("-" * 60)

        supervisors = []
        position = 0
        for (profile, ctx), (_, scene_map) in zip(contexts, pending_chosen):
            pendentes = all_pendentes.get(profile)
            if not pendentes:
                continue
            supervisors.append(asyncio.create_task(
                process_profile(base, profile, ctx, scene_map, pendentes, workers_per_profile, position)
            ))
            position += 1

        print("-" * 60)

        # Cada perfil fecha seu próprio browser ao terminar
        await asyncio.gather(*supervisors, return_exceptions=True)

        all_scene_ids = sorted({sid for _, m in chosen for sid in m.keys()})
        if not all_scene_ids:
            return
        total = max(all_scene_ids)
        restam = [sid for sid in all_scene_ids if not is_scene_complete(base, sid)]
        mf_final = load_manifest()
        if not restam:
            set_images_status(mf_final, base, "done", images_saved=total)
            print(f"\n🏁 Concluído: {base} ({total}/{total})")
        else:
            maior = max([sid for sid in all_scene_ids if is_scene_complete(base, sid)], default=0)
            set_images_status(mf_final, base, "in_progress", images_saved=maior)
            print(f"\n⏸️ Parcial: {base} (faltando {len(restam)} cenas) — mantendo 'in_progress'")
    finally:
        report_errors(base)

# ==========================
# MAIN
# ==========================


async def main():
    bases = list_pending_bases_from_manifest()
    if not bases:
        print("📭 Nenhuma base pendente para imagens.")
        return

    print("\n🗂️ Bases disponíveis:")
    for i, b in enumerate(bases, 1):
        print(f"{i}. {b}")
    print("0. todos")

    raw = input("➡️ Selecione (ex: 2 3 ou '0' p/ todos): ").strip().lower()
    if raw in ("0", "todos"):
        selected = bases
    else:
        try:
            idxs = [int(x) for x in raw.split()]
            selected = [bases[i-1] for i in idxs if 1 <= i <= len(bases)]
        except Exception:
            print("❌ Entrada inválida.")
            return
        if not selected:
            print("❌ Nada selecionado.")
            return

    try:
        workers_per_profile = int(input("➡️ Abas por perfil? (sugestão 2): ").strip() or "2")
    except Exception:
        workers_per_profile = 2
    workers_per_profile = max(1, min(4, workers_per_profile))

    async with async_playwright() as pw:
        for base in selected:
            await run_for_base_with_profiles(pw, base, workers_per_profile)

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
    asyncio.run(main())
