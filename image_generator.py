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
PATTERN_DIR = ROOT / "prompts"

IMAGEFX_URL = "https://labs.google/fx/tools/image-fx"
ALL_SUFFIXES = ["_01", "_02", "_03", "_04"]
SUFFIXES = ALL_SUFFIXES[:1]

def load_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def list_pattern_files() -> List[Path]:
    if not PATTERN_DIR.exists():
        return []
    return sorted([p for p in PATTERN_DIR.glob("*_PATTERN*.txt") if p.is_file()])


def select_pattern_text() -> str:
    pattern_files = list_pattern_files()
    if not pattern_files:
        print("⚠️ Nenhum arquivo *_PATTERN encontrado em prompts/.")
        return ""

    print("\n🎨 Patterns disponíveis:")
    for idx, path in enumerate(pattern_files, 1):
        print(f"{idx}. {path.name}")

    prompt = f"➡️ Escolha o pattern (1-{len(pattern_files)} | default 1): "
    raw = input(prompt).strip()
    try:
        choice = int(raw or "1")
    except Exception:
        choice = 1
    choice = max(1, min(len(pattern_files), choice))
    selected = pattern_files[choice - 1]

    try:
        return load_text(selected)
    except Exception as exc:
        print(f"⚠️ Falha ao carregar {selected.name}: {exc}")
        return ""

ALL_ERRORS = defaultdict(lambda: {"total": 0, "cenas": []})
# pattern = load_text(PATTERN_PATH)
# pattern='An off-white stick figure with a solid off-white head, drawn with clean lines. The main character has facial experession and wears a black cap and a black jacket layered over a white hoodie, with realistic folds and subtle shading.'
pattern=''

LAST_RETRY_DECISION: str | None = None
PROMPT_LOCK: asyncio.Lock | None = None

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


def prompt_retry_decision(base: str, profile: str, failed_ids: list[int]) -> bool:
    global LAST_RETRY_DECISION
    sample = ", ".join(f"{sid:03}" for sid in failed_ids[:5])
    suffix = "..." if len(failed_ids) > 5 else ""
    default_hint = ""
    if LAST_RETRY_DECISION:
        default_hint = f" [ENTER mantém '{LAST_RETRY_DECISION}']"
    prompt = (f"⚠️ {base}/{profile}: {len(failed_ids)} cenas falharam "
              f"(ex.: {sample}{suffix}). Repetir? (s/n){default_hint}: ")
    answer = input(prompt).strip().lower()
    if not answer and LAST_RETRY_DECISION:
        answer = LAST_RETRY_DECISION
    if answer in ("s", "sim", "y", "yes"):
        LAST_RETRY_DECISION = "s"
        return True
    if answer in ("n", "nao", "não", "no"):
        LAST_RETRY_DECISION = "n"
        return False
    if not answer:
        LAST_RETRY_DECISION = "n"
        return False
    LAST_RETRY_DECISION = answer
    return answer.startswith(("s", "y"))


async def ask_retry_decision(base: str, profile: str, failed_ids: list[int]) -> bool:
    global PROMPT_LOCK
    if PROMPT_LOCK is None:
        PROMPT_LOCK = asyncio.Lock()
    async with PROMPT_LOCK:
        return await asyncio.to_thread(prompt_retry_decision, base, profile, failed_ids)

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
                      scene_map: Dict[int, str], q: asyncio.Queue, pbar,
                      failures: list[int]):
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
            failures.append(idx)
        finally:
            q.task_done()
    await page.close()


async def execute_scene_batch(base: str,
                              profile: str,
                              ctx,
                              scene_map: Dict[int, str],
                              scene_ids: list[int],
                              workers_per_profile: int,
                              position: int,
                              desc_suffix: str) -> list[int]:
    if not scene_ids:
        return []

    q: asyncio.Queue = asyncio.Queue()
    for sid in scene_ids:
        q.put_nowait(sid)

    pbar = tqdm(
        total=len(scene_ids),
        desc=desc_suffix,
        position=position,
        leave=False,
        dynamic_ncols=True,
        ncols=100,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{percentage:3.0f}%]"
    )

    failures: list[int] = []
    workers = [
        asyncio.create_task(
            worker_task(wid, ctx, base, profile, scene_map, q, pbar, failures)
        )
        for wid in range(1, max(1, workers_per_profile) + 1)
    ]

    await q.join()
    for _ in workers:
        q.put_nowait(None)

    await asyncio.gather(*workers, return_exceptions=True)

    try:
        pbar.close()
    except Exception:
        pass

    return failures

async def process_profile(base: str,
                          profile: str,
                          ctx,
                          scene_map: Dict[int, str],
                          pendentes: list[int],
                          workers_per_profile: int,
                          position: int,
                          desc_suffix: str | None = None) -> list[int]:
    desc = desc_suffix or f"{base} / {profile}"
    await execute_scene_batch(
        base, profile, ctx, scene_map, pendentes, workers_per_profile, position, desc
    )
    return [sid for sid in pendentes if not is_scene_complete(base, sid)]


# ==========================
# EXECUÇÃO POR BASE
# ==========================

async def run_for_base_with_profiles(pw, base: str, workers_per_profile: int, headless: bool):
    profile_contexts = {}
    scene_maps = {}
    ordered_profiles: list[str] = []
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
        for idx, (profile, scene_map) in enumerate(pending_chosen):
            user_data_dir = resolve_user_data_dir(profile)
            ctx = await pw.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless,
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
            profile_contexts[profile] = ctx
            scene_maps[profile] = scene_map
            ordered_profiles.append(profile)
            if idx < len(pending_chosen) - 1:
                await asyncio.sleep(1.0)

        # === ETAPA 2: imprimir pendências ===
        print("\n")
        print("=" * 60)
        print(f"🎬 RESUMO DE CENAS PENDENTES\n")
        all_pendentes = {}

        for profile in ordered_profiles:
            scene_map = scene_maps[profile]
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
        profile_positions = {}
        active_profiles = [p for p in ordered_profiles if p in all_pendentes]
        for position, profile in enumerate(active_profiles):
            ctx = profile_contexts[profile]
            scene_map = scene_maps[profile]
            pendentes = all_pendentes[profile]
            profile_positions[profile] = position
            supervisors.append((profile, asyncio.create_task(
                process_profile(base, profile, ctx, scene_map, pendentes, workers_per_profile, position)
            )))

        print("-" * 60)

        results = await asyncio.gather(
            *(task for _, task in supervisors),
            return_exceptions=True
        )

        remaining_by_profile: dict[str, list[int]] = {}
        for (profile, _), result in zip(supervisors, results):
            if isinstance(result, Exception):
                print(f"❌ {base} / {profile}: erro durante processamento: {result}")
                remaining_by_profile[profile] = all_pendentes.get(profile, [])
            else:
                if result:
                    remaining_by_profile[profile] = result

        # === ETAPA 4: retries globais ===
        retry_round = 1
        while remaining_by_profile:
            normalized = {}
            for profile, ids in remaining_by_profile.items():
                unresolved = [sid for sid in ids if not is_scene_complete(base, sid)]
                if unresolved:
                    normalized[profile] = unresolved
            if not normalized:
                break

            retry_requests = {}
            for profile, unresolved in normalized.items():
                wants_retry = await ask_retry_decision(base, profile, unresolved)
                if wants_retry:
                    retry_requests[profile] = unresolved
            if not retry_requests:
                break

            retry_tasks = []
            for profile, retry_ids in retry_requests.items():
                ctx = profile_contexts.get(profile)
                scene_map = scene_maps.get(profile)
                if ctx is None or scene_map is None:
                    continue
                position = profile_positions.get(profile, len(profile_positions))
                desc = f"{base} / {profile} (retry #{retry_round})"
                retry_tasks.append((profile, asyncio.create_task(
                    process_profile(base, profile, ctx, scene_map, retry_ids, workers_per_profile, position, desc)
                )))

            if not retry_tasks:
                break

            retry_results = await asyncio.gather(
                *(task for _, task in retry_tasks),
                return_exceptions=True
            )
            remaining_by_profile = {}
            for (profile, _), result in zip(retry_tasks, retry_results):
                if isinstance(result, Exception):
                    print(f"❌ {base} / {profile}: erro durante retry: {result}")
                    remaining_by_profile[profile] = normalized.get(profile, [])
                elif result:
                    remaining_by_profile[profile] = result
            retry_round += 1

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
        for ctx in profile_contexts.values():
            try:
                await ctx.close()
            except Exception:
                pass
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

    try:
        total_images_raw = input("➡️ Total images to download? (Max: 4 | Default: 1): ").strip()
        total_images = int(total_images_raw or "1")
    except Exception:
        total_images = 1
    total_images = max(1, min(len(ALL_SUFFIXES), total_images))
    global SUFFIXES, pattern
    SUFFIXES = ALL_SUFFIXES[:total_images]
    pattern = select_pattern_text()

    headless_raw = input("➡️ Executar em modo headless? (ENTER = sim): ").strip().lower()
    headless = True
    if headless_raw in ("n", "nao", "não", "no", "false", "0"):
        headless = False

    async with async_playwright() as pw:
        for base in selected:
            await run_for_base_with_profiles(pw, base, workers_per_profile, headless)

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
