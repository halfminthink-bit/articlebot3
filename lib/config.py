# lib/config.py
# -*- coding: utf-8 -*-
"""設定管理の一元化"""
import os
import pathlib
from typing import Optional
from dotenv import load_dotenv

class Config:
    """環境変数と設定を一元管理"""
    
    def __init__(self, env_path: Optional[pathlib.Path] = None):
        # .envファイルをロード
        if env_path and env_path.exists():
            load_dotenv(dotenv_path=env_path, override=True)
        else:
            # デフォルトパス（ROOT/.env → CWD/.env の順）
            root = pathlib.Path(__file__).resolve().parent.parent
            load_dotenv(dotenv_path=root / ".env", override=False)
            load_dotenv(dotenv_path=pathlib.Path.cwd() / ".env", override=True)
        
        # ===== LLM設定 =====
        self.provider = os.getenv("PROVIDER", "openai").strip().lower()
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.claude_api_key = os.getenv("CLAUDE_API_KEY", "").strip()
        
        # モデル設定（省略時はプロバイダーに応じた既定値）
        default_model = "claude-sonnet-4-5" if self.provider == "anthropic" else "gpt-4o"
        self.model_title = os.getenv("MODEL_TITLE", default_model).strip()
        self.model_outline = os.getenv("MODEL_OUTLINE", default_model).strip()
        self.model_draft = os.getenv("MODEL_DRAFT", default_model).strip()
        
        # ===== 検索API設定 =====
        self.brave_api_key = os.getenv("BRAVE_API_KEY", "").strip()  # ← 追加
        
        # ===== Google設定 =====
        self.sheet_id = os.getenv("SHEET_ID", "").strip()
        self.sheet_name = os.getenv("SHEET_NAME", "Articles").strip()  # デフォルト値
        self.official_url = os.getenv("OFFICIAL_URL", "").strip()
        
        # ===== プロンプト設定 =====
        self.prompt_dir = os.getenv("PROMPT_DIR", "").strip()
        self.prompt_title = os.getenv("PROMPT_TITLE", "title_prompt_pre_outline.txt").strip()
        self.prompt_outline = os.getenv("PROMPT_OUTLINE", "outline_prompt_2call.txt").strip()
        self.prompt_draft = os.getenv("PROMPT_DRAFT", "draft_prompt_2call.txt").strip()
        
        # 検証
        self._validate()
    
    def _validate(self):
        """必須設定の検証"""
        if self.provider == "openai" and not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY が設定されていません。\n"
                ".env ファイルに OPENAI_API_KEY=sk-... を追加してください。"
            )
        if self.provider == "anthropic" and not self.claude_api_key:
            raise RuntimeError(
                "CLAUDE_API_KEY が設定されていません。\n"
                ".env ファイルに CLAUDE_API_KEY=sk-ant-... を追加してください。"
            )
        if self.provider not in ("openai", "anthropic"):
            raise RuntimeError(
                f"未知のPROVIDER: {self.provider}\n"
                "PROVIDER は 'openai' または 'anthropic' を指定してください。"
            )
    
    def get_prompt_paths(self) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
        """プロンプトファイルのパスを取得"""
        if not self.prompt_dir:
            raise RuntimeError(
                "PROMPT_DIR が設定されていません。\n"
                ".env ファイルに PROMPT_DIR=/path/to/prompts を追加してください。"
            )
        
        base = pathlib.Path(self.prompt_dir).expanduser().resolve()
        if not base.exists():
            raise FileNotFoundError(f"プロンプトディレクトリが見つかりません: {base}")
        
        title_path = base / self.prompt_title
        outline_path = base / self.prompt_outline
        draft_path = base / self.prompt_draft
        
        missing = [str(p) for p in (title_path, outline_path, draft_path) if not p.exists()]
        if missing:
            raise FileNotFoundError(
                "プロンプトファイルが見つかりません:\n" + 
                "\n".join(f"  - {p}" for p in missing)
            )
        
        return title_path, outline_path, draft_path