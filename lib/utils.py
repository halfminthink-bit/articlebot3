# lib/utils.py
# -*- coding: utf-8 -*-
"""共通ユーティリティ関数"""
import json
import pathlib
from typing import Any, Dict, List

def read_text(path: pathlib.Path) -> str:
    """テキストファイル読み込み"""
    return path.read_text(encoding="utf-8")

def read_json(path: pathlib.Path) -> Dict[str, Any]:
    """JSON読み込み"""
    return json.loads(read_text(path))

def read_lines_strip(path: pathlib.Path) -> List[str]:
    """行ごと読み込み（コメント除外）"""
    if not path.exists():
        return []
    lines = [ln.strip() for ln in read_text(path).splitlines()]
    return [ln for ln in lines if ln and not ln.startswith("#")]

def save_text(path: pathlib.Path, content: str):
    """テキストファイル保存"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def save_json(path: pathlib.Path, obj: Any):
    """JSON保存"""
    save_text(path, json.dumps(obj, ensure_ascii=False, indent=2))