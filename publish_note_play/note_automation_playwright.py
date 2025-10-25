# publish_note_play/note_automation_playwright.py
"""note_automation_playwright.py (async版)"""

import os
import asyncio
from typing import Optional
from playwright.async_api import Page, Locator, TimeoutError as PlaywrightTimeout

class NoteAutomationPlaywright:
    """note自動化クラス（Playwright/async版）"""

    def __init__(self, page: Page, selectors, utils):
        self.page = page
        self.sel = selectors
        self.utils = utils

    async def is_logged_in(self) -> bool:
        try:
            for s in self.sel.AVATAR_SELECTORS:
                locator = self.page.locator(s)
                if await locator.count() > 0 and await locator.first.is_visible():
                    return True

            locator = self.page.locator('a[href="/notes/new"]')
            if await locator.count() > 0 and await locator.first.is_visible():
                return True

            if await self.page.locator('a[href^="/login"]').count() > 0:
                return False

            return False
        except Exception:
            return False

    async def close_popups(self, timeout_sec: int = 4):
        end = asyncio.get_event_loop().time() + max(1, timeout_sec)
        while asyncio.get_event_loop().time() < end:
            for s in self.sel.POPUP_CLOSE:
                try:
                    locator = self.page.locator(f"xpath={s}") if s.startswith("//") else self.page.locator(s)
                    if await locator.count() > 0:
                        el = locator.first
                        if await el.is_visible() and await el.is_enabled():
                            await self.utils.safe_click(self.page, el)
                            await asyncio.sleep(0.2)
                            return
                except Exception:
                    pass
            await asyncio.sleep(0.15)

    async def login(self, email: str, password: str):
        try:
            await self.page.goto("https://note.com/logout", wait_until="domcontentloaded", timeout=10000)
            await self.utils.wait_doc_ready(self.page, 10000)
            await asyncio.sleep(0.6)
        except Exception:
            pass

        await self.page.goto("https://note.com/", wait_until="domcontentloaded", timeout=15000)
        await self.utils.wait_doc_ready(self.page, 15000)
        await self.close_popups(4)

        # ログインボタン
        for sel in self.sel.LOGIN_LINKS:
            try:
                locator = self.page.locator(f"xpath={sel}") if sel.startswith("//") else self.page.locator(sel)
                await locator.wait_for(state="visible", timeout=5000)
                await self.utils.safe_click(self.page, locator)
                break
            except Exception:
                continue

        try:
            await self.page.wait_for_url("**/login**", timeout=12000)
        except PlaywrightTimeout:
            await self.page.goto("https://note.com/login", wait_until="domcontentloaded")

        await self.utils.wait_doc_ready(self.page, 20000)
        await self.close_popups(4)

        if await self.is_logged_in():
            print("[info] 既にログイン済み")
            return

        if not email or not password:
            raise ValueError("NOTE_EMAIL / NOTE_PASSWORD が未設定です")

        # ===== メール入力 =====
        email_box = self.page.locator(self.sel.EMAIL_INPUT)
        await email_box.wait_for(state="visible", timeout=15000)
        await email_box.fill(email)
        # ▼ バリデーションを明示的に発火
        try:
            await email_box.dispatch_event("input")
            await email_box.dispatch_event("change")
        except Exception:
            pass
        await email_box.press("Tab")  # blur
        await asyncio.sleep(0.2)

        # ===== 「次へ」クリック（enabled待ち→クリック／Enterフォールバック）=====
        next_clicked = False
        for sel in self.sel.LOGIN_BUTTONS.split(","):
            sel = sel.strip()
            loc = self.page.locator(sel)
            if await loc.count() == 0:
                continue
            btn = loc.first
            try:
                await btn.wait_for(state="visible", timeout=10000)
                # enabledになるまでポーリング（最大10秒）
                for _ in range(40):
                    if await btn.is_enabled():
                        await btn.click()
                        next_clicked = True
                        break
                    await asyncio.sleep(0.25)
                if next_clicked:
                    break
            except Exception:
                continue

        if not next_clicked:
            # フォールバック：Enter送信
            try:
                await email_box.press("Enter")
            except Exception:
                pass
        await asyncio.sleep(0.6)

        # ===== パスワード入力 =====
        pw_box = self.page.locator(self.sel.PASSWORD_INPUT)
        await pw_box.wait_for(state="visible", timeout=15000)
        await pw_box.fill(password)
        # ▼ バリデーションを明示的に発火
        try:
            await pw_box.dispatch_event("input")
            await pw_box.dispatch_event("change")
        except Exception:
            pass
        await pw_box.press("Tab")
        await asyncio.sleep(0.2)

        # ===== 「ログイン」クリック（enabled待ち→クリック／Enterフォールバック）=====
        login_clicked = False
        for sel in self.sel.LOGIN_BUTTONS.split(","):
            sel = sel.strip()
            loc = self.page.locator(sel)
            if await loc.count() == 0:
                continue
            btn = loc.first
            try:
                await btn.wait_for(state="visible", timeout=10000)
                for _ in range(40):
                    if await btn.is_enabled():
                        await btn.click()
                        login_clicked = True
                        break
                    await asyncio.sleep(0.25)
                if login_clicked:
                    break
            except Exception:
                continue

        if not login_clicked:
            try:
                await pw_box.press("Enter")
            except Exception:
                pass

        # 完了待機
        await self.page.wait_for_function("() => true", timeout=45000)
        await asyncio.sleep(2)
        await self.utils.wait_doc_ready(self.page, 10000)
        await self.close_popups(4)
        print("[info] ログイン成功")

    async def open_new_post(self, timeout_sec: int = 30):
        print("[info] 新規作成ページへ遷移")
        await self.close_popups(3)
        await asyncio.sleep(1.0)

        clicked = False
        for sel in self.sel.NEW_POST_BUTTONS:
            try:
                locator = self.page.locator(sel)
                if await locator.count() > 0:
                    el = locator.first
                    await self.utils.safe_click(self.page, el)
                    clicked = True
                    print(f"[debug] 投稿ボタンクリック成功: {sel}")
                    break
            except Exception as e:
                print(f"[debug] 投稿ボタンクリック失敗: {sel} - {e}")
                continue

        if not clicked:
            raise RuntimeError("投稿ボタンのクリックに失敗")

        await asyncio.sleep(2.0)

        try:
            await self.page.wait_for_function(
                """() => {
                    return window.location.href.includes('/notes/new') ||
                           document.querySelector('div.ProseMirror[contenteditable="true"]') !== null;
                }""",
                timeout=timeout_sec * 1000
            )
        except PlaywrightTimeout:
            print(f"[warn] タイムアウト。現在のURL: {self.page.url}")

        await self.utils.wait_doc_ready(self.page, 20000)
        await self.close_popups(3)
        await asyncio.sleep(2.0)

    async def fill_title(self, title: str):
        print("[info] タイトル入力開始")
        await self.utils.wait_doc_ready(self.page, 30000)
        await asyncio.sleep(1.5)

        el: Optional[Locator] = None

        # 優先
        for sel in self.sel.TITLE_INPUT_PRIORITY:
            try:
                locator = self.page.locator(sel)
                if await locator.count() > 0:
                    el = locator.first
                    print(f"[debug] タイトル要素発見(優先): {sel}")
                    break
            except Exception as e:
                print(f"[debug] セレクタ失敗(優先): {sel} - {e}")

        # FB
        if el is None:
            for sel in self.sel.TITLE_INPUT_FALLBACKS:
                try:
                    locator = self.page.locator(f"xpath={sel}") if sel.startswith("//") else self.page.locator(sel)
                    if await locator.count() > 0:
                        el = locator.first
                        print(f"[debug] タイトル要素発見(FB): {sel}")
                        break
                except Exception as e:
                    print(f"[debug] セレクタ失敗(FB): {sel} - {e}")

        # 広範
        if el is None:
            print("[debug] 広範検索開始")
            await asyncio.sleep(1.0)
            try:
                all_textareas = await self.page.locator("textarea").all()
                print(f"[debug] textarea要素数: {len(all_textareas)}")
                for ta in all_textareas:
                    try:
                        placeholder = await ta.get_attribute("placeholder") or ""
                        print(f"[debug] textarea placeholder: {placeholder}")
                        if "タイトル" in placeholder or "title" in placeholder.lower():
                            el = ta
                            print("[debug] タイトル要素発見(広範検索)")
                            break
                    except Exception:
                        continue
            except Exception as e:
                print(f"[debug] 広範検索失敗: {e}")

        if el is None:
            print("[debug] ページHTML (先頭1000文字):")
            print((await self.page.content())[:1000])
            raise RuntimeError("タイトル入力欄が見つかりませんでした")

        try:
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)
            await el.focus()
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"[warn] フォーカス失敗: {e}")

        try:
            await el.fill(title)
            await asyncio.sleep(0.5)
            print("[info] タイトル入力 OK")
        except Exception as e:
            print(f"[error] タイトルセット失敗: {e}")
            raise

    async def set_eyecatch(self, image_path: str) -> bool:
        try:
            abs_path = os.path.abspath(image_path)
            print(f"[info] アイキャッチ画像パス: {abs_path}")

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

            # --- ① 直接 input[type=file] にセット（最優先: OSダイアログを出さない） ---
            file_input = await self._find_file_input()
            if file_input:
                try:
                    # hidden でもOK。UIを一切クリックしないのでエクスプローラーは開かない
                    await file_input.set_input_files(abs_path)
                    print("[info] ファイル入力完了（直接 set_input_files）")
                    # 保存ボタンがある場合は押しておく（あればでOK）
                    try:
                        save_btn = self.page.locator("//button[.//span[normalize-space()='保存'] or normalize-space()='保存']")
                        await save_btn.wait_for(state="visible", timeout=2000)
                        await self.utils.safe_click(self.page, save_btn)
                        print("[info] アイキャッチの保存ボタンをクリック")
                    except Exception:
                        pass
                    # プレビュー反映待ち
                    try:
                        await self.page.wait_for_function(
                            """() => document.querySelector('img[src*="noteusercontent"], img[src^="blob:"], img[alt*="アイキャッチ"]')""",
                            timeout=25000
                        )
                    except Exception:
                        print("[warn] プレビュー確認タイムアウト（反映遅延の可能性）")
                    return True
                except Exception as e:
                    print(f"[warn] 直接 set_input_files 失敗: {e}")
                    # 失敗時は②へフォールバック

            # --- ② expect_file_chooser でボタンクリックを包む（ネイティブダイアログを抑止） ---
            # 画像を追加 → アップロード まで（既存セレクタは極力そのまま）
            opened = False
            for sel in ['button[aria-label="画像を追加"]', '//button[@aria-label="画像を追加"]']:
                try:
                    locator = self.page.locator(f"xpath={sel}") if sel.startswith("//") else self.page.locator(sel)
                    await locator.wait_for(state="visible", timeout=7000)
                    await self.utils.safe_click(self.page, locator)
                    opened = True
                    break
                except Exception:
                    continue
            if not opened:
                print("[warn] 画像追加ボタンが見つかりません")
                return False

            await asyncio.sleep(0.3)

            # 「画像をアップロード」をクリックする瞬間を expect_file_chooser で包む
            try:
                async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                    # 代表セレクタ（既存のまま＋xpath）
                    if await self.page.locator('//button[.//div[normalize-space()="画像をアップロード"]]').count() > 0:
                        await self.page.locator('//button[.//div[normalize-space()="画像をアップロード"]]').first.click()
                    elif await self.page.locator('button.sc-920a17ca-7.cZcUfD').count() > 0:
                        await self.page.locator('button.sc-920a17ca-7.cZcUfD').first.click()
                    else:
                        raise RuntimeError("「画像をアップロード」ボタンが見つかりません")
                chooser = await fc_info.value
                await chooser.set_files(abs_path)  # ← ここでファイルを渡す（OSダイアログは実質制御下）
                print("[info] ファイル入力完了（expect_file_chooser）")
            except Exception as e:
                print(f"[error] filechooser 経由のアップロード失敗: {e}")
                return False

            # プレビュー待機
            try:
                await self.page.wait_for_function(
                    """() => document.querySelector('img[src*="noteusercontent"], img[src^="blob:"], img[alt*="アイキャッチ"]')""",
                    timeout=25000
                )
                print("[info] アイキャッチ画像のアップロード完了")
                await asyncio.sleep(0.4)
            except Exception:
                print("[warn] 画像プレビューの確認タイムアウト（反映遅延の可能性）")

            # 保存ボタン
            try:
                save_btn = self.page.locator("//button[.//span[normalize-space()='保存'] or normalize-space()='保存']")
                await save_btn.wait_for(state="visible", timeout=2000)
                await self.utils.safe_click(self.page, save_btn)
                print("[info] アイキャッチの保存ボタンをクリック")
                await asyncio.sleep(0.3)
            except Exception:
                pass

            return True

        except Exception as e:
            print(f"[error] set_eyecatch 例外: {e}")
            return False


    async def _click_button(self, selector: str, use_xpath: bool = False, timeout: int = 10000) -> bool:
        try:
            locator = self.page.locator(f"xpath={selector}") if use_xpath else self.page.locator(selector)
            await locator.wait_for(state="visible", timeout=timeout)
            await self.utils.safe_click(self.page, locator)
            return True
        except Exception:
            return False

    async def _find_file_input(self) -> Optional[Locator]:
        candidates = [
            'input[type="file"][accept*="image"]',
            'input[type="file"]',
        ]
        for css in candidates:
            try:
                locator = self.page.locator(css)
                if await locator.count() > 0:
                    return locator.first
            except Exception:
                continue
        return None

    async def insert_toc(self) -> bool:
        try:
            print("[info] 目次挿入開始]")
            menu_btn = await self.utils.find_clickable_with_retry(self.page, self.sel.MENU_BUTTON)
            if not menu_btn:
                print("[warn] メニューボタンが見つかりません")
                return False
            await self.utils.safe_click(self.page, menu_btn)
            await asyncio.sleep(0.4)

            toc_btn = await self.utils.find_clickable_with_retry(self.page, self.sel.TOC_BUTTON)
            if not toc_btn:
                print("[warn] 目次ボタンが見つかりません")
                return False
            await self.utils.safe_click(self.page, toc_btn)
            await asyncio.sleep(0.6)
            print("[info] 目次挿入完了")
            return True
        except Exception as e:
            print(f"[error] 目次挿入失敗: {e}")
            return False

    async def paste_content(self, title: str, gdoc_url: str) -> bool:
        editor = await self.utils.find_element_with_retry(self.page, self.sel.EDITOR_SELECTORS)
        if not editor:
            raise RuntimeError("エディタが見つかりませんでした")

        if not await self._copy_from_gdoc(gdoc_url):
            raise RuntimeError("GDocコピー失敗")

        for attempt in range(1, 4):
            try:
                await editor.scroll_into_view_if_needed()
                await editor.click()
                await asyncio.sleep(0.1)

                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.press("Delete")
                await asyncio.sleep(0.05)

                await self.page.keyboard.press("Control+V")
                await asyncio.sleep(0.8)

                text_len = await editor.evaluate("el => (el.innerText || '').length")
                node_count = await editor.evaluate("el => el.childNodes.length")

                if text_len >= 20 and node_count >= 1:
                    print(f"[ok] ペースト成功 (len={text_len}, nodes={node_count})")
                    await self._cleanup_pasted_content(editor, title)
                    return True
                else:
                    print(f"[warn] ペースト薄い (try={attempt})")
            except Exception as e:
                print(f"[warn] ペースト試行失敗 try={attempt}: {e}")
            await asyncio.sleep(0.4)

        return False

    async def _copy_from_gdoc(self, doc_url: str) -> bool:
        new_page: Page = None
        try:
            new_page = await self.page.context.new_page()
            await new_page.goto(doc_url, wait_until="domcontentloaded", timeout=15000)
            await self.utils.wait_doc_ready(new_page, 15000)
            await asyncio.sleep(1.0)

            await new_page.keyboard.press("Control+A")
            await asyncio.sleep(0.2)
            await new_page.keyboard.press("Control+C")
            await asyncio.sleep(0.4)

            print("[info] GDocからクリップボードにコピー完了")
            await new_page.close()
            return True
        except Exception as e:
            print(f"[error] GDocコピー失敗: {e}")
            try:
                if new_page:
                    await new_page.close()
            except:
                pass
            return False

    async def _cleanup_pasted_content(self, editor_el: Locator, title: str):
        try:
            cleanup_js = r"""
            (editor, title) => {
                function normalize(s){
                  return (s||'').normalize('NFKC')
                    .replace(/\u3000/g,' ')
                    .replace(/\s+/g,' ')
                    .trim()
                    .toLowerCase()
                    .replace(/[\"'""''、。,.!！?？:：;\-‐−—･・\/｜|\[\]\(\)（）【】「」『』…⋯-]+/g,'');
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
            }
            """
            await editor_el.evaluate(cleanup_js, title)
            print(f"[info] DOM修正完了")
        except Exception as e:
            print(f"[warn] DOM修正失敗: {e}")

    async def publish(self) -> str:
        print("[info] 公開フロー: Step1")
        for xp in self.sel.PUBLISH_STEP1:
            try:
                locator = self.page.locator(f"xpath={xp}")
                await locator.wait_for(state="visible", timeout=20000)
                await self.utils.safe_click(self.page, locator)
                await asyncio.sleep(0.8)
                break
            except Exception:
                continue

        print("[info] 公開フロー: Step2")
        await asyncio.sleep(1.0)
        for xp in self.sel.PUBLISH_STEP2:
            try:
                locator = self.page.locator(f"xpath={xp}")
                await locator.wait_for(state="visible", timeout=25000)
                await self.utils.safe_click(self.page, locator)
                break
            except Exception:
                continue

        return await self._wait_public_url()

    async def _wait_public_url(self, timeout_sec: int = 45) -> str:
        print("[info] 公開URL待機")
        end = asyncio.get_event_loop().time() + timeout_sec
        while asyncio.get_event_loop().time() < end:
            url = self.page.url
            if "/n/" in url and "/edit" not in url:
                print(f"[info] 公開URL確定: {url}")
                return url

            try:
                canon = self.page.locator('link[rel="canonical"]')
                if await canon.count() > 0:
                    href = await canon.first.get_attribute('href')
                    if href and "/n/" in href:
                        print(f"[info] 公開URL確定(canonical): {href}")
                        return href
            except Exception:
                pass

            await asyncio.sleep(0.6)

        return self.page.url
