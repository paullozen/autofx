import json
import os
import time
import re
import zipfile
from pathlib import Path
import googleapiclient.discovery
from dotenv import load_dotenv
from support_scripts.paths import COMMENTS_OUTPUT_DIR, OUTPUT_ROOT

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()
API_KEY = os.getenv("YT_API_KEY")

if not API_KEY:
    raise Exception("Chave da API não encontrada no .env. Certifique-se de ter YT_API_KEY=SEU_TOKEN no arquivo .env.")

# Pasta de destino dos comentários
COMMENTS_DIR = COMMENTS_OUTPUT_DIR
COMMENTS_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_INFO_DIR = OUTPUT_ROOT / "video_info"
VIDEO_INFO_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_COMMENTS_ZIP = OUTPUT_ROOT / "comentarios_coletados.zip"
GENERAL_INFO_COMMENT_LIMIT = 500

def get_channel_id_from_handle(api_key, handle):
    """Obtém o channel_id a partir do @handle do canal"""
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)

    request = youtube.search().list(
        part="snippet",
        q=handle,
        type="channel",
        maxResults=1
    )
    response = request.execute()

    if 'items' in response and len(response['items']) > 0:
        return response['items'][0]['id']['channelId']
    else:
        raise Exception("Não foi possível encontrar o canal para o handle fornecido.")

def get_channel_video_ids(api_key, channel_id, max_results=None, order_by_popularity=False):
    """
    Obtém os IDs dos vídeos do canal. Se max_results for None, retorna o máximo possível.
    """
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)

    video_ids = []
    next_page_token = None

    while True:
        if max_results is not None:
            remaining = max_results - len(video_ids)
            if remaining <= 0:
                break
            request_max = min(50, remaining)
        else:
            request_max = 50

        request = youtube.search().list(
            part="id",
            type="video",
            channelId=channel_id,
            maxResults=request_max,
            order="viewCount" if order_by_popularity else "date",
            pageToken=next_page_token
        )
        response = request.execute()

        items = response.get('items', [])
        for item in items:
            video_id = item.get('id', {}).get('videoId')
            if video_id:
                video_ids.append(video_id)

        if not items:
            break

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return video_ids

def clean_comment(comment):
    """Remove links HTML e caracteres especiais/emoji do comentário"""
    comment = re.sub(r'<a href=".*?">.*?</a>', '', comment)
    return strip_special_characters(comment)


def strip_special_characters(text: str) -> str:
    """Elimina emojis e símbolos fora do ASCII básico"""
    ascii_text = text.encode("ascii", "ignore").decode("ascii", "ignore")
    ascii_text = ascii_text.replace("\r", " ").replace("\n", " ")
    ascii_text = re.sub(r"[^A-Za-z0-9 .,!?;:'\"()\-]", "", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()

def get_video_title(api_key, video_id):
    """Obtém o título do vídeo"""
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)
    request = youtube.videos().list(part="snippet", id=video_id)
    response = request.execute()
    if response['items']:
        return response['items'][0]['snippet']['title']
    return video_id  # fallback caso não encontre título

def sanitize_filename(name):
    """Remove caracteres inválidos de nomes de arquivo"""
    return re.sub(r'[\\/*?:"<>|]', "", name)


def chunk_list(items, chunk_size=50):
    """Divida uma lista em blocos menores"""
    for idx in range(0, len(items), chunk_size):
        yield items[idx : idx + chunk_size]


def normalize_toon_value(value: str | int | float | None) -> str:
    """Sanitize values for Token-Oriented-Object Notation output."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace(",", ";")


def build_toon_block(label: str, rows: list[dict], fields: list[str]) -> str:
    """Monta um bloco TOON com cabeçalho e linhas de dados."""
    header = f"{label}[{len(rows)}]{{{','.join(fields)}}}:"
    lines = [header]
    for row in rows:
        values = [normalize_toon_value(row.get(field, "")) for field in fields]
        lines.append("  " + ",".join(values))
    return "\n".join(lines)


def fetch_video_comments(api_key, video_id, max_results=GENERAL_INFO_COMMENT_LIMIT):
    """Retorna uma lista de comentários limpos para um vídeo."""
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)
    comments: list[str] = []
    next_page_token = None

    while len(comments) < max_results:
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=min(100, max_results - len(comments)),
            pageToken=next_page_token
        )
        response = request.execute()

        for item in response.get('items', []):
            comment = item['snippet']['topLevelComment']['snippet']['textDisplay']
            comments.append(clean_comment(comment))
            if len(comments) >= max_results:
                break

        next_page_token = response.get('nextPageToken')
        if not next_page_token:
            break

    return comments


def get_videos_public_info(api_key, video_ids):
    """Busca informações públicas (snippet/estatísticas) dos vídeos"""
    if not video_ids:
        return []

    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)
    info_map = {}

    for chunk in chunk_list(video_ids, 50):
        request = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(chunk)
        )
        response = request.execute()

        for item in response.get('items', []):
            snippet = item.get('snippet', {})
            statistics = item.get('statistics', {})
            content_details = item.get('contentDetails', {})
            video_id = item.get('id')

            info_map[video_id] = {
                "id": video_id,
                "title": snippet.get('title', 'Sem título'),
                "description": snippet.get('description', '').strip(),
                "published_at": snippet.get('publishedAt', ''),
                "channel_title": snippet.get('channelTitle', ''),
                "duration": content_details.get('duration', ''),
                "view_count": statistics.get('viewCount', '0'),
                "like_count": statistics.get('likeCount', '0'),
                "comment_count": statistics.get('commentCount', '0'),
                "url": f"https://www.youtube.com/watch?v={video_id}",
            }

    return [info_map[video_id] for video_id in video_ids if video_id in info_map]


def save_video_info_files(handle, videos_info):
    """Salva as informações públicas em TOON e JSON."""
    if not videos_info:
        raise ValueError("videos_info precisa conter pelo menos um item")

    sanitized_handle = sanitize_filename(handle.lstrip("@")) or "canal"
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    toon_file = VIDEO_INFO_DIR / f"{sanitized_handle}_toon_{timestamp}.txt"
    json_file = VIDEO_INFO_DIR / f"{sanitized_handle}_{timestamp}.json"

    toon_video_fields = [
        "title",
        "channel_title",
        "published_at",
        "duration",
        "view_count",
        "like_count",
        "comment_count",
        "description",
    ]

    video_rows = [
        {field: info.get(field, "") for field in toon_video_fields}
        for info in videos_info
    ]

    comment_rows = []
    for video_index, info in enumerate(videos_info, start=1):
        for comment_text in info.get("comments", []):
            comment_rows.append(
                {
                    "video_index": video_index,
                    "comment": comment_text,
                }
            )

    videos_block = build_toon_block("videos", video_rows, toon_video_fields)
    comments_block = build_toon_block("comments", comment_rows, ["video_index", "comment"])

    with open(toon_file, "w", encoding="utf-8") as f:
        f.write(f"canal{{handle,video_count}}:\n  {normalize_toon_value(handle)},{len(videos_info)}\n")
        f.write(videos_block + "\n")
        f.write(comments_block + "\n")

    payload = {
        "channel_handle": handle,
        "video_count": len(videos_info),
        "videos": videos_info,
    }
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return toon_file, json_file

def get_video_comments(api_key, video_id, max_results=5000):
    """Obtém os comentários de um vídeo, numera e salva com o título"""
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)

    next_page_token = None

    # Busca o título do vídeo
    title = get_video_title(api_key, video_id)
    safe_title = sanitize_filename(title)
    output_file = COMMENTS_DIR / f"{safe_title}.txt"

    with open(output_file, "w", encoding="utf-8") as f:
        index = 1
        total_saved = 0
        while total_saved < max_results:
            request = youtube.commentThreads().list(
                part="snippet",
                videoId=video_id,
                maxResults=min(100, max_results - total_saved),
                pageToken=next_page_token
            )
            response = request.execute()

            for item in response.get('items', []):
                comment = item['snippet']['topLevelComment']['snippet']['textDisplay']
                cleaned_comment = clean_comment(comment)
                f.write(f"{index}. {cleaned_comment}\n\n")
                index += 1
                total_saved += 1

                if total_saved >= max_results:
                    break

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

    return output_file, total_saved, title

def extract_video_id(video_input):
    """Extrai o video_id de diferentes formatos de URL"""
    if re.fullmatch(r"^[a-zA-Z0-9_-]{11}$", video_input):
        return video_input
    
    match = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})", video_input)
    if match:
        return match.group(1)

    return None

def zip_files(file_list, zip_filename: str | Path = DEFAULT_COMMENTS_ZIP):
    """Cria um único arquivo ZIP contendo todos os arquivos coletados"""
    with zipfile.ZipFile(zip_filename, "w") as zipf:
        for file in file_list:
            zipf.write(file)
    return zip_filename

if __name__ == "__main__":
    modo = input("Escolha o modo de coleta | Canal (c); Vídeo (v): ").strip().lower()

    if modo == "c":
        handle = input("Digite o @handle do canal: ").strip()
        order_choice = input("Ordenar por popularidade? (s/N): ").strip().lower()
        order_by_popularity = order_choice == "s"
        coleta_tipo = input("Deseja coletar informações gerais (g) ou comentários (c)? ").strip().lower()

        if coleta_tipo not in {"g", "c"}:
            raise SystemExit("Opção inválida! Use 'g' para informações gerais ou 'c' para comentários.")

        max_videos_input = input("Quantidade de vídeos para coletar (Enter para o máximo disponível): ").strip()
        max_videos = int(max_videos_input) if max_videos_input else None
        max_comments = None
        if coleta_tipo == "c":
            max_comments = int(input("Quantidade de comentários por vídeo: "))

        print(f"Buscando ID do canal para {handle}...")
        channel_id = get_channel_id_from_handle(API_KEY, handle)
        print(f"ID do canal encontrado: {channel_id}")

        print("Buscando vídeos do canal...")
        video_ids = get_channel_video_ids(API_KEY, channel_id, max_videos, order_by_popularity)
        if not video_ids:
            raise SystemExit("Nenhum vídeo encontrado para o canal informado.")
        print(f"Vídeos coletados: {video_ids}")

        if coleta_tipo == "g":
            print("Coletando informações públicas dos vídeos...")
            videos_info = get_videos_public_info(API_KEY, video_ids)
            if not videos_info:
                print("Não foi possível obter informações dos vídeos.")
            else:
                print("Coletando comentários (máx. 500 por vídeo)...")
                for index, info in enumerate(videos_info, start=1):
                    print(f"  Vídeo {index}/{len(videos_info)}: {info['title']}")
                    info["comments"] = fetch_video_comments(API_KEY, info["id"], GENERAL_INFO_COMMENT_LIMIT)
                    time.sleep(1)
                toon_file, json_file = save_video_info_files(handle, videos_info)
                print(f"Informações TOON salvas em: {toon_file}")
                print(f"Informações JSON salvas em: {json_file}")
        else:
            arquivos = []
            for i, video_id in enumerate(video_ids):
                print(f"\n--- Vídeo {i+1}/{len(video_ids)} ---")
                output_file, num_comments, title = get_video_comments(API_KEY, video_id, max_comments)
                arquivos.append(output_file)
                print(f"'{title}' → {num_comments} comentários salvos em {output_file}")
                time.sleep(2)

            print("\nColeta finalizada!")
            if arquivos:
                zip_filename = zip_files(arquivos)
                print(f"Arquivos compactados em: {zip_filename}")

    elif modo in ["vídeo", "video", "v", "V"]:
        video_input = input("Cole o link do vídeo ou apenas o ID: ").strip()
        video_id = extract_video_id(video_input)

        if not video_id:
            print("URL ou ID inválido! Certifique-se de que está no formato correto.")
        else:
            print(f"ID do vídeo encontrado: {video_id}")
            print("Iniciando coleta de comentários...")
            output_file, num_comments, title = get_video_comments(API_KEY, video_id, 5000)
            print(f"'{title}' → {num_comments} comentários salvos em {output_file}")

    else:
        print("Modo inválido. Use 'c' para canal ou 'v' para vídeo.")
