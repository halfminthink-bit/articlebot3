# lib/youtube_fetcher.py
# -*- coding: utf-8 -*-
"""
YouTube動画の字幕取得モジュール
"""
import re
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
)

# 優先言語
PREFERRED_LANGUAGES = ["ja", "ja-JP", "en", "en-US"]


def extract_video_id(url: str) -> str:
    """
    YouTubeのURLから動画IDを抽出
    
    対応形式:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    """
    parsed = urlparse(url)
    
    # youtu.be 形式
    if parsed.netloc.endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0]
    
    # watch?v= 形式
    query_params = parse_qs(parsed.query)
    if "v" in query_params:
        return query_params["v"][0]
    
    # shorts/ 形式
    if "/shorts/" in parsed.path:
        return parsed.path.split("/shorts/")[1].split("/")[0]
    
    raise ValueError(f"動画IDを抽出できませんでした: {url}")


def fetch_transcript(video_id: str, languages: Optional[List[str]] = None) -> List[Dict]:
    """
    動画IDから字幕を取得（新旧API両対応）
    
    Returns:
        List[Dict]: [{"text": "...", "start": 0.0, "duration": 1.5}, ...]
    """
    if languages is None:
        languages = PREFERRED_LANGUAGES
    
    # 新API対応チェック
    has_legacy_api = hasattr(YouTubeTranscriptApi, "get_transcript")
    
    if not has_legacy_api:
        # 新API (0.7.0+)
        return _fetch_transcript_new_api(video_id, languages)
    else:
        # 旧API
        return _fetch_transcript_legacy_api(video_id, languages)


def _fetch_transcript_new_api(video_id: str, languages: List[str]) -> List[Dict]:
    """新API (0.7.0+) での字幕取得"""
    api = YouTubeTranscriptApi()
    
    # まず指定言語で直接取得を試みる
    try:
        return api.fetch(video_id, languages=languages).to_raw_data()
    except (NoTranscriptFound, TranscriptsDisabled):
        pass
    
    # 字幕一覧を取得
    try:
        transcript_list = api.list(video_id)
    except Exception:
        raise NoTranscriptFound(f"字幕が見つかりませんでした: {video_id}")
    
    # 手動作成字幕を優先
    for lang_code in languages:
        try:
            transcript = transcript_list.find_manually_created_transcript([lang_code])
            return transcript.fetch().to_raw_data()
        except Exception:
            continue
    
    # 自動生成字幕
    for lang_code in languages:
        try:
            transcript = transcript_list.find_generated_transcript([lang_code])
            return transcript.fetch().to_raw_data()
        except Exception:
            continue
    
    # 翻訳を試みる
    for transcript in transcript_list:
        try:
            return transcript.translate("ja").fetch().to_raw_data()
        except Exception:
            try:
                return transcript.fetch().to_raw_data()
            except Exception:
                continue
    
    raise NoTranscriptFound(f"利用可能な字幕が見つかりませんでした: {video_id}")


def _fetch_transcript_legacy_api(video_id: str, languages: List[str]) -> List[Dict]:
    """旧API (0.6.x) での字幕取得"""
    # まず指定言語で直接取得を試みる
    try:
        return YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
    except (NoTranscriptFound, TranscriptsDisabled):
        pass
    
    # 字幕一覧を取得
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    except Exception:
        raise NoTranscriptFound(f"字幕が見つかりませんでした: {video_id}")
    
    # 手動作成字幕を優先
    for lang_code in languages:
        try:
            transcript = transcript_list.find_manually_created_transcript([lang_code])
            return transcript.fetch()
        except Exception:
            continue
    
    # 自動生成字幕
    for lang_code in languages:
        try:
            transcript = transcript_list.find_generated_transcript([lang_code])
            return transcript.fetch()
        except Exception:
            continue
    
    # 翻訳を試みる
    for transcript in transcript_list:
        try:
            return transcript.translate("ja").fetch()
        except Exception:
            try:
                return transcript.fetch()
            except Exception:
                continue
    
    raise NoTranscriptFound(f"利用可能な字幕が見つかりませんでした: {video_id}")


def transcript_to_text(segments: List[Dict]) -> str:
    """
    字幕セグメントをプレーンテキストに変換
    
    Args:
        segments: [{"text": "...", "start": 0.0, "duration": 1.5}, ...]
    
    Returns:
        str: 整形されたプレーンテキスト
    """
    lines = []
    for segment in segments:
        text = segment.get("text", "").strip()
        if text:
            # 改行を除去
            text = text.replace("\n", " ")
            # 連続する空白を一つに
            text = re.sub(r"\s+", " ", text)
            lines.append(text)
    
    return "\n".join(lines)


def fetch_youtube_text(url: str, languages: Optional[List[str]] = None) -> tuple[str, str, List[Dict]]:
    """
    YouTube URLから字幕テキストを取得（便利関数）
    
    Returns:
        tuple: (video_id, plain_text, segments)
    """
    video_id = extract_video_id(url)
    segments = fetch_transcript(video_id, languages)
    text = transcript_to_text(segments)
    return video_id, text, segments