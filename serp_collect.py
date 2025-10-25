#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
serp_collect.py - SerpAPI Google検索結果収集ツール

【目的】
CSVファイルからキーワードリストを読み込み、SerpAPI（Google Search）で
各キーワードの検索結果（1ページ目、最大10件）のタイトルとURLを取得し、
CSV/Markdownファイルに保存します。

【必須ライブラリ】
requirements.txt:
    requests
    pandas
    python-dotenv

インストール:
    pip install requests pandas python-dotenv

【APIキー設定】
.envファイルに以下を記載:
    SERPAPI_KEY=your_serpapi_key_here

または環境変数で設定:
    # PowerShell
    $env:SERPAPI_KEY = "your_serpapi_key_here"
    
    # Bash
    export SERPAPI_KEY="your_serpapi_key_here"

【実行例】
# 基本的な使い方
python serp_collect.py --input keywords.csv --output results.csv

# Markdownも出力
python serp_collect.py --input data\search_keywords\boku.csv --output results.csv --markdown results.md

# デバッグ（最初の3件のみ処理）
python serp_collect.py --input data\search_keywords\boku.csv --output out\results_boku.csv  --sleep 1

# PowerShellでの実行例（複数行）
python serp_collect.py `
  --input data\keywords.csv `
  --output out\serp_results.csv `
  --markdown out\serp_results.md `
  --sleep 2 `
  --limit 50

【入力CSVフォーマット】
keyword,status
副業 ブログ 始め方,open
プログラミング 独学,pending

【出力CSVフォーマット】
keyword,status,rank,title,url,domain,is_note,fetched_at
副業 ブログ 始め方,open,1,タイトル例,https://example.com,example.com,FALSE,2025-10-12T10:23:45+09:00
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
import pandas as pd

# .envファイルからの読み込み（オプション）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class SerpCollector:
    """SerpAPI Google検索結果収集クラス"""
    
    SERPAPI_BASE_URL = "https://serpapi.com/search"
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 2, 4]  # 指数バックオフ
    
    def __init__(self, api_key: str, timeout: int = 30):
        """
        初期化
        
        Args:
            api_key: SerpAPI キー
            timeout: APIリクエストタイムアウト（秒）
        """
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        
    def search_google(self, keyword: str) -> List[Dict[str, str]]:
        """
        Google検索を実行し、organic_resultsを取得
        
        Args:
            keyword: 検索キーワード
            
        Returns:
            検索結果リスト [{"title": str, "link": str}, ...]
        """
        params = {
            "engine": "google",
            "q": keyword,
            "api_key": self.api_key,
            "google_domain": "google.co.jp",
            "hl": "ja",
            "gl": "jp",
            "num": 10
        }
        
        for attempt in range(self.MAX_RETRIES):
            try:
                logger.info(f"検索中: '{keyword}' (試行 {attempt + 1}/{self.MAX_RETRIES})")
                response = self.session.get(
                    self.SERPAPI_BASE_URL,
                    params=params,
                    timeout=self.timeout
                )
                
                # ステータスコードチェック
                if response.status_code == 200:
                    data = response.json()
                    
                    # エラーメッセージチェック
                    if "error" in data:
                        logger.error(f"APIエラー: {data['error']}")
                        return []
                    
                    # organic_results取得
                    organic_results = data.get("organic_results", [])
                    results = []
                    
                    for item in organic_results:
                        title = item.get("title", "").strip()
                        link = item.get("link", "").strip()
                        
                        # バリデーション
                        if not title or not link:
                            continue
                        if not link.startswith(("http://", "https://")):
                            continue
                            
                        results.append({"title": title, "link": link})
                    
                    logger.info(f"取得成功: '{keyword}' - {len(results)}件")
                    return results
                    
                elif response.status_code == 429:
                    # レート制限
                    logger.warning(f"レート制限 (429): リトライします...")
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(self.RETRY_DELAYS[attempt])
                        continue
                        
                elif response.status_code >= 500:
                    # サーバーエラー
                    logger.warning(f"サーバーエラー ({response.status_code}): リトライします...")
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(self.RETRY_DELAYS[attempt])
                        continue
                        
                else:
                    # その他のエラー
                    logger.error(f"HTTPエラー {response.status_code}: {response.text[:200]}")
                    return []
                    
            except requests.exceptions.Timeout:
                logger.warning(f"タイムアウト: リトライします...")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAYS[attempt])
                    continue
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"リクエストエラー: {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAYS[attempt])
                    continue
                    
            except Exception as e:
                logger.error(f"予期しないエラー: {e}")
                return []
        
        logger.error(f"最大リトライ回数に達しました: '{keyword}'")
        return []


def load_keywords(input_path: Path) -> List[Dict[str, str]]:
    """
    入力CSVからキーワードリストを読み込み
    
    Args:
        input_path: 入力CSVファイルパス
        
    Returns:
        キーワードリスト [{"keyword": str, "status": str}, ...]
    """
    keywords = []
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # 列名チェック
            if 'keyword' not in reader.fieldnames:
                logger.error("入力CSVに 'keyword' 列が見つかりません")
                return []
                
            for row in reader:
                keyword = row.get('keyword', '').strip()
                status = row.get('status', '').strip()
                
                # 空白行スキップ
                if not keyword:
                    continue
                    
                keywords.append({
                    'keyword': keyword,
                    'status': status
                })
        
        logger.info(f"キーワード読み込み完了: {len(keywords)}件")
        return keywords
        
    except FileNotFoundError:
        logger.error(f"ファイルが見つかりません: {input_path}")
        return []
    except Exception as e:
        logger.error(f"キーワード読み込みエラー: {e}")
        return []


def build_rows(keyword: str, status: str, results: List[Dict[str, str]]) -> List[Dict]:
    """
    検索結果から出力行を構築
    
    Args:
        keyword: 検索キーワード
        status: ステータス
        results: 検索結果リスト
        
    Returns:
        出力行リスト
    """
    rows = []
    seen_urls = set()
    fetched_at = datetime.now().astimezone().isoformat()
    
    for rank, result in enumerate(results, start=1):
        url = result['link']
        
        # 重複URL除外
        if url in seen_urls:
            continue
        seen_urls.add(url)
        
        # ドメイン抽出
        try:
            domain = urlparse(url).netloc
        except Exception:
            domain = ""
        
        # note.comチェック
        is_note = "TRUE" if "note.com" in url.lower() else "FALSE"
        
        rows.append({
            'keyword': keyword,
            'status': status,
            'rank': rank,
            'title': result['title'],
            'url': url,
            'domain': domain,
            'is_note': is_note,
            'fetched_at': fetched_at
        })
    
    return rows


def write_csv(rows: List[Dict], output_path: Path):
    """
    CSVファイルに出力（UTF-8 BOM）
    
    Args:
        rows: 出力行リスト
        output_path: 出力ファイルパス
    """
    if not rows:
        logger.warning("出力データがありません")
        return
    
    try:
        # 親ディレクトリ作成
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # pandas DataFrame使用
        df = pd.DataFrame(rows)
        
        # 列順指定
        columns = ['keyword', 'status', 'rank', 'title', 'url', 'domain', 'is_note', 'fetched_at']
        df = df[columns]
        
        # UTF-8 BOMで出力
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        logger.info(f"CSV出力完了: {output_path} ({len(rows)}行)")
        
    except Exception as e:
        logger.error(f"CSV出力エラー: {e}")


def write_markdown(rows: List[Dict], output_path: Path):
    """
    Markdownファイルに出力
    
    Args:
        rows: 出力行リスト
        output_path: 出力ファイルパス
    """
    if not rows:
        logger.warning("出力データがありません")
        return
    
    try:
        # 親ディレクトリ作成
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # キーワードごとにグループ化
        df = pd.DataFrame(rows)
        grouped = df.groupby('keyword', sort=False)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for keyword, group in grouped:
                # note_flag算出
                note_flag = "TRUE" if (group['is_note'] == "TRUE").any() else "FALSE"
                status = group['status'].iloc[0]
                
                # 見出し
                f.write(f"## {keyword}（status: {status}, note_flag: {note_flag}）\n\n")
                
                # 箇条書き
                for _, row in group.iterrows():
                    f.write(f"- [{row['title']}]({row['url']}) — {row['domain']}\n")
                
                f.write("\n")
        
        logger.info(f"Markdown出力完了: {output_path}")
        
    except Exception as e:
        logger.error(f"Markdown出力エラー: {e}")


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(
        description='SerpAPI Google検索結果収集ツール',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--input',
        type=str,
        required=True,
        help='入力CSVファイルパス（必須）'
    )
    parser.add_argument(
        '--output',
        type=str,
        required=True,
        help='出力CSVファイルパス（必須）'
    )
    parser.add_argument(
        '--markdown',
        type=str,
        help='出力Markdownファイルパス（任意）'
    )
    parser.add_argument(
        '--api-key',
        type=str,
        help='SerpAPI キー（任意、環境変数 SERPAPI_KEY を上書き）'
    )
    parser.add_argument(
        '--sleep',
        type=float,
        default=2.0,
        help='クエリ間のスリープ秒数（既定: 2秒）'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='処理するキーワード数の上限（デバッグ用）'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=30,
        help='APIタイムアウト秒数（既定: 30秒）'
    )
    
    args = parser.parse_args()
    
    # APIキー取得
    api_key = args.api_key or os.environ.get('SERPAPI_KEY')
    if not api_key:
        logger.error("APIキーが設定されていません")
        logger.error("環境変数 SERPAPI_KEY を設定するか、--api-key で指定してください")
        sys.exit(1)
    
    # パス変換
    input_path = Path(args.input)
    output_path = Path(args.output)
    markdown_path = Path(args.markdown) if args.markdown else None
    
    # 入力ファイル確認
    if not input_path.exists():
        logger.error(f"入力ファイルが見つかりません: {input_path}")
        sys.exit(1)
    
    # キーワード読み込み
    keywords = load_keywords(input_path)
    if not keywords:
        logger.error("キーワードが読み込めませんでした")
        sys.exit(1)
    
    # limit適用
    if args.limit and args.limit > 0:
        keywords = keywords[:args.limit]
        logger.info(f"処理制限: 最初の{args.limit}件のみ処理")
    
    # コレクター初期化
    collector = SerpCollector(api_key=api_key, timeout=args.timeout)
    
    # 全結果を格納
    all_rows = []
    
    # キーワードごとに検索
    total = len(keywords)
    for idx, item in enumerate(keywords, start=1):
        keyword = item['keyword']
        status = item['status']
        
        logger.info(f"進捗: {idx}/{total} - キーワード: '{keyword}'")
        
        # 検索実行
        results = collector.search_google(keyword)
        
        # 行構築
        rows = build_rows(keyword, status, results)
        all_rows.extend(rows)
        
        # スリープ（最後のキーワード以外）
        if idx < total and args.sleep > 0:
            logger.info(f"{args.sleep}秒スリープ...")
            time.sleep(args.sleep)
    
    # CSV出力
    logger.info(f"総取得件数: {len(all_rows)}行")
    write_csv(all_rows, output_path)
    
    # Markdown出力（オプション）
    if markdown_path:
        write_markdown(all_rows, markdown_path)
    
    logger.info("処理完了")


if __name__ == '__main__':
    main()