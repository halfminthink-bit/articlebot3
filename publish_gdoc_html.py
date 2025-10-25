# publish_gdoc_html.py
# -*- coding: utf-8 -*-
"""
Markdown(.md) -> 軽量HTML -> Googleドキュメント化 + 追記

今回の更新（リズム改行対応）
- "自然な段落リズム" をコード側で担保するための後処理を追加
  - `rhythmic_reflow_html(html, sentences_per_para=2)` を新設
  - 日本語の句点（。．！？）で文を分割し、N文ごとに<p>再構成
  - 見出し/箇条書き/code/table などは非対象
  - 既存の機能（CTA挿入・シート追記 等）は不変
- CLI 追加オプション
  - `--reflow` (0/1, 既定=1): リズム改行の有効/無効
  - `--sentences-per-para` (int, 既定=2): 1段落あたりの文数

ポイント：生成APIに過度な指示を加えず、**決定論的に**段落化することで、
テンプレの一貫性と可読性を担保します。

今回の更新（キーワード一括リンク付与）
- `docs_add_links_to_all_keywords(...)` を追加
- main() の末尾CTA処理の後に呼び出し、文中の「公式サイト」全箇所へ OFFICIAL_URL をリンク付与
"""

import os
import sys
import pathlib
import argparse
import io
import re
import html
from typing import List, Tuple, Optional

from dotenv import load_dotenv

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

# NEW: HTML整形用
from bs4 import BeautifulSoup, Tag

# ───────────── Google API スコープ ─────────────
SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]

# ───────────── 認証 ─────────────

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
        print("[info] token refresh failed (expired or revoked). Re-auth flow starts...", file=sys.stderr)
        return _run_flow()

# ───────────── Markdown → HTML（簡易）─────────────
RX_UL_HEAD = re.compile(r"^\s*-\s+")
RX_OL_HEAD = re.compile(r"^\s*\d+[.)]\s+")
RX_UL_INLINE_START = re.compile(r"-\s+\S")
RX_OL_INLINE_START = re.compile(r"\d+[.)]\s+\S")
RX_UL_SPLIT = re.compile(r"-\s+")
RX_OL_SPLIT = re.compile(r"\d+[.)]\s+")
RX_POST_TOKENS = re.compile("|".join(map(re.escape, [
    "これらの", "これにより", "続いて", "次に", "ここでは", "なお", "ただし",
    "一方で", "以上", "また", "さらに", "加えて", "最後に"
])))

BOLD_RX = re.compile(r"\*\*(.+?)\*\*")


def _split_last_item(item: str) -> Tuple[str, str]:
    m = RX_POST_TOKENS.search(item)
    if m and m.start() > 0:
        return item[:m.start()].rstrip(), item[m.start():].lstrip()
    return item.strip(), ""


def render_inline(text: str) -> str:
    out: List[str] = []
    pos = 0
    for m in BOLD_RX.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        inner = m.group(1)
        out.append(f"<strong>{html.escape(inner)}</strong>")
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


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

        if ln.strip() == "---":
            close_list(); out.append("<hr>"); continue
        if ln.startswith("### "):
            close_list(); out.append(f"<h3>{render_inline(ln[4:].strip())}</h3>"); continue
        if ln.startswith("## "):
            close_list(); out.append(f"<h2>{render_inline(ln[3:].strip())}</h2>"); continue
        if ln.startswith("# "):
            close_list(); out.append(f"<h1>{render_inline(ln[2:].strip())}</h1>"); continue

        if RX_UL_HEAD.match(ln):
            after = RX_UL_HEAD.sub("", ln).strip()
            open_list("ul"); out.append(f"<li>{render_inline(after)}</li>"); continue
        if RX_OL_HEAD.match(ln):
            after = RX_OL_HEAD.sub("", ln, count=1).strip()
            open_list("ol"); out.append(f"<li>{render_inline(after)}</li>"); continue

        m_ul = RX_UL_INLINE_START.search(ln)
        m_ol = RX_OL_INLINE_START.search(ln)
        if m_ul or m_ol:
            if m_ul and (not m_ol or m_ul.start() <= m_ol.start()):
                prefix = ln[:m_ul.start()].strip(); rest = ln[m_ul.start():].strip()
                parts = [s.strip() for s in RX_UL_SPLIT.split(rest) if s.strip()]
                if len(parts) >= 3:
                    parts[-1], post = _split_last_item(parts[-1])
                    close_list();
                    if prefix: out.append(f"<p>{render_inline(prefix)}</p>")
                    open_list("ul")
                    for it in parts: out.append(f"<li>{render_inline(it)}</li>")
                    close_list();
                    if post: out.append(f"<p>{render_inline(post)}</p>")
                    continue
            else:
                prefix = ln[:m_ol.start()].strip(); rest = ln[m_ol.start():].strip()
                parts = [s.strip() for s in RX_OL_SPLIT.split(rest) if s.strip()]
                if len(parts) >= 3:
                    parts[-1], post = _split_last_item(parts[-1])
                    close_list();
                    if prefix: out.append(f"<p>{render_inline(prefix)}</p>")
                    open_list("ol")
                    for it in parts: out.append(f"<li>{render_inline(it)}</li>")
                    close_list();
                    if post: out.append(f"<p>{render_inline(post)}</p>")
                    continue

        if ln.strip() == "":
            close_list(); out.append(""); continue

        close_list(); out.append(f"<p>{render_inline(ln)}</p>")

    close_list()

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
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Imported Article</title>
</head>
<body>
{body}
</body>
</html>"""

# ───────────── リズム改行（自然段落化）─────────────
_JA_SENT_SPLIT = re.compile(r"(?<=[。．！？])(?=[^\s　])")

INLINE_OK = {"b","strong","i","em","span","a","br","u","s","small","mark","sub","sup","code"}
SKIP_TAGS = {"code","pre","table","thead","tbody","tr","th","td","ul","ol","li","blockquote"}
HEADING_TAGS = {"h1","h2","h3","h4","h5","h6"}


def _reflow_paragraph_text(text: str, sentences_per_para: int = 2) -> List[str]:
    """テキストを句点で分割し、N文ごとに段落化。引用符内の句読点は無視。"""
    # 既存の改行は一旦詰める
    txt = re.sub(r"[ \t]*\n+[ \t]*", "", text)
    
    # ★★★ 新規追加: 引用符閉じ+句点のパターンを削除（」。→」、』。→』など）★★★
    txt = re.sub(r'([」』])([。．])', r'\1', txt)
    # 引用符閉じ+全角スペース+句点も削除（」　。→」など）
    txt = re.sub(r'([」』])[　\s]+([。．])', r'\1', txt)

    # ★★★ 改良版: 引用符の外側にある句読点のみで分割 ★★★
    sentences: List[str] = []
    current: List[str] = []
    in_quote = False

    for i, char in enumerate(txt):
        current.append(char)

        # 引用符の開閉を追跡（和文引用符）
        if char in "「『":
            in_quote = True
        elif char in "」』":
            in_quote = False

        # 引用符の外側で句読点かつ、次文字が空白類でない場合に文として確定
        if (not in_quote and char in "。．！？" and i + 1 < len(txt)):
            nxt = txt[i + 1]
            if not (nxt.isspace() or nxt == "　"):  # 全角スペースも空白扱い
                sent = "".join(current).strip()
                if sent:
                    sentences.append(sent)
                current = []

    # 残りを追加
    if current:
        sent = "".join(current).strip()
        if sent:
            sentences.append(sent)

    # 後処理: 文頭の不自然な句読点を削除
    cleaned_sentences: List[str] = []
    for sent in sentences:
        cleaned = re.sub(r'^[。、．，）"』]+\s*', '', sent).strip()
        if cleaned:
            cleaned_sentences.append(cleaned)

    if not cleaned_sentences:
        return [text.strip()] if text.strip() else []

    # N文ごとに段落化
    paras: List[str] = []
    for i in range(0, len(cleaned_sentences), sentences_per_para):
        chunk = "".join(cleaned_sentences[i:i+sentences_per_para]).strip()
        if chunk:
            paras.append(chunk)
    return paras

def rhythmic_reflow_html(html_text: str, sentences_per_para: int = 2) -> str:
    """
    見出し(h1-h6), 箇条書き(ul/ol/li), code/pre, table 等は触らず、
    通常テキストの <p>/<div> 内の"素のテキスト"のみを対象に N文ごと段落化。
    連続する段落ブロックを一度に集約して再配分する。
    """
    soup = BeautifulSoup(html_text, "html.parser")
    root = soup.body or soup
    
    # 統計用
    original_p_count = len(soup.find_all("p"))
    blocks_processed = 0
    total_new_paras = 0

    def is_inline_only(tag: Tag) -> bool:
        """タグがinline要素のみを含むか判定"""
        if not isinstance(tag, Tag):
            return False
        for c in tag.children:
            if isinstance(c, Tag) and c.name not in INLINE_OK:
                return False
        return True

    def is_text_paragraph(element) -> bool:
        """テキスト段落（再配分対象）か判定"""
        if not isinstance(element, Tag):
            return False
        if element.name in SKIP_TAGS or element.name in HEADING_TAGS:
            return False
        if element.name in {"p", "div"} and is_inline_only(element):
            return True
        return False

    def find_and_process_blocks(container: Tag):
        """コンテナ内の連続するテキスト段落ブロックを見つけて処理"""
        nonlocal blocks_processed, total_new_paras
        
        # 連続するテキスト段落を収集
        blocks_to_process = []
        current_block = []
        
        for child in list(container.children):
            if isinstance(child, Tag):
                if is_text_paragraph(child):
                    current_block.append(child)
                else:
                    if current_block:
                        blocks_to_process.append(current_block)
                        current_block = []
                    
                    # 再帰的に処理（スキップタグ以外）
                    if child.name not in SKIP_TAGS and child.name not in HEADING_TAGS:
                        find_and_process_blocks(child)
        
        if current_block:
            blocks_to_process.append(current_block)
        
        # 各ブロックを処理
        for block in blocks_to_process:
            if len(block) == 0:
                continue
            
            blocks_processed += 1
            
            # テキストを結合（段落を跨いで）
            combined_text = ""
            for tag in block:
                text = tag.get_text()
                # 既存の改行・余分な空白を除去
                text = re.sub(r"\s*\n\s*", "", text).strip()
                if text:
                    combined_text += text
            
            if not combined_text:
                continue
            
            # 句点で分割して N 文ごとに再配分
            paras = _reflow_paragraph_text(combined_text, sentences_per_para)
            
            if len(paras) == 0:
                continue
            
            total_new_paras += len(paras)
            
            # ★★★ 変更箇所: 新しい<p>タグを作成して挿入（段落間に空白行を追加）★★★
            first_tag = block[0]
            for i, para_text in enumerate(paras):
                # 通常の段落を挿入
                new_p = soup.new_tag("p")
                new_p.string = para_text
                first_tag.insert_before(new_p)
                
                # 最後の段落以外は、空白行用の空<p>を挿入
                if i < len(paras) - 1:
                    spacer_p = soup.new_tag("p")
                    spacer_p.append(soup.new_tag("br"))  # 空の<p><br></p>で行間確保
                    first_tag.insert_before(spacer_p)
            
            # 元のタグを削除
            for old_tag in block:
                old_tag.extract()

    # 処理実行
    find_and_process_blocks(root)

    # ★★★ 変更箇所: 連続 <br> 整理のロジックを削除または調整 ★★★
    # 空白行用の<p><br></p>を残すため、この処理は削除するかコメントアウト
    # brs_to_remove = []
    # for br in soup.find_all("br"):
    #     nxt = br.next_sibling
    #     if isinstance(nxt, Tag) and nxt.name == "br":
    #         brs_to_remove.append(nxt)
    # for br in brs_to_remove:
    #     br.extract()

    # ログ出力
    print(f"[reflow] blocks={blocks_processed} -> paragraphs={total_new_paras} (n={sentences_per_para}, original_p={original_p_count})")

    return str(soup)

# ───────────── Google Drive: HTML -> Google Doc 作成 ─────────────

def drive_create_gdoc_from_html(creds: Credentials, html_text: str, name: str, folder_id: Optional[str]=None) -> tuple[str, str]:
    drive = build("drive", "v3", credentials=creds)
    media = MediaIoBaseUpload(io.BytesIO(html_text.encode("utf-8")), mimetype="text/html", resumable=False)
    metadata = {"name": name, "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        metadata["parents"] = [folder_id]
    file = drive.files().create(body=metadata, media_body=media, fields="id, webViewLink").execute()
    return file["id"], file.get("webViewLink", "")


def drive_share_anyone_writer(creds: Credentials, file_id: str):
    drive = build("drive", "v3", credentials=creds)
    drive.permissions().create(fileId=file_id, body={"type": "anyone", "role": "writer"}).execute()

# ───────────── Sheets helper（任意）─────────────

def sheets_client(creds: Credentials):
    return build("sheets", "v4", credentials=creds)


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

# ───────────── Docs helper：挿入ユーティリティ ─────────────

def _build_docs(creds: Credentials):
    return build("docs", "v1", credentials=creds)


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("//"):
        u = "https:" + u
    return u


def _find_heading1_insert_index(docs_svc, document_id: str) -> int:
    """最初の H1 段落の直後（= その段落の endIndex）を返す。なければ 1。"""
    doc = docs_svc.documents().get(documentId=document_id).execute()
    for c in doc.get("body", {}).get("content", []):
        para = c.get("paragraph")
        if not para:
            continue
        style = para.get("paragraphStyle", {})
        if style.get("namedStyleType") == "HEADING_1":
            end_index = c.get("endIndex")
            if isinstance(end_index, int):
                return end_index
    return 1


def _find_range_for_text(doc: dict, needle: str, prefer: str = "last", near_index: Optional[int] = None) -> Tuple[Optional[int], Optional[int]]:
    """ドキュメント全体から needle の開始/終了 index を探す。
    prefer="last" なら最も後ろ、"near" なら near_index 以上で最小距離のものを優先。
    """
    best_start = best_end = None
    best_metric = -1 if prefer == "last" else 10**12

    for c in doc.get("body", {}).get("content", []):
        para = c.get("paragraph")
        if not para:
            continue
        for el in para.get("elements", []):
            tr = el.get("textRun")
            if not tr:
                continue
            text = tr.get("content", "")
            idx = text.find(needle)
            if idx < 0:
                continue
            start = (el.get("startIndex") or 0) + idx
            end = start + len(needle)

            if prefer == "last":
                metric = start
                if best_start is None or metric >= best_metric:
                    best_start, best_end, best_metric = start, end, metric
            elif prefer == "near" and near_index is not None:
                dist = max(0, start - near_index)
                if best_start is None or dist < best_metric:
                    best_start, best_end, best_metric = start, end, dist

    return best_start, best_end


def docs_insert_disclosure_below_title(creds: Credentials, document_id: str, text: str):
    """タイトル直下に注意喚起を差し込み、**フォント11pt/太字** を適用（リンクは付けない）。"""
    docs = _build_docs(creds)

    insert_at = _find_heading1_insert_index(docs, document_id)
    to_insert = text.strip() + "\n\n"
    docs.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"location": {"index": insert_at}, "text": to_insert}}]}
    ).execute()

    # 再取得して範囲を特定（挿入位置近傍を優先）
    doc = docs.documents().get(documentId=document_id).execute()
    start_idx, end_idx = _find_range_for_text(doc, text.strip(), prefer="near", near_index=insert_at)
    if start_idx is None:
        print("[warn] disclosure text not found after insertion; style skipped.", file=sys.stderr)
        return

    docs.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [{
                "updateTextStyle": {
                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                    "textStyle": {
                        "bold": True,
                        "link": None,
                        "fontSize": {"magnitude": 11, "unit": "PT"}
                    },
                    "fields": "bold,link,fontSize"
                }
            }]
        }
    ).execute()
    print("[ok] inserted disclosure under title (bold + 11pt)")


def docs_insert_midpage_cta(creds: Credentials, document_id: str, anchor_text: str, url: str, bold: bool = True, font_size_pt: Optional[int] = None):
    """H2 見出し群の “中央付近” の直前に CTA を 1 回だけ挿入。bold と font_size_pt を指定可。"""
    docs = _build_docs(creds)

    doc = docs.documents().get(documentId=document_id).execute()
    h2_positions: List[int] = []
    for c in doc.get("body", {}).get("content", []):
        para = c.get("paragraph")
        if not para:
            continue
        style = para.get("paragraphStyle", {})
        if style.get("namedStyleType") == "HEADING_2":
            start = c.get("startIndex")
            if isinstance(start, int):
                h2_positions.append(start)

    if not h2_positions:
        print("[info] no H2 found; skip mid CTA")
        return

    h2_positions.sort()
    insert_at = h2_positions[len(h2_positions) // 2]

    # テキストを差し込む
    docs.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"location": {"index": insert_at}, "text": "\n" + anchor_text + "\n\n"}}]}
    ).execute()

    # 再取得→範囲特定（直近に挿入した位置の近くを優先）
    doc = docs.documents().get(documentId=document_id).execute()
    start_idx, end_idx = _find_range_for_text(doc, anchor_text, prefer="near", near_index=insert_at)
    if start_idx is None:
        print("[warn] mid CTA text not found after insertion; style skipped.", file=sys.stderr)
        return

    url = _normalize_url(url)
    style = {"link": {"url": url}, "bold": bool(bold)}
    fields = "link,bold"
    if font_size_pt is not None:
        style["fontSize"] = {"magnitude": int(font_size_pt), "unit": "PT"}
        fields += ",fontSize"

    docs.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [{
                "updateTextStyle": {
                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                    "textStyle": style,
                    "fields": fields
                }
            }]
        }
    ).execute()
    print(f"[ok] inserted mid CTA (bold={bool(bold)}, font={font_size_pt or 'default'})")


def docs_append_anchor_link(creds: Credentials, document_id: str, anchor_text: str, url: str, bold: bool = True):
    """ドキュメント末尾に `anchor_text` を挿入し、その範囲へ URL リンクと太字を適用。
    末尾に同文言が複数ある場合は **最後の一致** を対象にする。
    """
    docs = _build_docs(creds)

    insert_text = f"\n\n{anchor_text}\n"
    docs.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"endOfSegmentLocation": {}, "text": insert_text}}]}
    ).execute()

    doc = docs.documents().get(documentId=document_id).execute()
    start_idx, end_idx = _find_range_for_text(doc, anchor_text, prefer="last")
    if start_idx is None:
        print("[warn] anchor text not found after insertion; style skipped.", file=sys.stderr)
        return

    url = _normalize_url(url)
    style = {"link": {"url": url}, "bold": bool(bold)}

    docs.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [{
                "updateTextStyle": {
                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                    "textStyle": style,
                    "fields": "link,bold"
                }
            }]
        }
    ).execute()
    print(f"[ok] appended anchor link (bold={bool(bold)})")


# ★★★ 新規関数: ドキュメント内の全「公式サイト」にURLリンクを付与 ★★★
def docs_add_links_to_all_keywords(creds: Credentials, document_id: str, keyword: str, url: str):
    """ドキュメント内の指定キーワードすべてにURLリンクを設定"""
    docs = _build_docs(creds)

    # ドキュメントを取得
    doc = docs.documents().get(documentId=document_id).execute()

    # キーワードの出現箇所をすべて検索
    ranges_to_update: List[Tuple[int, int]] = []

    for c in doc.get("body", {}).get("content", []):
        para = c.get("paragraph")
        if not para:
            continue
        for el in para.get("elements", []):
            tr = el.get("textRun")
            if not tr:
                continue
            text = tr.get("content", "")

            # テキスト内でキーワードを検索（複数出現に対応）
            start_pos = 0
            while True:
                idx = text.find(keyword, start_pos)
                if idx < 0:
                    break

                # 範囲を計算
                start_index = (el.get("startIndex") or 0) + idx
                end_index = start_index + len(keyword)
                ranges_to_update.append((start_index, end_index))

                start_pos = idx + len(keyword)

    if not ranges_to_update:
        print(f"[info] keyword '{keyword}' not found in document")
        return

    # URLを正規化
    url = _normalize_url(url)

    # 各範囲にリンクを設定（逆順で処理してインデックスのずれを防ぐ）
    requests = []
    for start_idx, end_idx in sorted(ranges_to_update, reverse=True):
        requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start_idx, "endIndex": end_idx},
                "textStyle": {"link": {"url": url}},
                "fields": "link"
            }
        })

    # 一括更新
    docs.documents().batchUpdate(
        documentId=document_id,
        body={"requests": requests}
    ).execute()

    print(f"[ok] added links to {len(ranges_to_update)} occurrences of '{keyword}'")


# ★★★ 追加: Markdownの **..** がDocに残った場合の救済（太字化＋**削除）★★★

def docs_bold_markdown_asterisks(creds: Credentials, document_id: str):
    """Doc内に残ってしまった **強調** 記法を検出し、
    1) 内側テキストに太字を適用、2) アスタリスク ** を削除 する。
    既存処理に影響しないよう、太字適用→削除の順。削除は降順でまとめて送る。
    """
    docs = _build_docs(creds)
    doc = docs.documents().get(documentId=document_id).execute()

    bold_requests = []
    delete_ranges = []  # (start, end)
    pat = re.compile(r"\*\*(.+?)\*\*")

    for c in doc.get("body", {}).get("content", []):
        para = c.get("paragraph")
        if not para:
            continue
        for el in para.get("elements", []):
            tr = el.get("textRun")
            if not tr:
                continue
            txt = tr.get("content", "")
            base = (el.get("startIndex") or 0)
            for m in pat.finditer(txt):
                inner_start = base + m.start() + 2
                inner_end   = base + m.end() - 2
                bold_requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": inner_start, "endIndex": inner_end},
                        "textStyle": {"bold": True},
                        "fields": "bold"
                    }
                })
                delete_ranges.append((base + m.start(), base + m.start() + 2))
                delete_ranges.append((base + m.end() - 2, base + m.end()))

    if not bold_requests and not delete_ranges:
        print("[info] no '**..**' patterns found; skip bold-fix")
        return

    if bold_requests:
        docs.documents().batchUpdate(documentId=document_id, body={"requests": bold_requests}).execute()

    if delete_ranges:
        delete_ranges.sort(key=lambda x: x[0], reverse=True)
        del_reqs = [{"deleteContentRange": {"range": {"startIndex": s, "endIndex": e}}} for s, e in delete_ranges]
        docs.documents().batchUpdate(documentId=document_id, body={"requests": del_reqs}).execute()

    print(f"[ok] bolded and cleaned {len(delete_ranges)//2} '**..**' regions")


# ───────────── main ─────────────

def main():
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True, help="入力Markdownファイルのパス（例: out/article.md）")
    ap.add_argument("--title-prefix", default="", help="Doc名の先頭に付ける接頭辞（任意）")
    ap.add_argument("--folder-id", default="", help="作成先のDriveフォルダID（任意）")
    ap.add_argument("--share-anyone-writer", type=int, default=0, help="1=リンク所持者を編集者で共有")
    ap.add_argument("--sheet", default="", help="書き込み先スプレッドシートID（任意）")
    ap.add_argument("--tab", default="Sheet1", help="シート名（任意）")
    ap.add_argument("--col-a-width", type=int, default=520)
    ap.add_argument("--col-b-width", type=int, default=820)
    ap.add_argument("--force-login", type=int, default=0, help="1=token.jsonを無視して再認証する")
    ap.add_argument("--ad-disclosure", default="本記事にはアフィリエイトリンクを含みます。")
    ap.add_argument("--mid-cta-text", default="")
    ap.add_argument("--last-cta-text", default="→公式サイトはこちらから")
    ap.add_argument("--reflow", type=int, default=1, help="1=句点ごと段落化を有効, 0=無効")
    ap.add_argument("--sentences-per-para", type=int, default=2, help="1段落の文数（既定=2）")
    ap.add_argument("--fix-bold", type=int, default=1, help="1=Doc内の **..** を太字化し、アスタリスクを削除")  # ★デフォルト1に変更

    args = ap.parse_args()

    md_path = pathlib.Path(args.md)
    if not md_path.is_file():
        raise FileNotFoundError(f"md not found: {md_path}")

    md_text = md_path.read_text(encoding="utf-8").strip()
    doc_title = None
    for line in md_text.splitlines():
        if line.startswith("# "):
            doc_title = line[2:].strip()
            break
    if not doc_title:
        doc_title = md_path.stem

    name = (args.title_prefix + " " + doc_title).strip() if args.title_prefix else doc_title
    html_text = md_to_html(md_text)

    # ★★★ Bold保護：reflow前に<strong>を特殊記号に変換 ★★★
    if int(args.reflow) == 1:
        # <strong>タグを一時マーカーに置き換え
        html_text = html_text.replace('<strong>', '【BOLDSTART】').replace('</strong>', '【BOLDEND】')
        
        # リズム改行を実行
        html_text = rhythmic_reflow_html(html_text, sentences_per_para=max(1, int(args.sentences_per_para)))
        
        # マーカーを<strong>タグに復元
        html_text = html_text.replace('【BOLDSTART】', '<strong>').replace('【BOLDEND】', '</strong>')
        
        print("[ok] bold tags preserved through reflow")

    creds = get_creds(force_login=bool(args.force_login))
    file_id, link = drive_create_gdoc_from_html(creds, html_text, name, args.folder_id or None)
    print(f"[ok] Google Doc created: id={file_id}")
    print(f"[link] {link}")

    if int(args.share_anyone_writer) == 1:
        drive_share_anyone_writer(creds, file_id)
        print("[ok] sharing set: anyone with the link = writer")

    if args.sheet:
        sheet_id = sheets_get_or_create_sheet_id(creds, args.sheet, args.tab)
        sheets_append_title_url(creds, args.sheet, args.tab, doc_title, link)
        sheets_set_column_widths(creds, args.sheet, sheet_id, [args.col_a_width, args.col_b_width])
        print(f"[ok] appended (title/url) to sheet '{args.tab}' and set column widths")

    official_url = os.getenv("OFFICIAL_URL", "").strip() or None

    # ① タイトル直下に注意喚起
    try:
        if (args.ad_disclosure or "").strip():
            docs_insert_disclosure_below_title(creds, document_id=file_id, text=args.ad_disclosure.strip())
    except Exception as e:
        print(f"[warn] failed to insert disclosure under title: {e}", file=sys.stderr)

    # ② 中盤CTA
    if official_url:
        try:
            docs_insert_midpage_cta(creds, document_id=file_id, anchor_text=args.mid_cta_text, url=official_url, bold=True, font_size_pt=11)
        except Exception as e:
            print(f"[warn] failed to insert mid CTA: {e}", file=sys.stderr)
    else:
        print("[info] OFFICIAL_URL not set; skip mid CTA.")

    # ③ 末尾CTA
    if official_url:
        try:
            docs_append_anchor_link(creds, document_id=file_id, anchor_text=args.last_cta_text, url=official_url, bold=True)
        except Exception as e:
            print(f"[warn] failed to append anchor link: {e}", file=sys.stderr)
    else:
        print("[info] OFFICIAL_URL not set; skip append CTA.")

    # ④ キーワード一括リンク
    if official_url:
        try:
            docs_add_links_to_all_keywords(creds, document_id=file_id, keyword="公式サイト", url=official_url)
        except Exception as e:
            print(f"[warn] failed to add links to all keywords: {e}", file=sys.stderr)
    else:
        print("[info] OFFICIAL_URL not set; skip keyword link patch.")

    # ⑤ 残った**を太字化（念のため）
    if int(args.fix_bold) == 1:
        try:
            docs_bold_markdown_asterisks(creds, file_id)
        except Exception as e:
            print(f"[warn] failed to fix bold **..**: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()