import os
import time
import re
import zipfile
import googleapiclient.discovery
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()
API_KEY = os.getenv("YT_API_KEY")

if not API_KEY:
    raise Exception("Chave da API não encontrada no .env. Certifique-se de ter YT_API_KEY=SEU_TOKEN no arquivo .env.")

# Pasta de destino dos comentários
COMMENTS_DIR = "comments"
os.makedirs(COMMENTS_DIR, exist_ok=True)

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

def get_channel_video_ids(api_key, channel_id, max_results=50, order_by_popularity=False):
    """Obtém os IDs dos vídeos do canal"""
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)

    request = youtube.search().list(
        part="id",
        channelId=channel_id,
        maxResults=max_results,
        order="viewCount" if order_by_popularity else "date"
    )
    response = request.execute()

    video_ids = [item['id']['videoId'] for item in response.get('items', [])]
    return video_ids

def clean_comment(comment):
    """Remove links HTML como [<a href="...">10:00</a>] do comentário"""
    return re.sub(r'<a href=".*?">.*?</a>', '', comment).strip()

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

def get_video_comments(api_key, video_id, max_results=5000):
    """Obtém os comentários de um vídeo, numera e salva com o título"""
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)

    comments = []
    next_page_token = None

    # Busca o título do vídeo
    title = get_video_title(api_key, video_id)
    safe_title = sanitize_filename(title)
    output_file = os.path.join(COMMENTS_DIR, f"{safe_title}.txt")

    with open(output_file, "w", encoding="utf-8") as f:
        index = 1
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
                cleaned_comment = clean_comment(comment)
                comments.append(cleaned_comment)
                f.write(f"{index}. {cleaned_comment}\n\n")
                index += 1

                if len(comments) >= max_results:
                    break

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

    return output_file, len(comments), title

def extract_video_id(video_input):
    """Extrai o video_id de diferentes formatos de URL"""
    if re.fullmatch(r"^[a-zA-Z0-9_-]{11}$", video_input):
        return video_input
    
    match = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})", video_input)
    if match:
        return match.group(1)

    return None

def zip_files(file_list, zip_filename="comentarios_coletados.zip"):
    """Cria um único arquivo ZIP contendo todos os arquivos coletados"""
    with zipfile.ZipFile(zip_filename, "w") as zipf:
        for file in file_list:
            zipf.write(file)
    return zip_filename

if __name__ == "__main__":
    modo = input("Escolha o modo de coleta | Canal (c); Vídeo (v): ").strip().lower()

    if modo == "c":
        handle = input("Digite o @handle do canal: ").strip()
        order_by_popularity = input("Ordenar por popularidade? (s/n): ").strip().lower() == "s"
        max_videos = int(input("Quantidade de vídeos para coletar: "))
        max_comments = int(input("Quantidade de comentários por vídeo: "))

        print(f"Buscando ID do canal para {handle}...")
        channel_id = get_channel_id_from_handle(API_KEY, handle)
        print(f"ID do canal encontrado: {channel_id}")

        print("Buscando vídeos do canal...")
        video_ids = get_channel_video_ids(API_KEY, channel_id, max_videos, order_by_popularity)
        print(f"Vídeos coletados: {video_ids}")

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
