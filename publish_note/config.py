"""config.py"""

import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """アプリケーション設定"""
    
    # Google Sheets
    SHEET_ID = os.getenv("SHEET_ID")
    SHEET_NAME = os.getenv("SHEET_NAME", "Articles")
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    
    # note認証
    NOTE_EMAIL = os.getenv("NOTE_EMAIL", "").strip()
    NOTE_PASSWORD = os.getenv("NOTE_PASSWORD", "").strip()
    
    # Selenium設定
    HEADLESS = os.getenv("HEADLESS", "1").strip() in ("1", "true", "TRUE", "True")
    CHROME_USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", "").strip()
    CHROME_PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "").strip()
    
    # 処理設定
    ROW_LIMIT = int(os.getenv("ROW_LIMIT", "0"))
    
    # スプレッドシート列定義
    COL_PERSONA = 0
    COL_TITLE = 1
    COL_DOC = 2
    COL_EYE = 3
    COL_STATUS = 4
    COL_NOTEURL = 5
