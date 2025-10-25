# orchestrate_personas.py
# -*- coding: utf-8 -*-
# 例:
#  python orchestrate_personas.py --info "data\info_ai_write.json" --persona-dir "data\personas\ren.txt" --force-login 1 


import os
import csv
import re
import sys
import json
import time
import argparse
import pathlib
import subprocess
from typing import List, Dict, Optional, Tuple

# ─────────────────────────────────────────────────────────────
# デフォルト設定（必要に応じて編集）
# ─────────────────────────────────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parent

DEFAULT_TWO_CALL_SCRIPT       = str(ROOT / "three_call_article.py")
DEFAULT_PUBLISH_SCRIPT        = str(ROOT / "publish_gdoc_html.py")
DEFAULT_TITLE_PROMPT          = str(ROOT / "prompts" / "title_prompt_pre_outline.txt")
DEFAULT_OUTLINE_PROMPT        = str(ROOT / "prompts" / "outline_prompt_2call.txt")
DEFAULT_DRAFT_PROMPT          = str(ROOT / "prompts" / "draft_prompt_2call.txt")
DEFAULT_OUT_BASE              = str(ROOT / "out_batch")

# Google関連 既定
DEFAULT_SHEET_ID              = "1KtnOdlsENINR9kiDuRH2l3q869lcvss4EeuJEXcMPHA"
DEFAULT_SHEET_TAB             = "Articles"
DEFAULT_TITLE_PREFIX          = "[記事]"
DEFAULT_SHARE_ANYONE_WRITER   = 1  # 1=リンクを知っている人に編集権限を付与
DEFAULT_DRIVE_FOLDER_PATH     = "document/plaud"

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

# ───── Google API クライアント ─────
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

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

def build_sheets(creds: Credentials):
    return build("sheets", "v4", credentials=creds)

def build_drive(creds: Credentials):
    return build("drive", "v3", credentials=creds)

def sheets_append_row(creds: Credentials, spreadsheet_id: str, sheet_name: str, row: List[str]):
    svc = build_sheets(creds)
    svc.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()

# ───── Markdown の h1 を抽出（Google Doc タイトルに利用）─────
def extract_h1(md_text: str) -> Optional[str]:
    for line in md_text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None

# ───── ユーティリティ ─────
def slugify(name: str) -> str:
    s = re.sub(r"[^\w\-一-龥ぁ-んァ-ン]", "_", name)
    return re.sub(r"_+", "_", s).strip("_")

def read_personas_csv(path: pathlib.Path) -> List[Dict[str, str]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            if not row.get("persona_name") or not row.get("persona_urls"):
                continue
            rows.append(
                {
                    "persona_name": row["persona_name"].strip(),
                    "persona_urls": row["persona_urls"].strip(),
                    "info_json": (row.get("info_json") or "").strip(),
                }
            )
    return rows

def discover_personas(path_like: pathlib.Path) -> List[Dict[str, str]]:
    """
    フォルダでも単一ファイルでもOKにする。
    - フォルダ: 配下の *.txt を列挙
    - ファイル: その1件をそのまま登録
    """
    items: List[Dict[str, str]] = []
    if path_like.is_file():
        items.append({"persona_name": path_like.stem, "persona_urls": str(path_like), "info_json": ""})
        return items
    if path_like.is_dir():
        for p in sorted(path_like.glob("*.txt")):
            items.append({"persona_name": p.stem, "persona_urls": str(p), "info_json": ""})
    return items

def run_subprocess(cmd: List[str]) -> Tuple[int, str, str]:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate()
    return proc.returncode, out, err

def parse_publish_link(stdout_text: str) -> Optional[str]:
    for ln in stdout_text.splitlines():
        if ln.startswith("[link] "):
            return ln.split(" ", 1)[1].strip()
    return None

# ───── Drive フォルダ解決＆移動機能 ─────
FOLDER_MIME = "application/vnd.google-apps.folder"

def _drive_find_one(drive, q: str, fields: str = "files(id,name,parents)", parent: Optional[str] = None):
    query = q
    if parent:
        query = f"({q}) and '{parent}' in parents"
    res = drive.files().list(
        q=query, spaces="drive", pageSize=1, corpora="user", fields=fields
    ).execute()
    files = res.get("files", [])
    return files[0] if files else None

def ensure_folder_path(creds: Credentials, path: str) -> str:
    drive = build_drive(creds)
    parent_id = None
    for segment in [p for p in path.split("/") if p.strip()]:
        q = f"name = '{segment}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        found = _drive_find_one(drive, q, parent=parent_id)
        if found:
            parent_id = found["id"]
            continue
        meta = {"name": segment, "mimeType": FOLDER_MIME}
        if parent_id:
            meta["parents"] = [parent_id]
        newf = drive.files().create(body=meta, fields="id,name,parents").execute()
        parent_id = newf["id"]
    if not parent_id:
        raise ValueError("drive folder path is empty")
    return parent_id

def extract_file_id_from_doc_url(url: str) -> Optional[str]:
    m = re.search(r"/document/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None

def move_file_to_folder(creds: Credentials, file_id: str, folder_id: str):
    drive = build_drive(creds)
    meta = drive.files().get(fileId=file_id, fields="parents").execute()
    prev_parents = ",".join(meta.get("parents", []))
    drive.files().update(
        fileId=file_id,
        addParents=folder_id,
        removeParents=prev_parents if prev_parents else None,
        fields="id,parents",
    ).execute()

# ───── メイン ─────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--info", required=True, help="info.json（全人格共通; CSVで個別指定も可）")
    ap.add_argument("--personas-csv", help="列: persona_name, persona_urls[, info_json]")
    ap.add_argument("--persona-dir", help="フォルダ or 単一ファイル（.txt）")

    # 以下はデフォルトあり（コマンド指定不要）
    ap.add_argument("--two-call-script", default=DEFAULT_TWO_CALL_SCRIPT)
    ap.add_argument("--publish-script",  default=DEFAULT_PUBLISH_SCRIPT)
    ap.add_argument("--title-prompt",   default=DEFAULT_TITLE_PROMPT)
    ap.add_argument("--outline-prompt", default=DEFAULT_OUTLINE_PROMPT)
    ap.add_argument("--draft-prompt",   default=DEFAULT_DRAFT_PROMPT)
    ap.add_argument("--out-base",       default=DEFAULT_OUT_BASE)

    ap.add_argument("--sheet-id",             default=DEFAULT_SHEET_ID)
    ap.add_argument("--sheet-tab",            default=DEFAULT_SHEET_TAB)
    ap.add_argument("--title-prefix",         default=DEFAULT_TITLE_PREFIX)
    ap.add_argument("--share-anyone-writer",  type=int, default=DEFAULT_SHARE_ANYONE_WRITER)
    ap.add_argument("--drive-folder-path",    default=DEFAULT_DRIVE_FOLDER_PATH)

    ap.add_argument("--force-login",   type=int, default=0, help="Google認証の再実行（1で再認証）")
    ap.add_argument("--sleep-seconds", type=float, default=1.0, help="各人格間のインターバル（秒）")
    ap.add_argument("--limit",         type=int, default=0, help="0=全件/ >0 なら先頭からN件だけ")
    args = ap.parse_args()

    info_path = pathlib.Path(args.info)
    if not info_path.exists():
        raise FileNotFoundError(f"info.json not found: {info_path}")

    # 人格セットの取得
    if args.personas_csv:
        personas = read_personas_csv(pathlib.Path(args.personas_csv))
    elif args.persona_dir:
        personas = discover_personas(pathlib.Path(args.persona_dir))
    else:
        print("ERROR: --personas-csv または --persona-dir を指定してください。", file=sys.stderr)
        sys.exit(2)

    if args.limit > 0:
        personas = personas[: args.limit]

    if not personas:
        print("ERROR: 指定された --persona-dir / --personas-csv から人格が1件も見つかりませんでした。", file=sys.stderr)
        sys.exit(3)

    print(f"[info] personas: {len(personas)} 件を検出")

    out_base = pathlib.Path(args.out_base)
    out_base.mkdir(parents=True, exist_ok=True)

    creds = get_creds(force_login=bool(args.force_login))

    target_folder_id = None
    if (args.drive_folder_path or "").strip():
        target_folder_id = ensure_folder_path(creds, args.drive_folder_path.strip())

    # 実行設定のサマリ
    print("[defaults]")
    print("  title_prompt   :", args.title_prompt)
    print("  outline_prompt :", args.outline_prompt)
    print("  draft_prompt   :", args.draft_prompt)
    print("  sheet_id       :", args.sheet_id)
    print("  sheet_tab      :", args.sheet_tab)
    print("  title_prefix   :", args.title_prefix)
    print("  share_anyone   :", args.share_anyone_writer)
    print("  drive_folder   :", args.drive_folder_path)
    print("  out_base       :", args.out_base)

    for idx, p in enumerate(personas, start=1):
        persona_name = p["persona_name"]
        persona_urls = p["persona_urls"]
        info_for_this = pathlib.Path(p["info_json"]).resolve() if p.get("info_json") else info_path

        slug = slugify(persona_name) or f"persona_{idx}"
        run_dir = out_base / f"{time.strftime('%Y%m%d_%H%M%S')}_{slug}"
        run_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n=== [{idx}/{len(personas)}] {persona_name} ===")
        print(f"[info] persona_urls: {persona_urls}")
        print(f"[info] outdir      : {run_dir}")

        # 1) 記事生成（2コール: タイトル→アウトライン→本文）
        cmd_two = [
            sys.executable,
            args.two_call_script,
            "--info",          str(info_for_this),
            "--persona_urls",  str(persona_urls),
            "--title_prompt",  args.title_prompt,
            "--outline_prompt",args.outline_prompt,
            "--draft_prompt",  args.draft_prompt,
            "--out",           str(run_dir),
        ]
        rc, out, err = run_subprocess(cmd_two)
        if rc != 0:
            print("[ERROR] three_call_article failed.")
            print(err or out)
            continue
        print(out.strip())

        sel_title_path = run_dir / "selected_title.txt"
        if sel_title_path.exists():
            try:
                print("[selected title]", sel_title_path.read_text(encoding="utf-8").strip())
            except Exception:
                pass

        md_path = run_dir / "article.md"
        if not md_path.exists():
            print("[ERROR] article.md not found. skip.")
            continue
        md_text = md_path.read_text(encoding="utf-8").strip()
        title = extract_h1(md_text) or md_path.stem

        # 2) Google Doc 作成（公開スクリプト）
        persona_prefix = f"[{persona_name}]"
        full_prefix = f"{args.title_prefix} {persona_prefix}".strip()

        cmd_pub = [
            sys.executable,
            args.publish_script,
            "--md",                   str(md_path),
            "--title-prefix",         full_prefix,
            "--share-anyone-writer",  str(args.share_anyone_writer),
        ]
        rc2, out2, err2 = run_subprocess(cmd_pub)
        if rc2 != 0:
            print("[ERROR] publish_gdoc_html failed.")
            print(err2 or out2)
            continue

        print(out2.strip())
        link = parse_publish_link(out2)
        if not link:
            print("[WARN] Doc link not detected in output. (続行)")

        # 2.5) Drive上の保存先フォルダへ移動
        if link and target_folder_id:
            file_id = extract_file_id_from_doc_url(link)
            if file_id:
                try:
                    move_file_to_folder(creds, file_id, target_folder_id)
                    print(f"[ok] moved doc to folder: {args.drive_folder_path}")
                except Exception as e:
                    print(f"[WARN] failed to move doc to '{args.drive_folder_path}': {e}")

        # 3) スプレッドシートに追記（人格/タイトル/Doc URL）
        row = [persona_name, title, (link or "")]
        sheets_append_row(creds, args.sheet_id, args.sheet_tab, row)
        print(f"[ok] Appended to sheet '{args.sheet_tab}': {persona_name} | {title}")

        time.sleep(float(args.sleep_seconds))

    print("\n[ALL DONE]")

if __name__ == "__main__":
    main()
