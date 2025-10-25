"""note_automation.py"""

import os
import time
from typing import Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


class NoteAutomation:
    """note自動化クラス"""
    
    def __init__(self, driver: webdriver.Chrome, selectors, utils):
        self.driver = driver
        self.sel = selectors
        self.utils = utils
    
    def is_logged_in(self) -> bool:
        """ログイン状態確認"""
        try:
            for s in self.sel.AVATAR_SELECTORS:
                for el in self.driver.find_elements(By.CSS_SELECTOR, s):
                    if el.is_displayed():
                        return True
            
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'a[href="/notes/new"]'):
                if el.is_displayed():
                    return True
            
            if self.driver.find_elements(By.CSS_SELECTOR, 'a[href^="/login"]'):
                return False
            
            return False
        except Exception:
            return False
    
    def close_popups(self, timeout_sec=4):
        """ポップアップを閉じる"""
        end = time.time() + max(1, timeout_sec)
        while time.time() < end:
            for s in self.sel.POPUP_CLOSE:
                try:
                    by = By.XPATH if s.startswith("//") else By.CSS_SELECTOR
                    for el in self.driver.find_elements(by, s):
                        if el.is_displayed() and el.is_enabled():
                            self.driver.execute_script("arguments[0].click();", el)
                            time.sleep(0.2)
                            return
                except Exception:
                    pass
            time.sleep(0.15)
    
    def login(self, email: str, password: str):
        """ログイン処理"""
        try:
            self.driver.get("https://note.com/logout")
            self.utils.wait_doc_ready(self.driver, 10)
            time.sleep(0.6)
        except Exception:
            pass
        
        self.driver.get("https://note.com/")
        self.utils.wait_doc_ready(self.driver, 15)
        self.close_popups(4)
        
        # ログインボタンをクリック
        for sel in self.sel.LOGIN_LINKS:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                el = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((by, sel))
                )
                self.utils.safe_click(self.driver, el)
                break
            except Exception:
                continue
        
        try:
            WebDriverWait(self.driver, 12).until(EC.url_contains("/login"))
        except TimeoutException:
            self.driver.get("https://note.com/login")
        
        self.utils.wait_doc_ready(self.driver, 20)
        self.close_popups(4)
        
        if self.is_logged_in():
            print("[info] 既にログイン済み")
            return
        
        if not email or not password:
            raise ValueError("NOTE_EMAIL / NOTE_PASSWORD が未設定です")
        
        # メール入力
        email_box = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, self.sel.EMAIL_INPUT))
        )
        self.driver.execute_script("""
            const el = arguments[0], val = arguments[1];
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, email_box, email)
        time.sleep(0.2)
        
        # 次へボタン
        for sel in self.sel.LOGIN_BUTTONS.split(","):
            els = self.driver.find_elements(By.CSS_SELECTOR, sel.strip())
            if els:
                self.driver.execute_script("arguments[0].click();", els[0])
                break
        time.sleep(0.6)
        
        # パスワード入力
        pw_box = WebDriverWait(self.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, self.sel.PASSWORD_INPUT))
        )
        self.driver.execute_script("""
            const el = arguments[0], val = arguments[1];
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            setter.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, pw_box, password)
        time.sleep(0.2)
        
        # ログインボタン
        login_btn = None
        for sel in self.sel.LOGIN_BUTTONS.split(","):
            els = self.driver.find_elements(By.CSS_SELECTOR, sel.strip())
            if els:
                login_btn = els[0]
                break
        
        if login_btn:
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script("return !arguments[0].disabled;", login_btn)
            )
            self.driver.execute_script("arguments[0].click();", login_btn)
        else:
            pw_box.send_keys(Keys.ENTER)
        
        WebDriverWait(self.driver, 45).until(lambda d: self.is_logged_in())
        print("[info] ログイン成功")
        time.sleep(2)
        self.utils.wait_doc_ready(self.driver, 10)
        self.close_popups(4)
    
    def open_new_post(self, timeout_sec=20):
        """新規投稿ページを開く"""
        print("[info] 新規作成ページへ遷移")
        self.close_popups(3)
        
        clicked = False
        for sel in self.sel.NEW_POST_BUTTONS:
            try:
                el = WebDriverWait(self.driver, 8).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                self.utils.safe_click(self.driver, el)
                clicked = True
                break
            except Exception:
                continue
        
        if not clicked:
            raise RuntimeError("投稿ボタンのクリックに失敗")
        
        try:
            WebDriverWait(self.driver, timeout_sec).until(
                lambda d: ("/notes/new" in d.current_url) or
                d.find_elements(By.CSS_SELECTOR, 'div.ProseMirror[contenteditable="true"]')
            )
        except TimeoutException:
            pass
        
        self.utils.wait_doc_ready(self.driver, 10)
        self.close_popups(3)
        time.sleep(1.0)
    
    def fill_title(self, title: str):
        """タイトル入力"""
        el = None
        for sel in self.sel.TITLE_INPUT_PRIORITY:
            els = self.driver.find_elements(By.CSS_SELECTOR, sel)
            if els:
                el = els[0]
                break
        
        if el is None:
            for sel in self.sel.TITLE_INPUT_FALLBACKS:
                if sel.startswith("//"):
                    try:
                        el = self.driver.find_element(By.XPATH, sel)
                        break
                    except Exception:
                        continue
                else:
                    els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        el = els[0]
                        break
        
        if el is None:
            raise RuntimeError("タイトル入力欄が見つかりませんでした")
        
        self.utils.safe_click(self.driver, el)
        time.sleep(0.2)
        
        self.driver.execute_script("""
            const el = arguments[0], val = arguments[1];
            const desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
            if (desc && desc.set) { desc.set.call(el, val); } else { el.value = val; }
            el.dispatchEvent(new Event('input',  {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            el.dispatchEvent(new Event('blur',   {bubbles:true}));
        """, el, title)
        time.sleep(0.2)
        print("[info] タイトル入力 OK")
    
    # note_automation.py の set_eyecatch メソッドを以下に置き換え

    def set_eyecatch(self, image_path: str) -> bool:
        """アイキャッチ画像設定（元のコードと同じロジック）"""
        try:
            abs_path = os.path.abspath(image_path)
            print(f"[info] アイキャッチ画像パス: {abs_path}")
            
            # パス検証
            if not os.path.exists(abs_path):
                print(f"[warn] ファイルが存在しません: {abs_path}")
                return False
            if not os.path.isfile(abs_path):
                print(f"[warn] パスがファイルではありません: {abs_path}")
                return False
            
            ext = os.path.splitext(abs_path)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                print(f"[warn] サポートされていない画像形式: {ext}")
                return False
            
            # 1) 「画像を追加」ボタン
            if not self._click_button('button[aria-label="画像を追加"]'):
                if not self._click_button('//button[@aria-label="画像を追加"]', use_xpath=True):
                    print("[warn] 画像追加ボタンが見つかりません")
                    return False
            time.sleep(0.3)
            
            # 2) 「画像をアップロード」ボタン
            if not self._click_button('//button[.//div[normalize-space()="画像をアップロード"]]', use_xpath=True):
                if not self._click_button('button.sc-920a17ca-7.cZcUfD'):
                    print("[warn] 「画像をアップロード」ボタンが見つかりません")
                    return False
            time.sleep(0.3)
            
            # 3) ファイル入力 - 2段階アプローチ
            # 3-1) まず通常DOMで可視なfile inputを探す
            file_input = self._find_visible_file_input()
            if file_input:
                try:
                    file_input.send_keys(abs_path)
                    print("[info] 可視な file input に send_keys 済み")
                except Exception as e:
                    print(f"[warn] send_keys 失敗（可視input）: {e}")
                    file_input = None
            
            # 3-2) 見つからない/失敗したら CDP で強制セット
            if not file_input:
                candidates = [
                    'input[type="file"][accept*="image"]',
                    'input[type="file"]',
                ]
                ok = False
                for css in candidates:
                    if self._set_file_via_cdp(css, abs_path):
                        ok = True
                        break
                if not ok:
                    print("[warn] file input へのセットに失敗（CDPでも不可）")
                    return False
            
            # 4) プレビュー出現待機
            try:
                WebDriverWait(self.driver, 25).until(
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
            
            # 5) モーダルの「保存」ボタンがあれば押す
            try:
                save_btn = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH,
                        "//button[.//span[normalize-space()='保存'] or normalize-space()='保存']"))
                )
                self.utils.safe_click(self.driver, save_btn)
                print("[info] アイキャッチの保存ボタンをクリック")
                time.sleep(0.3)
            except Exception:
                pass
            
            return True
        
        except Exception as e:
            print(f"[error] set_eyecatch 例外: {e}")
            return False

    def _click_button(self, selector: str, use_xpath: bool = False, timeout: int = 10) -> bool:
        """ボタンクリックヘルパー"""
        try:
            by = By.XPATH if use_xpath else By.CSS_SELECTOR
            el = WebDriverWait(self.driver, timeout).until(
                EC.element_to_be_clickable((by, selector))
            )
            self.utils.safe_click(self.driver, el)
            return True
        except Exception:
            return False

    def _find_visible_file_input(self):
        """可視なfile inputを探す（トップドキュメント＆iframe内）"""
        def _visible(el):
            try:
                return el.is_displayed() and el.is_enabled()
            except Exception:
                return False
        
        # トップドキュメント
        try:
            WebDriverWait(self.driver, 4).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'input[type="file"]'))
            )
            for el in self.driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]'):
                if _visible(el):
                    return el
        except Exception:
            pass
        
        # iframe内も探索
        frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe")
        for fr in frames:
            try:
                self.driver.switch_to.frame(fr)
                els = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
                for el in els:
                    if _visible(el):
                        return el
            except Exception:
                pass
            finally:
                self.driver.switch_to.default_content()
        
        return None

    def _set_file_via_cdp(self, css_selector: str, file_path: str) -> bool:
        """CDP経由でファイル入力（Shadow DOM対応）"""
        try:
            # DOMツリーを取得（pierce=True で Shadow DOM も展開）
            doc = self.driver.execute_cdp_cmd("DOM.getDocument", {"depth": -1, "pierce": True})
            root_id = doc.get("root", {}).get("nodeId")
            if not root_id:
                print("[warn] CDP: root nodeId が取得できません")
                return False
            
            # css_selector で該当ノードを探す
            q = self.driver.execute_cdp_cmd(
                "DOM.querySelector",
                {"nodeId": root_id, "selector": css_selector}
            )
            node_id = q.get("nodeId")
            if not node_id:
                print(f"[warn] CDP: selector 未検出 {css_selector}")
                return False
            
            # ファイルパスをセット（可視性無関係）
            self.driver.execute_cdp_cmd(
                "DOM.setFileInputFiles",
                {"nodeId": node_id, "files": [file_path]}
            )
            print("[info] CDP: file input にファイルをセットしました")
            return True
        except Exception as e:
            print(f"[warn] _set_file_via_cdp 失敗: {e}")
            return False
    
    def insert_toc(self) -> bool:
        """目次挿入"""
        try:
            print("[info] 目次挿入開始")
            
            # メニューボタン
            menu_btn = self.utils.find_clickable_with_retry(
                self.driver, self.sel.MENU_BUTTON
            )
            if not menu_btn:
                print("[warn] メニューボタンが見つかりません")
                return False
            
            self.utils.safe_click(self.driver, menu_btn)
            time.sleep(0.4)
            
            # 目次ボタン
            toc_btn = self.utils.find_clickable_with_retry(
                self.driver, self.sel.TOC_BUTTON
            )
            if not toc_btn:
                print("[warn] 目次ボタンが見つかりません")
                return False
            
            self.utils.safe_click(self.driver, toc_btn)
            time.sleep(0.6)
            print("[info] 目次挿入完了")
            return True
        except Exception as e:
            print(f"[error] 目次挿入失敗: {e}")
            return False
    
    def paste_content(self, title: str, gdoc_url: str) -> bool:
        """GDocからコピー＆ペースト"""
        # エディタ取得
        editor = self.utils.find_element_with_retry(
            self.driver, self.sel.EDITOR_SELECTORS
        )
        if not editor:
            raise RuntimeError("エディタが見つかりませんでした")
        
        # GDocからコピー
        if not self._copy_from_gdoc(gdoc_url):
            raise RuntimeError("GDocコピー失敗")
        
        # ペースト
        for attempt in range(1, 4):
            try:
                ActionChains(self.driver).key_up(Keys.CONTROL).key_up(Keys.SHIFT).key_up(Keys.ALT).perform()
                time.sleep(0.05)
                
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", editor)
                WebDriverWait(self.driver, 8).until(
                    EC.element_to_be_clickable((By.XPATH, "(//*[@contenteditable='true'])[1]"))
                )
                ActionChains(self.driver).move_to_element(editor).click().pause(0.05).click().perform()
                self.driver.execute_script("arguments[0].focus();", editor)
                
                self.driver.execute_script(
                    "document.execCommand('selectAll', false); document.execCommand('delete', false);"
                )
                time.sleep(0.05)
                
                ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
                time.sleep(0.8)
                
                text_len = self.driver.execute_script("return (arguments[0].innerText||'').length;", editor)
                node_count = self.driver.execute_script("return arguments[0].childNodes.length;", editor)
                
                if text_len >= 20 and node_count >= 1:
                    print(f"[ok] ペースト成功 (len={text_len}, nodes={node_count})")
                    self._cleanup_pasted_content(editor, title)
                    return True
                else:
                    print(f"[warn] ペースト薄い (try={attempt})")
            except Exception as e:
                print(f"[warn] ペースト試行失敗 try={attempt}: {e}")
            time.sleep(0.4)
        
        return False
    
    def _copy_from_gdoc(self, doc_url: str) -> bool:
        """GDocから直接コピー"""
        try:
            current = self.driver.current_window_handle
            self.driver.execute_script("window.open(arguments[0], '_blank');", doc_url)
            WebDriverWait(self.driver, 10).until(lambda d: len(d.window_handles) > 1)
            self.driver.switch_to.window(self.driver.window_handles[-1])
            self.utils.wait_doc_ready(self.driver, 15)
            time.sleep(1.0)
            
            ActionChains(self.driver).key_up(Keys.CONTROL).key_up(Keys.SHIFT).key_up(Keys.ALT).perform()
            time.sleep(0.05)
            
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
            time.sleep(0.2)
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('c').key_up(Keys.CONTROL).perform()
            time.sleep(0.4)
            
            print("[info] GDocからクリップボードにコピー完了")
            return True
        except Exception as e:
            print(f"[error] GDocコピー失敗: {e}")
            return False
        finally:
            try:
                self.driver.close()
                self.driver.switch_to.window(current)
            except Exception:
                pass
    
    def _cleanup_pasted_content(self, editor_el, title: str):
        """ペースト後のDOM修正"""
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
                }
                (el.querySelectorAll('strong, b')||[]).forEach(b=>{
                  const span = document.createElement('span');
                  span.innerHTML = b.innerHTML;
                  b.replaceWith(span);
                });
                break;
              }
            }
            return {ok:true};
            """
            result = self.driver.execute_script(cleanup_js, editor_el, title)
            print(f"[info] DOM修正完了")
        except Exception as e:
            print(f"[warn] DOM修正失敗: {e}")
    
    def publish(self) -> str:
        """公開処理"""
        # Step1: 公開に進む
        print("[info] 公開フロー: Step1")
        for xp in self.sel.PUBLISH_STEP1:
            try:
                el = WebDriverWait(self.driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                self.utils.safe_click(self.driver, el)
                time.sleep(0.8)
                break
            except Exception:
                continue
        
        # Step2: 投稿する
        print("[info] 公開フロー: Step2")
        time.sleep(1.0)
        for xp in self.sel.PUBLISH_STEP2:
            try:
                el = WebDriverWait(self.driver, 25).until(
                    EC.element_to_be_clickable((By.XPATH, xp))
                )
                self.utils.safe_click(self.driver, el)
                break
            except Exception:
                continue
        
        # URL確定待機
        return self._wait_public_url()
    
    def _wait_public_url(self, timeout_sec=45) -> str:
        """公開URL取得"""
        print("[info] 公開URL待機")
        end = time.time() + timeout_sec
        while time.time() < end:
            url = self.driver.current_url
            if "/n/" in url and "/edit" not in url:
                print(f"[info] 公開URL確定: {url}")
                return url
            
            try:
                canon = self.driver.find_elements(By.CSS_SELECTOR, 'link[rel="canonical"]')
                if canon:
                    href = canon[0].get_attribute('href')
                    if href and "/n/" in href:
                        print(f"[info] 公開URL確定(canonical): {href}")
                        return href
            except Exception:
                pass
            
            time.sleep(0.6)
        
        return self.driver.current_url
