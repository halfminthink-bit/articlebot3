# batch_persona_sweep.py
# -*- coding: utf-8 -*-
# https://docs.google.com/spreadsheets/d/1RaysuPyx13mGygHjr2hpVhQCJw2cD6xvadvV9ALxxEU/edit?copiedFromTrash=&gid=1333931101#gid=1333931101
"""
ペルソナ一括処理スクリプト（固定キーワード・プロンプト版）

使い方:
python batch_persona_sweep.py 
    --persona-dir data/personas/hukugyo
    --info data\info\hukugyo\next_franchise_info.json
    --prompts-dir data\prompts\next_fra
    --folder-id 11aS5WCwVWOk8F5g_PIJF5rmK7GA8Uru5 
    --sheet-id 1RaysuPyx13mGygHjr2hpVhQCJw2cD6xvadvV9ALxxEU 
    --sheet-tab fra
"""
import os
import re
import sys
import json
import time
import argparse
import pathlib
import subprocess
from typing import List, Dict, Tuple, Optional

# 共通モジュール
from lib.config import Config
from lib.auth import GoogleAuth

ROOT = pathlib.Path(__file__).resolve().parent
ENGINE_FILE = ROOT / "article_generator.py"
PUBLISH_FILE = ROOT / "document_publisher.py"
DEFAULT_OUT_BASE = ROOT / "out_persona_sweep"

# ------------- ユーティリティ -------------
def normpath(p: str) -> pathlib.Path:
    """パス正規化"""
    return pathlib.Path(os.path.expandvars(p)).expanduser().resolve()

def run(cmd: List[str]) -> Tuple[int, str, str]:
    """サブプロセス実行"""
    proc = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        text=True,
        encoding='utf-8',    # UTF-8エンコーディング指定
        errors='replace'      # デコードエラーを置換
    )
    out, err = proc.communicate()
    return proc.returncode, out or "", err or ""

def discover_personas(persona_dir: pathlib.Path) -> List[Dict[str, str]]:
    """ペルソナファイルを探索（ディレクトリ必須）"""
    if not persona_dir.is_dir():
        raise ValueError(f"persona-dir must be a directory: {persona_dir}")
    
    items: List[Dict[str, str]] = []
    for p in sorted(persona_dir.glob("*.txt")):
        items.append({
            "persona_name": p.stem, 
            "persona_urls": str(p)
        })
    return items

def extract_h1(md_text: str) -> Optional[str]:
    """Markdownからタイトル抽出"""
    for ln in md_text.splitlines():
        if ln.startswith("# "):
            return ln[2:].strip()
    return None

def parse_publish_link(stdout_text: str) -> Optional[str]:
    """標準出力からGDocリンク抽出"""
    for ln in stdout_text.splitlines():
        if ln.startswith("[link] "):
            return ln.split(" ", 1)[1].strip()
    return None

def sheets_append_row(auth: GoogleAuth, spreadsheet_id: str, 
                     sheet_name: str, row: List[str]):
    """スプレッドシートに行追加"""
    sheets = auth.build_service("sheets", "v4")
    sheets.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()

# ------------- メイン -------------
def main():
    ap = argparse.ArgumentParser(
        description="固定キーワード・プロンプトで全ペルソナを処理"
    )
    
    # 基本引数
    ap.add_argument("--persona-dir", required=True, 
                   help="ペルソナディレクトリ（必須・ディレクトリのみ）")
    ap.add_argument("--info", required=True, 
                   help="ベースとなるinfo.jsonのパス")
    ap.add_argument("--prompts-dir", required=True,
                   help="プロンプトディレクトリ（title.txt, outline.txt, draft.txt を含む）")
    
    # 出力設定
    ap.add_argument("--out-base", default=str(DEFAULT_OUT_BASE), 
                   help=f"出力ベースディレクトリ（既定: {DEFAULT_OUT_BASE}）")
    
    # GDoc公開設定
    ap.add_argument("--title-prefix", default="[記事]", 
                   help="GDocタイトルの接頭辞（既定: [記事]）")
    ap.add_argument("--folder-id", default="", 
                   help="GDriveフォルダID")
    ap.add_argument("--share-anyone-writer", type=int, default=1, 
                   help="誰でも編集可能にするか（1=有効, 0=無効）")
    ap.add_argument("--force-login", action='store_true', 
                   help="強制的に再ログインする")
    
    # CTA設定（デフォルトは全て空）
    ap.add_argument("--ad-disclosure", default="", 
                   help="記事冒頭の注意書き（空の場合はスキップ）")
    ap.add_argument("--mid-cta-text", default="", 
                   help="記事中盤のCTAテキスト（空の場合はスキップ）")
    ap.add_argument("--last-cta-text", default="", 
                   help="記事末尾のCTAテキスト（空の場合はスキップ）")
    
    # スプレッドシート設定
    ap.add_argument("--sheet-id", default="", 
                   help="スプレッドシートID（省略時は .env の SHEET_ID）")
    ap.add_argument("--sheet-tab", default="", 
                   help="シート名（省略時は .env の SHEET_NAME）")
    
    args = ap.parse_args()
    
    # 設定読み込み
    config = Config()
    
    # パス検証
    info_path = normpath(args.info)
    if not info_path.exists():
        raise SystemExit(f"info.json not found: {info_path}")
    
    persona_dir = normpath(args.persona_dir)
    if not persona_dir.is_dir():
        raise SystemExit(f"persona-dir must be a directory: {persona_dir}")
    
    prompts_dir = normpath(args.prompts_dir)
    if not prompts_dir.is_dir():
        raise SystemExit(f"prompts-dir not found: {prompts_dir}")
    
    # プロンプトファイル存在チェック
    required_prompts = ["title.txt", "outline.txt", "draft.txt"]
    for fname in required_prompts:
        prompt_file = prompts_dir / fname
        if not prompt_file.exists():
            raise SystemExit(f"Required prompt file not found: {prompt_file}")
    
    if not ENGINE_FILE.exists():
        raise SystemExit(f"article_generator.py not found: {ENGINE_FILE}")
    if not PUBLISH_FILE.exists():
        raise SystemExit(f"document_publisher.py not found: {PUBLISH_FILE}")
    
    # スプレッドシート設定
    sheet_id = (args.sheet_id or config.sheet_id).strip()
    sheet_tab = (args.sheet_tab or config.sheet_name).strip()
    
    # ペルソナ列挙
    personas = discover_personas(persona_dir)
    if not personas:
        raise SystemExit(f"No persona files found in {persona_dir}")
    
    # info.jsonからキーワード取得
    base_info = json.loads(info_path.read_text(encoding="utf-8"))
    primary_keyword = (base_info.get("primary_keyword") or "").strip()
    if not primary_keyword:
        raise SystemExit("primary_keyword required in info.json")
    
    out_base = normpath(args.out_base)
    out_base.mkdir(parents=True, exist_ok=True)
    
    # Google認証
    auth: Optional[GoogleAuth] = None
    if sheet_id and sheet_tab:
        auth = GoogleAuth()
        print(f"[sheets] target: {sheet_id} / {sheet_tab}")
    else:
        print("[sheets] skipped (no SHEET_ID)")
    
    print(f"[info] personas={len(personas)} | keyword={primary_keyword}")
    print(f"[info] prompts: {prompts_dir}")
    
    for p_idx, p in enumerate(personas, start=1):
        persona_name = p["persona_name"]
        persona_urls = p["persona_urls"]
        
        print(f"\n=== [{p_idx}/{len(personas)}] {persona_name} | {primary_keyword} ===")
        
        # 一時info.json作成
        tmp_info_data = dict(base_info)
        tmp_info_data["primary_keyword"] = primary_keyword
        tmp_info = out_base / f"_tmpinfo_{int(time.time())}_{persona_name}.json"
        tmp_info.write_text(json.dumps(tmp_info_data, ensure_ascii=False, indent=2), 
                          encoding="utf-8")
        
        # 出力ディレクトリ
        run_dir = out_base / f"{time.strftime('%Y%m%d_%H%M%S')}_{persona_name}"
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"[info] outdir: {run_dir}")
        
        # 記事生成コマンド
        cmd = [
            sys.executable,
            str(ENGINE_FILE),
            "--info", str(tmp_info),
            "--persona_urls", str(persona_urls),
            "--title_prompt", str(prompts_dir / "title.txt"),
            "--outline_prompt", str(prompts_dir / "outline.txt"),
            "--draft_prompt", str(prompts_dir / "draft.txt"),
            "--out", str(run_dir),
        ]
        
        rc, out_text, err_text = run(cmd)
        if rc != 0:
            print(f"[ERROR] article generation failed\n{err_text or out_text or '(no output)'}")
            continue
        if out_text and out_text.strip():
            print(out_text.strip())
        
        # GDoc公開
        md_path = run_dir / "article.md"
        if not md_path.exists():
            print("[ERROR] article.md not found")
            continue
        
        publish_cmd = [
            sys.executable,
            str(PUBLISH_FILE),
            "--md", str(md_path),
            "--title-prefix", args.title_prefix,
            "--share-anyone-writer", str(int(args.share_anyone_writer)),
            "--reflow", "1",
            "--sentences-per-para", "3",
        ]
        
        # CTAは空でない場合のみ追加
        if args.ad_disclosure:
            publish_cmd += ["--ad-disclosure", args.ad_disclosure]
        if args.mid_cta_text:
            publish_cmd += ["--mid-cta-text", args.mid_cta_text]
        if args.last_cta_text:
            publish_cmd += ["--last-cta-text", args.last_cta_text]
        
        if args.folder_id:
            publish_cmd += ["--folder-id", args.folder_id]
        if args.force_login:
            publish_cmd += ["--force-login", "1"]
        
        rc2, out2, err2 = run(publish_cmd)
        if rc2 != 0:
            print(f"[ERROR] publishing failed\n{err2 or out2 or '(no output)'}")
            continue
        if out2 and out2.strip():
            print(out2.strip())
        
        # タイトル・リンク抽出
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        title = extract_h1(md_text) or md_path.stem
        link = parse_publish_link(out2) or ""
        
        # スプレッドシート追記（persona | title | gdoc_url の3列）
        if auth and sheet_id and sheet_tab:
            try:
                sheets_append_row(auth, sheet_id, sheet_tab, 
                                [persona_name, title, link])
                print(f"[ok] Sheet updated: {persona_name} | {title}")
            except Exception as e:
                print(f"[warn] sheet append failed: {e}")
    
    print("\n[ALL DONE]")

if __name__ == "__main__":
    main()