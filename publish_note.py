# publish_note.py（目次・アイキャッチ対応版）
# ーーー 追加機能 ーーー
# ・アイキャッチ画像の自動挿入（Google DriveのURLから）
# ・目次の自動挿入
# ・公開後の確定URLのみをスプシに保存

import os
import re
import time
import argparse
import unicodedata
import tempfile
from dataclasses import dataclass
from typing import Optional, List, Tuple
from pathlib import Path

from dotenv import load_dotenv
from bs4 import BeautifulSoup
import requests

# --- Google Sheets ---
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GRequest
from googleapiclient.discovery import build

# --- Selenium ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# ========== ENV ==========
load_dotenv()
SHEET_ID      = os.getenv("SHEET_ID")
SHEET_NAME    = os.getenv("SHEET_NAME", "Articles")
NOTE_EMAIL    = os.getenv("NOTE_EMAIL", "").strip()
NOTE_PASSWORD = os.getenv("NOTE_PASSWORD", "").strip()
HEADLESS      = os.getenv("HEADLESS", "1").strip() in ("1","true","TRUE","True")
ROW_LIMIT     = int(os.getenv("ROW_LIMIT", "0"))

CHROME_USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", "").strip()
CHROME_PROFILE_DIR   = os.getenv("CHROME_PROFILE_DIR", "").strip()

# スプシ列: A..F  (persona, title, doc_url, eyecatch, status, note_url)
COL_PERSONA=0; COL_TITLE=1; COL_DOC=2; COL_EYE=3; COL_STATUS=4; COL_NOTEURL=5
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ========== Data ==========
@dataclass
class RowItem:
    row_index: int
    persona: str
    title: str
    doc_url: str
    status: str
    note_url: str
    eyecatch_path: str

# ========== Sheets ==========

def gs_service():
    if not SHEET_ID:
        raise ValueError("SHEET_ID が .env に未設定です")
    creds=None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(GRequest())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError("credentials.json がありません（Google Sheets認可用）")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json","w",encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("sheets","v4",credentials=creds)


def read_rows(svc) -> List[RowItem]:
    rng = f"{SHEET_NAME}!A2:F"
    values = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=rng
    ).execute().get("values",[])
    out=[]
    for i,row in enumerate(values,start=2):
        row += [""]*(6-len(row))
        persona,title,doc,eye,status,nurl = row[:6]
        out.append(RowItem(
            row_index=i,
            persona=(persona or "").strip(),
            title=(title or "").strip(),
            doc_url=(doc or "").strip(),
            status=(status or "").strip(),
            note_url=(nurl or "").strip(),
            eyecatch_path=(eye or "").strip(),
        ))
    return out


def write_back(svc, row_index:int, status:str, note_url:str):
    svc.spreadsheets().values().update(
        spreadsheetId=SHEET_ID,
        range=f"{SHEET_NAME}!E{row_index}:F{row_index}",
        valueInputOption="RAW",
        body={"values":[[status, note_url]]}
    ).execute()

# ========== アイキャッチ画像パス検証 ==========

def validate_image_path(image_path: str) -> bool:
    """画像ファイルパスの存在確認"""
    if not image_path:
        return False
    if not os.path.exists(image_path):
        print(f"[warn] 画像ファイルが見つかりません: {image_path}")
        return False
    if not os.path.isfile(image_path):
        print(f"[warn] パスがファイルではありません: {image_path}")
        return False
    # 拡張子チェック
    ext = os.path.splitext(image_path)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        print(f"[warn] サポートされていない画像形式: {ext}")
        return False
    return True

# ========== GDoc -> HTML ==========

def _doc_id(url:str)->Optional[str]:
    m=re.search(r"/document/d/([a-zA-Z0-9\-_]+)", url)
    return m.group(1) if m else None


def gdoc_raw_html(url:str)->str:
    did=_doc_id(url)
    if not did:
        raise ValueError(f"DocID抽出失敗: {url}")
    ex=f"https://docs.google.com/document/d/{did}/export?format=html"
    r=requests.get(ex,timeout=60)
    r.raise_for_status()
    return r.text


def cleanup_exported_html(raw_html: str) -> str:
    """GDocのexport HTMLから<body>配下だけ抽出（style温存）。"""
    soup = BeautifulSoup(raw_html, "html.parser")
    body = soup.find("body")
    html = body.decode_contents() if body else raw_html
    return html

# ===== タイトル除去ロジック =====

def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = re.sub(r"[""\"'''、。,.!！?？:：;\-‐−—･・/｜|\\\\\\[\\\\]\\(\\)（）【】「」『』…⋯]+", "", s)
    return s


def remove_leading_title_from_html(html: str, title: str) -> Tuple[str, bool]:
    """本文先頭付近のタイトル相当ノード（h1/h2/p/div 等）を1つだけ除去。"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        body = soup if soup.name == "body" else soup
        candidates = []
        for el in list(body.children):
            if getattr(el, "name", None) is None:
                if len(str(el).strip()) == 0:
                    continue
                continue
            if el.name in ["h1","h2","h3","p","div"]:
                if not el.get_text(strip=True):
                    continue
                candidates.append(el)
                if len(candidates) >= 5:
                    break
        if not candidates:
            return html, False
        norm_title = _norm_text(title)
        removed = False
        for el in candidates:
            txt = el.get_text(separator=" ", strip=True)
            nt  = _norm_text(txt)
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


def normalize_inline_styles_to_semantic(html: str) -> str:
    """<span style="font-weight:700">等を<strong>/<em>へ正規化し、余計な属性を削除。"""
    soup = BeautifulSoup(html, "html.parser")

    def is_bold(style: str) -> bool:
        style = (style or "").lower()
        return ("font-weight" in style) and any(w in style for w in ["bold", "600", "700", "800", "900"])

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
            tag.clear(); tag.append(new_strong); tag.name = "span"
        elif bold:
            tag.name = "strong"
        elif ital:
            tag.name = "em"
        for k in list(tag.attrs.keys()):
            if k in ("style","class","id") or k.startswith("data-"):
                try: del tag.attrs[k]
                except Exception: pass

    for b in soup.find_all("b"): b.name = "strong"
    for i in soup.find_all("i"): i.name = "em"
    body = soup.find("body")
    return body.decode_contents() if body else str(soup)


def normalize_affiliate_notice(html: str) -> str:
    """先頭付近のアフィリエイト/PR告知を"通常の本文スタイル"（太字/大見出しを外す）に整形。"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body") or soup
        blocks = [el for el in body.find_all(
            ["h1","h2","h3","h4","h5","h6","p","div"], recursive=False
        )][:10]

        pat = re.compile(r"(アフィリエイト|プロモーション|広告|\\bPR\\b|スポンサー|紹介料)")
        target = None
        for el in blocks:
            txt = (el.get_text(" ", strip=True) or "")
            if pat.search(txt):
                target = el
                break
        if not target:
            return html

        for b in target.find_all(["strong","b"]):
            b.unwrap()

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

        if target.name in ["h1","h2","h3","h4","h5","h6"]:
            target.name = "p"

        return (soup.find("body").decode_contents() if soup.find("body") else str(soup))
    except Exception:
        return html


def drop_title_headings_anywhere_early(html: str, title: str) -> str:
    """先頭から10ブロックの中にタイトルと完全一致する h1/h2 があれば除去（保険）。"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body") or soup
        norm_title = _norm_text(title)
        blocks = [el for el in body.find_all(["h1","h2","p","div"], recursive=False)][:10]
        for el in blocks:
            txt = el.get_text(" ", strip=True) if hasattr(el, 'get_text') else ""
            if _norm_text(txt) == norm_title and el.name in ("h1","h2"):
                el.decompose()
                break
        return (soup.find("body").decode_contents() if soup.find("body") else str(soup))
    except Exception:
        return html


def gdoc_html_without_title(url: str, title: str) -> Tuple[str, bool]:
    raw = gdoc_raw_html(url)
    html = cleanup_exported_html(raw)
    html = normalize_inline_styles_to_semantic(html)
    cleaned, removed = remove_leading_title_from_html(html, title)
    cleaned = drop_title_headings_anywhere_early(cleaned, title)
    cleaned = normalize_affiliate_notice(cleaned)
    return cleaned, removed

# ========== Selenium helpers ==========

def build_driver(headless:bool,user_data_dir:Optional[str],profile:Optional[str])->webdriver.Chrome:
    opts=webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=ja-JP")
    if user_data_dir:
        opts.add_argument(f"--user-data-dir={user_data_dir}")
    if profile:
        opts.add_argument(f"--profile-directory={profile}")
    drv=webdriver.Chrome(options=opts)
    drv.set_page_load_timeout(60)
    return drv


def doc_ready(drv,timeout=20):
    try:
        WebDriverWait(drv,timeout).until(
            lambda d:d.execute_script("return document.readyState")=="complete"
        )
    except Exception:
        pass


def is_logged_in(drv)->bool:
    try:
        avatar_sels = [
            'img[alt="ユーザーアイコン"]',
            'a[href^="/users/"] img',
            'button[aria-haspopup="menu"] img',
            'a[href^="/settings"]',
            'a[href^="/@"] img',
        ]
        for s in avatar_sels:
            for el in drv.find_elements(By.CSS_SELECTOR, s):
                if el.is_displayed():
                    return True
        for el in drv.find_elements(By.CSS_SELECTOR, 'a[href="/notes/new"]'):
            if el.is_displayed():
                return True
        if drv.find_elements(By.CSS_SELECTOR, 'a[href^="/login"]'):
            return False
        return False
    except Exception:
        return False


def click_nav_login(drv):
    candidates = [
        '.o-navbarPrimaryGuest__navItem.login a',
        'a.a-button[href^="/login"]',
        'a[href^="/login"]',
        '//a[contains(.,"ログイン")]',
    ]
    for sel in candidates:
        try:
            by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
            el = WebDriverWait(drv, 5).until(EC.element_to_be_clickable((by, sel)))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            drv.execute_script("arguments[0].click();", el)
            break
        except Exception:
            continue
    try:
        WebDriverWait(drv, 12).until(EC.url_contains("/login"))
    except TimeoutException:
        drv.get("https://note.com/login")
        WebDriverWait(drv, 10).until(EC.url_contains("/login"))


def close_popups(drv,timeout_sec:int=4):
    sels=[
        "button#onetrust-accept-btn-handler",
        "button[data-testid='cookie-policy-agree-button']",
        "button[aria-label='閉じる']",
        "button[aria-label='Close']",
        "//button[contains(., '同意')]",
        "//button[contains(., 'OK')]",
        "//button[contains(., '後で')]",
    ]
    end=time.time()+max(1,timeout_sec)
    while time.time()<end:
        for s in sels:
            try:
                by=By.XPATH if s.startswith("//") else By.CSS_SELECTOR
                for el in drv.find_elements(by,s):
                    if el.is_displayed() and el.is_enabled():
                        drv.execute_script("arguments[0].click();", el)
                        time.sleep(0.2)
                        return
            except Exception:
                pass
        time.sleep(0.15)


def ensure_logged_in(drv,email:str,password:str):
    try:
        drv.get("https://note.com/logout")
        doc_ready(drv,10)
        time.sleep(0.6)
    except Exception:
        pass

    drv.get("https://note.com/")
    doc_ready(drv,15)
    close_popups(drv,4)

    click_nav_login(drv)
    doc_ready(drv,20)
    close_popups(drv,4)

    if is_logged_in(drv):
        print("[info] 既にログイン済み（想定外だが続行）")
        return

    if not email or not password:
        raise ValueError("NOTE_EMAIL / NOTE_PASSWORD が未設定です (.env)")

    email_sel = "input#email"
    pw_sel    = "input#password"
    btn_sel   = ".o-login__button button, button[type='submit']"

    try:
        email_box = WebDriverWait(drv,15).until(EC.presence_of_element_located((By.CSS_SELECTOR,email_sel)))
        drv.execute_script("""
            const el = arguments[0], val = arguments[1];
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, email_box, email)
        time.sleep(0.2)

        next_btn = None
        for sel in btn_sel.split(","):
            els = drv.find_elements(By.CSS_SELECTOR, sel.strip())
            if els: next_btn = els[0]; break
        if next_btn:
            drv.execute_script("arguments[0].click();", next_btn)
            time.sleep(0.6)

        pw_box = WebDriverWait(drv,15).until(EC.presence_of_element_located((By.CSS_SELECTOR,pw_sel)))
        drv.execute_script("""
            const el = arguments[0], val = arguments[1];
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, pw_box, password)
        time.sleep(0.2)

        login_btn = None
        for sel in btn_sel.split(","):
            els = drv.find_elements(By.CSS_SELECTOR, sel.strip())
            if els: login_btn = els[0]; break
        if login_btn:
            WebDriverWait(drv,10).until(lambda d: d.execute_script("return !arguments[0].disabled;", login_btn))
            drv.execute_script("arguments[0].click();", login_btn)
        else:
            pw_box.send_keys(Keys.ENTER)

        WebDriverWait(drv,45).until(lambda d: is_logged_in(d))
        print("[info] ログイン成功（UI検知）")
        time.sleep(2)
        doc_ready(drv, 10)
        close_popups(drv, 4)
    except TimeoutException as e:
        ts=time.strftime("%Y%m%d_%H%M%S")
        try:
            drv.save_screenshot(f"debug_login_failed_{ts}.png")
            with open(f"debug_login_failed_{ts}.html","w",encoding="utf-8") as f:
                f.write(drv.page_source)
        except Exception:
            pass
        raise e


def check_and_relogin_if_needed(drv, email: str, password: str):
    if is_logged_in(drv):
        print("[info] ログイン状態を確認: OK")
        return
    print("[warn] ログアウトを検知、再ログイン実施")
    click_nav_login(drv)
    doc_ready(drv, 20)
    close_popups(drv, 4)
    if is_logged_in(drv):
        print("[info] 既にログイン済み（再確認）")
        return
    if not email or not password:
        raise ValueError("NOTE_EMAIL / NOTE_PASSWORD が未設定です (.env)")
    email_sel = "input#email"; pw_sel = "input#password"; btn_sel = ".o-login__button button, button[type='submit']"
    try:
        email_box = WebDriverWait(drv, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, email_sel)))
        drv.execute_script("""
            const el = arguments[0], val = arguments[1];
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, email_box, email)
        time.sleep(0.2)
        next_btn = None
        for sel in btn_sel.split(","):
            els = drv.find_elements(By.CSS_SELECTOR, sel.strip())
            if els: next_btn = els[0]; break
        if next_btn:
            drv.execute_script("arguments[0].click();", next_btn)
            time.sleep(0.6)
        pw_box = WebDriverWait(drv, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, pw_sel)))
        drv.execute_script("""
            const el = arguments[0], val = arguments[1];
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, pw_box, password)
        time.sleep(0.2)
        login_btn = None
        for sel in btn_sel.split(","):
            els = drv.find_elements(By.CSS_SELECTOR, sel.strip())
            if els: login_btn = els[0]; break
        if login_btn:
            WebDriverWait(drv, 10).until(lambda d: d.execute_script("return !arguments[0].disabled;", login_btn))
            drv.execute_script("arguments[0].click();", login_btn)
        else:
            pw_box.send_keys(Keys.ENTER)
        WebDriverWait(drv, 15).until(lambda d: "/login" not in d.current_url)
        drv.get("https://note.com/")
        doc_ready(drv, 15)
        close_popups(drv, 4)
        WebDriverWait(drv, 45).until(lambda d: is_logged_in(d))
        print("[info] 再ログイン成功")
        time.sleep(2)
    except TimeoutException as e:
        ts = time.strftime("%Y%m%d_%H%M%S")
        try:
            drv.save_screenshot(f"debug_relogin_failed_{ts}.png")
            with open(f"debug_relogin_failed_{ts}.html", "w", encoding="utf-8") as f:
                f.write(drv.page_source)
        except Exception:
            pass
        raise e


def return_to_home_safely(drv):
    print("[info] ホームに戻ります")
    drv.get("https://note.com/")
    doc_ready(drv, 15)
    close_popups(drv, 3)
    time.sleep(1.0)
    print("[info] ホーム画面に戻りました")


def open_new_post_via_header(drv, timeout_sec:int=20):
    print("[info] ヘッダーの投稿ボタンをクリックして新規作成ページへ遷移")
    header_ready = ["header.o-navBar", "div.m-navbarContainer", "div.a-split-button"]
    close_popups(drv, 3)
    for sel in header_ready:
        try:
            WebDriverWait(drv, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            break
        except Exception:
            continue
    candidates = [
        'a.a-split-button__left.svelte-4d611i[href="/notes/new"]',
        'a.a-split-button__left[href="/notes/new"]',
        'a[href="/notes/new"]',
        'a.a-split-button__left[href^="/notes/new"]',
    ]
    clicked = False
    last_err = None
    for sel in candidates:
        try:
            el = WebDriverWait(drv, 8).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            drv.execute_script("arguments[0].click();", el)
            clicked = True
            break
        except Exception as e:
            last_err = e
            continue
    if not clicked:
        raise RuntimeError(f"投稿ボタンのクリックに失敗しました: {last_err}")
    print("[info] 新しい投稿画面への遷移を待機...")
    try:
        WebDriverWait(drv, timeout_sec).until(
            lambda d: ("/notes/new" in d.current_url) or
            d.find_elements(By.CSS_SELECTOR, 'div.ProseMirror[contenteditable="true"]') or
            d.find_elements(By.CSS_SELECTOR, 'textarea[placeholder="記事タイトル"]')
        )
    except TimeoutException:
        pass
    doc_ready(drv, 10)
    close_popups(drv, 3)
    time.sleep(1.0)

# ========== アイキャッチ画像設定 ==========
def set_eyecatch_image(drv, image_path: str) -> bool:
    """アイキャッチ画像を設定（OSダイアログを開かせずに file input に直接セット）"""
    import os, time
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException

    def _click(by, sel, timeout=10):
        try:
            el = WebDriverWait(drv, timeout).until(EC.element_to_be_clickable((by, sel)))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            drv.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            return False

    try:
        abs_path = os.path.abspath(image_path)
        print(f"[info] アイキャッチ画像パス: {abs_path}")
        if not validate_image_path(abs_path):
            print("[warn] パスがファイルではありません（拡張子・存在を確認）")
            return False

        # 1) 「画像を追加」
        if not (_click(By.CSS_SELECTOR, 'button[aria-label="画像を追加"]') or
                _click(By.XPATH, '//button[@aria-label="画像を追加"]')):
            print("[warn] 画像追加ボタンが見つかりません")
            return False
        time.sleep(0.3)

        # 2) 「画像をアップロード」
        if not (_click(By.XPATH, '//button[.//div[normalize-space()="画像をアップロード"]]') or
                _click(By.CSS_SELECTOR, 'button.sc-920a17ca-7.cZcUfD')):
            print("[warn] 「画像をアップロード」ボタンが見つかりません")
            return False
        time.sleep(0.3)

        # ★ ここが肝：OSの“開く”ダイアログを無視して file input に直接セットする
        # 3-1) まず通常DOMで可視な file input を探す
        file_input = _find_visible_file_input(drv)
        if file_input:
            try:
                file_input.send_keys(abs_path)
                print("[info] 可視な file input に send_keys 済み")
            except Exception as e:
                print(f"[warn] send_keys 失敗（可視input）: {e}")
                file_input = None

        # 3-2) 見つからない/失敗したら CDP で強制セット（Shadow DOM対応）
        if not file_input:
            # よくあるセレクタの候補を順に試す
            candidates = [
                'input[type="file"][accept*="image"]',
                'input[type="file"]',
            ]
            ok = False
            for css in candidates:
                if _set_file_input_via_cdp(drv, css, abs_path):
                    ok = True
                    break
            if not ok:
                print("[warn] file input へのセットに失敗（CDPでも不可）")
                return False

        # 4) プレビュー出現待機（アップロード完了の目安）
        try:
            WebDriverWait(drv, 25).until(
                lambda d: (
                    len(d.find_elements(By.CSS_SELECTOR, 'img[src*="noteusercontent"]')) > 0
                    or len(d.find_elements(By.CSS_SELECTOR, 'img[src^="blob:"]')) > 0
                    or len(d.find_elements(By.CSS_SELECTOR, 'img[alt*="アイキャッチ"]')) > 0
                )
            )
            print("[info] アイキャッチ画像のアップロード完了")
            time.sleep(0.4)
        except TimeoutException:
            print("[warn] 画像プレビューの確認タイムアウト（反映遅延の可能性）")

        # 5) モーダルの「保存」ボタンがあれば押す（無ければスキップ）
        try:
            save_btn = WebDriverWait(drv, 2).until(
                EC.element_to_be_clickable((By.XPATH,
                    "//button[.//span[normalize-space()='保存'] or normalize-space(.)='保存']"))
            )
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", save_btn)
            drv.execute_script("arguments[0].click();", save_btn)
            print("[info] アイキャッチの保存ボタンをクリック")
            time.sleep(0.3)
        except Exception:
            pass

        return True

    except Exception as e:
        print(f"[error] set_eyecatch_image 例外: {e}")
        return False


# ========== 目次挿入 ==========

def insert_table_of_contents(drv) -> bool:
    """目次を挿入（公式UIのメニュー→目次）。見つからなければ False。"""
    try:
        print("[info] 目次の挿入を開始")

        menu_button_selectors = [
            'button#menu-button[aria-label="メニューを開く"]',
            'button#menu-button',
            '//button[@id="menu-button"]',
            # 追加の保険（ラベル系）
            '//button[contains(@aria-label,"メニュー")]',
        ]
        menu_btn = None
        for sel in menu_button_selectors:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                el = WebDriverWait(drv, 8).until(EC.element_to_be_clickable((by, sel)))
                menu_btn = el
                break
            except Exception:
                continue
        if not menu_btn:
            print("[warn] メニューボタンが見つかりません")
            return False

        drv.execute_script("arguments[0].scrollIntoView({block:'center'});", menu_btn)
        drv.execute_script("arguments[0].click();", menu_btn)
        time.sleep(0.4)

        toc_button_selectors = [
            'button#toc-setting',
            '//button[@id="toc-setting"]',
            # 文言で拾う保険
            '//button[.//div[normalize-space()="目次"] or normalize-space()="目次"]',
        ]
        toc_btn = None
        for sel in toc_button_selectors:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                el = WebDriverWait(drv, 8).until(EC.element_to_be_clickable((by, sel)))
                toc_btn = el
                break
            except Exception:
                continue
        if not toc_btn:
            print("[warn] 目次ボタンが見つかりません")
            return False

        drv.execute_script("arguments[0].scrollIntoView({block:'center'});", toc_btn)
        drv.execute_script("arguments[0].click();", toc_btn)
        time.sleep(0.6)
        print("[info] 目次の挿入完了")
        return True

    except Exception as e:
        print(f"[error] 目次挿入失敗: {e}")
        return False

def _set_file_input_via_cdp(drv, css_selector: str, file_path: str) -> bool:
    """
    CDPを使って css_selector で見つかる <input type=file> に file_path をセットする。
    Shadow DOM を横断 (pierce=True)。非表示でも可。
    """
    try:
        # 1) DOMツリーを取得（pierce=True で Shadow DOM も展開）
        doc = drv.execute_cdp_cmd("DOM.getDocument", {"depth": -1, "pierce": True})
        root_id = doc.get("root", {}).get("nodeId")
        if not root_id:
            print("[warn] CDP: root nodeId が取得できません")
            return False

        # 2) css_selector で該当ノードを探す
        q = drv.execute_cdp_cmd(
            "DOM.querySelector",
            {"nodeId": root_id, "selector": css_selector}
        )
        node_id = q.get("nodeId")
        if not node_id:
            print(f"[warn] CDP: selector 未検出 {css_selector}")
            return False

        # 3) ファイルパスをセット（可視性無関係）
        drv.execute_cdp_cmd(
            "DOM.setFileInputFiles",
            {"nodeId": node_id, "files": [file_path]}
        )
        print("[info] CDP: file input にファイルをセットしました")
        return True
    except Exception as e:
        print(f"[warn] _set_file_input_via_cdp 失敗: {e}")
        return False



def _find_visible_file_input(drv):
    """
    現在のドキュメントと全iframe内を検索し、可視な input[type=file] を返す。
    見つからなければ None。
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    def _visible(el):
        try:
            return el.is_displayed() and el.is_enabled()
        except Exception:
            return False

    # まずはトップドキュメント
    try:
        WebDriverWait(drv, 4).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'input[type="file"]'))
        )
        for el in drv.find_elements(By.CSS_SELECTOR, 'input[type="file"]'):
            if _visible(el):
                return el
    except Exception:
        pass

    # iframe 内も探索
    frames = drv.find_elements(By.CSS_SELECTOR, "iframe")
    for fr in frames:
        try:
            drv.switch_to.frame(fr)
            els = drv.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
            for el in els:
                if _visible(el):
                    return el
        except Exception:
            pass
        finally:
            drv.switch_to.default_content()

    return None

# ========== GDoc直接コピー ==========

def copy_from_gdoc_directly(drv, doc_url: str) -> bool:
    """GDocを新規タブで開いて Ctrl+A/C。Chrome プロファイルにGoogleログイン済み前提。"""
    try:
        current = drv.current_window_handle
        drv.execute_script("window.open(arguments[0], '_blank');", doc_url)
        WebDriverWait(drv, 10).until(lambda d: len(d.window_handles) > 1)
        drv.switch_to.window(drv.window_handles[-1])
        doc_ready(drv, 15)
        time.sleep(1.0)

        ActionChains(drv).key_up(Keys.CONTROL).key_up(Keys.SHIFT).key_up(Keys.ALT).perform()
        time.sleep(0.05)

        ActionChains(drv).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
        time.sleep(0.2)
        ActionChains(drv).key_down(Keys.CONTROL).send_keys('c').key_up(Keys.CONTROL).perform()
        time.sleep(0.4)

        print("[info] GDocからクリップボードにコピー完了")
    except Exception as e:
        print(f"[error] GDocコピー失敗: {e}")
        try:
            drv.switch_to.window(current)
        except Exception:
            pass
        return False
    finally:
        try:
            drv.close()
            drv.switch_to.window(current)
        except Exception:
            pass
    return True


def cleanup_pasted_content(drv, editor_el, title: str) -> bool:
    """ペースト直後にnoteエディタ内のDOMを修正"""
    try:
        cleanup_js = r"""
        const editor = arguments[0];
        const title = arguments[1];
        function normalize(s){
          return (s||'').normalize('NFKC')
            .replace(/\u3000/g,' ')
            .replace(/\s+/g,' ')
            .trim()
            .toLowerCase()
            .replace(/[\"'""''、。,.!！?？:：;\-‐−—･・\/｜|\[\]\(\)（）【】「」『』…⋯]+/g,'');
        }
        const normTitle = normalize(title);
        const blocks = Array.from(editor.children).slice(0,10);
        for(const el of blocks){
          if(['H1','H2','H3','P','DIV'].includes(el.tagName)){
            const text = el.textContent||'';
            const norm = normalize(text);
            if(norm===normTitle || norm.startsWith(normTitle)){
              el.remove();
              break;
            }
          }
        }
        const affiliatePat = /(アフィリエイト|プロモーション|広告|\bPR\b|スポンサー|紹介料)/;
        const remainBlocks = Array.from(editor.children).slice(0,5);
        for(const el of remainBlocks){
          const text = el.textContent||'';
          if(affiliatePat.test(text)){
            if(['H1','H2','H3','H4','H5','H6'].includes(el.tagName)){
              const p = document.createElement('p');
              p.innerHTML = el.innerHTML;
              el.replaceWith(p);
              el = p;
            }
            (el.querySelectorAll('strong, b')||[]).forEach(b=>{
              const span = document.createElement('span');
              span.innerHTML = b.innerHTML;
              b.replaceWith(span);
            });
            break;
          }
        }
        return {
          ok:true,
          blocks: editor.children.length,
          text: (editor.textContent||'').slice(0,100)
        };
        """
        result = drv.execute_script(cleanup_js, editor_el, title)
        print(f"[info] DOM修正完了: {result}")
        return True
    except Exception as e:
        print(f"[warn] DOM修正失敗: {e}")
        return False


def focus_editor_and_paste(drv, editor_el, title: str) -> bool:
    """noteエディタへフォーカスし、Ctrl+V後にDOM修正（最大3回リトライ）。"""
    for attempt in range(1, 4):
        try:
            ActionChains(drv).key_up(Keys.CONTROL).key_up(Keys.SHIFT).key_up(Keys.ALT).perform()
            time.sleep(0.05)

            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", editor_el)
            WebDriverWait(drv, 8).until(EC.element_to_be_clickable((By.XPATH, "(//*[@contenteditable='true'])[1]")))
            ActionChains(drv).move_to_element(editor_el).click().pause(0.05).click().perform()
            drv.execute_script("arguments[0].focus();", editor_el)

            drv.execute_script("document.execCommand('selectAll', false); document.execCommand('delete', false);")
            time.sleep(0.05)

            ActionChains(drv).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
            time.sleep(0.8)

            text_len = drv.execute_script("return (arguments[0].innerText||'').length;", editor_el)
            node_count = drv.execute_script("return arguments[0].childNodes.length;", editor_el)
            if text_len >= 20 and node_count >= 1:
                print(f"[ok] ペースト成功 (len={text_len}, nodes={node_count}, try={attempt})")
                cleanup_pasted_content(drv, editor_el, title)
                return True
            else:
                print(f"[warn] ペースト薄い (len={text_len}, nodes={node_count}, try={attempt}) → 再試行")
        except Exception as e:
            print(f"[warn] ペースト試行失敗 try={attempt}: {e}")
        time.sleep(0.4)
    return False

# ========== タイトル・本文入力 ==========

def _fill_title(drv, title: str):
    title_priority = [
        'textarea[placeholder="記事タイトル"][spellcheck="true"]',
        'textarea.sc-80832eb4-0.heevId',
    ]
    title_fallbacks = [
        'textarea[placeholder="記事タイトル"]',
        'textarea[spellcheck="true"]',
        'textarea.sc-80832eb4-0',
        '//textarea[@placeholder="記事タイトル"]',
    ]
    el = None
    for sel in title_priority:
        els = drv.find_elements(By.CSS_SELECTOR, sel)
        if els:
            el = els[0]; break
    if el is None:
        for sel in title_fallbacks:
            if sel.startswith("//"):
                try:
                    el = drv.find_element(By.XPATH, sel); break
                except Exception:
                    continue
            else:
                els = drv.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    el = els[0]; break
    if el is None:
        raise RuntimeError("タイトル入力欄が見つかりませんでした")
    drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    WebDriverWait(drv,10).until(EC.element_to_be_clickable((By.XPATH, "//textarea")))
    drv.execute_script("arguments[0].focus();", el)
    time.sleep(0.2)
    try:
        drv.execute_script("arguments[0].value='';", el)
    except Exception:
        pass
    drv.execute_script("""
        const el = arguments[0];
        const val = arguments[1];
        const desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
        if (desc && desc.set) { desc.set.call(el, val); } else { el.value = val; }
        el.dispatchEvent(new Event('input',  {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        el.dispatchEvent(new Event('blur',   {bubbles:true}));
    """, el, title)
    time.sleep(0.2)
    ok = drv.execute_script("return !!arguments[0].value && arguments[0].value.length>0;", el)
    if ok:
        print("[info] タイトル入力 OK")
    else:
        raise RuntimeError("タイトル入力に失敗しました")


def _kbd_save(drv):
    try:
        body = drv.find_element(By.TAG_NAME, 'body')
        body.send_keys(Keys.CONTROL, 's')
    except Exception:
        pass


def wait_saved_or_url(drv, timeout_sec:int=30) -> str:
    start = time.time()
    _kbd_save(drv)
    time.sleep(0.8)
    while time.time() - start < timeout_sec:
        url = drv.current_url
        if "/n/" in url:
            return url
        time.sleep(0.4)
    return drv.current_url

def move_caret_to_editor_start(drv, editor_el):
    js = r"""
    const el = arguments[0];
    el.focus();
    const range = document.createRange();
    range.setStart(el, 0);
    range.collapse(true);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    """
    drv.execute_script(js, editor_el)


def fill_editor_on_current_page(drv, title:str, html_body:str, gdoc_url: Optional[str]=None, 
                                eyecatch_path: Optional[str]=None)->str:
    """記事作成のメインフロー：タイトル→アイキャッチ→本文→目次"""
    
    # 1. タイトル入力
    _fill_title(drv, title)
    
    # 2. アイキャッチ画像設定（パスが指定されている場合）
    if eyecatch_path:
        if validate_image_path(eyecatch_path):
            set_eyecatch_image(drv, eyecatch_path)
            time.sleep(0.5)
        else:
            print(f"[warn] アイキャッチ画像パスが無効です: {eyecatch_path}")
    
    # 3. 本文エディタの取得
    editor_selectors = [
        'div.ProseMirror.note-common-styles__textnote-body[contenteditable="true"]',
        'div.ProseMirror[contenteditable="true"]',
        'div[role="textbox"][contenteditable="true"]',
        '.ProseMirror'
    ]
    editor=None
    for sel in editor_selectors:
        els=drv.find_elements(By.CSS_SELECTOR, sel)
        if els:
            editor=els[0]; break
    if not editor:
        raise RuntimeError("本文エディタが見つかりませんでした")

    # 4. GDocから実クリップボードへコピー
    if not gdoc_url or not copy_from_gdoc_directly(drv, gdoc_url):
        raise RuntimeError("GDocコピーに失敗しました（Googleログイン/権限を確認）")

    # 5. エディタへペースト＋DOM修正
    ok = focus_editor_and_paste(drv, editor, title)
    if not ok:
        raise RuntimeError("ペーストに失敗しました（3回試行も不成立）")
    
    # ★ 先頭へキャレット移動 → 目次挿入（まず目次を入れる）
    move_caret_to_editor_start(drv, editor)
    insert_table_of_contents(drv)
    time.sleep(0.5)
    

    # 7. 自動保存/URL安定を少し待機
    url_after = wait_saved_or_url(drv, timeout_sec=30)
    print(f"[info] 下書きURL候補: {url_after}")
    return url_after

# ========== 公開処理 ==========

PUBLISH_STEP1_XPATHS = [
    "//button[.//span[contains(normalize-space(.), '公開に進む')]]",
    "//span[contains(normalize-space(.), '公開に進む')]/ancestor::button[1]",
]

PUBLISH_STEP2_XPATHS = [
    "//button[.//span[contains(normalize-space(.), '投稿する')]]",
    "//span[contains(normalize-space(.), '投稿する')]/ancestor::button[1]",
]


def click_publish_step1(drv, timeout_sec:int=20):
    print("[info] 公開フロー: Step1『公開に進む』をクリック")
    last_err=None
    for xp in PUBLISH_STEP1_XPATHS:
        try:
            el = WebDriverWait(drv, timeout_sec).until(EC.element_to_be_clickable((By.XPATH, xp)))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            drv.execute_script("arguments[0].click();", el)
            time.sleep(0.8)
            return
        except Exception as e:
            last_err=e
            continue
    raise RuntimeError(f"『公開に進む』ボタンが見つからない/クリック不可: {last_err}")


def click_publish_step2(drv, timeout_sec:int=25):
    print("[info] 公開フロー: Step2『投稿する』をクリック")
    time.sleep(1.0)
    last_err=None
    for xp in PUBLISH_STEP2_XPATHS:
        try:
            el = WebDriverWait(drv, timeout_sec).until(EC.element_to_be_clickable((By.XPATH, xp)))
            drv.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            drv.execute_script("arguments[0].click();", el)
            return
        except Exception as e:
            last_err=e
            continue
    raise RuntimeError(f"『投稿する』ボタンが見つからない/クリック不可: {last_err}")


def wait_public_url(drv, timeout_sec:int=45) -> str:
    """公開後の確定URLを取得（/n/を含み/editを含まない）"""
    print("[info] 公開後URLを待機 (/n/ を含む公開URL)")
    end=time.time()+timeout_sec
    last_url=drv.current_url
    while time.time()<end:
        url=drv.current_url
        if "/n/" in url and "/edit" not in url:
            print(f"[info] 公開URL確定: {url}")
            return url
        try:
            canon = drv.find_elements(By.CSS_SELECTOR, 'link[rel="canonical"]')
            if canon:
                href = canon[0].get_attribute('href')
                if href and "/n/" in href:
                    print(f"[info] 公開URL確定(canonical): {href}")
                    return href
        except Exception:
            pass
        if url!=last_url:
            last_url=url
        time.sleep(0.6)
    return drv.current_url

# ========== メイン処理 ==========

def process_rows(dry_run:bool=False, sleep_sec:float=3.0):
    gs=None
    rows=[]
    try:
        gs=gs_service()
        rows=read_rows(gs)
    except Exception as e:
        if dry_run:
            print(f"[warn] Sheets 取得失敗（DRY-RUN継続）: {e}")
        else:
            raise

    targets=[r for r in rows if (r.status=="" or r.status.upper()=="READY")]
    if ROW_LIMIT>0:
        targets=targets[:ROW_LIMIT]
    if not targets and not dry_run:
        print("[info] 対象行なし")
        return

    drv=build_driver(HEADLESS, CHROME_USER_DATA_DIR, CHROME_PROFILE_DIR)
    
    try:
        ensure_logged_in(drv, NOTE_EMAIL, NOTE_PASSWORD)
        time.sleep(0.8)
        
        for idx, it in enumerate(targets):
            print("\n"+"="*64)
            print(f"[row {it.row_index}] ({idx+1}/{len(targets)}) {it.title}")
            print("="*64)
            
            if idx>0:
                return_to_home_safely(drv)
                check_and_relogin_if_needed(drv, NOTE_EMAIL, NOTE_PASSWORD)
            
            try:
                open_new_post_via_header(drv)
            except Exception as e:
                print(f"[error] 新規作成ページ遷移に失敗: {e}")
                if gs: write_back(gs, it.row_index, "ERROR_OPEN_NEW", str(e)[:500])
                time.sleep(sleep_sec)
                continue

            # GDoc取得
            try:
                html, removed = gdoc_html_without_title(it.doc_url, it.title)
                print(f"[debug] GDoc HTML length: {len(html)} (removed_title={removed})")
            except Exception as e:
                print(f"[error] GDoc取得失敗 row={it.row_index}: {e}")
                if gs: write_back(gs, it.row_index, "ERROR_GDOC", str(e)[:500])
                time.sleep(sleep_sec)
                continue

            # アイキャッチ画像パスの確認
            eyecatch_file = None
            if it.eyecatch_path:
                print(f"[info] アイキャッチ画像パス: {it.eyecatch_path}")
                if validate_image_path(it.eyecatch_path):
                    eyecatch_file = it.eyecatch_path
                else:
                    print("[warn] アイキャッチ画像パスが無効（処理は続行）")

            # タイトル＆本文＆アイキャッチ＆目次の投入
            try:
                draft_like_url = fill_editor_on_current_page(
                    drv, it.title, html, 
                    gdoc_url=it.doc_url,
                    eyecatch_path=eyecatch_file
                )
            except Exception as e:
                print(f"[error] 記事作成失敗 row={it.row_index}: {e}")
                ts=int(time.time())
                try: drv.save_screenshot(f"debug_create_{ts}.png")
                except Exception: pass
                try:
                    with open(f"debug_create_{ts}.html","w",encoding="utf-8") as f:
                        f.write(drv.page_source)
                except Exception:
                    pass
                if gs: write_back(gs, it.row_index, "ERROR_CREATE", str(e)[:500])
                time.sleep(sleep_sec)
                continue

            if dry_run:
                pub_url = draft_like_url
                if gs: write_back(gs, it.row_index, "DRY_RUN", pub_url)
                print(f"[ok] DRY-RUN: {pub_url}")
                time.sleep(sleep_sec)
                continue

            # 公開ボタン（2段階）
            try:
                click_publish_step1(drv)
                click_publish_step2(drv)
            except Exception as e:
                print(f"[error] 公開ボタンクリックに失敗 row={it.row_index}: {e}")
                if gs: write_back(gs, it.row_index, "ERROR_PUBLISH_CLICK", str(e)[:500])
                time.sleep(sleep_sec)
                continue

            # 公開後の確定URL待機
            try:
                pub_url = wait_public_url(drv, timeout_sec=60)
                print(f"[ok] 公開URL: {pub_url}")
            except Exception as e:
                print(f"[warn] 公開URL待機で例外: {e}")
                pub_url = drv.current_url

            # シート更新（POSTED）
            try:
                if gs: write_back(gs, it.row_index, "POSTED", pub_url)
                print(f"[info] シート更新完了 row={it.row_index} -> POSTED")
            except Exception as e:
                print(f"[warn] シート更新失敗: {e}")

            return_to_home_safely(drv)
            time.sleep(sleep_sec)
            
    finally:
        print("\n[info] ブラウザ終了")
        try: drv.quit()
        except Exception: pass

# ========== CLI ==========

def main():
    ap=argparse.ArgumentParser(description="Sheets→GDoc→note 公開（目次・アイキャッチ対応）")
    ap.add_argument("--dry-run", action="store_true", help="公開せずに動作確認")
    ap.add_argument("--sleep", type=float, default=3.0, help="投稿間スリープ秒")
    args=ap.parse_args()
    process_rows(dry_run=args.dry_run, sleep_sec=args.sleep)

if __name__=="__main__":
    main()