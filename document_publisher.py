# document_publisher.py
# -*- coding: utf-8 -*-
"""
ドキュメント公開スクリプト（リファクタ版）
旧publish_gdoc_html.pyの全機能を維持

使い方:
  python document_publisher.py --md out/article.md --folder-id 1Ay4...
"""
import os
import sys
import pathlib
import argparse
import io
import re
import html
from typing import List, Tuple, Optional

from bs4 import BeautifulSoup, Tag
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# 共通モジュール
from lib.auth import GoogleAuth
from lib.config import Config

# ───────────── Markdown → HTML 変換 ─────────────
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
    """インライン要素のレンダリング"""
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
    """Markdown→HTML変換（簡易版）"""
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
                    close_list()
                    if prefix: out.append(f"<p>{render_inline(prefix)}</p>")
                    open_list("ul")
                    for it in parts: out.append(f"<li>{render_inline(it)}</li>")
                    close_list()
                    if post: out.append(f"<p>{render_inline(post)}</p>")
                    continue
            else:
                prefix = ln[:m_ol.start()].strip(); rest = ln[m_ol.start():].strip()
                parts = [s.strip() for s in RX_OL_SPLIT.split(rest) if s.strip()]
                if len(parts) >= 3:
                    parts[-1], post = _split_last_item(parts[-1])
                    close_list()
                    if prefix: out.append(f"<p>{render_inline(prefix)}</p>")
                    open_list("ol")
                    for it in parts: out.append(f"<li>{render_inline(it)}</li>")
                    close_list()
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
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Imported Article</title>
</head>
<body>
{body}
</body>
</html>"""

# ───────────── リズム改行処理 ─────────────
INLINE_OK = {"b","strong","i","em","span","a","br","u","s","small","mark","sub","sup","code"}
SKIP_TAGS = {"code","pre","table","thead","tbody","tr","th","td","ul","ol","li","blockquote"}
HEADING_TAGS = {"h1","h2","h3","h4","h5","h6"}

def _reflow_paragraph_text(text: str, sentences_per_para: int = 2) -> List[str]:
    """テキストを句点で分割してN文ごとに段落化"""
    txt = re.sub(r"[ \t]*\n+[ \t]*", "", text)
    txt = re.sub(r'([」』])([。．])', r'\1', txt)
    txt = re.sub(r'([」』])[　\s]+([。．])', r'\1', txt)

    sentences: List[str] = []
    current: List[str] = []
    in_quote = False

    for i, char in enumerate(txt):
        current.append(char)
        if char in "「『":
            in_quote = True
        elif char in "」』":
            in_quote = False

        if (not in_quote and char in "。．！？" and i + 1 < len(txt)):
            nxt = txt[i + 1]
            if not (nxt.isspace() or nxt == "　"):
                sent = "".join(current).strip()
                if sent:
                    sentences.append(sent)
                current = []

    if current:
        sent = "".join(current).strip()
        if sent:
            sentences.append(sent)

    cleaned_sentences: List[str] = []
    for sent in sentences:
        cleaned = re.sub(r'^[。、．，）"』]+\s*', '', sent).strip()
        if cleaned:
            cleaned_sentences.append(cleaned)

    if not cleaned_sentences:
        return [text.strip()] if text.strip() else []

    paras: List[str] = []
    for i in range(0, len(cleaned_sentences), sentences_per_para):
        chunk = "".join(cleaned_sentences[i:i+sentences_per_para]).strip()
        if chunk:
            paras.append(chunk)
    return paras

def rhythmic_reflow_html(html_text: str, sentences_per_para: int = 2) -> str:
    """HTMLのリズム改行処理"""
    soup = BeautifulSoup(html_text, "html.parser")
    root = soup.body or soup
    
    original_p_count = len(soup.find_all("p"))
    blocks_processed = 0
    total_new_paras = 0

    def is_inline_only(tag: Tag) -> bool:
        if not isinstance(tag, Tag):
            return False
        for c in tag.children:
            if isinstance(c, Tag) and c.name not in INLINE_OK:
                return False
        return True

    def is_text_paragraph(element) -> bool:
        if not isinstance(element, Tag):
            return False
        if element.name in SKIP_TAGS or element.name in HEADING_TAGS:
            return False
        if element.name in {"p", "div"} and is_inline_only(element):
            return True
        return False

    def find_and_process_blocks(container: Tag):
        nonlocal blocks_processed, total_new_paras
        
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
                    
                    if child.name not in SKIP_TAGS and child.name not in HEADING_TAGS:
                        find_and_process_blocks(child)
        
        if current_block:
            blocks_to_process.append(current_block)
        
        for block in blocks_to_process:
            if len(block) == 0:
                continue
            
            blocks_processed += 1
            
            combined_text = ""
            for tag in block:
                text = tag.get_text()
                text = re.sub(r"\s*\n\s*", "", text).strip()
                if text:
                    combined_text += text
            
            if not combined_text:
                continue
            
            paras = _reflow_paragraph_text(combined_text, sentences_per_para)
            
            if len(paras) == 0:
                continue
            
            total_new_paras += len(paras)
            
            first_tag = block[0]
            for i, para_text in enumerate(paras):
                new_p = soup.new_tag("p")
                new_p.string = para_text
                first_tag.insert_before(new_p)
                
                if i < len(paras) - 1:
                    spacer_p = soup.new_tag("p")
                    spacer_p.append(soup.new_tag("br"))
                    first_tag.insert_before(spacer_p)
            
            for old_tag in block:
                old_tag.extract()

    find_and_process_blocks(root)
    
    print(f"[reflow] blocks={blocks_processed} -> paragraphs={total_new_paras} (n={sentences_per_para}, original={original_p_count})")
    
    return str(soup)

# ───────────── Google Drive/Docs/Sheets操作 ─────────────
def drive_create_gdoc_from_html(auth: GoogleAuth, html_text: str, name: str, 
                               folder_id: Optional[str] = None) -> Tuple[str, str]:
    """HTMLからGoogleドキュメントを作成"""
    drive = auth.build_service("drive", "v3")
    media = MediaIoBaseUpload(io.BytesIO(html_text.encode("utf-8")), 
                             mimetype="text/html", resumable=False)
    metadata = {"name": name, "mimeType": "application/vnd.google-apps.document"}
    if folder_id:
        metadata["parents"] = [folder_id]
    file = drive.files().create(body=metadata, media_body=media, 
                               fields="id, webViewLink").execute()
    return file["id"], file.get("webViewLink", "")

def drive_share_anyone_writer(auth: GoogleAuth, file_id: str):
    """誰でも編集可能に設定"""
    drive = auth.build_service("drive", "v3")
    drive.permissions().create(fileId=file_id, 
                              body={"type": "anyone", "role": "writer"}).execute()

def sheets_get_or_create_sheet_id(auth: GoogleAuth, spreadsheet_id: str, 
                                  sheet_name: str) -> int:
    """シートIDを取得（なければ作成）"""
    sheets = auth.build_service("sheets", "v4")
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    
    for sh in meta.get("sheets", []):
        if sh.get("properties", {}).get("title") == sheet_name:
            return int(sh["properties"]["sheetId"])
    
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}
    ).execute()
    
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sh in meta.get("sheets", []):
        if sh.get("properties", {}).get("title") == sheet_name:
            return int(sh["properties"]["sheetId"])
    
    raise RuntimeError(f"シート作成失敗: {sheet_name}")

def sheets_set_column_widths(auth: GoogleAuth, spreadsheet_id: str, 
                            sheet_id: int, widths_px: List[int]):
    """列幅設定"""
    reqs = []
    for idx, px in enumerate(widths_px):
        reqs.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", 
                         "startIndex": idx, "endIndex": idx+1},
                "properties": {"pixelSize": int(px)},
                "fields": "pixelSize"
            }
        })
    sheets = auth.build_service("sheets", "v4")
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": reqs}
    ).execute()

def sheets_append_title_url(auth: GoogleAuth, spreadsheet_id: str, 
                           sheet_name: str, title: str, url: str):
    """タイトルとURLを追記"""
    sheets = auth.build_service("sheets", "v4")
    sheets.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [[title, url]]}
    ).execute()

# ───────────── Docs編集ユーティリティ ─────────────
def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("//"):
        u = "https:" + u
    return u

def _find_heading1_insert_index(docs_svc, document_id: str) -> int:
    """H1の直後位置を取得"""
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

def _find_range_for_text(doc: dict, needle: str, prefer: str = "last", 
                        near_index: Optional[int] = None) -> Tuple[Optional[int], Optional[int]]:
    """テキストの範囲を検索"""
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

def docs_insert_disclosure_below_title(auth: GoogleAuth, document_id: str, text: str):
    """タイトル直下に注意書き挿入"""
    docs = auth.build_service("docs", "v1")
    
    insert_at = _find_heading1_insert_index(docs, document_id)
    to_insert = text.strip() + "\n\n"
    docs.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"location": {"index": insert_at}, "text": to_insert}}]}
    ).execute()
    
    doc = docs.documents().get(documentId=document_id).execute()
    start_idx, end_idx = _find_range_for_text(doc, text.strip(), prefer="near", near_index=insert_at)
    if start_idx is None:
        print("[warn] disclosure text not found", file=sys.stderr)
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
    print("[ok] disclosure inserted")

def docs_insert_midpage_cta(auth: GoogleAuth, document_id: str, anchor_text: str, 
                           url: str, bold: bool = True, font_size_pt: Optional[int] = None):
    """中盤にCTA挿入"""
    docs = auth.build_service("docs", "v1")
    
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
        print("[info] no H2; skip mid CTA")
        return
    
    h2_positions.sort()
    insert_at = h2_positions[len(h2_positions) // 2]
    
    docs.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"location": {"index": insert_at}, 
                                          "text": "\n" + anchor_text + "\n\n"}}]}
    ).execute()
    
    doc = docs.documents().get(documentId=document_id).execute()
    start_idx, end_idx = _find_range_for_text(doc, anchor_text, prefer="near", near_index=insert_at)
    if start_idx is None:
        print("[warn] mid CTA text not found", file=sys.stderr)
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
    print(f"[ok] mid CTA inserted (bold={bold}, font={font_size_pt or 'default'})")

def docs_append_anchor_link(auth: GoogleAuth, document_id: str, anchor_text: str, 
                           url: str, bold: bool = True):
    """末尾にアンカーリンク追加"""
    docs = auth.build_service("docs", "v1")
    
    insert_text = f"\n\n{anchor_text}\n"
    docs.documents().batchUpdate(
        documentId=document_id,
        body={"requests": [{"insertText": {"endOfSegmentLocation": {}, "text": insert_text}}]}
    ).execute()
    
    doc = docs.documents().get(documentId=document_id).execute()
    start_idx, end_idx = _find_range_for_text(doc, anchor_text, prefer="last")
    if start_idx is None:
        print("[warn] anchor text not found", file=sys.stderr)
        return
    
    url = _normalize_url(url)
    docs.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [{
                "updateTextStyle": {
                    "range": {"startIndex": start_idx, "endIndex": end_idx},
                    "textStyle": {"link": {"url": url}, "bold": bool(bold)},
                    "fields": "link,bold"
                }
            }]
        }
    ).execute()
    print(f"[ok] anchor link appended")

def docs_add_links_to_all_keywords(auth: GoogleAuth, document_id: str, 
                                  keyword: str, url: str):
    """全キーワードにリンク付与"""
    docs = auth.build_service("docs", "v1")
    doc = docs.documents().get(documentId=document_id).execute()
    
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
            
            start_pos = 0
            while True:
                idx = text.find(keyword, start_pos)
                if idx < 0:
                    break
                start_index = (el.get("startIndex") or 0) + idx
                end_index = start_index + len(keyword)
                ranges_to_update.append((start_index, end_index))
                start_pos = idx + len(keyword)
    
    if not ranges_to_update:
        print(f"[info] keyword '{keyword}' not found")
        return
    
    url = _normalize_url(url)
    requests = []
    for start_idx, end_idx in sorted(ranges_to_update, reverse=True):
        requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start_idx, "endIndex": end_idx},
                "textStyle": {"link": {"url": url}},
                "fields": "link"
            }
        })
    
    docs.documents().batchUpdate(
        documentId=document_id,
        body={"requests": requests}
    ).execute()
    
    print(f"[ok] {len(ranges_to_update)} keyword links added")

def docs_bold_markdown_asterisks(auth: GoogleAuth, document_id: str):
    """残った**記法を太字化"""
    docs = auth.build_service("docs", "v1")
    doc = docs.documents().get(documentId=document_id).execute()
    
    bold_requests = []
    delete_ranges = []
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
                inner_end = base + m.end() - 2
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
        print("[info] no '**..**' found")
        return
    
    if bold_requests:
        docs.documents().batchUpdate(documentId=document_id, 
                                    body={"requests": bold_requests}).execute()
    
    if delete_ranges:
        delete_ranges.sort(key=lambda x: x[0], reverse=True)
        del_reqs = [{"deleteContentRange": {"range": {"startIndex": s, "endIndex": e}}} 
                   for s, e in delete_ranges]
        docs.documents().batchUpdate(documentId=document_id, 
                                    body={"requests": del_reqs}).execute()
    
    print(f"[ok] {len(delete_ranges)//2} bold regions fixed")

# ───────────── メイン ─────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--title-prefix", default="")
    ap.add_argument("--folder-id", default="")
    ap.add_argument("--share-anyone-writer", type=int, default=0)
    ap.add_argument("--sheet", default="")
    ap.add_argument("--tab", default="Sheet1")
    ap.add_argument("--col-a-width", type=int, default=520)
    ap.add_argument("--col-b-width", type=int, default=820)
    ap.add_argument("--force-login", type=int, default=0)
    ap.add_argument("--ad-disclosure", default="本記事にはアフィリエイトリンクを含みます。")
    ap.add_argument("--mid-cta-text", default="")
    ap.add_argument("--last-cta-text", default="→公式サイトはこちらから")
    ap.add_argument("--reflow", type=int, default=1)
    ap.add_argument("--sentences-per-para", type=int, default=2)
    ap.add_argument("--fix-bold", type=int, default=1)
    
    args = ap.parse_args()
    
    # 設定読み込み
    config = Config()
    
    # MD読み込み
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
    
    # リズム改行
    if int(args.reflow) == 1:
        html_text = html_text.replace('<strong>', '【BOLDSTART】').replace('</strong>', '【BOLDEND】')
        html_text = rhythmic_reflow_html(html_text, sentences_per_para=max(1, int(args.sentences_per_para)))
        html_text = html_text.replace('【BOLDSTART】', '<strong>').replace('【BOLDEND】', '</strong>')
        print("[ok] reflow completed")
    
    # Google認証
    auth = GoogleAuth()
    
    # ドキュメント作成
    file_id, link = drive_create_gdoc_from_html(
        auth, html_text, name, args.folder_id or None
    )
    print(f"[ok] Google Doc created: {file_id}")
    print(f"[link] {link}")
    
    # 共有設定
    if int(args.share_anyone_writer) == 1:
        drive_share_anyone_writer(auth, file_id)
        print("[ok] sharing enabled")
    
    # スプレッドシート追記
    if args.sheet:
        sheet_id = sheets_get_or_create_sheet_id(auth, args.sheet, args.tab)
        sheets_append_title_url(auth, args.sheet, args.tab, doc_title, link)
        sheets_set_column_widths(auth, args.sheet, sheet_id, 
                                [args.col_a_width, args.col_b_width])
        print(f"[ok] sheet updated")
    
    official_url = config.official_url or None
    
    # 注意書き
    try:
        if (args.ad_disclosure or "").strip():
            docs_insert_disclosure_below_title(auth, file_id, args.ad_disclosure.strip())
    except Exception as e:
        print(f"[warn] disclosure failed: {e}", file=sys.stderr)
    
    # 中盤CTA
    if official_url and args.mid_cta_text:
        try:
            docs_insert_midpage_cta(auth, file_id, args.mid_cta_text, 
                                   official_url, bold=True, font_size_pt=11)
        except Exception as e:
            print(f"[warn] mid CTA failed: {e}", file=sys.stderr)
    
    # 末尾CTA
    if official_url:
        try:
            docs_append_anchor_link(auth, file_id, args.last_cta_text, 
                                   official_url, bold=True)
        except Exception as e:
            print(f"[warn] last CTA failed: {e}", file=sys.stderr)
    
    # キーワードリンク
    if official_url:
        try:
            docs_add_links_to_all_keywords(auth, file_id, "公式サイト", official_url)
        except Exception as e:
            print(f"[warn] keyword links failed: {e}", file=sys.stderr)
    
    # **記法修正
    if int(args.fix_bold) == 1:
        try:
            docs_bold_markdown_asterisks(auth, file_id)
        except Exception as e:
            print(f"[warn] bold fix failed: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()