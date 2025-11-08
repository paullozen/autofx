# manifesto.py
import json
import time
from pathlib import Path

MANIFEST_PATH = Path("scripts/manifesto.json")


# ==========================
# CORE LOAD/SAVE
# ==========================
def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def save_manifest(mf: dict):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(mf, indent=2, ensure_ascii=False), encoding="utf-8")


# ==========================
# HELPERS
# ==========================
def ensure_entry(base: str):
    mf = load_manifest()
    if base not in mf:
        mf[base] = {
            "txt": "ready",          # já existe o TXT na inbox
            "audio": "pending",
            "srt": "pending",        # legenda ainda não gerada
            "suggestions": "pending",# prompts ainda não gerados
            "images": "pending",     # imagens ainda não feitas
            "timeline": "pending",   # timeline JSON ainda não criado
            "video": "pending",      # render final ainda não feito
            "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "sentences": 0,
            "scenes": 0,
            "images_saved": 0,
            "group_size": 1
        }
        save_manifest(mf)
    return mf



def update_stage(base: str, stage: str, status: str, extra: dict | None = None):
    """
    Atualiza o status de um estágio específico da base.
    """
    mf = load_manifest()
    entry = mf.setdefault(base, {})
    entry[stage] = status
    if extra:
        entry.update(extra)
    entry["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_manifest(mf)


def set_stage(mf: dict, base: str, stage: str, status: str):
    """
    Atualiza status de forma inline (quando já tem o mf carregado).
    """
    entry = mf.setdefault(base, {})
    entry[stage] = status
    entry["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_manifest(mf)


