#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下書き記事を公開するスクリプト
"""

from wordpress_api import WordPressAPI
import requests
import base64

# WordPress設定
WP_SITE_URL = 'https://halfminthinking.com'
WP_USERNAME = 'halfminthinking'
WP_APP_PASSWORD = 'iN4H IfZf gt0l Yl2M ZCrO QWyO'

# 公開する記事のID
POST_ID = 1302

def main():
    # WordPress API設定
    site_url = WP_SITE_URL.rstrip('/')
    api_base = f"{site_url}/wp-json/wp/v2"
    
    clean_password = WP_APP_PASSWORD.replace(' ', '')
    credentials = f"{WP_USERNAME}:{clean_password}"
    token = base64.b64encode(credentials.encode()).decode()
    headers = {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }
    
    # 記事を公開
    url = f"{api_base}/posts/{POST_ID}"
    data = {'status': 'publish'}
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        post = response.json()
        print(f"✅ 記事を公開しました！")
        print(f"   URL: {post['link']}")
    except Exception as e:
        print(f"❌ 公開に失敗しました: {e}")
        if hasattr(e, 'response'):
            print(f"レスポンス: {e.response.text}")

if __name__ == "__main__":
    main()
