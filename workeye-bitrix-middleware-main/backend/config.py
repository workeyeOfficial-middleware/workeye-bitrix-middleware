import os
from dotenv import load_dotenv

load_dotenv()  # Load variables from .env

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK")
WORKEYE_API = os.getenv("WORKEYE_API")
JWT_SECRET = os.getenv("JWT_SECRET")