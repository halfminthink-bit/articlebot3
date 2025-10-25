"""sheets_handler.py"""

import os
from typing import List
from dataclasses import dataclass
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GRequest
from googleapiclient.discovery import build


@dataclass
class RowItem:
    """スプレッドシート行データ"""
    row_index: int
    persona: str
    title: str
    doc_url: str
    status: str
    note_url: str
    eyecatch_path: str


class SheetsHandler:
    """Google Sheets操作クラス"""
    
    def __init__(self, sheet_id: str, sheet_name: str, scopes: List[str]):
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.scopes = scopes
        self.service = None
    
    def connect(self):
        """Google Sheetsに接続"""
        if not self.sheet_id:
            raise ValueError("SHEET_ID が .env に未設定です")
        
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", self.scopes)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(GRequest())
            else:
                if not os.path.exists("credentials.json"):
                    raise FileNotFoundError("credentials.json がありません")
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", self.scopes
                )
                creds = flow.run_local_server(port=0)
            
            with open("token.json", "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        
        self.service = build("sheets", "v4", credentials=creds)
        return self.service
    
    def read_rows(self) -> List[RowItem]:
        """全行を読み込み"""
        rng = f"{self.sheet_name}!A2:F"
        values = self.service.spreadsheets().values().get(
            spreadsheetId=self.sheet_id, range=rng
        ).execute().get("values", [])
        
        out = []
        for i, row in enumerate(values, start=2):
            row += [""] * (6 - len(row))
            persona, title, doc, eye, status, nurl = row[:6]
            out.append(RowItem(
                row_index=i,
                persona=(persona or "").strip(),
                title=(title or "").strip(),
                doc_url=(doc or "").strip(),
                status=(status or "").strip(),
                note_url=(nurl or "").strip(),
                eyecatch_path=(eye or "").strip(),
            ))
        return out
    
    def write_back(self, row_index: int, status: str, note_url: str):
        """ステータスとURLを書き戻し"""
        self.service.spreadsheets().values().update(
            spreadsheetId=self.sheet_id,
            range=f"{self.sheet_name}!E{row_index}:F{row_index}",
            valueInputOption="RAW",
            body={"values": [[status, note_url]]}
        ).execute()
