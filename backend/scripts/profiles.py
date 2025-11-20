"""Shared helpers for managing Chrome profile folders."""
from __future__ import annotations

from pathlib import Path
from typing import List

PROFILE_FOLDER = Path(__file__).resolve().parent / "chrome_profiles"


def list_profiles() -> List[str]:
    if not PROFILE_FOLDER.exists():
        return []
    return sorted([p.name for p in PROFILE_FOLDER.iterdir() if p.is_dir()])


def resolve_user_data_dir(profile_name: str) -> Path:
    profile_dir = PROFILE_FOLDER / profile_name
    default_dir = profile_dir / "Default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    default_dir.mkdir(parents=True, exist_ok=True)
    if profile_dir.name.lower() == "default" and (profile_dir / "Preferences").exists():
        profile_dir = profile_dir.parent
        default_dir = profile_dir / "Default"
        default_dir.mkdir(parents=True, exist_ok=True)
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock = default_dir / lock_name
        try:
            if lock.exists():
                lock.unlink()
        except Exception:
            pass
    return profile_dir


def choose_profiles(profiles: List[str]) -> List[str]:
    """
    Pergunta ao usuário quais perfis deseja usar. Retorna lista de nomes.
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
