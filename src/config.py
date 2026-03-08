import os
import sys
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    BOT_TOKEN       = (os.getenv("BOT_TOKEN") or "").strip()
    # ✅ FIX #2: ADMIN_IDS тепер оголошено через os.getenv — чекер і IDE бачать змінну
    ADMIN_IDS       = [int(x.strip()) for x in (os.getenv("ADMIN_IDS") or "").split(",") if x.strip()]
    CHANNEL_ID      = int((os.getenv("CHANNEL_ID") or "0").strip())
    CHANNEL_USERNAME = (os.getenv("CHANNEL_USERNAME") or "").strip()
    GROQ_API_KEY    = (os.getenv("GROQ_API_KEY") or "").strip()
    GEMINI_API_KEY  = (os.getenv("GEMINI_API_KEY") or "").strip()
    TMDB_API_KEY    = (os.getenv("TMDB_API_KEY") or "").strip()
    MONO_CARD       = (os.getenv("MONO_CARD") or "").strip()
    MONO_NAME       = (os.getenv("MONO_NAME") or "").strip()
    DB_PATH         = (os.getenv("DB_PATH") or "bot_database.db").strip()
    
    # TURSO Database Config
    TURSO_DATABASE_URL = (os.getenv("TURSO_DATABASE_URL") or "").strip()
    TURSO_AUTH_TOKEN   = (os.getenv("TURSO_AUTH_TOKEN") or "").strip()

    def validate(self):
        """Call once at startup — crashes fast with a clear message if .env is missing keys."""
        required = {
            "BOT_TOKEN":        self.BOT_TOKEN,
            "CHANNEL_ID":       self.CHANNEL_ID,
            "CHANNEL_USERNAME": self.CHANNEL_USERNAME,
            "GROQ_API_KEY":     self.GROQ_API_KEY,
            "GEMINI_API_KEY":   self.GEMINI_API_KEY,
            "TMDB_API_KEY":     self.TMDB_API_KEY,
            "TURSO_DATABASE_URL": self.TURSO_DATABASE_URL,
            "TURSO_AUTH_TOKEN":   self.TURSO_AUTH_TOKEN,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            logger.critical(f"Missing required .env variables: {missing}")
            sys.exit(1)
        logger.info("Config validated OK.")


config = Config()