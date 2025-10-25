# batch_orchestrator.py
# -*- coding: utf-8 -*-
"""
バッチ処理スクリプト（リファクタ版）
旧orchestrate_personas.pyの全機能を維持

使い方:
  python batch_orchestrator.py \
    --info data/info.json \
    --persona-dir data/personas \
    --folder-id 1Ay4ROIpd-83CYn8PR_Pbw6M4ADW5XBn7
    
    python batch_orchestrator.py 
  --info data/info/info_bokuno.json 
  --persona-dir data/personas/ren.txt
  --folder-id 1Ay4ROIpd-83CYn8PR_Pbw6M4ADW5XBn7 
  --force-login
  
  
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
ENGINE_FILE = ROOT / "article_generator.py"
PUBLISH_FILE = ROOT / "document_publisher.py"
DEFAULT_OUT_BASE = ROOT / "out_batch"

# ───────────── ユーティリティ ─────────────
def normpath(p: str) -> pathlib.Path:
    """パス正規化"""
    return pathlib.Path(os.path.expandvars(p)).expanduser().resolve()

def run(cmd: List[str]) -> Tuple[int, str, str]:
    """サブプロセス実行"""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
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

# ───────────── メイン ─────────────
def main():
    ap = argparse.ArgumentParser(
        description="記事をバッチ生成してGoogleドキュメント化"
    )
    
    # 必須引数
    ap.add_argument("--info", required=True, 
                   help="ベースとなるinfo.jsonのパス")
    ap.add_argument("--persona-dir", required=True, 
                   help="ペルソナファイル or ペルソナディレクトリ")
    
    # キーワード設定
    ap.add_argument("--keywords_csv", default="", 
                   help="キーワードCSVファイル（省略時はinfo.jsonのprimary_keywordを使用）")
    
    # 出力設定
    ap.add_argument("--out-base", default=str(DEFAULT_OUT_BASE), 
                   help=f"出力ベースディレクトリ（既定: {DEFAULT_OUT_BASE}）")
    
    # LLM温度設定
    ap.add_argument("--t0", type=float, default=0.7, 
                   help="タイトル生成の温度（既定: 0.7）")
    ap.add_argument("--t1", type=float, default=0.6, 
                   help="アウトライン生成の温度（既定: 0.6）")
    ap.add_argument("--t2", type=float, default=0.6, 
                   help="本文生成の温度（既定: 0.6）")
    ap.add_argument("--limit", type=int, default=0, 
                   help="処理キーワード上限（0=無制限）")
    
    # GDoc公開設定
    ap.add_argument("--title-prefix", default="[記事]", 
                   help="GDocタイトルの接頭辞（既定: [記事]）")
    ap.add_argument("--folder-id", default="", 
                   help="GDriveフォルダID（必須ではないが、指定推奨）")
    ap.add_argument("--share-anyone-writer", type=int, default=1, 
                   help="誰でも編集可能にするか（1=有効, 0=無効）")
    ap.add_argument("--force-login", action='store_true', 
                   help="強制的に再ログインする")
    
    # CTA設定
    ap.add_argument("--ad-disclosure", 
                   default="本記事にはアフィリエイトリンクを含みます。", 
                   help="記事冒頭の注意書き")
    ap.add_argument("--mid-cta-text", default="", 
                   help="記事中盤のCTAテキスト（空の場合はスキップ）")
    ap.add_argument("--last-cta-text", default="→無料相談会はこちらから", 
                   help="記事末尾のCTAテキスト")
    
    # スプレッドシート設定（省略時は .env から取得）
    ap.add_argument("--sheet-id", default="", 
                   help="スプレッドシートID（省略時は .env の SHEET_ID）")
    ap.add_argument("--sheet-tab", default="", 
                   help="シート名（省略時は .env の SHEET_NAME）")
    
    args = ap.parse_args()
    
    # 設定読み込み
    config = Config()
    
    # ★変更点：プロンプトパスは config から取得（CLI引数で渡さない）
    # article_generator.py 内部で config.get_prompt_paths() が呼ばれる
    
    # パス検証
    info_path = normpath(args.info)
    persona_arg = normpath(args.persona_dir)
    
    if not info_path.exists():
        raise SystemExit(f"info.json not found: {info_path}")
    if not persona_arg.exists():
        raise SystemExit(f"persona path not found: {persona_arg}")
    if not ENGINE_FILE.exists():
        raise SystemExit(f"article_generator.py not found: {ENGINE_FILE}")
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
    use_csv = bool(args.keywords_csv.strip())
    ready_list: List[str] = []
    
    if use_csv:
        csv_path = normpath(args.keywords_csv)
        if not csv_path.exists():
            raise SystemExit(f"CSV not found: {csv_path}")
        
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            rdr = csv.DictReader(f)
            hdr = [h.strip() for h in (rdr.fieldnames or [])]
            if "keyword" not in hdr or "status" not in hdr:
                raise SystemExit("CSV requires 'keyword' and 'status' columns")
            
            for row in rdr:
                kw = (row.get("keyword") or "").strip()
                st = (row.get("status") or "").strip().upper()
                if kw and (st == "" or st == "READY"):
                    ready_list.append(kw)
        
        if args.limit > 0:
            ready_list = ready_list[:args.limit]
    else:
        info_dict = json.loads(info_path.read_text(encoding="utf-8"))
        pk = (info_dict.get("primary_keyword") or "").strip()
        if not pk:
            raise SystemExit("primary_keyword required in info.json")
        ready_list = [pk]
    
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
        
        for kw in ready_list:
            print(f"\n=== [{p_idx}/{len(personas)}] {persona_name} | {kw} ===")
            
            # 一時info.json作成
            base_info = json.loads(info_path.read_text(encoding="utf-8"))
            base_info["primary_keyword"] = kw
            tmp_info = out_base / f"_tmpinfo_{int(time.time())}_{persona_name}.json"
            tmp_info.write_text(json.dumps(base_info, ensure_ascii=False, indent=2), 
                              encoding="utf-8")
            
            # 出力ディレクトリ
            run_dir = out_base / f"{time.strftime('%Y%m%d_%H%M%S')}_{persona_name}"
            run_dir.mkdir(parents=True, exist_ok=True)
            print(f"[info] outdir: {run_dir}")
            
            # ★変更点：記事生成コマンド（プロンプトパス引数を削除）
            cmd = [
                sys.executable,
                str(ENGINE_FILE),
                "--info", str(tmp_info),
                "--persona_urls", str(persona_urls),
                "--out", str(run_dir),
                "--t0", str(args.t0),
                "--t1", str(args.t1),
                "--t2", str(args.t2),
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
                "--ad-disclosure", args.ad_disclosure,
                "--mid-cta-text", args.mid_cta_text,
                "--last-cta-text", args.last_cta_text,
                "--reflow", "1",
                "--sentences-per-para", "3",
            ]
            
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