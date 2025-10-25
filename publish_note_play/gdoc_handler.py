"""gdoc_handler.py"""

import re
import unicodedata
from typing import Tuple, Optional
import requests
from bs4 import BeautifulSoup


class GDocHandler:
    """Google Docs HTML処理クラス"""
    
    @staticmethod
    def extract_doc_id(url: str) -> Optional[str]:
        """URLからドキュメントIDを抽出"""
        m = re.search(r"/document/d/([a-zA-Z0-9\-_]+)", url)
        return m.group(1) if m else None
    
    @staticmethod
    def fetch_html(url: str) -> str:
        """GDocからHTMLをエクスポート"""
        doc_id = GDocHandler.extract_doc_id(url)
        if not doc_id:
            raise ValueError(f"DocID抽出失敗: {url}")
        
        export_url = f"https://docs.google.com/document/d/{doc_id}/export?format=html"
        r = requests.get(export_url, timeout=60)
        r.raise_for_status()
        return r.text
    
    @staticmethod
    def cleanup_html(raw_html: str) -> str:
        """<body>配下のみ抽出"""
        soup = BeautifulSoup(raw_html, "html.parser")
        body = soup.find("body")
        return body.decode_contents() if body else raw_html
    
    @staticmethod
    def normalize_text(s: str) -> str:
        """テキスト正規化（比較用）"""
        s = unicodedata.normalize("NFKC", s or "")
        s = s.replace("\u3000", " ")
        s = re.sub(r"\s+", " ", s).strip().lower()
        s = re.sub(r"""["'、。,.!！?？:：;‐−—･・/｜|\[\]\(\)（）【】「」『』…⋯\-]+""", "", s)
        return s
    
    @staticmethod
    def normalize_inline_styles(html: str) -> str:
        """インラインスタイルをセマンティックタグに変換"""
        soup = BeautifulSoup(html, "html.parser")
        
        def is_bold(style: str) -> bool:
            style = (style or "").lower()
            return ("font-weight" in style) and any(
                w in style for w in ["bold", "600", "700", "800", "900"]
            )
        
        def is_italic(style: str) -> bool:
            style = (style or "").lower()
            return ("font-style" in style) and ("italic" in style)
        
        for tag in soup.find_all(True):
            bold = tag.name in ("b", "strong") or is_bold(tag.get("style", ""))
            ital = tag.name in ("i", "em") or is_italic(tag.get("style", ""))
            
            if bold and ital:
                new_strong = soup.new_tag("strong")
                new_em = soup.new_tag("em")
                for c in list(tag.contents):
                    new_em.append(c)
                new_strong.append(new_em)
                tag.clear()
                tag.append(new_strong)
                tag.name = "span"
            elif bold:
                tag.name = "strong"
            elif ital:
                tag.name = "em"
            
            # 属性削除
            for k in list(tag.attrs.keys()):
                if k in ("style", "class", "id") or k.startswith("data-"):
                    try:
                        del tag.attrs[k]
                    except Exception:
                        pass
        
        for b in soup.find_all("b"):
            b.name = "strong"
        for i in soup.find_all("i"):
            i.name = "em"
        
        body = soup.find("body")
        return body.decode_contents() if body else str(soup)
    
    @staticmethod
    def remove_title_from_html(html: str, title: str) -> Tuple[str, bool]:
        """先頭のタイトル要素を除去"""
        try:
            soup = BeautifulSoup(html, "html.parser")
            body = soup if soup.name == "body" else soup
            
            candidates = []
            for el in list(body.children):
                if getattr(el, "name", None) is None:
                    if len(str(el).strip()) == 0:
                        continue
                    continue
                if el.name in ["h1", "h2", "h3", "p", "div"]:
                    if not el.get_text(strip=True):
                        continue
                    candidates.append(el)
                    if len(candidates) >= 5:
                        break
            
            if not candidates:
                return html, False
            
            norm_title = GDocHandler.normalize_text(title)
            removed = False
            
            for el in candidates:
                txt = el.get_text(separator=" ", strip=True)
                nt = GDocHandler.normalize_text(txt)
                if nt == norm_title or nt.startswith(norm_title):
                    el.decompose()
                    removed = True
                    break
            
            cleaned = str(soup)
            if removed and "<body" in cleaned:
                soup2 = BeautifulSoup(cleaned, "html.parser")
                b2 = soup2.find("body")
                return (b2.decode_contents() if b2 else cleaned), True
            
            return (cleaned if removed else html), removed
        except Exception:
            return html, False
    
    @staticmethod
    def normalize_affiliate_notice(html: str) -> str:
        """アフィリエイト告知を通常スタイルに"""
        try:
            soup = BeautifulSoup(html, "html.parser")
            body = soup.find("body") or soup
            blocks = [
                el for el in body.find_all(
                    ["h1", "h2", "h3", "h4", "h5", "h6", "p", "div"],
                    recursive=False
                )
            ][:10]
            
            pat = re.compile(r"(アフィリエイト|プロモーション|広告|\\bPR\\b|スポンサー|紹介料)")
            target = None
            
            for el in blocks:
                txt = (el.get_text(" ", strip=True) or "")
                if pat.search(txt):
                    target = el
                    break
            
            if not target:
                return html
            
            # 太字タグ除去
            for b in target.find_all(["strong", "b"]):
                b.unwrap()
            
            # スタイル除去
            def strip_styles(node):
                if hasattr(node, 'attrs'):
                    st = (node.get('style') or '').lower()
                    if 'font-weight' in st or 'font-size' in st:
                        try:
                            del node['style']
                        except Exception:
                            pass
                for ch in getattr(node, 'children', []) or []:
                    strip_styles(ch)
            
            strip_styles(target)
            
            # 見出しをpに降格
            if target.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                target.name = "p"
            
            return (soup.find("body").decode_contents() if soup.find("body") else str(soup))
        except Exception:
            return html
    
    @staticmethod
    def process_document(url: str, title: str) -> Tuple[str, bool]:
        """ドキュメント全体の処理"""
        raw = GDocHandler.fetch_html(url)
        html = GDocHandler.cleanup_html(raw)
        html = GDocHandler.normalize_inline_styles(html)
        cleaned, removed = GDocHandler.remove_title_from_html(html, title)
        cleaned = GDocHandler.normalize_affiliate_notice(cleaned)
        return cleaned, removed
