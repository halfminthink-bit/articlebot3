"""sheets_handler.py"""

import os
from typing import List
from dataclasses import dataclass
from lib.auth import GoogleAuth


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
        
        auth = GoogleAuth()
        self.service = auth.build_service("sheets", "v4")
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
