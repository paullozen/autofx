# create_chrome_profile.py
import asyncio
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright

# ==========================
# CONFIG
# ==========================
ROOT           = Path(__file__).resolve().parent
PROFILE_FOLDER = ROOT / "chrome_profiles"
START_URLS = [
    # Abra direto o ImageFX (vai pedir login Google)
    "https://labs.google/fx/tools/image-fx",
    # Fallbacks úteis se preferir autenticar por aqui
    "https://accounts.google.com/",
    "https://www.google.com/",
]


# ==========================
# HELPERS
# ==========================
def list_profiles() -> list[str]:
    if not PROFILE_FOLDER.exists():
        return []
    return sorted([p.name for p in PROFILE_FOLDER.iterdir() if p.is_dir()])

def sanitize_name(name: str) -> str:
    name = name.strip().replace("\\", "_").replace("/", "_").replace(":", "_")
    name = name.replace("*", "_").replace("?", "_").replace("\"", "_")
    name = name.replace("<", "_").replace(">", "_").replace("|", "_")
    return name or datetime.now().strftime("profile_%Y%m%d_%H%M%S")

def ensure_profile_dir(profile_name: str) -> Path:
    """
    Cria pasta chrome_profiles/<profile_name>/Default e remove possíveis locks.
    Retorna o caminho de user_data_dir (a pasta do perfil).
    """
    PROFILE_FOLDER.mkdir(parents=True, exist_ok=True)
    user_data_dir = PROFILE_FOLDER / profile_name
    default_dir = user_data_dir / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)

    # Remove locks (ajuda no Windows)
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = default_dir / lock_name
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    return user_data_dir


# ==========================
# CORE
# ==========================
async def create_profile_interactive() -> str:
    """
    Cria um novo perfil persistente do Chrome e abre uma janela
    para que você faça login. Mantém a janela aberta até você pressionar ENTER.
    Retorna o nome do perfil criado.
    """
    existing = list_profiles()
    if existing:
        print("Perfis já existentes:")
        for i, name in enumerate(existing, 1):
            print(f"  {i}. {name}")
        print()

    raw = input("🆕 Nome do novo perfil (ENTER sugere automático): ").strip()
    profile_name = sanitize_name(raw) if raw else datetime.now().strftime("profile_%Y%m%d_%H%M%S")

    if profile_name in existing:
        print(f"⚠️ Já existe um perfil chamado '{profile_name}'. Vou acrescentar um sufixo de data/hora.")
        profile_name = f"{profile_name}_{datetime.now().strftime('%H%M%S')}"

    user_data_dir = ensure_profile_dir(profile_name)
    print(f"✅ Pasta do perfil: {user_data_dir}")

    async with async_playwright() as pw:
        # Abre Chrome com o perfil persistente
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run", "--no-default-browser-check",
                "--disable-infobars",
            ],
        )

        # Anti-detections simples
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            if (!window.chrome) window.chrome = { runtime: {} };
        """)

        page = await context.new_page()
        # Tenta abrir o ImageFX primeiro (vai pedir login do Google)
        for url in START_URLS:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                break
            except Exception:
                pass

        print("\n✨ Janela aberta. Faça login na sua conta do Google (e no ImageFX, se quiser).")
        print("   Quando terminar, volte ao terminal e pressione ENTER para fechar a janela.\n")

        # Mantém o Chrome aberto até ENTER no terminal
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, input, "Pressione ENTER para encerrar o navegador… ")
        except KeyboardInterrupt:
            pass

        await context.close()

    print(f"🎉 Perfil '{profile_name}' criado/pronto para uso.")
    return profile_name


def main():
    asyncio.run(create_profile_interactive())


if __name__ == "__main__":
    main()
