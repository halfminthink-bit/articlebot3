#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投稿した記事を削除するスクリプト
"""

from wordpress_api import WordPressAPI

# WordPress設定
WP_SITE_URL = 'https://halfminthinking.com'
WP_USERNAME = 'halfminthinking'
WP_APP_PASSWORD = 'iN4H IfZf gt0l Yl2M ZCrO QWyO'

# 削除する記事のID
POST_IDS = [1291, 1292, 1293, 1295, 1297, 1299]

def main():
    wp = WordPressAPI(WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD)
    
    for post_id in POST_IDS:
        print(f"🗑️  記事 ID {post_id} を削除中...")
        result = wp.delete_post(post_id)
        if result:
            print(f"✅ 削除成功: ID {post_id}")
        else:
            print(f"❌ 削除失敗: ID {post_id}")

if __name__ == "__main__":
    main()
