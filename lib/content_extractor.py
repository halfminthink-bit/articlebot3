# lib/content_extractor.py
# -*- coding: utf-8 -*-
"""
動画テキストから記事用の情報を抽出
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional

from lib.llm import LLMClient


def chunk_text(text: str, max_chars: int = 30000) -> List[str]:
    """
    長いテキストを段落優先で分割
    
    Args:
        text: 分割対象のテキスト
        max_chars: 1チャンクの最大文字数
    
    Returns:
        List[str]: チャンクのリスト
    """
    chunks = []
    i = 0
    n = len(text)
    
    while i < n:
        j = min(n, i + max_chars)
        # 段落区切りを探す
        k = text.rfind("\n", i, j)
        if k == -1 or k < i + int(max_chars * 0.6):
            k = j
        
        chunk = text[i:k].strip()
        if chunk:
            chunks.append(chunk)
        i = k
    
    return chunks


def load_prompt(prompt_path: Path) -> str:
    """プロンプトファイルを読み込み"""
    if not prompt_path.exists():
        raise FileNotFoundError(f"プロンプトが見つかりません: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8")


def inject_text_to_prompt(prompt_template: str, text: str) -> str:
    """
    プロンプトにテキストを挿入
    
    以下の順で試行：
    1. 「【テキスト】\\n添付ファイル」を置換
    2. 「【テキスト】」の直後に挿入
    3. 末尾に追加
    """
    if "【テキスト】\n添付ファイル" in prompt_template:
        return prompt_template.replace("【テキスト】\n添付ファイル", f"【テキスト】\n{text}")
    
    if "【テキスト】" in prompt_template:
        return prompt_template.replace("【テキスト】", f"【テキスト】\n{text}")
    
    return f"{prompt_template}\n\n【テキスト】\n{text}"


def extract_json_from_response(response: str) -> Dict[str, Any]:
    """
    LLMレスポンスからJSON部分を抽出してパース
    
    ```json ... ``` 形式や生のJSONに対応
    """
    # まず全体をJSONとしてパース試行
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass
    
    # ```json ... ``` 形式を探す
    import re
    json_pattern = re.compile(r'```json\s*\n(.*?)\n```', re.DOTALL)
    match = json_pattern.search(response)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # ``` ... ``` 形式（jsonなし）
    code_pattern = re.compile(r'```\s*\n(.*?)\n```', re.DOTALL)
    match = code_pattern.search(response)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # { ... } を探す（最初と最後の波括弧）
    first_brace = response.find('{')
    last_brace = response.rfind('}')
    if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
        try:
            return json.loads(response[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass
    
    raise ValueError("レスポンスからJSONを抽出できませんでした")


def extract_video_content(
    video_text: str,
    llm: LLMClient,
    model: str,
    extraction_prompt_path: Path,
    max_tokens: int = 16000
) -> Dict[str, Any]:
    """
    単一動画から情報を抽出
    
    Args:
        video_text: 動画の文字起こしテキスト
        llm: LLMクライアント
        model: 使用するモデル名
        extraction_prompt_path: 抽出プロンプトのパス
        max_tokens: 最大トークン数
    
    Returns:
        Dict: 抽出された情報（JSON形式）
    """
    prompt_template = load_prompt(extraction_prompt_path)
    chunks = chunk_text(video_text, max_chars=30000)
    
    # 短い動画（1チャンク）
    if len(chunks) == 1:
        user_prompt = inject_text_to_prompt(prompt_template, chunks[0])
        system_prompt = "あなたは哲学に精通した編集者です。動画から読み応えのある記事素材を抽出してください。"
        
        response = llm.generate(model, system_prompt, user_prompt, max_tokens=max_tokens)
        return extract_json_from_response(response)
    
    # 長い動画（複数チャンク）- Map-Reduce方式
    print(f"[info] 長い動画です。{len(chunks)}チャンクに分割して処理します")
    
    # Map: 各チャンクから情報抽出
    partial_results = []
    for idx, chunk in enumerate(chunks, 1):
        print(f"[map] チャンク {idx}/{len(chunks)} 処理中...")
        chunk_with_header = f"[動画の一部: Part {idx}/{len(chunks)}]\n{chunk}"
        user_prompt = inject_text_to_prompt(prompt_template, chunk_with_header)
        system_prompt = "あなたは哲学に精通した編集者です。動画の一部から読み応えのある記事素材を抽出してください。"
        
        response = llm.generate(model, system_prompt, user_prompt, max_tokens=max_tokens)
        try:
            partial_json = extract_json_from_response(response)
            partial_results.append(json.dumps(partial_json, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[warn] チャンク{idx}のJSON抽出失敗: {e}")
            partial_results.append(response)
    
    # Reduce: 部分結果を統合
    print("[reduce] 部分結果を統合中...")
    merged_text = "\n\n---\n\n".join(partial_results)
    
    reduce_prompt = f"""以下は同一動画の部分ごとに抽出された情報です。
これらを統合して、一つの記事用JSON情報にまとめてください。
重複を避け、動画全体の流れを保ちながら統合してください。

【部分抽出結果】
{merged_text}
"""
    
    response = llm.generate(
        model,
        "あなたは哲学に精通した編集者です。部分情報を統合して完全な記事素材を作成してください。",
        reduce_prompt,
        max_tokens=max_tokens
    )
    
    return extract_json_from_response(response)


def synthesize_multiple_videos(
    extracted_contents: List[Dict[str, Any]],
    llm: LLMClient,
    model: str,
    synthesis_prompt_path: Path,
    max_tokens: int = 16000
) -> Dict[str, Any]:
    """
    複数動画の抽出情報を統合
    
    Args:
        extracted_contents: 各動画から抽出されたJSON情報のリスト
        llm: LLMクライアント
        model: 使用するモデル名
        synthesis_prompt_path: 統合プロンプトのパス
        max_tokens: 最大トークン数
    
    Returns:
        Dict: 統合された情報（JSON形式）
    """
    if len(extracted_contents) == 1:
        return extracted_contents[0]
    
    prompt_template = load_prompt(synthesis_prompt_path)
    
    # 各動画の情報をテキスト化
    video_infos = []
    for idx, content in enumerate(extracted_contents, 1):
        json_text = json.dumps(content, ensure_ascii=False, indent=2)
        video_infos.append(f"=== 動画{idx}の抽出情報 ===\n{json_text}")
    
    merged_text = "\n\n".join(video_infos)
    user_prompt = inject_text_to_prompt(prompt_template, merged_text)
    
    system_prompt = "あなたは哲学に精通した編集者です。複数動画の情報を統合して、読み応えのある記事素材を作成してください。"
    
    response = llm.generate(model, system_prompt, user_prompt, max_tokens=max_tokens)
    return extract_json_from_response(response)