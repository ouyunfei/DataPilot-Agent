from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DEFAULT_DATABASE_PATH = DATA_DIR / "datapilot.db"

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_TIMEOUT_SECONDS = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "30"))
QUERY_TIMEOUT_SECONDS = float(os.getenv("QUERY_TIMEOUT_SECONDS", "5"))

_qdrant_path = Path(os.getenv("QDRANT_PATH", "data/qdrant"))
QDRANT_PATH = _qdrant_path if _qdrant_path.is_absolute() else BASE_DIR / _qdrant_path
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "datapilot_knowledge_bge_small_zh_v15")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
KNOWLEDGE_TOP_K = max(1, int(os.getenv("KNOWLEDGE_TOP_K", "5")))
META_DB_TYPE = os.getenv("META_DB_TYPE", "mysql").strip().lower()
META_DATABASE_URL = os.getenv(
    "META_DATABASE_URL",
    "mysql://root:0522@127.0.0.1:3306/datapilot",
).strip()
