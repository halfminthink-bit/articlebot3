"""main.py"""

import argparse
import time


def validate_image_path(image_path: str) -> bool:
    """画像パス検証"""
    import os
    if not image_path or not os.path.exists(image_path):
        return False
    ext = os.path.splitext(image_path)[1].lower()
    return ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']


def process_rows(dry_run=False, sleep_sec=3.0):
    """メイン処理"""
    # 設定読み込み
    from .config import Config
    from .note_selectors import NoteSelectors
    
    # ハンドラー初期化
    from .sheets_handler import SheetsHandler
    from .gdoc_handler import GDocHandler
    from .selenium_utils import SeleniumUtils
    from .note_automation import NoteAutomation
    
    # Sheets接続
    sheets = SheetsHandler(Config.SHEET_ID, Config.SHEET_NAME, Config.SCOPES)
    try:
        sheets.connect()
        rows = sheets.read_rows()
    except Exception as e:
        if dry_run:
            print(f"[warn] Sheets取得失敗（DRY-RUN継続）: {e}")
            rows = []
        else:
            raise
    
    targets = [r for r in rows if (r.status == "" or r.status.upper() == "READY")]
    if Config.ROW_LIMIT > 0:
        targets = targets[:Config.ROW_LIMIT]
    
    if not targets and not dry_run:
        print("[info] 対象行なし")
        return
    
    # ドライバ作成
    driver = SeleniumUtils.build_driver(
        Config.HEADLESS,
        Config.CHROME_USER_DATA_DIR,
        Config.CHROME_PROFILE_DIR
    )
    
    try:
        # note自動化インスタンス
        note = NoteAutomation(driver, NoteSelectors, SeleniumUtils)
        
        # ログイン
        note.login(Config.NOTE_EMAIL, Config.NOTE_PASSWORD)
        time.sleep(0.8)
        
        # 各行を処理
        for idx, it in enumerate(targets):
            print("\n" + "=" * 64)
            print(f"[row {it.row_index}] ({idx+1}/{len(targets)}) {it.title}")
            print("=" * 64)
            
            if idx > 0:
                driver.get("https://note.com/")
                SeleniumUtils.wait_doc_ready(driver, 15)
                note.close_popups(3)
                time.sleep(1.0)
            
            try:
                # 新規投稿ページ
                note.open_new_post()
                
                # GDoc取得
                try:
                    html, removed = GDocHandler.process_document(it.doc_url, it.title)
                    print(f"[debug] GDoc HTML length: {len(html)}")
                except Exception as e:
                    print(f"[error] GDoc取得失敗: {e}")
                    if sheets.service:
                        sheets.write_back(it.row_index, "ERROR_GDOC", str(e)[:500])
                    time.sleep(sleep_sec)
                    continue
                
                # タイトル
                note.fill_title(it.title)
                
                # アイキャッチ
                if it.eyecatch_path and validate_image_path(it.eyecatch_path):
                    note.set_eyecatch(it.eyecatch_path)
                    time.sleep(0.5)
                
                # 本文ペースト
                if not note.paste_content(it.title, it.doc_url):
                    raise RuntimeError("ペースト失敗")
                
                # 目次挿入（キャレットを先頭に移動してから）
                editor = SeleniumUtils.find_element_with_retry(
                    driver, NoteSelectors.EDITOR_SELECTORS
                )
                if editor:
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
                    driver.execute_script(js, editor)
                
                note.insert_toc()
                time.sleep(0.5)
                
                # 保存待機
                time.sleep(2.0)
                
                if dry_run:
                    pub_url = driver.current_url
                    if sheets.service:
                        sheets.write_back(it.row_index, "DRY_RUN", pub_url)
                    print(f"[ok] DRY-RUN: {pub_url}")
                    time.sleep(sleep_sec)
                    continue
                
                # 公開
                try:
                    pub_url = note.publish()
                    print(f"[ok] 公開URL: {pub_url}")
                except Exception as e:
                    print(f"[error] 公開失敗: {e}")
                    if sheets.service:
                        sheets.write_back(it.row_index, "ERROR_PUBLISH", str(e)[:500])
                    time.sleep(sleep_sec)
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
            
            time.sleep(sleep_sec)
    
    finally:
        print("\n[info] ブラウザ終了")
        try:
            driver.quit()
        except Exception:
            pass


def main():
    """CLIエントリーポイント"""
    parser = argparse.ArgumentParser(
        description="Sheets→GDoc→note 自動公開（モジュール版）"
    )
    parser.add_argument("--dry-run", action="store_true", help="公開せずに動作確認")
    parser.add_argument("--sleep", type=float, default=3.0, help="投稿間スリープ秒")
    args = parser.parse_args()
    
    process_rows(dry_run=args.dry_run, sleep_sec=args.sleep)


if __name__ == "__main__":
    main()