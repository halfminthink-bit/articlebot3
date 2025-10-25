# publish_note_play/main_playwright.py
"""main_playwright.py - Playwright版メイン処理"""

import argparse
import asyncio
import os
from pathlib import Path


def validate_image_path(image_path: str) -> bool:
    """画像パス検証"""
    if not image_path or not os.path.exists(image_path):
        return False
    ext = os.path.splitext(image_path)[1].lower()
    return ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']


def normalize_note_url(url: str, note_id: str = "") -> str:
    """
    editor のURL(https://editor.note.com/notes/{post_id}/publish/) を
    公開URL(https://note.com/{note_id}/n/{post_id}) に変換。
    NOTE_ID が空なら https://note.com/n/{post_id} を返す。
    """
    try:
        if "editor.note.com/notes/" in url:
            # 例: https://editor.note.com/notes/n3e8643e1b344/publish/
            part = url.split("/notes/")[1]      # n3e8643e1b344/publish/
            post_id = part.split("/")[0]        # n3e8643e1b344
            return f"https://note.com/{note_id}/n/{post_id}" if note_id else f"https://note.com/n/{post_id}"
    except Exception:
        pass
    return url

async def process_rows_async(dry_run=False, sleep_sec=3.0, sheet_tab=None):
    """メイン処理（非同期版）"""
    from playwright.async_api import async_playwright
    from .config import Config
    from .note_selectors import NoteSelectors
    from .sheets_handler import SheetsHandler
    from .playwright_utils import PlaywrightUtils
    from .note_automation_playwright import NoteAutomationPlaywright
    
    target_sheet_name = sheet_tab if sheet_tab and sheet_tab.strip() else Config.SHEET_NAME
    
    # スプレッドシート接続
    sheets = SheetsHandler(Config.SHEET_ID, target_sheet_name, Config.SCOPES)
    try:
        sheets.connect()
        rows = sheets.read_rows()
        print(f"[info] スプレッドシート接続: {Config.SHEET_ID} / {target_sheet_name}")
    except Exception as e:
        if dry_run:
            print(f"[warn] Sheets取得失敗(DRY-RUN継続): {e}")
            rows = []
        else:
            raise
    
    # 対象行抽出
    targets = [r for r in rows if (r.status == "" or r.status.upper() == "READY")]
    if Config.ROW_LIMIT > 0:
        targets = targets[:Config.ROW_LIMIT]
    
    if not targets and not dry_run:
        print("[info] 対象行なし")
        return
    
    # Playwright起動
    async with async_playwright() as p:
        # ブラウザ起動オプション
        launch_options = {
            "headless": Config.HEADLESS,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox"
            ]
        }
        
        # ユーザーデータディレクトリ設定
        if Config.CHROME_USER_DATA_DIR:
            user_data_dir = Path(Config.CHROME_USER_DATA_DIR)
            context_options = {
                "viewport": {"width": 1280, "height": 720},
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            
            browser = await p.chromium.launch_persistent_context(
                str(user_data_dir),
                **launch_options,
                **context_options
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()
        else:
            browser = await p.chromium.launch(**launch_options)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()
        
        # ヘッドレス時は待機時間を自動調整
        if Config.HEADLESS:
            sleep_sec = max(sleep_sec, 5.0)
            print(f"[info] ヘッドレスモード: sleep={sleep_sec}秒に調整")
        
        try:
            note = NoteAutomationPlaywright(page, NoteSelectors, PlaywrightUtils)
            
            # ログイン
            await note.login(Config.NOTE_EMAIL, Config.NOTE_PASSWORD)
            await asyncio.sleep(1.5)
            
            # 各記事処理
            for idx, it in enumerate(targets):
                print("\n" + "=" * 64)
                print(f"[row {it.row_index}] ({idx+1}/{len(targets)}) {it.title}")
                print("=" * 64)
                
                if idx > 0:
                    await page.goto("https://note.com/")
                    await page.wait_for_load_state("networkidle")
                    await note.close_popups(3)
                    await asyncio.sleep(2.0)
                
                try:
                    await note.open_new_post()
                    
                    # ★ HTML整形は使わない（GDocはPlaywrightで開いてコピー）
                    # ここでの GDocHandler 呼び出しは削除して重複を解消
                    
                    # タイトル入力
                    await note.fill_title(it.title)
                    await asyncio.sleep(0.8)
                    
                    # アイキャッチ設定
                    if it.eyecatch_path and validate_image_path(it.eyecatch_path):
                        await note.set_eyecatch(it.eyecatch_path)
                        await asyncio.sleep(1.0)
                    
                    # 本文ペースト（GDoc → Ctrl+C → Ctrl+V）
                    if not await note.paste_content(it.title, it.doc_url):
                        raise RuntimeError("ペースト失敗")
                    
                    await asyncio.sleep(1.0)
                    
                    # 目次挿入（冒頭へ移動→TOC）
                    editor = await PlaywrightUtils.find_element_with_retry(
                        page, NoteSelectors.EDITOR_SELECTORS
                    )
                    if editor:
                        await editor.evaluate("""
                            el => {
                                el.focus();
                                const range = document.createRange();
                                range.setStart(el, 0);
                                range.collapse(true);
                                const sel = window.getSelection();
                                sel.removeAllRanges();
                                sel.addRange(range);
                            }
                        """)
                    
                    await note.insert_toc()
                    await asyncio.sleep(1.0)
                    
                    # 保存待機
                    await asyncio.sleep(3.0)
                    
                    if dry_run:
                        pub_url = page.url
                        if sheets.service:
                            sheets.write_back(it.row_index, "DRY_RUN", pub_url)
                        print(f"[ok] DRY-RUN: {pub_url}")
                        await asyncio.sleep(sleep_sec)
                        continue
                    
                    # 公開
                    try:
                        pub_url = await note.publish()
                        from .config import Config
                        pub_url = normalize_note_url(pub_url, getattr(Config, "NOTE_ID", ""))
                        print(f"[ok] 公開URL: {pub_url}")
                    except Exception as e:
                        print(f"[error] 公開失敗: {e}")
                        if sheets.service:
                            sheets.write_back(it.row_index, "ERROR_PUBLISH", str(e)[:500])
                        await asyncio.sleep(sleep_sec)
                        continue
                    
                    # シート更新
                    try:
                        if sheets.service:
                            sheets.write_back(it.row_index, "POSTED", pub_url)
                            print(f"[info] シート更新完了")
                    except Exception as e:
                        print(f"[warn] シート更新失敗: {e}")
                
                except Exception as e:
                    print(f"[error] 記事作成失敗: {e}")
                    if sheets.service:
                        sheets.write_back(it.row_index, "ERROR_CREATE", str(e)[:500])
                
                await asyncio.sleep(sleep_sec)
        
        finally:
            print("\n[info] ブラウザ終了")
            try:
                await browser.close()
            except Exception:
                pass


def process_rows(dry_run=False, sleep_sec=3.0, sheet_tab=None):
    """同期ラッパー関数"""
    asyncio.run(process_rows_async(dry_run, sleep_sec, sheet_tab))


def main():
    """CLIエントリーポイント"""
    parser = argparse.ArgumentParser(
        description="Sheets→GDoc→note 自動公開(Playwright版)"
    )
    parser.add_argument("--dry-run", action="store_true", help="公開せずに動作確認")
    parser.add_argument("--sleep", type=float, default=3.0, help="投稿間スリープ秒")
    parser.add_argument(
        "--sheet-tab", 
        default="", 
        help="スプレッドシートのタブ名(未指定時はConfig/envから取得、デフォルト: Articles)"
    )
    args = parser.parse_args()
    
    process_rows(dry_run=args.dry_run, sleep_sec=args.sleep, sheet_tab=args.sheet_tab)


if __name__ == "__main__":
    main()
