#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完全版 哲学記事自動投稿スクリプト（AI画像生成付き）
"""

import os
import sys
from article_generator_seo import ArticleGeneratorSEO
from ai_thumbnail_generator import AIThumbnailGenerator
from wordpress_api import WordPressAPI


# WordPress設定
WP_SITE_URL = 'https://halfminthinking.com'
WP_USERNAME = 'halfminthinking'
WP_APP_PASSWORD = 'iN4H IfZf gt0l Yl2M ZCrO QWyO'


class PhilosophyBotComplete:
    """完全版 哲学記事自動投稿ボット（AI画像生成付き）"""
    
    def __init__(self):
        """初期化"""
        self.article_generator = ArticleGeneratorSEO()
        self.thumbnail_generator = AIThumbnailGenerator()
        self.wp_api = WordPressAPI(WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD)
        self.output_dir = '/home/ubuntu/philosophy_bot/output'
        os.makedirs(self.output_dir, exist_ok=True)
    
    def upload_thumbnail(self, image_path: str, philosopher: str) -> int:
        """
        アイキャッチ画像をWordPressにアップロード
        
        Args:
            image_path: 画像ファイルのパス
            philosopher: 哲学者名
            
        Returns:
            メディアID
        """
        print(f"\n3. アイキャッチ画像をアップロード中...")
        
        if not os.path.exists(image_path):
            print(f"❌ 画像ファイルが見つかりません: {image_path}")
            return None
        
        media_id = self.wp_api.upload_media(
            image_path=image_path,
            title=f"{philosopher}_thumbnail"
        )
        
        if media_id:
            print(f"✅ アイキャッチ画像アップロード完了 (ID: {media_id})")
        else:
            print("❌ アイキャッチ画像のアップロードに失敗しました")
        
        return media_id
    
    def create_and_post_article(
        self,
        philosopher: str,
        famous_quote: str,
        theme: str,
        overview_items: list,
        target_keyword: str = None,
        status: str = 'draft',
        thumbnail_path: str = None
    ) -> dict:
        """
        SEO最適化された記事を生成してWordPressに投稿（AI画像付き）
        
        Args:
            philosopher: 哲学者名
            famous_quote: 有名な言葉
            theme: テーマ
            overview_items: 「この記事で分かること」の項目リスト
            target_keyword: ターゲットキーワード（省略可）
            status: 投稿ステータス ('draft' or 'publish')
            thumbnail_path: アイキャッチ画像のパス（省略時は生成しない）
            
        Returns:
            投稿結果の辞書
        """
        print(f"\n{'='*60}")
        print(f"記事生成開始: {philosopher}")
        print(f"テーマ: {theme}")
        print(f"ターゲットキーワード: {target_keyword or 'なし'}")
        print(f"{'='*60}\n")
        
        # 1. 記事生成
        print("1. 記事を生成中...")
        article_data = self.article_generator.generate_article(
            philosopher=philosopher,
            famous_quote=famous_quote,
            theme=theme,
            overview_items=overview_items,
            target_keyword=target_keyword
        )
        
        if not article_data:
            print("❌ 記事生成に失敗しました")
            return {'success': False, 'error': '記事生成失敗'}
        
        print(f"✅ 記事生成完了")
        print(f"   タイトル: {article_data['title']}")
        print(f"   メタディスクリプション: {article_data['meta_description']}")
        
        # 2. 完全なHTMLを生成
        print("\n2. HTMLを構築中...")
        full_html = self.article_generator.create_full_html(
            article_data=article_data,
            overview_items=overview_items
        )
        
        # HTMLを保存（デバッグ用）
        html_path = os.path.join(self.output_dir, f'{philosopher}_article_complete.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(full_html)
        print(f"✅ HTML保存: {html_path}")
        
        # 3. アイキャッチ画像をアップロード
        thumbnail_id = None
        if thumbnail_path and os.path.exists(thumbnail_path):
            thumbnail_id = self.upload_thumbnail(thumbnail_path, philosopher)
        
        # 4. WordPressに投稿
        print("\n4. WordPressに投稿中...")
        
        # カテゴリーIDを取得
        category_id = self.wp_api.get_category_id('philosophy')
        
        # 投稿
        result = self.wp_api.create_post(
            title=article_data['title'],
            content=full_html,
            category_ids=[category_id] if category_id else None,
            featured_media_id=thumbnail_id,
            status=status
        )
        
        if result:
            print(f"\n{'='*60}")
            print(f"✅ 投稿成功!")
            print(f"   URL: {WP_SITE_URL}/?p={result['id']}")
            print(f"   ステータス: {status}")
            print(f"   タイトル: {article_data['title']}")
            if thumbnail_id:
                print(f"   アイキャッチ: 設定済み")
            print(f"{'='*60}\n")
            
            return {
                'success': True,
                'post_id': result['id'],
                'url': result.get('link', f"{WP_SITE_URL}/?p={result['id']}"),
                'title': article_data['title'],
                'meta_description': article_data['meta_description'],
                'target_keyword': article_data.get('target_keyword'),
                'thumbnail_id': thumbnail_id
            }
        else:
            print("❌ 投稿に失敗しました")
            return {'success': False, 'error': '投稿失敗'}


def main():
    """メイン関数"""
    bot = PhilosophyBotComplete()
    
    # ニーチェの記事を投稿（生成済みのアイキャッチ画像を使用）
    result = bot.create_and_post_article(
        philosopher="ニーチェ",
        famous_quote="神は死んだ",
        theme="虚無を超えて生きる力",
        target_keyword="人生 意味 わからない",
        overview_items=[
            "なぜ現代人は「生きる意味」を見失ってしまうのか",
            "ニーチェが語る「神の死」の本当の意味とは何か",
            "虚無の先にある「超人」という生き方とは"
        ],
        status='draft',
        thumbnail_path='/home/ubuntu/philosophy_bot/output/nietzsche_thumbnail.png'
    )
    
    if result['success']:
        print("\n【SEO情報】")
        print(f"ターゲットキーワード: {result.get('target_keyword')}")
        print(f"メタディスクリプション: {result.get('meta_description')}")
        if result.get('thumbnail_id'):
            print(f"アイキャッチID: {result.get('thumbnail_id')}")


if __name__ == '__main__':
    main()
