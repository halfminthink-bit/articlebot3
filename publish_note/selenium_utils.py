"""selenium_utils.py"""

import time
from typing import Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


class SeleniumUtils:
    """Selenium共通ユーティリティ"""
    
    @staticmethod
    def build_driver(headless: bool, user_data_dir: Optional[str],
                    profile: Optional[str]) -> webdriver.Chrome:
        """Chromeドライバ作成"""
        opts = webdriver.ChromeOptions()
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
        
        drv = webdriver.Chrome(options=opts)
        drv.set_page_load_timeout(60)
        return drv
    
    @staticmethod
    def wait_doc_ready(drv, timeout=20):
        """ドキュメント読み込み完了を待機"""
        try:
            WebDriverWait(drv, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass
    
    @staticmethod
    def safe_click(drv, element, description=""):
        """安全なクリック"""
        try:
            drv.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", element
            )
            time.sleep(0.3)
            drv.execute_script("arguments[0].click();", element)
            if description:
                print(f"  ✓ {description}をクリック")
            return True
        except Exception as e:
            if description:
                print(f"  ✗ {description}のクリック失敗: {e}")
            return False
    
    @staticmethod
    def find_element_with_retry(drv, selectors, timeout=10):
        """複数セレクタでリトライしながら要素を探す"""
        for sel in selectors:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                el = WebDriverWait(drv, timeout).until(
                    EC.presence_of_element_located((by, sel))
                )
                if el:
                    return el
            except Exception:
                continue
        return None
    
    @staticmethod
    def find_clickable_with_retry(drv, selectors, timeout=10):
        """複数セレクタでクリック可能な要素を探す"""
        for sel in selectors:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                el = WebDriverWait(drv, timeout).until(
                    EC.element_to_be_clickable((by, sel))
                )
                if el:
                    return el
            except Exception:
                continue
        return None
