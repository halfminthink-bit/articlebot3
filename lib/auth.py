# lib/auth.py
# -*- coding: utf-8 -*-
"""Google認証の統合管理"""
import pathlib
import sys
from typing import List
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]

class GoogleAuth:
    """Google API認証マネージャー"""
    
    def __init__(self, credentials_path: str = "credentials.json", 
                 token_path: str = "token.json"):
        self.credentials_path = pathlib.Path(credentials_path)
        self.token_path = pathlib.Path(token_path)
        self._creds: Credentials = None
    
    def _run_flow(self) -> Credentials:
        """認証フローを実行"""
        if not self.credentials_path.exists():
            raise FileNotFoundError(f"credentials.json が見つかりません: {self.credentials_path}")
        
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.credentials_path), SCOPES
        )
        creds = flow.run_local_server(
            port=0,
            authorization_prompt_message="",
            success_message="認証完了。ウィンドウを閉じて処理に戻ります。",
            access_type="offline",
            prompt="consent",
        )
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    
    def get_credentials(self, force_login: bool = False) -> Credentials:
        """認証情報を取得（キャッシュあり）"""
        if self._creds and not force_login:
            return self._creds
        
        if force_login and self.token_path.exists():
            try:
                self.token_path.unlink()
                print("[info] token.json削除（再認証）")
            except Exception:
                pass
        
        if not force_login and self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            try:
                if not creds.valid:
                    if creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        self.token_path.write_text(creds.to_json(), encoding="utf-8")
                    else:
                        raise RefreshError("トークン無効")
                self._creds = creds
                return creds
            except RefreshError:
                print("[info] トークン更新失敗。再認証します...", file=sys.stderr)
        
        self._creds = self._run_flow()
        return self._creds
    
    def build_service(self, service_name: str, version: str, force_login: bool = False):
        """Google APIサービスを構築"""
        creds = self.get_credentials(force_login)
        return build(service_name, version, credentials=creds)