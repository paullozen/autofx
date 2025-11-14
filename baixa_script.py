import os
import re
from dotenv import load_dotenv
from notion_client import Client
from notion_utils import normalize_notion_id
from paths import TXT_DOWNLOADS_DIR

# ==========================
# CONFIG
# ==========================
load_dotenv()
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = normalize_notion_id(os.getenv("NOTION_DATABASE_ID"))

if not NOTION_TOKEN or not DATABASE_ID:
    raise RuntimeError("Missing NOTION_TOKEN or NOTION_DATABASE_ID in environment.")

notion = Client(auth=NOTION_TOKEN)


def query_database(database_id: str, **kwargs):
    if hasattr(notion.databases, "query"):
        return notion.databases.query(database_id=database_id, **kwargs)
    return notion.request(
        path=f"databases/{database_id}/query",
        method="POST",
        body=kwargs,
    )
OUTPUT_DIR = TXT_DOWNLOADS_DIR

# ==========================
# HELPERS
# ==========================
def sanitize_filename(filename: str) -> str:
    """Remove caracteres especiais não permitidos no Windows"""
    # Caracteres não permitidos no Windows: < > : " / \ | ? *
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '', filename)
    # Remove espaços múltiplos e espaços nas extremidades
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    # Evita nomes reservados do Windows
    reserved = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 
                'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
    if sanitized.upper() in reserved:
        sanitized = f"_{sanitized}"
    return sanitized

# ==========================
# NOTION FUNCTIONS
# ==========================
def get_notion_entries_by_canal():
    """Busca páginas onde 'canal' é vazio ou 'Seed'"""
    pages = []
    query = query_database(
        DATABASE_ID,
        filter={
            "or": [
                {
                    "property": "Canal",
                    "select": {"is_empty": True}
                },
                {
                    "property": "Canal",
                    "select": {"equals": "Seed"}
                }
            ]
        }
    )

    for page in query["results"]:
        title_prop = page["properties"]["Title"]["title"]
        title = "".join([t["plain_text"] for t in title_prop]) or f"page_{page['id'][:6]}"
        pages.append({
            "id": page["id"],
            "title": title
        })
    return pages


def get_script_from_page(page_id):
    """Pega o conteúdo do campo 'Script' (Rich Text)"""
    page = notion.pages.retrieve(page_id=page_id)
    prop = page["properties"].get("Script", {})
    if "rich_text" in prop:
        text = "".join([t["plain_text"] for t in prop["rich_text"]])
        return text.strip()
    return ""


def download_scripts():
    """Faz download de todos os scripts com canal vazio ou 'Seed'"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    entries = get_notion_entries_by_canal()
    if not entries:
        print("Nenhum script encontrado com 'canal' vazio ou 'Seed'.")
        return

    print(f"\n📥 Encontrados {len(entries)} script(s):\n")
    for i, e in enumerate(entries, start=1):
        print(f"{i}. {e['title']}")

    choice = input("\nDigite o número para baixar (ou 0 para baixar todos): ").strip()
    
    if not choice:
        print("Operação cancelada.")
        return

    if choice == "0":
        print("\n⬇️ Baixando todos os scripts...\n")
        for entry in entries:
            script_content = get_script_from_page(entry["id"])
            if script_content:
                safe_title = sanitize_filename(entry['title'])
                txt_path = OUTPUT_DIR / f"{safe_title}.txt"
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(script_content)
                print(f"✅ {safe_title}.txt")
            else:
                print(f"⚠️  {entry['title']} - Script vazio, pulado")
        return

    try:
        idx = int(choice)
        if idx < 1 or idx > len(entries):
            print("Número inválido.")
            return
    except ValueError:
        print("Entrada inválida.")
        return

    selected = entries[idx - 1]
    script_content = get_script_from_page(selected["id"])
    
    if not script_content:
        print(f"⚠️  Script vazio para '{selected['title']}'")
        return

    safe_title = sanitize_filename(selected['title'])
    txt_path = OUTPUT_DIR / f"{safe_title}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(script_content)

    print(f"\n✅ Download concluído!")
    print(f"📁 Arquivo: {txt_path.resolve()}")


if __name__ == "__main__":
    download_scripts()
