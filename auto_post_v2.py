#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
哲学記事自動生成・投稿スクリプト（改善版）
"""

import os
import sys
from wordpress_api import WordPressAPI
from thumbnail_generator import ThumbnailGenerator
from article_generator_v2 import ArticleGeneratorV2


class PhilosophyBotV2:
    """記事生成から投稿までを統括するクラス（改善版）"""
    
    def __init__(
        self,
        wp_site_url: str,
        wp_username: str,
        wp_app_password: str,
        pptx_template_path: str
    ):
        """
        初期化
        
        Args:
            wp_site_url: WordPressサイトURL
            wp_username: WordPressユーザー名
            wp_app_password: アプリケーションパスワード
            pptx_template_path: PPTXテンプレートのパス
        """
        self.wp = WordPressAPI(wp_site_url, wp_username, wp_app_password)
        self.thumbnail_gen = ThumbnailGenerator(pptx_template_path)
        self.article_gen = ArticleGeneratorV2()
        
        # 作業ディレクトリ
        self.work_dir = '/home/ubuntu/philosophy_bot/output'
        os.makedirs(self.work_dir, exist_ok=True)
    
    def create_and_post_article(
        self,
        philosopher: str,
        famous_quote: str,
        theme: str,
        overview_items: list,
        philosopher_image_url: str = None,
        status: str = 'draft'
    ) -> dict:
        """
        記事を生成してWordPressに投稿
        
        Args:
            philosopher: 哲学者名
            famous_quote: 有名な言葉
            theme: テーマ
            overview_items: 「この記事で分かること」の項目リスト
            philosopher_image_url: 哲学者の画像URL
            status: 投稿ステータス（'draft' or 'publish'）
            
        Returns:
            投稿結果の辞書
        """
        print(f"\n{'='*60}")
        print(f"記事生成開始: {philosopher}")
        print(f"{'='*60}\n")
        
        # 1. 記事本文を生成
        print("1. Gemini APIで記事本文を生成中...")
        article_data = self.article_gen.generate_article(
            philosopher=philosopher,
            famous_quote=famous_quote,
            theme=theme,
            overview_items=overview_items
        )
        
        if not article_data:
            print("❌ 記事生成に失敗しました")
            return None
        
        print(f"✅ 記事生成完了: {article_data['title']}")
        
        # 2. 完全なHTMLを生成
        print("\n2. 完全なHTMLを生成中...")
        full_html = self.article_gen.create_full_html(
            article_data=article_data,
            overview_items=overview_items,
            philosopher_image_url=philosopher_image_url
        )
        print(f"✅ HTML生成完了（{len(full_html)}文字）")
        
        # デバッグ用: HTMLをファイルに保存
        debug_html_path = os.path.join(self.work_dir, f"{philosopher}_article.html")
        with open(debug_html_path, 'w', encoding='utf-8') as f:
            f.write(full_html)
        print(f"   デバッグ用HTMLを保存: {debug_html_path}")
        
        # 3. アイキャッチ画像を生成
        print("\n3. アイキャッチ画像を生成中...")
        thumbnail_path = os.path.join(
            self.work_dir,
            f"{philosopher}_thumbnail.png"
        )
        
        success = self.thumbnail_gen.create_thumbnail(
            title=article_data['title'],
            output_path=thumbnail_path
        )
        
        if not success:
            print("⚠️  アイキャッチ画像の生成に失敗しました（投稿は続行）")
            thumbnail_path = None
        else:
            print(f"✅ アイキャッチ画像生成完了: {thumbnail_path}")
        
        # 4. アイキャッチ画像をアップロード
        featured_media_id = None
        if thumbnail_path and os.path.exists(thumbnail_path):
            print("\n4. アイキャッチ画像をWordPressにアップロード中...")
            featured_media_id = self.wp.upload_media(
                image_path=thumbnail_path,
                title=article_data['title']
            )
            
            if featured_media_id:
                print(f"✅ アイキャッチ画像アップロード完了（ID: {featured_media_id}）")
            else:
                print("⚠️  アイキャッチ画像のアップロードに失敗しました")
        
        # 5. カテゴリーIDを取得
        print("\n5. カテゴリーIDを取得中...")
        category_id = self.wp.get_category_id('philosophy')
        if category_id:
            print(f"✅ カテゴリーID取得完了: {category_id}")
        else:
            print("⚠️  カテゴリーIDの取得に失敗しました")
        
        # 6. タグを作成/取得
        print("\n6. タグを作成/取得中...")
        tag_id = self.wp.get_or_create_tag(philosopher)
        tag_ids = [tag_id] if tag_id else []
        if tag_id:
            print(f"✅ タグID取得完了: {tag_id}")
        
        # 7. 記事を投稿
        print(f"\n7. WordPressに記事を投稿中（ステータス: {status}）...")
        post = self.wp.create_post(
            title=article_data['title'],
            content=full_html,
            category_ids=[category_id] if category_id else None,
            tags=tag_ids,
            featured_media_id=featured_media_id,
            status=status
        )
        
        if post:
            print(f"\n{'='*60}")
            print(f"✅ 投稿完了！")
            print(f"{'='*60}")
            print(f"タイトル: {post['title']['rendered']}")
            print(f"URL: {post['link']}")
            print(f"ステータス: {post['status']}")
            print(f"{'='*60}\n")
            
            return {
                'success': True,
                'post_id': post['id'],
                'url': post['link'],
                'title': post['title']['rendered']
            }
        else:
            print("\n❌ 投稿に失敗しました")
            return None


def main():
    """メイン関数"""
    
    # 設定
    WP_SITE_URL = 'https://halfminthinking.com'
    WP_USERNAME = 'halfminthinking'
    WP_APP_PASSWORD = 'iN4H IfZf gt0l Yl2M ZCrO QWyO'
    PPTX_TEMPLATE = '/home/ubuntu/upload/ブルーシンプル資料noteアイキャッチ.pptx'
    
    # Botを初期化
    bot = PhilosophyBotV2(
        wp_site_url=WP_SITE_URL,
        wp_username=WP_USERNAME,
        wp_app_password=WP_APP_PASSWORD,
        pptx_template_path=PPTX_TEMPLATE
    )
    
    # テスト投稿: ショーペンハウアー（改善版）
    result = bot.create_and_post_article(
        philosopher="ショーペンハウアー",
        famous_quote="人生は振り子",
        theme="満たされない心の正体",
        overview_items=[
            "なぜ目標を達成しても、すぐに虚しくなってしまうのか",
            "私たちを常に駆り立てる「満たされない心」の正体とは何か",
            "どうすれば、心の平穏を少しでも取り戻せるのか"
        ],
        status='draft'  # まずは下書きとして投稿
    )
    
    if result:
        print("\n✨ すべての処理が正常に完了しました！")
        print(f"\n記事を確認: {result['url']}")
        return 0
    else:
        print("\n⚠️  処理中にエラーが発生しました")
        return 1


if __name__ == '__main__':
    sys.exit(main())
