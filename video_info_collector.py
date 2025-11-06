# video_info_collector.py
# -*- coding: utf-8 -*-
"""
YouTube動画から記事用情報を収集するスクリプト

使い方:
  # 単発実行
  python video_info_collector.py ^
    --keyword "カントの純粋理性批判" ^
    --urls "https://youtube.com/watch?v=xxx,https://youtube.com/watch?v=yyy" ^
    --out data/generated_infos/kant.json
  
  # CSV一括処理
  python video_info_collector.py 
    --csv half_data\keywords\test.csv 
    --out-dir data/generated_infos/
"""
import sys
import csv
import json
import argparse
import pathlib
from typing import List, Dict, Any

from lib.config import Config
from lib.llm import LLMClient
from lib.youtube_fetcher import fetch_youtube_text
from lib.content_extractor import (
    extract_video_content,
    synthesize_multiple_videos
)

ROOT = pathlib.Path(__file__).resolve().parent


def sanitize_filename(text: str, max_length: int = 64) -> str:
    """ファイル名として安全な文字列に変換"""
    import re
    # 使えない文字を除去
    safe = re.sub(r'[\\/:*?"<>|]', '', text)
    safe = re.sub(r'\s+', '_', safe)
    return safe[:max_length]


def process_single_keyword(
    keyword: str,
    video_urls: List[str],
    llm: LLMClient,
    config: Config,
    extraction_prompt: pathlib.Path,
    synthesis_prompt: pathlib.Path,
    output_path: pathlib.Path
):
    """
    1つのキーワードについて複数動画から情報を収集
    
    Args:
        keyword: 主キーワード
        video_urls: 動画URLのリスト
        llm: LLMクライアント
        config: 設定
        extraction_prompt: 抽出プロンプトパス
        synthesis_prompt: 統合プロンプトパス
        output_path: 出力先JSONパス
    """
    print(f"\n{'='*60}")
    print(f"[処理開始] キーワード: {keyword}")
    print(f"[処理開始] 動画数: {len(video_urls)}")
    print(f"{'='*60}\n")
    
    # 各動画から情報抽出
    extracted_contents = []
    video_sources = []
    
    for idx, url in enumerate(video_urls, 1):
        try:
            print(f"[{idx}/{len(video_urls)}] 動画取得中: {url}")
            video_id, text, segments = fetch_youtube_text(url)
            
            print(f"[{idx}/{len(video_urls)}] 文字起こし取得完了: {len(text)}文字, {len(segments)}セグメント")
            
            # 動画情報を保存
            video_sources.append({
                "video_id": video_id,
                "url": url,
                "text_length": len(text),
                "segments_count": len(segments)
            })
            
            # 情報抽出
            print(f"[{idx}/{len(video_urls)}] 情報抽出中...")
            content = extract_video_content(
                text,
                llm,
                config.model_draft,  # 記事生成と同じモデルを使用
                extraction_prompt,
                max_tokens=16000
            )
            
            extracted_contents.append(content)
            print(f"[{idx}/{len(video_urls)}] 抽出完了\n")
            
        except Exception as e:
            print(f"[ERROR] 動画{idx}の処理失敗: {e}\n")
            continue
    
    if not extracted_contents:
        raise RuntimeError("すべての動画の処理に失敗しました")
    
    # 複数動画の場合は統合
    if len(extracted_contents) > 1:
        print(f"[統合] {len(extracted_contents)}本の動画情報を統合中...")
        final_content = synthesize_multiple_videos(
            extracted_contents,
            llm,
            config.model_draft,
            synthesis_prompt,
            max_tokens=16000
        )
        print("[統合] 完了\n")
    else:
        final_content = extracted_contents[0]
    
    # info.json形式で保存
    info_json = {
        "primary_keyword": keyword,
        "video_sources": video_sources,
        "narrative_content": final_content
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(info_json, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    
    print(f"[完了] 出力: {output_path}")
    print(f"{'='*60}\n")


def process_csv(
    csv_path: pathlib.Path,
    llm: LLMClient,
    config: Config,
    extraction_prompt: pathlib.Path,
    synthesis_prompt: pathlib.Path,
    output_dir: pathlib.Path,
    limit: int = 0
):
    """
    CSVファイルから一括処理
    
    CSV形式:
      primary_keyword,video_url_1,video_url_2,video_url_3
    """
    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    required_cols = ["primary_keyword"]
    if not all(col in reader.fieldnames for col in required_cols):
        raise ValueError(f"CSVに必須列がありません: {required_cols}")
    
    processed = 0
    
    for idx, row in enumerate(rows, 1):
        if limit > 0 and processed >= limit:
            print(f"[制限] 処理上限({limit}件)に達しました")
            break
        
        keyword = row.get("primary_keyword", "").strip()
        if not keyword:
            print(f"[スキップ] 行{idx}: キーワードが空です")
            continue
        
        # 動画URLを収集（video_url_1, video_url_2, ... の列）
        video_urls = []
        for i in range(1, 10):  # 最大9本まで
            url_col = f"video_url_{i}"
            # Noneチェックを追加
            if url_col in row and row[url_col] is not None and row[url_col].strip():
                video_urls.append(row[url_col].strip())
        
        if not video_urls:
            print(f"[スキップ] 行{idx}: 動画URLがありません")
            continue
        
        # 出力ファイル名
        filename = sanitize_filename(keyword) + ".json"
        output_path = output_dir / filename
        
        try:
            process_single_keyword(
                keyword,
                video_urls,
                llm,
                config,
                extraction_prompt,
                synthesis_prompt,
                output_path
            )
            processed += 1
        except Exception as e:
            print(f"[ERROR] キーワード「{keyword}」の処理失敗: {e}\n")
            continue
    
    print(f"\n[完了] {processed}件のキーワードを処理しました")


def main():
    ap = argparse.ArgumentParser(
        description="YouTube動画から哲学記事用の情報を収集"
    )
    
    # 実行モード
    mode_group = ap.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--keyword",
        help="単発実行: 主キーワード"
    )
    mode_group.add_argument(
        "--csv",
        help="CSV一括処理: CSVファイルパス"
    )
    
    # 単発実行用
    ap.add_argument(
        "--urls",
        help="単発実行: 動画URLをカンマ区切りで指定"
    )
    ap.add_argument(
        "--out",
        help="単発実行: 出力JSONパス"
    )
    
    # CSV一括処理用
    ap.add_argument(
        "--out-dir",
        help="CSV一括処理: 出力ディレクトリ"
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="処理上限（0=無制限）"
    )
    
    # プロンプト設定（raw stringでWindows対応）
    ap.add_argument(
        "--extraction-prompt",
        default=r"half_data\prompts\philosophy_video_extraction.txt",
        help="情報抽出プロンプト"
    )
    ap.add_argument(
        "--synthesis-prompt",
        default=r"half_data\prompts\philosophy_video_synthesis.txt",
        help="複数動画統合プロンプト"
    )
    
    args = ap.parse_args()
    
    # 設定読み込み
    config = Config()
    
    # LLMクライアント初期化
    api_key = config.claude_api_key if config.provider == "anthropic" else config.openai_api_key
    llm = LLMClient(config.provider, api_key)
    
    print(f"[起動] プロバイダー: {config.provider}")
    print(f"[起動] モデル: {config.model_draft}")
    
    # プロンプトパス
    extraction_prompt = pathlib.Path(args.extraction_prompt)
    synthesis_prompt = pathlib.Path(args.synthesis_prompt)
    
    if not extraction_prompt.exists():
        raise FileNotFoundError(f"抽出プロンプトが見つかりません: {extraction_prompt}")
    if not synthesis_prompt.exists():
        raise FileNotFoundError(f"統合プロンプトが見つかりません: {synthesis_prompt}")
    
    # 実行モード判定
    if args.keyword:
        # 単発実行
        if not args.urls or not args.out:
            raise SystemExit("--keyword モードでは --urls と --out が必須です")
        
        urls = [u.strip() for u in args.urls.split(",") if u.strip()]
        if not urls:
            raise SystemExit("動画URLを指定してください")
        
        output_path = pathlib.Path(args.out)
        
        process_single_keyword(
            args.keyword,
            urls,
            llm,
            config,
            extraction_prompt,
            synthesis_prompt,
            output_path
        )
    
    else:
        # CSV一括処理
        if not args.out_dir:
            raise SystemExit("--csv モードでは --out-dir が必須です")
        
        csv_path = pathlib.Path(args.csv)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSVファイルが見つかりません: {csv_path}")
        
        output_dir = pathlib.Path(args.out_dir)
        
        process_csv(
            csv_path,
            llm,
            config,
            extraction_prompt,
            synthesis_prompt,
            output_dir,
            args.limit
        )


if __name__ == "__main__":
    main()