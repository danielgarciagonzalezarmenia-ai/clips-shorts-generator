import os
import json
import tempfile
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def _get_client_secrets_file():
    env_json = os.environ.get('GOOGLE_CLIENT_SECRETS')
    if env_json:
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        tmp.write(env_json)
        tmp.close()
        return tmp.name
    if os.path.exists("client_secrets.json"):
        return "client_secrets.json"
    raise FileNotFoundError("client_secrets.json no encontrado ni GOOGLE_CLIENT_SECRETS en env")

def get_authenticated_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secrets_file = _get_client_secrets_file()
            flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
            auth_url, _ = flow.authorization_url(prompt='consent')
            print('Visita esta URL para autorizar:', auth_url)
            code = input('Ingresa el código de autorización: ')
            flow.fetch_token(code=code)
            creds = flow.credentials
            if secrets_file != "client_secrets.json" and os.path.exists(secrets_file):
                os.unlink(secrets_file)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    try:
        return build("youtube", "v3", credentials=creds)
    except HttpError as e:
        print(f"Error creando servicio YouTube: {e}")
        return None

def upload_short(video_path, title, description="", tags=None):
    youtube = get_authenticated_service()
    if not youtube:
        return None
    if tags is None:
        tags = ["Shorts"]
    if "#Shorts" not in title and "#shorts" not in title.lower():
        title = f"{title} #Shorts"
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "24"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    try:
        print(f"Subiendo '{title}'...")
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
        insert_request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )
        response = None
        error = None
        retry = 0
        while response is None:
            try:
                status, response = insert_request.next_chunk()
                if status:
                    print(f"Subido {int(status.progress() * 100)}%.")
            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    error = f"Error HTTP {e.resp.status}"
                else:
                    raise
            except Exception as e:
                error = f"Error: {e}"
            if error is not None:
                print(error)
                retry += 1
                if retry > 3:
                    return None
        print(f"Subido! Video ID: {response['id']}")
        return response['id']
    except HttpError as e:
        print(f"Error HTTP {e.resp.status}: {e.content}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None