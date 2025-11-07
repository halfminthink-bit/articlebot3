#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WordPress REST API連携クラス
"""

import requests
import base64
import os
from typing import Optional, Dict, Any


class WordPressAPI:
    """WordPress REST APIとの連携を管理するクラス"""
    
    def __init__(self, site_url: str, username: str, app_password: str):
        """
        初期化
        
        Args:
            site_url: WordPressサイトのURL（例: https://halfminthinking.com）
            username: WordPressユーザー名
            app_password: アプリケーションパスワード（スペースあり/なし両方対応）
        """
        self.site_url = site_url.rstrip('/')
        self.api_base = f"{self.site_url}/wp-json/wp/v2"
        
        # アプリケーションパスワードからスペースを削除
        clean_password = app_password.replace(' ', '')
        
        # Basic認証用のヘッダーを作成
        credentials = f"{username}:{clean_password}"
        token = base64.b64encode(credentials.encode()).decode()
        self.headers = {
            'Authorization': f'Basic {token}',
            'Content-Type': 'application/json'
        }
    
    def get_category_id(self, category_slug: str) -> Optional[int]:
        """
        カテゴリースラッグからカテゴリーIDを取得
        
        Args:
            category_slug: カテゴリースラッグ（例: "philosophy"）
            
        Returns:
            カテゴリーID、見つからない場合はNone
        """
        url = f"{self.api_base}/categories"
        params = {'slug': category_slug}
        
        try:
            response = requests.get(url, params=params, headers=self.headers)
            response.raise_for_status()
            categories = response.json()
            
            if categories:
                return categories[0]['id']
            return None
        except Exception as e:
            print(f"カテゴリー取得エラー: {e}")
            return None
    
    def upload_media(self, image_path: str, title: str = None) -> Optional[int]:
        """
        画像をWordPressメディアライブラリにアップロード
        
        Args:
            image_path: アップロードする画像のパス
            title: 画像のタイトル（省略時はファイル名）
            
        Returns:
            アップロードされた画像のメディアID、失敗時はNone
        """
        url = f"{self.api_base}/media"
        
        # ファイル名を取得（日本語ファイル名を英数字に変換）
        import hashlib
        import time
        
        original_filename = os.path.basename(image_path)
        file_ext = os.path.splitext(original_filename)[1]
        
        # タイムスタンプとハッシュでユニークなファイル名を生成
        timestamp = int(time.time())
        hash_str = hashlib.md5(original_filename.encode()).hexdigest()[:8]
        filename = f"thumbnail_{timestamp}_{hash_str}{file_ext}"
        
        if title is None:
            title = os.path.splitext(original_filename)[0]
        
        # ファイルを読み込み
        with open(image_path, 'rb') as f:
            file_data = f.read()
        
        # ヘッダーを準備（Content-Typeを画像用に変更）
        headers = self.headers.copy()
        headers['Content-Type'] = 'image/png'
        headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        try:
            response = requests.post(
                url,
                headers=headers,
                data=file_data,
                params={'title': title}
            )
            response.raise_for_status()
            media = response.json()
            return media['id']
        except Exception as e:
            print(f"メディアアップロードエラー: {e}")
            if hasattr(e, 'response'):
                print(f"レスポンス: {e.response.text}")
            return None
    
    def create_post(
        self,
        title: str,
        content: str,
        category_ids: list = None,
        tags: list = None,
        featured_media_id: int = None,
        status: str = 'draft'
    ) -> Optional[Dict[str, Any]]:
        """
        記事を投稿
        
        Args:
            title: 記事タイトル
            content: 記事本文（HTML）
            category_ids: カテゴリーIDのリスト
            tags: タグIDまたはタグ名のリスト
            featured_media_id: アイキャッチ画像のメディアID
            status: 投稿ステータス（'draft' or 'publish'）
            
        Returns:
            作成された投稿の情報、失敗時はNone
        """
        url = f"{self.api_base}/posts"
        
        data = {
            'title': title,
            'content': content,
            'status': status
        }
        
        if category_ids:
            data['categories'] = category_ids
        
        if tags:
            data['tags'] = tags
        
        if featured_media_id:
            data['featured_media'] = featured_media_id
        
        try:
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()
            post = response.json()
            return post
        except Exception as e:
            print(f"投稿作成エラー: {e}")
            if hasattr(e, 'response'):
                print(f"レスポンス: {e.response.text}")
            return None
    
    def get_or_create_tag(self, tag_name: str) -> Optional[int]:
        """
        タグ名からタグIDを取得、存在しない場合は作成
        
        Args:
            tag_name: タグ名
            
        Returns:
            タグID、失敗時はNone
        """
        # まず既存のタグを検索
        url = f"{self.api_base}/tags"
        params = {'search': tag_name}
        
        try:
            response = requests.get(url, params=params, headers=self.headers)
            response.raise_for_status()
            tags = response.json()
            
            # 完全一致するタグを探す
            for tag in tags:
                if tag['name'] == tag_name:
                    return tag['id']
            
            # 見つからない場合は新規作成
            data = {'name': tag_name}
            response = requests.post(url, headers=self.headers, json=data)
            response.raise_for_status()
            new_tag = response.json()
            return new_tag['id']
        except Exception as e:
            print(f"タグ取得/作成エラー: {e}")
            return None


if __name__ == '__main__':
    # テスト用コード
    wp = WordPressAPI(
        site_url='https://halfminthinking.com',
        username='halfminthinking',
        app_password='iN4H IfZf gt0l Yl2M ZCrO QWyO'
    )
    
    # カテゴリーIDを取得
    category_id = wp.get_category_id('philosophy')
    print(f"Philosophy category ID: {category_id}")
