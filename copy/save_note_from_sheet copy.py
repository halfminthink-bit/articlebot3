# post_note_from_sheet.py（強制ログアウト固定＋UI検知ログイン必須／ヘッダ投稿ボタンで新規作成）
# Sheets「タイトル / GDoc URL」→ note新規テキスト記事をブラウザ操作で作成。
# 変更点：
# - 毎回「/logout」から開始し、UI要素（アバター等）でログイン完了を必須化
# - 投稿画面遷移は、指定の <a class="a-split-button__left svelte-4d611i" href="/notes/new"> を最優先でクリック
# - その後にGDoc取得＆本文貼り付け（ClipboardEvent→insertHTMLフォールバック）
# - 【今回の差分】保存後の次記事処理を安定化：
#     - return_to_home_safely() で確実にホームへ戻りポップアップ処理
#     - check_and_relogin_if_needed() でセッション切れを自動復旧
#     - メインループを enumerate 化し、2件目以降は必ずホーム戻り＋再ログイン確認→投稿画面遷移

import os
import re
import time
import argparse
import unicodedata
from dataclasses import dataclass
from typing import Optional, List, Tuple

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

# ========== ENV ==========
load_dotenv()
SHEET_ID      = os.getenv("SHEET_ID")
SHEET_NAME    = os.getenv("SHEET_NAME", "Articles")
NOTE_EMAIL    = os.getenv("NOTE_EMAIL", "").strip()
NOTE_PASSWORD = os.getenv("NOTE_PASSWORD", "").strip()
NOTE_USERNAME = os.getenv("NOTE_USERNAME", "").strip()
HEADLESS      = os.getenv("HEADLESS", "1").strip() in ("1","true","TRUE","True")
ROW_LIMIT     = int(os.getenv("ROW_LIMIT", "0"))

# 例：
# CHROME_USER_DATA_DIR=C:\\Users\\<you>\\AppData\\Local\\Google\\Chrome\\User Data
# CHROME_PROFILE_DIR=Profile 3
CHROME_USER_DATA_DIR = os.getenv("CHROME_USER_DATA_DIR", "").strip()
CHROME_PROFILE_DIR   = os.getenv("CHROME_PROFILE_DIR", "").strip()

# スプシ列: A..F  (persona, title, doc_url, status, note_url, eyecatch)
COL_PERSONA=0; COL_TITLE=1; COL_DOC=2; COL_STATUS=3; COL_NOTEURL=4; COL_EYE=5
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
        persona,title,doc,status,nurl,eye = row[:6]
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
        range=f"{SHEET_NAME}!D{row_index}:E{row_index}",
        valueInputOption="RAW",
        body={"values":[[status, note_url]]}
    ).execute()

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

def cleanup_exported_html(raw_html:str)->str:
    soup=BeautifulSoup(raw_html,"html.parser")
    body=soup.find("body")
    html = body.decode_contents() if body else raw_html
    # 余計な inline style を軽く除去（最低限）
    html = re.sub(r'style=\"[^\"]*\"', "", html)
    return html

# ===== タイトル除去ロジック =====

def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = re.sub(r"[“”\"'’‘、。,.!！?？:：;\-‐−—･・/｜|\\\\\\[\\\\]\\(\\)（）【】「」『』…⋯]+", "", s)
    return s

def remove_leading_title_from_html(html: str, title: str) -> Tuple[str, bool]:
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
                if len(candidates) >= 2:
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

        if removed:
            cleaned = str(soup)
            if "<body" in cleaned:
                soup2 = BeautifulSoup(cleaned, "html.parser")
                b2 = soup2.find("body")
                return (b2.decode_contents() if b2 else cleaned), True
            else:
                return cleaned, True
        else:
            return html, False
    except Exception:
        return html, False


def gdoc_html_without_title(url: str, title: str) -> Tuple[str, bool]:
    raw = gdoc_raw_html(url)
    html = cleanup_exported_html(raw)
    cleaned, removed = remove_leading_title_from_html(html, title)
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
    """
    アバター/ユーザーメニュー or 投稿ボタンの可視で判定
    """
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


# ========== 強制ログアウト固定 → UI検知ログイン必須 ==========

def ensure_logged_in(drv,email:str,password:str):
    # 1) まず必ずログアウト
    try:
        drv.get("https://note.com/logout")
        doc_ready(drv,10)
        time.sleep(0.6)
    except Exception:
        pass

    # 2) トップへ → ログイン導線へ
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

        # 「次へ」系があればクリック
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

        # ログイン直後の安定化
        time.sleep(2)
        doc_ready(drv, 10)
        close_popups(drv, 4)
        try:
            WebDriverWait(drv, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.a-split-button"))
            )
            print("[debug] ヘッダーUIの表示を確認")
        except Exception:
            print("[warn] ヘッダーUIが見つからない（続行）")

    except TimeoutException as e:
        ts=time.strftime("%Y%m%d_%H%M%S")
        try:
            drv.save_screenshot(f"debug_login_failed_{ts}.png")
            with open(f"debug_login_failed_{ts}.html","w",encoding="utf-8") as f:
                f.write(drv.page_source)
        except Exception:
            pass
        raise e


# ========== 追加: ログイン状態確認＆必要時再ログイン関数 ==========

def check_and_relogin_if_needed(drv, email: str, password: str):
    """
    現在のページでログイン状態を確認し、未ログインなら再ログインする。
    ホームに戻った後など、セッション切れを検知して復旧するために使用。
    """
    if is_logged_in(drv):
        print("[info] ログイン状態を確認: OK")
        return

    print("[warn] ログアウトを検知、再ログイン実施")
    # 既にログアウトしているので /logout は不要、直接ログイン導線へ
    click_nav_login(drv)
    doc_ready(drv, 20)
    close_popups(drv, 4)

    if is_logged_in(drv):
        print("[info] 既にログイン済み（再確認）")
        return

    if not email or not password:
        raise ValueError("NOTE_EMAIL / NOTE_PASSWORD が未設定です (.env)")

    email_sel = "input#email"
    pw_sel    = "input#password"
    btn_sel   = ".o-login__button button, button[type='submit']"

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


# ========== 追加: 安全にホームへ戻る ==========

def return_to_home_safely(drv):
    """
    ホームに安全に戻る。ポップアップを閉じて画面を安定化。
    """
    print("[info] ホームに戻ります")
    drv.get("https://note.com/")
    doc_ready(drv, 15)
    close_popups(drv, 3)
    time.sleep(1.0)
    print("[info] ホーム画面に戻りました")


# ========== 本文貼り付け（軽めフォールバック） ==========

PASTE_JS = r"""
const editor = arguments[0];
const html   = arguments[1];
function pasteHTML(target, html) {
  const dt = new DataTransfer();
  dt.setData('text/html', html);
  const e = new ClipboardEvent('paste', {bubbles:true, cancelable:true});
  Object.defineProperty(e, 'clipboardData', { value: dt });
  target.dispatchEvent(e);
}
editor.focus();
(function(){
  const isMac = navigator.platform.toUpperCase().indexOf('MAC')>=0;
  const evtDown = (code, key, ctrlKey, metaKey) => new KeyboardEvent('keydown', {bubbles:true, cancelable:true, key, code, ctrlKey, metaKey});
  const evtUp   = (code, key, ctrlKey, metaKey) => new KeyboardEvent('keyup',   {bubbles:true, cancelable:true, key, code, ctrlKey, metaKey});
  const ctrl = isMac ? {ctrlKey:false, metaKey:true} : {ctrlKey:true, metaKey:false};
  editor.dispatchEvent(evtDown('KeyA','a', ctrl.ctrlKey, ctrl.metaKey));
  editor.dispatchEvent(evtUp('KeyA','a', ctrl.ctrlKey, ctrl.metaKey));
  editor.dispatchEvent(new KeyboardEvent('keydown', {key:'Delete', code:'Delete', bubbles:true, cancelable:true}));
  editor.dispatchEvent(new KeyboardEvent('keyup',   {key:'Delete', code:'Delete', bubbles:true, cancelable:true}));
})();
pasteHTML(editor, html);
return {
  textLen: (editor.textContent||'').length,
  h2: editor.querySelectorAll('h2').length,
  h3: editor.querySelectorAll('h3').length,
  p: editor.querySelectorAll('p').length
};
"""

PASTE_FALLBACK_HTML_JS = r"""
const editor = arguments[0];
const html   = arguments[1];
editor.focus();
document.execCommand('insertHTML', false, html);
return {
  textLen: (editor.textContent||'').length,
  h2: editor.querySelectorAll('h2').length,
  h3: editor.querySelectorAll('h3').length,
  p: editor.querySelectorAll('p').length
};
"""

# ========== タイトル入力 ==========

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
        body = drv.find_element(By.TAG_NAME, 'body')
        if os.name == 'posix' and 'darwin' in os.sys.platform:
            body.send_keys(Keys.COMMAND, 'a')
        else:
            body.send_keys(Keys.CONTROL, 'a')
        body.send_keys(Keys.DELETE)
        time.sleep(0.1)
    except Exception:
        pass

    drv.execute_script("""
        const el = arguments[0];
        const val = arguments[1];
        el.focus();
        const desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
        if (desc && desc.set) { desc.set.call(el, val); } else { el.value = val; }
        el.dispatchEvent(new Event('input',  {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        el.dispatchEvent(new Event('blur',   {bubbles:true}));
    """, el, title)
    time.sleep(0.2)

    ok = drv.execute_script("return !!arguments[0].value && arguments[0].value.length>0;", el)
    if not ok:
        try: el.clear()
        except Exception: pass
        el.send_keys(title)
        time.sleep(0.2)
        ok = drv.execute_script("return !!arguments[0].value && arguments[0].value.length>0;", el)

    if ok:
        print("[info] タイトル入力 OK")
    else:
        raise RuntimeError("タイトル入力に失敗しました")


# ========== 保存待機（軽め） ==========

def _kbd_save(drv):
    try:
        body = drv.find_element(By.TAG_NAME, 'body')
        if os.name == 'posix' and 'darwin' in os.sys.platform:
            body.send_keys(Keys.COMMAND, 's')
        else:
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
        # 軽く再保存
        if int(time.time() - start) % 5 == 0:
            _kbd_save(drv)
        time.sleep(0.4)
    return drv.current_url


# ========== 新規作成ページを「ボタンで」開く ==========

def open_new_post_via_header(drv, timeout_sec:int=20):
    """
    ヘッダーの「投稿」ボタン（左側）をクリックして /notes/new に遷移する。
    指定のHTMLを最優先セレクタに採用：
      <a class=\"a-split-button__left svelte-4d611i\" href=\"/notes/new\"> ... </a>
    UI揺れ対策として複数セレクタでフォールバック。
    """
    print("[info] ヘッダーの投稿ボタンをクリックして新規作成ページへ遷移")

    # まずヘッダー領域が出ていることを軽く確認
    header_ready = [
        "header.o-navBar",
        "div.m-navbarContainer",
        "div.a-split-button",
    ]
    close_popups(drv, 3)
    for sel in header_ready:
        try:
            WebDriverWait(drv, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
            break
        except Exception:
            continue

    # 指定のアンカーを最優先
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


# ========== 画面にタイトル/本文を流し込み ==========

def fill_editor_on_current_page(drv, title:str, html_body:str)->str:
    # タイトル
    _fill_title(drv, title)

    # 本文エディタ
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

    drv.execute_script("arguments[0].scrollIntoView({block:'center'});", editor)
    WebDriverWait(drv, 12).until(EC.element_to_be_clickable((By.CSS_SELECTOR, editor_selectors[0] if drv.find_elements(By.CSS_SELECTOR, editor_selectors[0]) else editor_selectors[1])))
    drv.execute_script("arguments[0].click();", editor)
    time.sleep(0.4)

    # 1) HTML paste（ClipboardEvent）
    print("[info] 本文（HTML）を貼り付け中... (method=ClipboardEvent)")
    result = drv.execute_script(PASTE_JS, editor, html_body)
    h_cnt = (result.get('h2',0)+result.get('h3',0))
    print(f"[debug] paste result: text={result.get('textLen')} h2={result.get('h2')} h3={result.get('h3')} p={result.get('p')}")
    time.sleep(0.6)

    # 2) 控えめ fallback: insertHTML のみ
    if h_cnt == 0 or result.get('textLen',0) < 50:
        print("[warn] fallback(insertHTML) を実施")
        result2 = drv.execute_script(PASTE_FALLBACK_HTML_JS, editor, html_body)
        print(f"[debug] fallback result: text={result2.get('textLen')} h2={result2.get('h2')} h3={result2.get('h3')} p={result2.get('p')}")
        time.sleep(0.5)

    # 保存 or /n/ 遷移待ち
    url_after = wait_saved_or_url(drv, timeout_sec=30)
    print(f"[info] 下書きURL: {url_after}")
    return url_after


# ========== Main flow ==========

def process_rows(dry_run:bool=False, sleep_sec:float=3.0):
    gs=None
    rows=[]
    if dry_run:
        print("[info] DRY-RUN: Sheets読取はスキップ可能ですが、認可確認のため実行します")
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
        # ★ 初回ログイン（強制ログアウト→ログイン）
        ensure_logged_in(drv, NOTE_EMAIL, NOTE_PASSWORD)
        time.sleep(0.8)

        if dry_run:
            for it in targets:
                if gs:
                    dummy=f"https://note.com/{NOTE_USERNAME or 'user'}/n/dummy"
                    write_back(gs, it.row_index, "DRY_RUN", dummy)
            print("[ok] DRY-RUN 完了")
            return

        for idx, it in enumerate(targets):
            print("\n"+"="*64)
            print(f"[row {it.row_index}] ({idx+1}/{len(targets)}) {it.title}")
            print("="*64)

            # ★ 2件目以降: ホームに戻ってログイン状態確認
            if idx > 0:
                try:
                    return_to_home_safely(drv)
                    check_and_relogin_if_needed(drv, NOTE_EMAIL, NOTE_PASSWORD)
                except Exception as e:
                    print(f"[error] ホーム復帰/ログイン確認失敗: {e}")
                    if gs: write_back(gs, it.row_index, "ERROR_HOME_RETURN", str(e)[:500])
                    time.sleep(sleep_sec)
                    continue

            # ★ 投稿画面遷移前に再度ログイン確認（念のため）
            try:
                if not is_logged_in(drv):
                    print("[warn] 投稿前にログアウト検知、再ログイン")
                    check_and_relogin_if_needed(drv, NOTE_EMAIL, NOTE_PASSWORD)
            except Exception as e:
                print(f"[error] ログイン確認失敗: {e}")
                if gs: write_back(gs, it.row_index, "ERROR_LOGIN_CHECK", str(e)[:500])
                time.sleep(sleep_sec)
                continue

            # 先にヘッダーの投稿ボタンで新規ページへ
            try:
                open_new_post_via_header(drv)
            except Exception as e:
                print(f"[error] 新規作成ページ遷移に失敗: {e}")
                if gs: write_back(gs, it.row_index, "ERROR_OPEN_NEW", str(e)[:500])
                time.sleep(sleep_sec)
                continue

            # その後に GDoc 取得 & タイトル除去
            try:
                html, removed = gdoc_html_without_title(it.doc_url, it.title)
                print(f"[debug] GDoc HTML length: {len(html)} (removed_title={removed})")
            except Exception as e:
                print(f"[error] GDoc取得失敗 row={it.row_index}: {e}")
                if gs: write_back(gs, it.row_index, "ERROR_GDOC", str(e)[:500])
                time.sleep(sleep_sec)
                continue

            # タイトル＆本文投入（現在開いている新規ページに対して）
            try:
                note_url = fill_editor_on_current_page(drv, it.title, html)
                print(f"[ok] 下書き作成: {note_url}")
            except Exception as e:
                print(f"[error] 記事作成失敗 row={it.row_index}: {e}")
                ts=int(time.time())
                try: 
                    drv.save_screenshot(f"debug_create_{ts}.png")
                except Exception: 
                    pass
                try:
                    with open(f"debug_create_{ts}.html","w",encoding="utf-8") as f:
                        f.write(drv.page_source)
                except Exception:
                    pass
                if gs: write_back(gs, it.row_index, "ERROR_CREATE", str(e)[:500])
                time.sleep(sleep_sec)
                continue

            # シート更新
            try:
                if gs: write_back(gs, it.row_index, "DRAFTED", note_url)
                print(f"[info] シート更新完了 row={it.row_index}")
            except Exception as e:
                print(f"[warn] シート更新失敗: {e}")

            time.sleep(sleep_sec)

    finally:
        print("\n[info] ブラウザ終了")
        try: 
            drv.quit()
        except Exception: 
            pass


# ========== CLI ==========

def main():
    ap=argparse.ArgumentParser(description="Sheets→GDoc→note 下書き（強制ログアウト固定／UI検知ログイン→ヘッダ投稿ボタン→GDoc→貼り付け）")
    ap.add_argument("--dry-run", action="store_true", help="投稿せずシートだけ更新（疎通確認向け）")
    ap.add_argument("--sleep", type=float, default=3.0, help="投稿間スリープ秒")
    args=ap.parse_args()
    process_rows(dry_run=args.dry_run, sleep_sec=args.sleep)

if __name__=="__main__":
    main()
