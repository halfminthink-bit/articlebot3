# publish_md_to_gdoc_afterH2_images.py
# -*- coding: utf-8 -*-
"""
Markdown(.md) → (画像タグ無しの)軽量HTML → Googleドキュメント作成
→ Docs APIで HEADING_2 の直後に画像を"埋め込み"挿入

改良点:
- Google Docs API 未有効時(403 SERVICE_DISABLED)の例外を丁寧に処理
  - 記事Docの作成は成功させ、画像挿入のみスキップ
  - 有効化URLのヒントを表示
- ログの可読性アップ

使い方(例):
  python publish_md_to_gdoc_afterH2_images.py ^
    --md "C:\\path\\to\\article.md" ^
    --image-dir "G:\\マイドライブ\\document\\images\\tamesi" ^
    --folder-id "xxxxxxxxxxxxxxxx" ^
    --title-prefix "[記事]" ^
    --share-anyone-writer 1 ^
    --share-images 1
"""

import os
import io
import re
import sys
import html
import json
import pathlib
import argparse
import unicodedata
from typing import List, Dict, Tuple, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

# ───────────────────────────────────────────────────────────────
# Google API SCOPES
# ───────────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",  # ← Docs API
]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# ───────────────────────────────────────────────────────────────
# 認証
# ───────────────────────────────────────────────────────────────
def _run_flow() -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(
        port=0,
        authorization_prompt_message="",
        success_message="認証完了。ウィンドウを閉じて処理に戻ります。",
        access_type="offline",
        prompt="consent",
    )
    pathlib.Path("token.json").write_text(creds.to_json(), encoding="utf-8")
    return creds

def get_creds(force_login: bool = False) -> Credentials:
    tok = pathlib.Path("token.json")
    if force_login or not tok.exists():
        if force_login and tok.exists():
            try:
                tok.unlink()
                print("[info] token.json removed (force-login).")
            except Exception:
                pass
        return _run_flow()
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    try:
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                pathlib.Path("token.json").write_text(creds.to_json(), encoding="utf-8")
            else:
                raise RefreshError("no refresh token or invalid")
        return creds
    except RefreshError:
        print("[info] token refresh failed. Re-auth flow starts...", file=sys.stderr)
        return _run_flow()

# ───────────────────────────────────────────────────────────────
# Markdown → HTML（h1/h2/h3/p/hr/ul/ol/li を最低限サポート）
# ※ 画像(![]())はここでは出力しない（後段のDocs APIで挿入するため）
# ───────────────────────────────────────────────────────────────
RX_UL_HEAD = re.compile(r"^\s*-\s+")
RX_OL_HEAD = re.compile(r"^\s*\d+[.)]\s+")
RX_UL_INLINE_START = re.compile(r"-\s+\S")
RX_OL_INLINE_START = re.compile(r"\d+[.)]\s+\S")
RX_UL_SPLIT = re.compile(r"-\s+")
RX_OL_SPLIT = re.compile(r"\d+[.)]\s+")

def _split_last_item(item: str) -> Tuple[str, str]:
    tokens = ["これらの", "これにより", "続いて", "次に", "ここでは", "なお", "ただし",
              "一方で", "以上", "また", "さらに", "加えて", "最後に"]
    rx = re.compile("|".join(map(re.escape, tokens)))
    m = rx.search(item)
    if m and m.start() > 0:
        return item[:m.start()].rstrip(), item[m.start():].lstrip()
    return item.strip(), ""

def md_to_html(md: str) -> str:
    lines = md.splitlines()
    out: List[str] = []
    in_list = False
    list_tag: Optional[str] = None

    def close_list():
        nonlocal in_list, list_tag
        if in_list:
            out.append(f"</{list_tag}>")
            in_list = False
            list_tag = None

    def open_list(tag: str):
        nonlocal in_list, list_tag
        if in_list and list_tag != tag:
            close_list()
        if not in_list:
            out.append(f"<{tag}>")
            in_list = True
            list_tag = tag

    for raw in lines:
        ln = raw.rstrip("\n")

        # 画像行(![]())はスキップ（後段で挿入する）
        if ln.strip().startswith("!"):  # 粗いが十分
            continue

        if ln.strip() == "---":
            close_list()
            out.append("<hr>")
            continue

        if ln.startswith("### "):
            close_list()
            out.append(f"<h3>{html.escape(ln[4:].strip())}</h3>")
            continue
        if ln.startswith("## "):
            close_list()
            out.append(f"<h2>{html.escape(ln[3:].strip())}</h2>")
            continue
        if ln.startswith("# "):
            close_list()
            out.append(f"<h1>{html.escape(ln[2:].strip())}</h1>")
            continue

        if RX_UL_HEAD.match(ln):
            after = RX_UL_HEAD.sub("", ln).strip()
            open_list("ul"); out.append(f"<li>{html.escape(after)}</li>")
            continue
        if RX_OL_HEAD.match(ln):
            after = RX_OL_HEAD.sub("", ln, count=1).strip()
            open_list("ol"); out.append(f"<li>{html.escape(after)}</li>")
            continue

        m_ul = RX_UL_INLINE_START.search(ln)
        m_ol = RX_OL_INLINE_START.search(ln)
        if m_ul or m_ol:
            if m_ul and (not m_ol or m_ul.start() <= m_ol.start()):
                prefix = ln[:m_ul.start()].strip()
                rest   = ln[m_ul.start():].strip()
                parts  = [s.strip() for s in RX_UL_SPLIT.split(rest) if s.strip()]
                if len(parts) >= 3:
                    parts[-1], post = _split_last_item(parts[-1])
                    close_list()
                    if prefix:
                        out.append(f"<p>{html.escape(prefix)}</p>")
                    open_list("ul")
                    for it in parts:
                        out.append(f"<li>{html.escape(it)}</li>")
                    close_list()
                    if post:
                        out.append(f"<p>{html.escape(post)}</p>")
                    continue
            else:
                prefix = ln[:m_ol.start()].strip()
                rest   = ln[m_ol.start():].strip()
                parts  = [s.strip() for s in RX_OL_SPLIT.split(rest) if s.strip()]
                if len(parts) >= 3:
                    parts[-1], post = _split_last_item(parts[-1])
                    close_list()
                    if prefix:
                        out.append(f"<p>{html.escape(prefix)}</p>")
                    open_list("ol")
                    for it in parts:
                        out.append(f"<li>{html.escape(it)}</li>")
                    close_list()
                    if post:
                        out.append(f"<p>{html.escape(post)}</p>")
                    continue

        if ln.strip() == "":
            close_list(); out.append(""); continue

        close_list()
        out.append(f"<p>{html.escape(ln)}</p>")

    close_list()

    # 連続空行を1つに圧縮
    html_body: List[str] = []
    prev_blank = False
    for x in out:
        if x == "":
            if not prev_blank:
                html_body.append("")
            prev_blank = True
        else:
            html_body.append(x)
            prev_blank = False

    body = "\n".join(html_body)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Imported Article</title>
</head>
<body>
{body}
</body>
</html>"""

# ───────────────────────────────────────────────────────────────
# Markdown解析（H2抽出 & タイトル抽出）
# ───────────────────────────────────────────────────────────────
def extract_title_and_h2(md_text: str) -> Tuple[str, List[str]]:
    title = ""
    h2s: List[str] = []
    for line in md_text.splitlines():
        if not title and line.startswith("# "):
            title = line[2:].strip()
        if line.startswith("## "):
            h2s.append(line[3:].strip())
    if not title:
        title = "Untitled"
    return title, h2s

def slugify(text: str) -> str:
    # 正規化 → アルファベット・数字以外はハイフンに
    t = unicodedata.normalize("NFKC", text).strip().lower()
    t = re.sub(r"[^\w\-]+", "-", t)  # 非単語→-
    t = re.sub(r"-{2,}", "-", t).strip("-")
    return t or "h2"

# ───────────────────────────────────────────────────────────────
# Drive / Docs / Sheets クライアント
# ───────────────────────────────────────────────────────────────
def drive_client(creds: Credentials):
    return build("drive", "v3", credentials=creds)

def docs_client(creds: Credentials):
    return build("docs", "v1", credentials=creds)

def sheets_client(creds: Credentials):
    return build("sheets", "v4", credentials=creds)

# ───────────────────────────────────────────────────────────────
# Drive: HTMLインポートでGDocを作る
# ───────────────────────────────────────────────────────────────
def drive_create_gdoc_from_html(creds: Credentials, html_text: str, name: str, folder_id: Optional[str]=None) -> tuple[str, str]:
    drive = drive_client(creds)
    media = MediaIoBaseUpload(io.BytesIO(html_text.encode("utf-8")), mimetype="text/html", resumable=False)
    metadata = {"name": name, "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        metadata["parents"] = [folder_id]
    file = drive.files().create(body=metadata, media_body=media, fields="id, webViewLink").execute()
    return file["id"], file.get("webViewLink", "")

def drive_share_anyone(creds: Credentials, file_id: str, role: str = "reader"):
    drive = drive_client(creds)
    drive.permissions().create(fileId=file_id, body={"type": "anyone", "role": role}).execute()

def drive_upload_image(creds: Credentials, path: pathlib.Path, folder_id: Optional[str]=None) -> str:
    drive = drive_client(creds)
    file_metadata = {"name": path.name}
    if folder_id:
        file_metadata["parents"] = [folder_id]
    media = MediaFileUpload(str(path), resumable=False)
    file = drive.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return file["id"]

def drive_get_image_link(creds: Credentials, file_id: str, link_type: str = "download") -> str:
    """
    link_type:
      - "download" => webContentLink（高解像度, 要 公開権限）
      - "thumbnail" => thumbnailLink（安定だが既定220px。末尾 =s220 を =s800 等に拡張）
    """
    drive = drive_client(creds)
    if link_type == "thumbnail":
        info = drive.files().get(fileId=file_id, fields="thumbnailLink").execute()
        link = info.get("thumbnailLink", "")
        if link.endswith("=s220"):
            link = link[:-5] + "=s800"
        return link
    else:
        info = drive.files().get(fileId=file_id, fields="webContentLink").execute()
        return info.get("webContentLink", "")

# ───────────────────────────────────────────────────────────────
# Sheets（任意）
# ───────────────────────────────────────────────────────────────
def sheets_get_or_create_sheet_id(creds: Credentials, spreadsheet_id: str, sheet_name: str) -> int:
    svc = sheets_client(creds)
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sh in meta.get("sheets", []):
        if sh.get("properties", {}).get("title") == sheet_name:
            return int(sh["properties"]["sheetId"])
    svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
    ).execute()
    meta = svc.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sh in meta.get("sheets", []):
        if sh.get("properties", {}).get("title") == sheet_name:
            return int(sh["properties"]["sheetId"])
    raise RuntimeError(f"failed to create/find sheet: {sheet_name}")

def sheets_set_column_widths(creds: Credentials, spreadsheet_id: str, sheet_id: int, widths_px: List[int]):
    reqs = []
    for idx, px in enumerate(widths_px):
        reqs.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": idx, "endIndex": idx+1},
                "properties": {"pixelSize": int(px)},
                "fields": "pixelSize"
            }
        })
    sheets_client(creds).spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": reqs}
    ).execute()

def sheets_append_title_url(creds: Credentials, spreadsheet_id: str, sheet_name: str, title: str, url: str):
    sheets_client(creds).spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [[title, url]]}
    ).execute()

# ───────────────────────────────────────────────────────────────
# 見出し→画像ファイルの対応付け
# ───────────────────────────────────────────────────────────────
def list_images(image_dir: pathlib.Path) -> List[pathlib.Path]:
    items = []
    for p in image_dir.glob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            items.append(p)
    # 自然な順序（先頭の数字に反応）
    def keyfun(x: pathlib.Path):
        m = re.match(r"(\d+)[\-_]", x.name)
        if m:
            return (int(m.group(1)), x.name.lower())
        return (10**9, x.name.lower())
    return sorted(items, key=keyfun)

def map_h2_to_images(h2s: List[str], images: List[pathlib.Path]) -> Dict[str, List[pathlib.Path]]:
    # まずスラッグインデックスを作成
    h2_slugs = [(h2, slugify(h2)) for h2 in h2s]
    mapping: Dict[str, List[pathlib.Path]] = {h2: [] for h2 in h2s}
    used = set()

    # スラッグ一致（含む）で割当
    for idx, img in enumerate(images):
        nm = img.stem.lower()
        best = None
        for h2, sl in h2_slugs:
            if sl and sl in nm:
                best = h2
                break
        if best:
            mapping[best].append(img)
            used.add(idx)

    # 未使用を順番で補充
    remain = [img for i, img in enumerate(images) if i not in used]
    it = iter(remain)
    for h2 in h2s:
        # 既に何枚か割当済みでも、残りがあれば1枚ずつ追加していく
        try:
            mapping[h2].append(next(it))
        except StopIteration:
            break

    return mapping

# ───────────────────────────────────────────────────────────────
# Docs API: HEADING_2 の直後に画像を挿入
# ───────────────────────────────────────────────────────────────
def docs_insert_images_after_h2s(
    creds: Credentials,
    doc_id: str,
    h2_to_image_links: Dict[str, List[str]],
    width_pt: float = 450.0,
):
    docs = docs_client(creds)
    try:
        doc = docs.documents().get(documentId=doc_id).execute()
    except HttpError as e:
        # Docs APIが未有効な典型ケースを丁寧に案内
        if e.resp.status == 403:
            try:
                err = json.loads(e.content.decode("utf-8"))
            except Exception:
                err = {}
            reason = ""
            activation_url = "https://console.developers.google.com/apis/library/docs.googleapis.com"
            for det in err.get("error", {}).get("details", []):
                if det.get("@type", "").endswith("ErrorInfo"):
                    reason = det.get("reason", "")
                    activation_url = det.get("metadata", {}).get("activationUrl", activation_url)
            if reason == "SERVICE_DISABLED":
                msg = (
                    "\n[error] Google Docs API がこのプロジェクトで未有効です。\n"
                    f"  → 下記URLで『Google Docs API』を有効化して、再実行してください。\n"
                    f"  {activation_url}\n"
                    "（Cloud Consoleで credentials.json を作成した **同じプロジェクト** を有効化する必要があります）\n"
                )
                print(msg, file=sys.stderr)
                return  # 画像挿入はスキップ（Doc自体は作成済み）
        # その他のエラーはそのまま投げる
        raise

    content = doc.get("body", {}).get("content", [])
    requests = []

    # 末尾から走査（インデックスずれ回避）
    for elem in reversed(content):
        para = elem.get("paragraph")
        if not para:
            continue
        style = para.get("paragraphStyle", {})
        if style.get("namedStyleType") == "HEADING_2":
            # 見出しテキスト
            h2_text = "".join(
                (run.get("textRun", {}).get("content", "") or "")
                for run in para.get("elements", [])
            ).strip()
            if not h2_text:
                continue
            imgs = h2_to_image_links.get(h2_text) or []
            if not imgs:
                continue

            insert_index = elem["endIndex"] - 1  # 段落末尾
            # 見出しの直後に改行を入れてから画像群を追加（実行順の都合で逆順に積む）
            requests.append({
                "insertText": {
                    "location": {"index": insert_index},
                    "text": "\n"
                }
            })
            for url in reversed(imgs):
                requests.append({
                    "insertInlineImage": {
                        "location": {"index": insert_index},
                        "uri": url,
                        "objectSize": {
                            "width": {"magnitude": float(width_pt), "unit": "PT"}
                        }
                    }
                })

    if requests:
        docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        print(f"[ok] inserted {sum(len(v) for v in h2_to_image_links.values())} image(s) after H2.")
    else:
        print("[info] no insertInlineImage requests were generated (no mapped images or no H2 found).")

# ───────────────────────────────────────────────────────────────
# main
# ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True, help="入力Markdownファイルのパス")
    ap.add_argument("--image-dir", default="", help="H2直後に入れたい画像フォルダのパス")
    ap.add_argument("--folder-id", default="", help="作成先のDriveフォルダID（任意）")
    ap.add_argument("--image-folder-id", default="", help="画像アップロード先のDriveフォルダID（任意）")
    ap.add_argument("--title-prefix", default="", help="Doc名の接頭辞（任意）")
    ap.add_argument("--share-anyone-writer", type=int, default=0, help="1=Docをリンク所持者:編集可に")
    ap.add_argument("--share-images", type=int, default=1, help="1=画像をリンク所持者:閲覧可に（推奨）")
    ap.add_argument("--image-link-type", choices=["download","thumbnail"], default="download", help="Docs挿入に使う画像URL種別")
    ap.add_argument("--image-width-pt", type=float, default=450.0, help="画像幅(PT)。noteコピペ安定化のため指定を推奨")
    ap.add_argument("--sheet", default="", help="書き込み先スプレッドシートID（任意）")
    ap.add_argument("--tab", default="Sheet1", help="シート名（任意）")
    ap.add_argument("--col-a-width", type=int, default=520)
    ap.add_argument("--col-b-width", type=int, default=820)
    ap.add_argument("--force-login", type=int, default=0, help="1=token.jsonを無視して再認証")
    args = ap.parse_args()

    md_path = pathlib.Path(args.md)
    if not md_path.is_file():
        raise FileNotFoundError(f"md not found: {md_path}")

    md_text = md_path.read_text(encoding="utf-8").strip()
    doc_title, h2s = extract_title_and_h2(md_text)
    name = (args.title_prefix + " " + doc_title).strip() if args.title_prefix else doc_title
    print(f"[info] H2 count: {len(h2s)}")

    # HTML（画像タグは出力しない）
    html_text = md_to_html(md_text)

    creds = get_creds(force_login=bool(args.force_login))

    # 1) テキストだけでDoc作成
    doc_id, link = drive_create_gdoc_from_html(creds, html_text, name, args.folder_id or None)
    print(f"[ok] Google Doc created: id={doc_id}")
    print(f"[link] {link}")

    if int(args.share_anyone_writer) == 1:
        drive_share_anyone(creds, doc_id, role="writer")
        print("[ok] Doc sharing set: anyone with the link = writer")

    # 2) 画像の準備（フォルダが指定されていれば）
    h2_to_image_links: Dict[str, List[str]] = {h: [] for h in h2s}
    total_uploaded = 0

    if args.image_dir:
        image_dir = pathlib.Path(args.image_dir)
        if not image_dir.is_dir():
            print(f"[warn] image-dir not found: {image_dir}")
        else:
            imgs = list_images(image_dir)
            print(f"[info] found {len(imgs)} image file(s) in: {image_dir}")
            h2_to_imgs = map_h2_to_images(h2s, imgs)

            # Drive にアップロード → 公開リンク取得
            for h2, files in h2_to_imgs.items():
                for p in files:
                    try:
                        img_id = drive_upload_image(creds, p, args.image_folder_id or None)
                        total_uploaded += 1
                        if int(args.share_images) == 1:
                            drive_share_anyone(creds, img_id, role="reader")
                        url = drive_get_image_link(creds, img_id, link_type=args.image_link_type)
                        if not url:
                            print(f"[warn] failed to get link for image: {p.name}")
                            continue
                        h2_to_image_links[h2].append(url)
                    except Exception as e:
                        print(f"[warn] image upload failed: {p} ({e})")

    print(f"[debug] H2 with images:")
    count_pair = 0
    for h2 in h2s:
        n = len(h2_to_image_links.get(h2) or [])
        if n > 0:
            count_pair += n
        print(f"  - {h2} : {n} image(s)")
    print(f"[info] H2 count with images: {count_pair} / total images uploaded: {total_uploaded}")

    # 3) Docs API で見出し直後に画像挿入
    if count_pair > 0:
        try:
            docs_insert_images_after_h2s(
                creds=creds,
                doc_id=doc_id,
                h2_to_image_links=h2_to_image_links,
                width_pt=float(args.image_width_pt),
            )
        except HttpError as e:
            # SERVICE_DISABLED 以外の想定外エラーも見やすく
            print(f"[error] Docs API batchUpdate failed: HTTP {e.resp.status}\n{e}", file=sys.stderr)
    else:
        print("[info] no images to insert.")

    # 4) 任意でSheet追記
    if args.sheet:
        sheet_id = sheets_get_or_create_sheet_id(creds, args.sheet, args.tab)
        sheets_append_title_url(creds, args.sheet, args.tab, doc_title, link)
        sheets_set_column_widths(creds, args.sheet, sheet_id, [args.col_a_width, args.col_b_width])
        print(f"[ok] appended (title/url) to sheet '{args.tab}' and set column widths")

if __name__ == "__main__":
    main()
