# -*- coding: utf-8 -*-
"""
このスクリプトは three_call_article.py → publish_gdoc_html.py の実行に加えて、
.env の SHEET_ID / SHEET_NAME を読み取り、生成物（persona / タイトル / GDoc URL）を
Google スプレッドシートへ 1 行追記します。
Gドライブ articles の保存 → 1Ay4ROIpd-83CYn8PR_Pbw6M4ADW5XBn7

使い方（例）:
  python orchestrate_personas.py 
    --info data\info\info_aws.json 
    --persona-dir data\personas\AWS.txt
    --folder-id 1Ay4ROIpd-83CYn8PR_Pbw6M4ADW5XBn7
    --force-login 
    
python orchestrate_personas.py 
    --info data\info\info_bokuno.json 
    --persona-dir data\personas\00_jiro.txt
    --keywords_csv data\keywords\boku.csv
    --folder-id 1Ay4ROIpd-83CYn8PR_Pbw6M4ADW5XBn7
    
必要ファイル:
- three_call_article.py / publish_gdoc_html.py（同ディレクトリ）
- credentials.json（Google API）
- .env（少なくとも以下）
    SHEET_ID=1KtnOdlsENINR9kiDuRH2l3q869lcvss4EeuJEXcMPHA
    SHEET_NAME=Articles
    PROMPT_DIR=.../goods_prompts
    PROMPT_TITLE=title_prompt_pre_outline.txt
    PROMPT_OUTLINE=outline_prompt_2call.txt
    PROMPT_DRAFT=draft_prompt_2call.txt

メモ:
- --sheet-id/--sheet-tab を未指定の場合、.env の SHEET_ID/SHEET_NAME を使用します。
- publish_gdoc_html.py の標準出力内の行 "[link] <url>" を検出して GDoc URL に採用します。
- GDoc タイトルは article.md の先頭の「# 見出し」から抽出（なければファイル名）。
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

# ===== dotenv（任意：無ければ .env 読み込みをスキップ） =====
try:
    from dotenv import load_dotenv
except Exception:  # dotenv 未導入でも動作するようにダミー
    def load_dotenv(*args, **kwargs):
        return False

# ===== Google API =====
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

ROOT = pathlib.Path(__file__).resolve().parent
CWD  = pathlib.Path.cwd()
ENGINE_FILE  = ROOT / "three_call_article.py"      # 固定
PUBLISH_FILE = ROOT / "publish_gdoc_html.py"       # 固定
DEFAULT_OUT_BASE = ROOT / "out_batch"

# ============ 便利関数 ============

def normpath(p: str) -> pathlib.Path:
    return pathlib.Path(os.path.expandvars(p)).expanduser().resolve()


def run(cmd: List[str]) -> Tuple[int, str, str]:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out, err


def discover_personas(path_like: pathlib.Path) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if path_like.is_file():
        items.append({"persona_name": path_like.stem, "persona_urls": str(path_like)})
    elif path_like.is_dir():
        for p in sorted(path_like.glob("*.txt")):
            items.append({"persona_name": p.stem, "persona_urls": str(p)})
    return items


def extract_h1(md_text: str) -> Optional[str]:
    for ln in md_text.splitlines():
        if ln.startswith("# "):
            return ln[2:].strip()
    return None


def parse_publish_link(stdout_text: str) -> Optional[str]:
    for ln in stdout_text.splitlines():
        if ln.startswith("[link] "):
            return ln.split(" ", 1)[1].strip()
    return None

# ============ .env からプロンプトパス解決（後勝ち: CWD/.env） ============

def resolve_prompts_from_env():
    load_dotenv(dotenv_path=ROOT / ".env", override=False)
    load_dotenv(dotenv_path=CWD / ".env",  override=True)

    prompt_dir = os.getenv("PROMPT_DIR", "").strip()
    title_name = os.getenv("PROMPT_TITLE", "").strip()
    outline_name = os.getenv("PROMPT_OUTLINE", "").strip()
    draft_name = os.getenv("PROMPT_DRAFT", "").strip()

    if not (prompt_dir and title_name and outline_name and draft_name):
        raise SystemExit(
            "必要な .env の値がありません。\n"
            "PROMPT_DIR / PROMPT_TITLE / PROMPT_OUTLINE / PROMPT_DRAFT を設定してください。"
        )

    base = normpath(prompt_dir)
    t = base / title_name
    o = base / outline_name
    d = base / draft_name

    missing = [str(p) for p in (t, o, d) if not p.exists()]
    if missing:
        raise SystemExit("プロンプトファイルが見つかりません:\n - " + "\n - ".join(missing))

    return t, o, d

# ============ Google 認証 & Sheets 追記 ============

def _run_flow() -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / "credentials.json"), SCOPES)
    creds = flow.run_local_server(
        port=0,
        authorization_prompt_message="",
        success_message="認証完了。ウィンドウを閉じて処理に戻ります。",
        access_type="offline",
        prompt="consent",
    )
    (ROOT / "token.json").write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_creds(force_login: bool = False) -> Credentials:
    tok = ROOT / "token.json"
    if force_login or not tok.exists():
        if force_login and tok.exists():
            try:
                tok.unlink()
            except Exception:
                pass
        return _run_flow()
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    try:
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                tok.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise RefreshError("no refresh token or invalid")
        return creds
    except RefreshError:
        print("[info] token refresh failed. Re-auth...", file=sys.stderr)
        return _run_flow()


def sheets_append_row(creds: Credentials, spreadsheet_id: str, sheet_name: str, row: List[str]):
    svc = build("sheets", "v4", credentials=creds)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()

# ============ メイン ============

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--info", required=True, help="info.json（全人格共通）")
    ap.add_argument("--persona-dir", required=True, help="フォルダ or 単一ファイル（.txt）")

    # キーワード CSV（任意）: keyword,status で READY/空 のみ処理
    ap.add_argument("--keywords_csv", default="", help="列: keyword,status で READY/空 のみ処理")

    # 出力/生成温度
    ap.add_argument("--out-base", default=str(DEFAULT_OUT_BASE))
    ap.add_argument("--t0", type=float, default=0.7)
    ap.add_argument("--t1", type=float, default=0.6)
    ap.add_argument("--t2", type=float, default=0.6)
    ap.add_argument("--limit", type=int, default=0, help="処理キーワード上限（0=無制限）")

    # publish_gdoc_html.py に渡すオプション
    ap.add_argument("--title-prefix", default="[記事]")
    ap.add_argument("--folder-id", default="")
    ap.add_argument("--share-anyone-writer", type=int, default=1)
    ap.add_argument("--force-login", action='store_true', help="強制的に再ログインする（省略時は既存トークンを使用）")
    ap.add_argument("--ad-disclosure", default="本記事にはアフィリエイトリンクを含みます。")
    ap.add_argument("--mid-cta-text", default="")
    ap.add_argument("--last-cta-text", default="→無料相談会はこちらから")

    # スプレッドシート（未指定時は .env を使用）
    ap.add_argument("--sheet-id", default="")
    ap.add_argument("--sheet-tab", default="")

    args = ap.parse_args()

    # .env 読み込み（ROOT → CWD の順に）
    load_dotenv(dotenv_path=ROOT / ".env", override=False)
    load_dotenv(dotenv_path=CWD / ".env",  override=True)

    # three_call 用プロンプト解決
    title_p, outline_p, draft_p = resolve_prompts_from_env()

    # IO 検証
    info_path = normpath(args.info)
    persona_arg = normpath(args.persona_dir)
    if not info_path.exists():
        raise SystemExit(f"info.json not found: {info_path}")
    if not persona_arg.exists():
        raise SystemExit(f"persona path not found: {persona_arg}")
    if not ENGINE_FILE.exists():
        raise SystemExit(f"three_call_article.py が見つかりません: {ENGINE_FILE}")
    if not PUBLISH_FILE.exists():
        raise SystemExit(f"publish_gdoc_html.py が見つかりません: {PUBLISH_FILE}")

    # スプレッドシート設定（CLI優先 → .env フォールバック）
    sheet_id = (args.sheet_id or os.getenv("SHEET_ID", "")).strip()
    sheet_tab = (args.sheet_tab or os.getenv("SHEET_NAME", "")).strip()

    # ペルソナ列挙
    personas = discover_personas(persona_arg)
    if not personas:
        raise SystemExit("persona (.txt) が見つかりません")

    # キーワード入力（CSV有り/無し）
    use_csv = bool(args.keywords_csv.strip())
    ready_list: List[str] = []
    if use_csv:
        csv_path = normpath(args.keywords_csv)
        if not csv_path.exists():
            raise SystemExit(f"keywords_csv not found: {csv_path}")
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            rdr = csv.DictReader(f)
            hdr = [h.strip() for h in (rdr.fieldnames or [])]
            if "keyword" not in hdr or "status" not in hdr:
                raise SystemExit("CSVに 'keyword' と 'status' 列が必要です。")
            for row in rdr:
                kw = (row.get("keyword") or "").strip()
                st = (row.get("status") or "").strip().upper()
                if kw and (st == "" or st == "READY"):
                    ready_list.append(kw)
        if args.limit > 0:
            ready_list = ready_list[: args.limit]
    else:
        info_dict = json.loads(info_path.read_text(encoding="utf-8"))
        pk = (info_dict.get("primary_keyword") or "").strip()
        if not pk:
            raise SystemExit("CSV未指定の場合、info.json に primary_keyword が必要です。")
        ready_list = [pk]

    out_base = normpath(args.out_base)
    out_base.mkdir(parents=True, exist_ok=True)

    # Google 認証（シート追記が有効な場合のみ）
    creds: Optional[Credentials] = None
    if sheet_id and sheet_tab:
        creds = get_creds(force_login=args.force_login)
        print(f"[sheets] will append to: {sheet_id} / {sheet_tab}")
    else:
        print("[sheets] SHEET_ID/SHEET_NAME 未設定のため、スプシ追記はスキップします。")

    print(f"[info] personas: {len(personas)} | keywords to process: {len(ready_list)} (csv={use_csv})")

    processed = 0
    for p_idx, p in enumerate(personas, start=1):
        persona_name = p["persona_name"]
        persona_urls = p["persona_urls"]

        for kw in ready_list:
            print(f"\n=== [{p_idx}/{len(personas)}] persona={persona_name} | KW={kw} ===")

            # 1) info.json を一時拡張（primary_keyword を上書き）
            base_info = json.loads(info_path.read_text(encoding="utf-8"))
            base_info["primary_keyword"] = kw
            tmp_info = normpath(str(out_base / f"_tmpinfo_{int(time.time())}_{persona_name}.json"))
            tmp_info.write_text(json.dumps(base_info, ensure_ascii=False, indent=2), encoding="utf-8")

            # 2) 出力ディレクトリ
            run_dir = out_base / f"{time.strftime('%Y%m%d_%H%M%S')}_{persona_name}"
            run_dir.mkdir(parents=True, exist_ok=True)
            print("[info] outdir:", run_dir)

            # 3) three_call 実行
            cmd = [
                sys.executable,
                str(ENGINE_FILE),
                "--info",           str(tmp_info),
                "--persona_urls",   str(persona_urls),
                "--title_prompt",   str(title_p),
                "--outline_prompt", str(outline_p),
                "--draft_prompt",   str(draft_p),
                "--out",            str(run_dir),
                "--t0",             str(args.t0),
                "--t1",             str(args.t1),
                "--t2",             str(args.t2),
            ]
            rc, out_text, err_text = run(cmd)
            if rc != 0:
                print("[ERROR] three_call_article failed\n" + (err_text or out_text))
                continue
            if out_text.strip():
                print(out_text.strip())

            # 4) md → GDoc 公開
            md_path = run_dir / "article.md"
            if not md_path.exists():
                print("[ERROR] article.md not found; skip publish")
                continue

            publish_cmd = [
                sys.executable,
                str(PUBLISH_FILE),
                "--md", str(md_path),
                "--title-prefix", args.title_prefix,
                "--share-anyone-writer", str(int(args.share_anyone_writer)),
                "--ad-disclosure", args.ad_disclosure,
                "--mid-cta-text",  args.mid_cta_text,
                "--last-cta-text",  args.last_cta_text,
                "--reflow", "1",                 # ★追加：有効（既定も1）
                "--sentences-per-para", "3",   
            ]
            if args.folder_id:
                publish_cmd += ["--folder-id", args.folder_id]
            if args.force_login:
                publish_cmd += ["--force-login", "1"]

            rc2, out2, err2 = run(publish_cmd)
            if rc2 != 0:
                print("[ERROR] publish_gdoc_html failed\n" + (err2 or out2))
                continue
            if out2.strip():
                print(out2.strip())

            # 5) タイトルと GDoc リンク抽出
            md_text = md_path.read_text(encoding="utf-8", errors="ignore")
            title = extract_h1(md_text) or md_path.stem
            link  = parse_publish_link(out2) or ""

            # 6) スプシ追記（persona, タイトル, 記事URL）
            if creds and sheet_id and sheet_tab:
                try:
                    sheets_append_row(creds, sheet_id, sheet_tab, [persona_name, title, link])
                    print(f"[ok] Appended to sheet '{sheet_tab}': {persona_name} | {title}")
                except Exception as e:
                    print(f"[warn] sheets append failed: {e}")

            processed += 1
            if args.limit and processed >= args.limit:
                print("[info] limit reached; stop.")
                return

    print("\n[ALL DONE]")


if __name__ == "__main__":
    main()
