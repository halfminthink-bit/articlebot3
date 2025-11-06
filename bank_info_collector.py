#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
銀行情報収集スクリプト v2.1（問題点特化版）
その銀行で働く人に「このままでいいのか？」と思わせる情報に特化

環境変数（.envファイルに設定）:
  BRAVE_API_KEY=your_api_key
  CLAUDE_API_KEY=sk-ant-...
  PROVIDER=anthropic
  
使い方:
  python bank_info_collector.py --csv data\keywords\collect_info.csv --output output/
  
特徴:
  - 重要URL 12件に厳選（質重視）
  - 3つの視点（地域・組織・事業）から問題を構造化
  - キャリアアドバイス等の不要な情報は削除
  - LINE誘導に必要な「不安定さ・問題点」を強調
"""

import os
import sys
import csv
import json
import argparse
import pathlib
import time
import re
import requests
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from datetime import datetime

# 共通モジュール
try:
    from lib.config import Config
    from lib.llm import LLMClient
except ImportError:
    print("[ERROR] lib/モジュールが見つかりません")
    sys.exit(1)


# ========================================
# ユーティリティ関数
# ========================================

def brave_search(query: str, api_key: str, count: int = 10) -> List[Dict[str, str]]:
    """Brave Search APIで検索"""
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key
    }
    params = {"q": query, "count": count}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", "")
            })
        return results
    except Exception as e:
        print(f"  [ERROR] Search failed: {e}")
        return []


def fetch_url_content(url: str, timeout: int = 15) -> Optional[Dict[str, str]]:
    """URLから本文を取得（requests + BeautifulSoup）"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        
        # エンコーディング推定
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 不要なタグ除去
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        
        # タイトル取得
        title = soup.title.string if soup.title else ""
        
        # 本文取得
        text = soup.get_text(separator='\n', strip=True)
        
        # 空白行削除
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)
        
        return {
            "url": url,
            "title": title.strip() if title else "",
            "text": text[:50000],  # 最大50KB（Claude contextに収まる範囲）
            "length": len(text)
        }
    except Exception as e:
        print(f"    [WARN] Fetch failed ({url[:60]}...): {e}")
        return None


def is_relevant_url(url: str, bank_name: str) -> bool:
    """銀行情報として有用なURLか判定"""
    url_lower = url.lower()
    
    # 優先度高いドメイン
    priority_domains = [
        'openwork.jp', 'en-hyouban.com', 'careerconnection.jp',  # 口コミサイト
        'jp.fsc.go.jp', 'edinet-fsa.go.jp',  # 金融庁・EDINET
        'e-stat.go.jp', 'stat.go.jp',  # 統計データ
        'nikkei.com', 'asahi.com', 'mainichi.jp',  # 大手メディア
    ]
    
    if any(domain in url_lower for domain in priority_domains):
        return True
    
    # 除外ドメイン
    exclude_domains = [
        'wikipedia.org', 'twitter.com', 'x.com', 'facebook.com', 
        'instagram.com', 'youtube.com', 'tiktok.com',
        'amazon.co.jp', 'rakuten.co.jp', 'yahoo.co.jp',
    ]
    
    if any(domain in url_lower for domain in exclude_domains):
        return False
    
    return True


# ========================================
# 銀行情報収集クラス
# ========================================

class BankInfoCollectorV2:
    """銀行情報収集クラス v2.1（問題点特化版）"""
    
    # 戦略的キーワード分類（問題点に特化）
    KEYWORD_CATEGORIES = {
        "ネガティブ情報": [
            "やめたい", "つらい", "ブラック", "給料安い", "稼げない"
        ],
        "構造的問題": [
            "店舗統廃合", "リストラ", "人口減少", "地域経済"
        ],
        "キャリア実態": [
            "年収", "昇進", "転勤", "離職率", "残業"
        ],
        "評判・口コミ": [
            "評判", "口コミ", "OpenWork", "ライトハウス"
        ],
        "企業情報": [
            "有価証券報告書", "IR資料", "決算説明会", "経営統合"
        ]
    }
    
    def __init__(self, config: Config, llm: LLMClient):
        self.config = config
        self.llm = llm
        self.brave_api_key = config.brave_api_key
        
        if not self.brave_api_key:
            raise RuntimeError("BRAVE_API_KEY が設定されていません")
    
    def collect_bank_info(self, bank_name: str) -> Dict[str, Any]:
        """銀行情報を収集して構造化JSONを生成"""
        print(f"\n{'='*60}")
        print(f"[START] {bank_name} の情報収集開始")
        print(f"{'='*60}")
        
        # Phase 1: 検索 → 重要URL発見
        print("\n[PHASE 1] Brave Search実行")
        search_results = self._search_all_keywords(bank_name)
        print(f"  → 検索完了: {len(search_results)}件")
        
        # Phase 2: 重要URL選択（12件に厳選）→ 本文取得
        print("\n[PHASE 2] 重要URL本文取得（上位12件）")
        important_urls = self._select_important_urls(search_results, bank_name, limit=12)
        fetched_contents = self._fetch_contents(important_urls)
        print(f"  → 取得完了: {len(fetched_contents)}件")
        
        # Phase 3: Claude で深い分析 → JSON生成
        print("\n[PHASE 3] Claude分析 → JSON生成")
        bank_json = self._analyze_with_claude(bank_name, search_results, fetched_contents)
        
        print(f"\n{'='*60}")
        print(f"[COMPLETE] {bank_name} の情報収集完了")
        print(f"{'='*60}\n")
        
        return bank_json
    
    def _search_all_keywords(self, bank_name: str) -> List[Dict[str, Any]]:
        """全キーワードで検索"""
        all_results = []
        total_keywords = sum(len(kws) for kws in self.KEYWORD_CATEGORIES.values())
        current = 0
        
        for category, keywords in self.KEYWORD_CATEGORIES.items():
            print(f"\n  [{category}]")
            for keyword in keywords:
                current += 1
                query = f"{bank_name} {keyword}"
                print(f"    [{current}/{total_keywords}] {keyword}", end=" ", flush=True)
                
                results = brave_search(query, self.brave_api_key, count=10)
                print(f"→ {len(results)}件")
                
                all_results.append({
                    "category": category,
                    "keyword": keyword,
                    "query": query,
                    "results": results
                })
                
                time.sleep(0.5)  # API制限対策
        
        return all_results
    
    def _select_important_urls(self, search_results: List[Dict], bank_name: str, limit: int = 12) -> List[str]:
        """重要URLを選択（優先度順・重複排除）"""
        url_scores = {}  # {url: score}
        
        for result in search_results:
            category = result["category"]
            results = result["results"]
            
            # カテゴリーごとの重要度（問題点特化）
            category_weight = {
                "ネガティブ情報": 1.5,
                "構造的問題": 1.4,
                "キャリア実態": 1.3,
                "評判・口コミ": 1.2,
                "企業情報": 1.0
            }
            weight = category_weight.get(category, 1.0)
            
            # 上位5件を重視
            for idx, item in enumerate(results[:5]):
                url = item["url"]
                if not is_relevant_url(url, bank_name):
                    continue
                
                # スコア計算（順位 + カテゴリー重要度）
                position_score = (5 - idx) / 5  # 0.2〜1.0
                total_score = position_score * weight
                
                if url in url_scores:
                    url_scores[url] += total_score  # 複数カテゴリーで出現したら加算
                else:
                    url_scores[url] = total_score
        
        # スコア順にソート
        sorted_urls = sorted(url_scores.items(), key=lambda x: x[1], reverse=True)
        
        # 上位N件を返す
        return [url for url, score in sorted_urls[:limit]]
    
    def _fetch_contents(self, urls: List[str]) -> List[Dict[str, str]]:
        """URLから本文を取得"""
        contents = []
        for i, url in enumerate(urls, 1):
            print(f"    [{i}/{len(urls)}] {url[:60]}...", end=" ", flush=True)
            content = fetch_url_content(url)
            if content:
                contents.append(content)
                print(f"OK ({content['length']}文字)")
            else:
                print("SKIP")
            time.sleep(0.3)  # サーバー負荷軽減
        return contents
    
    def _analyze_with_claude(self, bank_name: str, 
                            search_results: List[Dict], 
                            fetched_contents: List[Dict]) -> Dict[str, Any]:
        """Claudeで深い分析 → JSON生成"""
        
        # 検索結果サマリー作成
        search_summary = []
        for result in search_results:
            category = result["category"]
            keyword = result["keyword"]
            items = result["results"][:5]  # 各キーワード上位5件
            
            search_summary.append({
                "category": category,
                "keyword": keyword,
                "results": [
                    {
                        "title": item["title"],
                        "description": item["description"],
                        "url": item["url"]
                    }
                    for item in items
                ]
            })
        
        # URL本文（全文）
        content_texts = []
        for content in fetched_contents:
            content_texts.append({
                "url": content["url"],
                "title": content["title"],
                "text": content["text"]  # 全文（最大50KB）
            })
        
        # Claudeプロンプト構築
        system_prompt = self._build_system_prompt(bank_name)
        user_prompt = self._build_user_prompt(bank_name, search_summary, content_texts)
        
        # Claude実行（200K contextフル活用）
        print(f"  → Claude分析開始（context: 約{len(user_prompt)//1000}K文字）...")
        response = self.llm.generate(
            model="claude-sonnet-4-5",  # Claude Sonnet 4.5 (2025年最新)
            system=system_prompt,
            user=user_prompt,
            max_tokens=16000  # 最大出力
        )
        
        # JSON抽出
        bank_json = self._extract_json(response)
        
        return bank_json
    
    def _build_system_prompt(self, bank_name: str) -> str:
        """システムプロンプト構築"""
        return f"""あなたは金融業界の深い洞察を持つアナリストです。
{bank_name}について、膨大な検索結果とURL本文から、**その銀行固有の問題・不安定さ**を徹底的に掘り起こしてください。

【最重要ミッション】
この情報は、{bank_name}で働く20〜40代の銀行員が読みます。
彼らに「このままでいいのか？」と思わせる材料を提供することが目的です。

1. **3つの視点から問題を構造化**
   - ①地域の問題（人口減少・経済縮小・競合激化）
   - ②組織の問題（給与・昇進・転勤・労働環境・離職率）
   - ③事業の問題（店舗統廃合・収益悪化・デジタル化の遅れ・経営統合）

2. **その銀行固有の問題を最優先**
   - 「どの銀行にも当てはまる話」は不要
   - 地域特性・歴史・組織文化・具体的なエピソードを重視
   - 「○○支店が統廃合された」「○○年に△△があった」等の具体性

3. **数字の裏側を読み解く**
   - 公式発表と口コミの矛盾を見つける
   - 「○○万円」「○○%減少」等の具体的な数字
   - 数字が意味する「人の動き」「キャリアへの影響」を推測

4. **働く人の視点で書く**
   - 「安定」の裏にあるリスクを可視化
   - 給与・昇進枠・転勤負担・ノルマの実態
   - 口コミの生の声を具体的に引用

【絶対に書かない内容】
- キャリアアドバイス（「〜すべき」「〜がおすすめ」）
- 一般論（「銀行業界全体が〜」）
- ポジティブすぎる美辞麗句
- 情報源がない内容（推測・創作禁止）
- 「情報なし」「不明」（情報がない項目は省略）

【出力形式】
群馬銀行.jsonと同じ構造の詳細なJSON（必ず有効なJSON形式）
ただし、以下のセクションは削除:
  - キャリア視点での考察（20代/30代/40代/50代別のアドバイス）
  - 記事執筆時のポイント（これは不要）"""

    def _build_user_prompt(self, bank_name: str, 
                          search_summary: List[Dict], 
                          content_texts: List[Dict]) -> str:
        """ユーザープロンプト構築"""
        
        # 検索結果サマリー
        search_json = json.dumps(search_summary, ensure_ascii=False, indent=2)
        
        # URL本文（長さ制限：合計150KB程度まで）
        content_parts = []
        total_length = 0
        max_total = 150000
        
        for content in content_texts:
            url = content["url"]
            title = content["title"]
            text = content["text"]
            
            # 1URL あたり最大10KB
            text_preview = text[:10000]
            
            content_parts.append(f"""
■ URL: {url}
■ タイトル: {title}
■ 本文:
{text_preview}
{'[...続く]' if len(text) > 10000 else ''}
""")
            
            total_length += len(text_preview)
            if total_length > max_total:
                break
        
        contents_text = "\n\n".join(content_parts)
        
        return f"""# {bank_name} の情報収集結果

## 検索結果サマリー（全カテゴリー・全キーワード）
{search_json}

## URL本文（上位{len(content_parts)}件）
{contents_text}

---

上記の情報から、**{bank_name}固有の問題・不安定さ**を徹底的に分析し、
群馬銀行.jsonと同じ形式の詳細なJSONを生成してください。

【必須セクション】
1. **基本情報**（正式名称、本店所在地、従業員数、店舗数、設立年、展開エリア等）

2. **特徴・ポジティブ情報**（この銀行の強み・特色）
   ※ただし、美辞麗句ではなく、事実ベースで簡潔に

3. **ネガティブ情報**
   - よくある不満・懸念（口コミから具体的に引用）
   - 長期課題（構造的な問題）

4. **固有の課題・地域特性**（最重要パート）
   
   4-1. **市場環境**
   - 営業エリアの人口動態（現状・将来推計・高齢化率・若年女性減少・消滅可能性自治体）
   - 地域経済の特性（産業構造・主力産業・リスク・好況期/不況期の影響）
   - 競合状況（県内・隣県・メガバンク・統合の動き）
   
   4-2. **組織・人事**
   - 給与水準（有価証券報告書 vs 口コミサイトの差、若手実態、地銀比較、県内比較、課題）
   - 昇進スピード（標準、支店長、特徴、性別、女性管理職）
   - 転勤頻度（頻度、エリア、負担、影響）
   - 離職率（傾向、理由、退職後）
   - 働き方（残業、休暇、土日、課題、ノルマ）
   
   4-3. **事業戦略**
   - 店舗戦略（統廃合実績、統廃合例、計画、理由、影響、人員）
   - デジタル化（進捗、評価、課題、機会）
   - 収益構造（貸出、預貸利鞘、手数料収入、課題、海外）
   - 中期経営計画（テーマ、目標、施策、進捗）
   - 経営統合（相手先、発表、規模、狙い）

5. **世間の評価**
   - 総合所感（地元での評価、不満点）
   - 口コミ傾向（顧客、従業員、ポジティブ、ネガティブ）
   - OpenWorkスコア
   - 退職検討理由

6. **監視キーワード**（この銀行で検索されそうなネガティブワード一覧）

7. **競合他行との比較**（簡潔に）

8. **meta**（generated_at、schema_version、sources、注意事項）

【重要指示】
- 全ての数値には単位を付ける（"514万円"、"1524名"、"2000年"）
- 具体的なエピソード・事例を優先
- 矛盾・ギャップ・裏側を読み解く
- 口コミは具体的に引用（「〜という声」）
- 情報源がない内容は絶対に書かない

【削除すべき内容】
- キャリア視点での考察（20代/30代/40代/50代別）
- 記事執筆時のポイント
- その他、アドバイス的な内容

必ず有効なJSON形式で出力してください。"""

    def _extract_json(self, response: str) -> Dict[str, Any]:
        """Claude応答からJSON抽出"""
        # JSONブロック抽出
        json_match = re.search(r'```json\s*(\{.+?\})\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # ``` なしの場合、{ } で囲まれた部分を探す
            json_match = re.search(r'(\{.+\})', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # 最終手段：全体をJSONとして解釈
                json_str = response.strip()
        
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"  [ERROR] JSON解析失敗: {e}")
            print(f"  [ERROR] 応答の先頭500文字:\n{response[:500]}")
            # エラー時は最低限の構造を返す
            return {
                "正式名称": "情報収集失敗",
                "error": str(e),
                "raw_response": response[:1000]
            }


# ========================================
# メイン処理
# ========================================

def main():
    parser = argparse.ArgumentParser(description="銀行情報収集 v2.1（問題点特化版）")
    parser.add_argument("--csv", required=True, help="銀行リストCSV（列: bank_name）")
    parser.add_argument("--output", default="output", help="出力ディレクトリ（デフォルト: output）")
    parser.add_argument("--limit", type=int, default=0, help="処理上限（0=全件）")
    
    args = parser.parse_args()
    
    # 設定読み込み
    config = Config()
    
    # プロバイダーチェック
    if config.provider != "anthropic":
        print("[WARN] PROVIDER=anthropic を推奨（.envで設定）")
        print("[WARN] 現在のPROVIDER:", config.provider)
    
    # LLMクライアント初期化
    api_key = config.claude_api_key if config.provider == "anthropic" else config.openai_api_key
    llm = LLMClient(config.provider, api_key)
    
    print(f"[BOOT] {config.provider} / claude-sonnet-4-5")
    print(f"[BOOT] Brave Search API: {'設定済み' if config.brave_api_key else '未設定'}")
    
    # CSV読み込み
    csv_path = pathlib.Path(args.csv)
    if not csv_path.exists():
        print(f"[ERROR] CSVファイルが見つかりません: {csv_path}")
        sys.exit(1)
    
    with csv_path.open("r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    if "bank_name" not in reader.fieldnames:
        print("[ERROR] CSVに 'bank_name' 列が必要です")
        sys.exit(1)
    
    # 出力ディレクトリ作成
    output_dir = pathlib.Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 処理対象抽出
    banks_to_process = [row["bank_name"].strip() for row in rows if row["bank_name"].strip()]
    if args.limit > 0:
        banks_to_process = banks_to_process[:args.limit]
    
    print(f"[INFO] 処理対象: {len(banks_to_process)}行")
    
    # 収集実行
    collector = BankInfoCollectorV2(config, llm)
    
    for i, bank_name in enumerate(banks_to_process, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(banks_to_process)}] {bank_name}")
        print(f"{'='*60}")
        
        try:
            bank_json = collector.collect_bank_info(bank_name)
            
            # ファイル名作成（安全な文字列に変換）
            safe_name = re.sub(r'[^\w\-_]', '_', bank_name)
            output_path = output_dir / f"{safe_name}.json"
            
            # JSON保存
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(bank_json, f, ensure_ascii=False, indent=2)
            
            print(f"\n[OK] {bank_name} → {output_path}")
            
        except Exception as e:
            print(f"\n[ERROR] {bank_name} の処理に失敗: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*60}")
    print(f"[ALL DONE] {len(banks_to_process)}件処理完了")
    print(f"  出力先: {output_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()