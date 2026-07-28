import os
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_credentials = {}
_cred_path = os.path.join(BASE_DIR, "credentials.yaml")
if os.path.exists(_cred_path):
    with open(_cred_path) as f:
        _credentials = yaml.load(f, Loader=yaml.FullLoader) or {}


def cred(key: str, default: str = "") -> str:
    """Read a credential from credentials.yaml first, falling back to env vars."""
    return _credentials.get(key) or os.environ.get(key, default)


class Config:
    SECRET_KEY = cred("SECRET_KEY", "dev-secret-key-change-me")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'mino_chat.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Azure OpenAI
    AZURE_OPENAI_API_KEY = cred("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT = cred("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_DEPLOYMENT = cred("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
    AZURE_OPENAI_API_VERSION = cred("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = cred("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    


    # RAG paths
    DATA_PATH = os.path.join(BASE_DIR, "pdfs")
    VECTORSTORE_ROOT = os.path.join(BASE_DIR, "vectorstore")
    UPLOAD_TMP_DIR = os.path.join(BASE_DIR, "tmp_uploads")
    UPLOAD_SECTION = "UPLOAD"
    MAX_HISTORY_MSGS = 4

    # Tools: web search + hate speech analyzer
    TAVILY_API_KEY = cred("TAVILY_API_KEY")
    HATE_SPEECH_INDEX_DIR = os.path.join(BASE_DIR, "indexes")

    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25 MB upload limit
