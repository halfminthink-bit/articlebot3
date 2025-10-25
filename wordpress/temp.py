#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
python temp.py 
  --sheet-id "1IHbEqLDqA1S-dmweDdl1jM8OeuXbvkXcevMYK3DGsao" 
  --range "'稼げない'!A2:E" 
  --col-keywords 1 
  --col-title 2 
  --col-url 3 
  --col-docurl 4 
  --col-flag 5 
  --ok-token "OK" 
  --outdir "kasegenai3"
"""

import argparse
import os
import re
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pickle

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# =========================
# Helpers
# =========================

DOC_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")

def extract_doc_id(doc_url: str) -> Optional[str]:
    if not doc_url:
        return None
    m = DOC_ID_RE.search(doc_url)
    return m.group(1) if m else None

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.strip().lower()
    # 括弧や記号をダッシュへ
    text = re.sub(r"[^\w\-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    text = text.strip("-_")
    return text or "untitled"

def ensure_unique_path(base_dir: str, base_name: str, ext: str = ".md") -> str:
    os.makedirs(base_dir, exist_ok=True)
    path = os.path.join(base_dir, base_name + ext)
    if not os.path.exists(path):
        return path
    i = 2
    while True:
        p = os.path.join(base_dir, f"{base_name}-{i}{ext}")
        if not os.path.exists(p):
            return p
        i += 1

def escape_md(text: str) -> str:
    # 最低限のエスケープ（必要に応じて拡張）
    return text.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")

def is_ok_row(row: List[str], col_flag: int, ok_token: str) -> bool:
    """
    指定列が OK かどうか（1始まりの列番号を受け取り、大文字小文字を無視して比較）
    """
    i = col_flag - 1  # 1始まり→0始まり
    if i >= len(row):
        return False
    return row[i].strip().upper() == ok_token.strip().upper()

# =========================
# Google API Clients（InstalledAppFlow）
# =========================

def get_clients():
    # SCOPES は既存の配列をそのまま利用
    creds = None
    token_path = "token.pickle"  # 承認後のトークンをローカル保存

    if os.path.exists(token_path):
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # カレントフォルダの credentials.json を利用
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    sheets = build("sheets", "v4", credentials=creds)
    docs   = build("docs",   "v1", credentials=creds)
    drive  = build("drive",  "v3", credentials=creds)
    return sheets, docs, drive

# =========================
# Docs → Markdown 変換
# =========================

def text_run_to_md(tr: Dict) -> str:
    """
    Docs API: ParagraphElement.textRun を Markdown に変換
    - 制御文字 (VTなど [\x00-\x1F]) はスペースに置換してゴミ混入を防止
    """
    if "content" not in tr:
        return ""
    txt = tr["content"]
    # 制御文字（vt等）を除去
    txt = re.sub(r"[\x00-\x1F]+", " ", txt)
    style = (tr.get("textStyle") or {})
    link = (style.get("link") or {}).get("url")
    bold = style.get("bold", False)
    italic = style.get("italic", False)
    code = style.get("code", False)

    # 行末の単独改行を維持（Docs は要素単位で改行含むことが多い）
    txt = txt.replace("\r", "")

    # マークダウン装飾
    out = txt
    if link:
        # リンク優先（装飾は中に含めない簡易実装）
        out = f"[{out.strip()}]({link})"
    else:
        if code:
            out = f"`{out.strip()}`"
        if bold and italic:
            out = f"***{out.strip()}***"
        elif bold:
            out = f"**{out.strip()}**"
        elif italic:
            out = f"*{out.strip()}*"

    return out

def paragraph_to_md(p: Dict, lists_meta: Dict) -> str:
    """
    Docs API: Paragraph を Markdown に変換
    - 見出し: HEADING_1..6
    - 箇条書き: bullet があれば「・」に統一（ordered/unordered 問わず）
    - 通常段落
    """
    pstyle = (p.get("paragraphStyle") or {})
    named = pstyle.get("namedStyleType", "NORMAL_TEXT")

    # テキスト要素の連結
    texts: List[str] = []
    for el in p.get("elements", []):
        tr = el.get("textRun")
        if tr:
            texts.append(text_run_to_md(tr))
    content = "".join(texts).rstrip("\n")

    # 見出し
    if named.startswith("HEADING_"):
        try:
            level = int(named.split("_", 1)[1])
        except:
            level = 2
        level = min(max(level, 1), 6)
        return f"{'#' * level} {content}\n"

    # 箇条書き（ordered/unordered に関わらず「・」を使用）
    bullet = p.get("bullet")
    if bullet:
        nesting = 0
        if bullet.get("nestingLevel") is not None:
            nesting = bullet["nestingLevel"]
        indent = "  " * nesting
        prefix = "・"  # ←ご要望に合わせて固定
        line = f"{indent}{prefix} {content}".rstrip()
        return f"{line}\n"

    # 通常段落
    if content.strip() == "":
        return "\n"
    return f"{content}\n"

def analyze_lists(document: Dict) -> Dict[str, Dict]:
    """
    Docs の listId -> ordered/unordered の簡易判定
    （今回は prefix を常に「・」にするため、参照のみで実質未使用）
    """
    meta: Dict[str, Dict] = {}
    for lid, props in (document.get("lists") or {}).items():
        glyph = (props.get("listProperties") or {}).get("nestingLevels", [])
        ordered = False
        if glyph:
            if any("glyphType" in g for g in glyph):
                ordered = True
        meta[lid] = {"ordered": ordered}
    return meta

def document_to_markdown(document: Dict) -> str:
    """
    Google Docs の構造を見て Markdown 文字列に変換
    """
    body = (document.get("body") or {}).get("content", [])
    lists_meta = analyze_lists(document)

    lines: List[str] = []
    for el in body:
        if "horizontalRule" in el:
            continue
        p = el.get("paragraph")
        if p:
            lines.append(paragraph_to_md(p, lists_meta))
        # 表・画像・図形などは今回はスキップ（必要に応じて拡張）

    # 末尾の余計な空行を整理
    md = "".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md

# =========================
# シート読み取り & 書き出し
# =========================

def read_sheet_rows(sheets, sheet_id: str, range_a1: str) -> List[List[str]]:
    res = sheets.spreadsheets().values().get(spreadsheetId=sheet_id, range=range_a1).execute()
    return res.get("values", [])

def fetch_document(docs, doc_id: str) -> Dict:
    return docs.documents().get(documentId=doc_id).execute()

def build_front_matter(title: str, src_url: str, doc_url: str) -> str:
    """
    先頭に H1 とコメントを付与。
    - source_url は値が空なら出力しない（空コメント行が出ないように）
    """
    fm = []
    if title:
        fm.append(f"# {title}\n")
    if src_url:
        fm.append(f"<!-- source_url: {src_url} -->\n")
    fm.append(f"<!-- gdoc_url:  {doc_url or ''} -->\n\n")
    return "".join(fm)

def remove_tail_cta(md: str) -> str:
    """
    末尾に入っているLINE/メルマガ誘導の告知ブロックを削除する。
    """
    md = re.sub(
        r"(?s)\n?[ \t]*僕はLINEとメルマガをやっていて.*\Z",
        "\n",
        md,
        flags=re.MULTILINE,
    )
    patterns = [
        r"(?m)^[ \t]*👉.*\n?",                 # 👉で始まる行
        r"(?m)^.*公式LINE.*\n?",              # 公式LINE の行
        r"(?m)^.*メルマガ.*\n?",              # メルマガ の行
        r"(?m)^.*line\.me/R/ti/p/%40dxw9105c.*\n?",            # LINE URL
        r"(?m)^.*バックパッカー\.jp/manga/?\S*.*\n?",          # メルマガURL
    ]
    for pat in patterns:
        md = re.sub(pat, "", md)

    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md

def process_row(
    docs,
    row: List[str],
    idx: int,
    col_keywords: int,
    col_title: int,
    col_url: int,
    col_docurl: int,
    outdir: str,
) -> Optional[str]:
    """
    1 行処理して MD をファイルに保存。成功したらパスを返す
    """
    def safe_get(col: int) -> str:
        # 1始まり → 0-based
        i = col - 1
        return row[i].strip() if (0 <= i < len(row)) else ""

    keywords = safe_get(col_keywords)
    title = safe_get(col_title) or keywords or f"no-title-{idx}"
    url = safe_get(col_url)
    doc_url = safe_get(col_docurl)
    doc_id = extract_doc_id(doc_url)
    if not doc_id:
        print(f"[warn] row {idx}: ドキュメントURL不正のためスキップ ({doc_url})", file=sys.stderr)
        return None

    try:
        document = fetch_document(docs, doc_id)
    except HttpError as e:
        print(f"[error] row {idx}: Docs取得に失敗 docId={doc_id} {e}", file=sys.stderr)
        return None

    body_md = document_to_markdown(document)
    body_md = remove_tail_cta(body_md)
    head = build_front_matter(title, url, doc_url)

    base_name = slugify(title)
    out_path = ensure_unique_path(outdir, base_name, ".md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(head)
        f.write(body_md)

    print(f"[ok]  row {idx}: {out_path}")
    return out_path

def main():
    ap = argparse.ArgumentParser(description="Google Docs → Markdown exporter (from Google Sheets rows)")
    ap.add_argument("--sheet-id", required=True, help="スプレッドシートID")
    ap.add_argument("--range", required=True, help="読み取り範囲（例: 'Articles!A2:E'）")
    ap.add_argument("--col-keywords", type=int, default=1, help="キーワードリスト 列番号(1始まり)")
    ap.add_argument("--col-title", type=int, default=2, help="記事タイトル 列番号(1始まり)")
    ap.add_argument("--col-url", type=int, default=3, help="URL 列番号(1始まり)")
    ap.add_argument("--col-docurl", type=int, default=4, help="ドキュメントURL 列番号(1始まり)")
    ap.add_argument("--outdir", default="kasegenai", help="出力フォルダ")
    # ★追加: フィルタ列とトークン
    ap.add_argument("--col-flag", type=int, default=5, help="変換フラグ列番号(1始まり) 例: E列=5")
    ap.add_argument("--ok-token", default="OK", help="変換対象とみなすセルの値（大文字小文字無視）")
    args = ap.parse_args()

    try:
        sheets, docs, drive = get_clients()
    except Exception as e:
        print(f"[fatal] Google API 認証/初期化に失敗: {e}", file=sys.stderr)
        sys.exit(1)

    rows = read_sheet_rows(sheets, args.sheet_id, args.range)
    if not rows:
        print("[info] シートにデータがありません")
        return

    count = 0
    for i, row in enumerate(rows, start=1):
        # ★ E列(既定)が OK の行だけ処理
        if not is_ok_row(row, args.col_flag, args.ok_token):
            print(f"[skip] row {i}: フラグ列がOKではないためスキップ")
            continue

        p = process_row(
            docs,
            row,
            idx=i,
            col_keywords=args.col_keywords,
            col_title=args.col_title,
            col_url=args.col_url,
            col_docurl=args.col_docurl,
            outdir=args.outdir,
        )
        if p:
            count += 1

    print(f"[done] {count} 件の Markdown を {args.outdir}/ に出力しました。")

if __name__ == "__main__":
    main()
