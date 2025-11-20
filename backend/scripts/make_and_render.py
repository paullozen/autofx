# make_and_render.py (OpenCV, com ajuste automático de duração por imagem + seleção manual)
import json
from pathlib import Path
from typing import Tuple, Optional
import cv2
import numpy as np

from manifesto import load_manifest, update_stage
from alerts import ring_bell
from paths import (
    SRT_OUTPUT_DIR,
    TIMELINES_DIR,
    IMG_OUTPUT_DIR,
    RENDER_OUTPUT_DIR,
)

# ======================
# CONFIG
# ======================
SRT_DIR        = SRT_OUTPUT_DIR
TIMELINE_DIR   = TIMELINES_DIR
IMGS_DIR       = IMG_OUTPUT_DIR
OUTPUT_DIR     = RENDER_OUTPUT_DIR

FPS = 30  # FPS fixo do vídeo
FOURCCS_TRY = ["mp4v", "avc1", "X264", "H264", "MJPG"]

# make sure output directories exist
for d in (TIMELINE_DIR, OUTPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ======================
# HELPERS
# ======================
def list_image_variants(base: str) -> list[str]:
    """Return sorted list of variant folders (e.g., _01, _02) inside imgs_output/<base>."""
    root = IMGS_DIR / base
    if not root.exists():
        return []
    variants = [p.name for p in root.iterdir() if p.is_dir()]

    def sort_key(name: str):
        digits = "".join(ch for ch in name if ch.isdigit())
        return (int(digits) if digits else 0, name)

    return sorted(variants, key=sort_key)


def imread_u8(path_str: str):
    try:
        data = np.fromfile(path_str, dtype=np.uint8)
        if data.size == 0:
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None

def ts_to_sec(ts: str) -> float:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

def parse_srt(srt_path: Path):
    """Lê o .srt e retorna lista com tempos e durações."""
    scenes = []
    content = srt_path.read_text(encoding="utf-8")
    blocks = content.strip().split("\n\n")
    for idx, block in enumerate(blocks, start=1):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        times = lines[1]
        if "-->" not in times:
            continue
        start, end = times.split("-->")
        start_s, end_s = ts_to_sec(start.strip()), ts_to_sec(end.strip())
        scenes.append({
            "scene": idx,
            "start": start_s,
            "end": end_s,
            "duration": round(max(0.01, end_s - start_s), 3),
            "file": None
        })
    return scenes

def merge_timeline_by_images(base: str, scenes: list, variant: str):
    """
    Ajusta o timeline automaticamente com base na quantidade de imagens.
    Se há menos imagens que cenas SRT, agrupa as falas e soma suas durações.
    """
    img_root = IMGS_DIR / base / variant
    imgs = sorted(img_root.glob("*.jpg"))

    if not imgs or not scenes:
        return scenes

    num_imgs = len(imgs)
    num_scenes = len(scenes)
    group_size = max(1, round(num_scenes / num_imgs))

    if group_size <= 1 and num_imgs == num_scenes:
        for i, s in enumerate(scenes):
            if i < len(imgs):
                s["file"] = str(imgs[i])
        return scenes

    print(f"🔁 {base}{variant}: ajustando durações ({num_scenes} falas → {num_imgs} imagens, ~{group_size} falas/img)")

    merged = []
    for i in range(0, num_scenes, group_size):
        block = scenes[i:i+group_size]
        if not block:
            continue
        start = block[0]["start"]
        end = block[-1]["end"]
        duration = end - start
        img_path = imgs[len(merged)] if len(merged) < len(imgs) else None
        merged.append({
            "scene": len(merged) + 1,
            "start": start,
            "end": end,
            "duration": duration,
            "file": str(img_path) if img_path else None
        })
    return merged

def try_build_timeline(base: str, variant: str) -> Optional[Path]:
    """Cria ou atualiza o timeline.json conforme o SRT e imagens."""
    srt_path = SRT_DIR / f"{base}.srt"
    timeline_path = TIMELINE_DIR / f"{base}{variant}_timeline.json"

    if not srt_path.exists() and not timeline_path.exists():
        print(f"❌ Sem SRT e sem timeline para {base}{variant}")
        return None

    scenes_source = []
    if timeline_path.exists():
        try:
            data = json.loads(timeline_path.read_text(encoding="utf-8"))
            scenes_source = data.get("scenes", [])
        except Exception as e:
            print(f"⚠️ Falha ao ler timeline existente ({timeline_path}): {e}")
            scenes_source = []

    if not scenes_source:
        if not srt_path.exists():
            print(f"❌ SRT ausente para {base}, não foi possível construir timeline {variant}.")
            return None
        scenes_source = parse_srt(srt_path)
        print(f"📝 Construindo timeline para {base}{variant} (a partir do SRT)...")

    merged = merge_timeline_by_images(base, scenes_source, variant)
    data = {"base": base, "variant": variant, "scenes": merged}
    timeline_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Timeline salva/atualizada: {timeline_path}")
    return timeline_path

def letterbox(img: np.ndarray, target_wh: Tuple[int, int]) -> np.ndarray:
    th, tw = target_wh[1], target_wh[0]
    h, w = img.shape[:2]
    scale = min(tw / w, th / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((th, tw, 3), dtype=np.uint8)
    y0 = (th - nh) // 2
    x0 = (tw - nw) // 2
    canvas[y0:y0+nh, x0:x0+nw] = resized
    return canvas

def first_valid_frame_size(scenes) -> Optional[Tuple[int, int]]:
    for s in scenes:
        path = s.get("file")
        if path and Path(path).exists():
            img = imread_u8(str(path))
            if img is not None:
                h, w = img.shape[:2]
                return (w, h)
    return None

def open_writer(out_path: Path, size: Tuple[int, int]):
    for fourcc_name in FOURCCS_TRY:
        fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
        vw = cv2.VideoWriter(str(out_path), fourcc, FPS, size)
        if vw.isOpened():
            print(f"🎞️  Writer OK: {fourcc_name}, {size[0]}x{size[1]} @ {FPS}fps → {out_path}")
            return vw
        else:
            vw.release()
    return None


# ======================
# SELEÇÃO
# ======================
def select_bases_with_images_done(mf: dict):
    """Lista bases com 'images':'done' e deixa o usuário escolher quais renderizar."""
    ready = [b for b, info in mf.items() if info.get("images") == "done" and (info.get("timeline") != "done" or info.get("video") != "done")]
    if not ready:
        print("📭 Nenhuma base com 'images: done' encontrada.")
        return []

    print("\n📸 Bases prontas para renderização:")
    for i, base in enumerate(ready, 1):
        print(f"[{i}] {base}")

    selected = input("\nDigite os números das bases que deseja renderizar (ex: 1,3,5) ou ENTER para cancelar: ").strip()
    if not selected:
        print("🚫 Nenhuma base selecionada. Abortando.")
        return []

    try:
        indices = [int(x.strip()) for x in selected.split(",")]
        chosen = [ready[i - 1] for i in indices if 1 <= i <= len(ready)]
        print(f"\n✅ Selecionadas para render: {chosen}\n")
        return chosen
    except Exception:
        print("⚠️ Entrada inválida. Abortando.")
        return []


def choose_variants_for_base(base: str, variants: list[str]) -> list[str]:
    """
    Previously interactive; now automatically processes every variant found.
    """
    if not variants:
        return []
    print(f"\n🎨 {base}: usando todas as {len(variants)} variações detectadas ({', '.join(variants)})")
    return variants[:]

# ======================
# RENDER
# ======================
def render_video(base: str, timeline_path: Path, variant: str) -> bool:
    out_path = OUTPUT_DIR / f"{base}{variant}.mp4"

    try:
        data = json.loads(timeline_path.read_text(encoding="utf-8"))
        scenes = data.get("scenes", [])

        if not scenes:
            print(f"⚠️ Timeline vazia para {base}{variant}")
            return False

        size = first_valid_frame_size(scenes)
        if not size:
            print(f"⚠️ Nenhuma imagem válida encontrada em {base}{variant}")
            return False

        writer = open_writer(out_path, size)
        if writer is None:
            print("❌ Não foi possível abrir VideoWriter.")
            return False

        total_frames = 0
        for s in scenes:
            img_path = s.get("file")
            dur = float(s.get("duration", 1.0) or 1.0)
            frames_this = max(1, int(round(dur * FPS)))

            if not img_path or not Path(img_path).exists():
                frame = np.zeros((size[1], size[0], 3), dtype=np.uint8)
            else:
                img = imread_u8(img_path)
                frame = letterbox(img, size) if img is not None else np.zeros((size[1], size[0], 3), dtype=np.uint8)

            for _ in range(frames_this):
                writer.write(frame)
            total_frames += frames_this

        writer.release()
        print(f"✅ Vídeo finalizado ({total_frames} frames): {out_path}")
        return True

    except Exception as e:
        print(f"❌ Erro ao gerar vídeo para {base}{variant}: {e}")
        return False

# ======================
# MAIN
# ======================
def main():
    try:
        mf = load_manifest()
        selected_bases = select_bases_with_images_done(mf)

        if not selected_bases:
            return

        for base in selected_bases:
            variants = list_image_variants(base)
            if not variants:
                print(f"⚠️ Nenhuma variação de imagens encontrada em {IMGS_DIR / base}.")
                update_stage(base, "timeline", "error")
                update_stage(base, "video", "error")
                continue

            chosen_variants = choose_variants_for_base(base, variants)
            if not chosen_variants:
                continue

            update_stage(base, "timeline", "in_progress")
            update_stage(base, "video", "in_progress")

            timeline_ok = True
            video_ok = True

            for variant in chosen_variants:
                print(f"\n🎞️ Processando {base}{variant}...")
                timeline_path = try_build_timeline(base, variant)
                if not timeline_path:
                    timeline_ok = False
                    video_ok = False
                    continue
                success = render_video(base, timeline_path, variant)
                if not success:
                    video_ok = False

            update_stage(base, "timeline", "done" if timeline_ok else "error")
            update_stage(base, "video", "done" if video_ok else "error")
    finally:
        ring_bell("✅ Render finalizado.")

if __name__ == "__main__":
    main()
