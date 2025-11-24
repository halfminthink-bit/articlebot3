# batch_orchestrator.py
# -*- coding: utf-8 -*-
"""
バッチ処理スクリプト(リファクタ版・temperature削除版)
旧 orchestrate_personas.py の全機能を維持
note-asp
https://docs.google.com/spreadsheets/d/1izdh3e2GJP1VbNM4eoUHX0-1RQ1x7NvceKBC2Ju4Krc/edit?usp=sharing

やめませんか
https://docs.google.com/spreadsheets/d/1XEOsAIiKNBe5IwqGmvV87ui8tVrvyA6TF8wVPkW_zNA/edit?gid=0#gid=0

半分思考
https://docs.google.com/spreadsheets/d/1DodLnBNvxlmgK5kKE5niRO7YbMNYOWbS3gnB_umg26g/edit?gid=0#gid=0

使い方:
  python batch_orchestrator_bank.py 
    --persona-dir data\personas\note\saito.txt
    --keywords_csv data\keywords\ginkou_yabai02.csv
    --folder-id 1WJNsfUl5Arst58E8b2LPo1h7A0inlwlI 
    --sheet-id  1XEOsAIiKNBe5IwqGmvV87ui8tVrvyA6TF8wVPkW_zNA
    --sheet-tab kasegenai
"""
import os
import re
import sys
import csv
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
CWD = pathlib.Path.cwd()
ENGINE_FILE = ROOT / "article_generator_bank.py"
PUBLISH_FILE = ROOT / "document_publisher.py"
DEFAULT_OUT_BASE = ROOT / "out_batch"

# ------------- ユーティリティ -------------
def normpath(p: str) -> pathlib.Path:
    """パス正規化"""
    return pathlib.Path(os.path.expandvars(p)).expanduser().resolve()

def run(cmd: List[str]) -> Tuple[int, str, str]:
    """サブプロセス実行（Windows UTF-8対応）"""
    # Windows環境でのUTF-8エンコーディング指定
    proc = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE, 
        text=True,
        encoding='utf-8',  # UTF-8を明示指定
        errors='replace'   # デコードエラーを置換
    )
    out, err = proc.communicate()
    # Noneの場合は空文字列に変換
    out = out or ""
    err = err or ""
    return proc.returncode, out, err

def discover_personas(path_like: pathlib.Path) -> List[Dict[str, str]]:
    """ペルソナファイルを探索"""
    items: List[Dict[str, str]] = []
    if path_like.is_file():
        items.append({"persona_name": path_like.stem, 
                     "persona_urls": str(path_like)})
    elif path_like.is_dir():
        for p in sorted(path_like.glob("*.txt")):
            items.append({"persona_name": p.stem, 
                         "persona_urls": str(p)})
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
        description="記事をバッチ生成してGoogleドキュメント化"
    )
    
    # 基本引数
    ap.add_argument("--info", default="", 
                   help="ベースとなるinfo.jsonのパス(CSVモード時は不要)")
    ap.add_argument("--persona-dir", required=True, 
                   help="ペルソナファイル or ペルソナディレクトリ")
    
    # キーワード設定
    ap.add_argument("--keywords_csv", default="", 
                   help="キーワードCSVファイル(省略時はinfo.jsonのprimary_keywordを使用)")
    
    # 出力設定
    ap.add_argument("--out-base", default=str(DEFAULT_OUT_BASE), 
                   help=f"出力ベースディレクトリ(既定: {DEFAULT_OUT_BASE})")
    
    # 処理制限
    ap.add_argument("--limit", type=int, default=0, 
                   help="処理キーワード上限(0=無制限)")
    
    # GDoc公開設定
    ap.add_argument("--title-prefix", default="[記事]", 
                   help="GDocタイトルの接頭辞(既定: [記事])")
    ap.add_argument("--folder-id", default="", 
                   help="GDriveフォルダID")
    ap.add_argument("--share-anyone-writer", type=int, default=1, 
                   help="誰でも編集可能にするか(1=有効, 0=無効)")
    ap.add_argument("--force-login", action='store_true', 
                   help="強制的に再ログインする")
    
    # CTA設定(デフォルトは全て空)
    ap.add_argument("--ad-disclosure", default="", 
                   help="記事冒頭の注意書き(空の場合はスキップ)")
    ap.add_argument("--mid-cta-text", default="", 
                   help="記事中盤のCTAテキスト(空の場合はスキップ)")
    ap.add_argument("--last-cta-text", default="", 
                   help="記事末尾のCTAテキスト(空の場合はスキップ)")
    
    # スプレッドシート設定
    ap.add_argument("--sheet-id", default="", 
                   help="スプレッドシートID(省略時は .env の SHEET_ID)")
    ap.add_argument("--sheet-tab", default="", 
                   help="シート名(省略時は .env の SHEET_NAME)")
    
    args = ap.parse_args()
    
    # 設定読み込み
    config = Config()
    
    # パス検証
    use_csv = bool(args.keywords_csv.strip())
    
    if not use_csv:
        # 単発モード時はinfoが必須
        if not args.info:
            raise SystemExit("--info is required when not using CSV mode")
        info_path = normpath(args.info)
        if not info_path.exists():
            raise SystemExit(f"info.json not found: {info_path}")
    
    persona_arg = normpath(args.persona_dir)
    
    if not persona_arg.exists():
        raise SystemExit(f"persona path not found: {persona_arg}")
    if not ENGINE_FILE.exists():
        raise SystemExit(f"article_generator_bank.py not found: {ENGINE_FILE}")
    if not PUBLISH_FILE.exists():
        raise SystemExit(f"document_publisher.py not found: {PUBLISH_FILE}")
    
    # スプレッドシート設定
    sheet_id = (args.sheet_id or config.sheet_id).strip()
    sheet_tab = (args.sheet_tab or config.sheet_name).strip()
    
    # ペルソナ列挙
    personas = discover_personas(persona_arg)
    if not personas:
        raise SystemExit("persona files not found")
    
    # キーワード読み込み
    ready_list: List[Dict[str, any]] = []
    
    if use_csv:
        csv_path = normpath(args.keywords_csv)
        if not csv_path.exists():
            raise SystemExit(f"CSV not found: {csv_path}")
        
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            rdr = csv.DictReader(f)
            hdr = [h.strip() for h in (rdr.fieldnames or [])]
            if "keyword" not in hdr or "info" not in hdr or "prompts" not in hdr:
                raise SystemExit("CSV requires 'keyword', 'info', and 'prompts' columns")
            
            rows_data = []
            for idx, row in enumerate(rdr, start=2):
                kw = (row.get("keyword") or "").strip()
                info_str = (row.get("info") or "").strip()
                prompts_str = (row.get("prompts") or "").strip()
                
                # 空欄チェック
                if not kw:
                    raise SystemExit(f"CSV行{idx}: 'keyword' が空です")
                if not info_str:
                    raise SystemExit(f"CSV行{idx}: 'info' が空です(keyword: {kw})")
                if not prompts_str:
                    raise SystemExit(f"CSV行{idx}: 'prompts' が空です(keyword: {kw})")
                
                # パス検証
                info_file = normpath(info_str)
                if not info_file.exists():
                    raise SystemExit(f"CSV行{idx}: info.json が見つかりません: {info_file}")
                
                prompts_dir = normpath(prompts_str)
                if not prompts_dir.is_dir():
                    raise SystemExit(f"CSV行{idx}: プロンプトディレクトリが見つかりません: {prompts_dir}")
                
                # プロンプトファイル存在チェック
                required_prompts = ["title.txt", "outline.txt", "draft.txt"]
                for fname in required_prompts:
                    prompt_file = prompts_dir / fname
                    if not prompt_file.exists():
                        raise SystemExit(f"CSV行{idx}: {fname} が見つかりません: {prompt_file}")
                
                rows_data.append({
                    "keyword": kw,
                    "info_path": info_file,
                    "prompts_dir": prompts_dir
                })
            
            ready_list = rows_data
        
        if args.limit > 0:
            ready_list = ready_list[:args.limit]
    else:
        info_dict = json.loads(info_path.read_text(encoding="utf-8"))
        pk = (info_dict.get("primary_keyword") or "").strip()
        if not pk:
            raise SystemExit("primary_keyword required in info.json")
        ready_list = [{
            "keyword": pk,
            "info_path": info_path,
            "prompts_dir": None
        }]
    
    out_base = normpath(args.out_base)
    out_base.mkdir(parents=True, exist_ok=True)
    
    # Google認証
    auth: Optional[GoogleAuth] = None
    if sheet_id and sheet_tab:
        auth = GoogleAuth()
        print(f"[sheets] target: {sheet_id} / {sheet_tab}")
    else:
        print("[sheets] skipped (no SHEET_ID)")
    
    print(f"[info] personas={len(personas)} | keywords={len(ready_list)} (csv={use_csv})")
    
    processed = 0
    for p_idx, p in enumerate(personas, start=1):
        persona_name = p["persona_name"]
        persona_urls = p["persona_urls"]
        
        for item in ready_list:
            kw = item["keyword"]
            item_info_path = item["info_path"]
            item_prompts_dir = item["prompts_dir"]
            
            print(f"\n=== [{p_idx}/{len(personas)}] {persona_name} | {kw} ===")
            
            # 一時info.json作成
            base_info = json.loads(item_info_path.read_text(encoding="utf-8"))
            base_info["primary_keyword"] = kw
            tmp_info = out_base / f"_tmpinfo_{int(time.time())}_{persona_name}.json"
            tmp_info.write_text(json.dumps(base_info, ensure_ascii=False, indent=2), 
                              encoding="utf-8")
            
            # 出力ディレクトリ
            run_dir = out_base / f"{time.strftime('%Y%m%d_%H%M%S')}_{persona_name}"
            run_dir.mkdir(parents=True, exist_ok=True)
            print(f"[info] outdir: {run_dir}")
            print(f"[info] info: {item_info_path}")
            if item_prompts_dir:
                print(f"[info] prompts: {item_prompts_dir}")
            
            # 記事生成コマンド(temperature削除)
            cmd = [
                sys.executable,
                str(ENGINE_FILE),
                "--info", str(tmp_info),
                "--persona_urls", str(persona_urls),
                "--out", str(run_dir),
            ]
            
            # プロンプトディレクトリが指定されている場合は追加
            if item_prompts_dir:
                cmd += [
                    "--title_prompt", str(item_prompts_dir / "title.txt"),
                    "--outline_prompt", str(item_prompts_dir / "outline.txt"),
                    "--draft_prompt", str(item_prompts_dir / "draft.txt"),
                ]
            
            rc, out_text, err_text = run(cmd)
            if rc != 0:
                print(f"[ERROR] article generation failed\n{err_text or out_text}")
                continue
            if out_text.strip():
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
                print(f"[ERROR] publishing failed\n{err2 or out2}")
                continue
            if out2.strip():
                print(out2.strip())
            
            # タイトル・リンク抽出
            md_text = md_path.read_text(encoding="utf-8", errors="ignore")
            title = extract_h1(md_text) or md_path.stem
            # タイトルから「」『』""を削除
            title = title.replace('「', '').replace('」', '')
            title = title.replace('『', '').replace('』', '')
            title = title.replace('"', '').replace('"', '')
            title = title.strip()
            link = parse_publish_link(out2) or ""
            
            # スプレッドシート追記
            if auth and sheet_id and sheet_tab:
                try:
                    sheets_append_row(auth, sheet_id, sheet_tab, 
                                    [persona_name, title, link])
                    print(f"[ok] Sheet updated: {persona_name} | {title}")
                except Exception as e:
                    print(f"[warn] sheet append failed: {e}")
            
            processed += 1
            if args.limit and processed >= args.limit:
                print("[info] limit reached")
                return
    
    print("\n[ALL DONE]")

if __name__ == "__main__":
    main()