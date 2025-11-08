# make_and_render.py (OpenCV, com ajuste automático de duração por imagem + seleção manual)
import json
import shutil
from pathlib import Path
from typing import Tuple, Optional
import cv2
import numpy as np

from manifesto import load_manifest, update_stage

# ======================
# CONFIG
# ======================
SRT_DIR        = Path("scripts/srt_outputs")
TIMELINE_DIR   = Path("scripts/timelines")
IMGS_DIR       = Path("imgs_output")
OUTPUT_DIR     = Path("render_output")
IMG_SUGGESTIONS_DIR = Path("scripts/img_suggestions")
AUDIO_DIR      = Path("audio")
VIDEOS_DIR     = Path("videos")
TXT_INBOX      = Path("scripts/txt_inbox")
TXT_PROCESSED  = Path("scripts/txt_processed")

FPS = 30  # FPS fixo do vídeo
FOURCCS_TRY = ["mp4v", "avc1", "X264", "H264", "MJPG"]

# make sure output directories exist
for d in (TIMELINE_DIR, OUTPUT_DIR, TXT_PROCESSED):
    d.mkdir(parents=True, exist_ok=True)

# ======================
# HELPERS
# ======================
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

def merge_timeline_by_images(base: str, scenes: list):
    """
    Ajusta o timeline automaticamente com base na quantidade de imagens.
    Se há menos imagens que cenas SRT, agrupa as falas e soma suas durações.
    """
    img_root = IMGS_DIR / base / "_01"
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

    print(f"🔁 {base}: ajustando durações ({num_scenes} falas → {num_imgs} imagens, ~{group_size} falas/img)")

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

def try_build_timeline(base: str) -> Optional[Path]:
    """Cria ou atualiza o timeline.json conforme o SRT e imagens."""
    srt_path = SRT_DIR / f"{base}.srt"
    timeline_path = TIMELINE_DIR / f"{base}_timeline.json"

    if not srt_path.exists() and not timeline_path.exists():
        print(f"❌ Sem SRT e sem timeline para {base}")
        return None

    if not timeline_path.exists():
        print(f"📝 Construindo timeline para {base} (a partir do SRT)...")
        scenes = parse_srt(srt_path)
        merged = merge_timeline_by_images(base, scenes)
        data = {"base": base, "scenes": merged}
        timeline_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✅ Timeline salva: {timeline_path}")
        return timeline_path

    try:
        data = json.loads(timeline_path.read_text(encoding="utf-8"))
        scenes = data.get("scenes", [])
        merged = merge_timeline_by_images(base, scenes)
        timeline_path.write_text(json.dumps({"base": base, "scenes": merged}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"🩹 Timeline atualizada: {timeline_path}")
        return timeline_path
    except Exception as e:
        print(f"⚠️ Falha ao ler timeline existente ({timeline_path}): {e}")
        return None

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


def move_txt_to_processed(base: str):
    src = TXT_INBOX / f"{base}.txt"
    if not src.exists():
        return
    TXT_PROCESSED.mkdir(parents=True, exist_ok=True)
    dest = TXT_PROCESSED / src.name
    try:
        shutil.move(str(src), str(dest))
        print(f"📁 TXT movido para processados: {dest}")
    except Exception as exc:
        print(f"⚠️ Não foi possível mover {src} para {dest}: {exc}")


def move_final_video(temp_path: Optional[Path]) -> Optional[Path]:
    if not temp_path or not temp_path.exists():
        return None
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = VIDEOS_DIR / temp_path.name
    try:
        if dest.exists():
            dest.unlink()
        shutil.move(str(temp_path), str(dest))
        print(f"🎞️ Vídeo final movido para {dest}")
        return dest
    except Exception as exc:
        print(f"⚠️ Falha ao mover vídeo para {dest}: {exc}")
        return temp_path


def cleanup_base_artifacts(base: str, delivered_video: Optional[Path]):
    """Remove pastas e arquivos intermediários relacionados ao base."""
    dir_candidates = [
        IMGS_DIR / base,
        IMG_SUGGESTIONS_DIR / base,
    ]
    for d in dir_candidates:
        if d.exists():
            try:
                shutil.rmtree(d)
                print(f"🧹 Pasta removida: {d}")
            except Exception as exc:
                print(f"⚠️ Falha ao remover pasta {d}: {exc}")

    delivered_resolved = delivered_video.resolve() if delivered_video else None
    file_candidates = [
        TIMELINE_DIR / f"{base}_timeline.json",
        SRT_DIR / f"{base}.srt",
        OUTPUT_DIR / f"{base}.mp4",
        AUDIO_DIR / f"{base}.mp3",
    ]
    for file_path in file_candidates:
        if not file_path.exists():
            continue
        if delivered_resolved and file_path.resolve() == delivered_resolved:
            continue
        try:
            file_path.unlink()
            print(f"🗑️ Arquivo removido: {file_path}")
        except Exception as exc:
            print(f"⚠️ Falha ao remover arquivo {file_path}: {exc}")

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

# ======================
# RENDER
# ======================
def render_video(base: str, timeline_path: Path):
    out_path = OUTPUT_DIR / f"{base}.mp4"

    try:
        data = json.loads(timeline_path.read_text(encoding="utf-8"))
        scenes = data.get("scenes", [])

        if not scenes:
            print(f"⚠️ Timeline vazia para {base}")
            update_stage(base, "video", "error")
            return

        size = first_valid_frame_size(scenes)
        if not size:
            print(f"⚠️ Nenhuma imagem válida encontrada em {base}")
            update_stage(base, "video", "error")
            return

        writer = open_writer(out_path, size)
        if writer is None:
            print("❌ Não foi possível abrir VideoWriter.")
            update_stage(base, "video", "error")
            return

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
        update_stage(base, "video", "done")
        return out_path

    except Exception as e:
        print(f"❌ Erro ao gerar vídeo para {base}: {e}")
        update_stage(base, "video", "error")
        return None

# ======================
# MAIN
# ======================
def main():
    mf = load_manifest()
    selected_bases = select_bases_with_images_done(mf)

    if not selected_bases:
        return

    for base in selected_bases:
        timeline_path = try_build_timeline(base)
        if not timeline_path:
            continue
        update_stage(base, "timeline", "done")
        update_stage(base, "video", "in_progress")
        tmp_video = render_video(base, timeline_path)
        final_video = move_final_video(tmp_video) if tmp_video else None
        move_txt_to_processed(base)
        cleanup_base_artifacts(base, final_video)

if __name__ == "__main__":
    main()
