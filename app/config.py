"""Environment settings for VisualDetox."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


class Settings:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    MOCK_MODE = os.getenv("MOCK_MODE", "false" if GEMINI_API_KEY else "true").lower() == "true"
    BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL") or None
    PORT = int(os.getenv("PORT", "8000"))
    REPO_URL = os.getenv("REPO_URL", "https://github.com/shivamgoel234/VisualDetox")
    CACHE_DIR = ROOT / "cache"
    DEMO_DIR = ROOT / "demo-sites"
    OUTPUT_DIR = ROOT / "output"
    MOCK_DIR = ROOT / "mock"


settings = Settings()
