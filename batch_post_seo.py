#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEO強化版 哲学記事一括投稿スクリプト
"""

import os
import sys
import time
import argparse
from article_generator_seo import ArticleGeneratorSEO
from ai_thumbnail_generator import AIThumbnailGenerator
from wordpress_api import WordPressAPI


# WordPress設定
WP_SITE_URL = 'https://halfminthinking.com'
WP_USERNAME = 'halfminthinking'
WP_APP_PASSWORD = 'iN4H IfZf gt0l Yl2M ZCrO QWyO'


# 哲学者リスト（SEO最適化版）
PHILOSOPHERS = [
    {
        "philosopher": "キルケゴール",
        "famous_quote": "不安は自由のめまい",
        "theme": "選択の重さと向き合う",
        "target_keyword": "不安 対処法",
        "overview_items": [
            "なぜ選択肢が多いほど不安になってしまうのか",
            "キルケゴールが語る「不安」の本当の意味とは",
            "不安を力に変える実存的な生き方"
        ]
    },
    {
        "philosopher": "カミュ",
        "famous_quote": "不条理",
        "theme": "意味のない世界で生きる",
        "target_keyword": "人生 意味ない",
        "overview_items": [
            "なぜ人生に意味を求めてしまうのか",
            "カミュが語る「不条理」の本当の意味",
            "意味のない世界を肯定して生きる方法"
        ]
    },
    {
        "philosopher": "ハイデガー",
        "famous_quote": "死への先駆",
        "theme": "死を意識して本当に生きる",
        "target_keyword": "死 怖い",
        "overview_items": [
            "なぜ私たちは死から目を背けてしまうのか",
            "ハイデガーが語る「本来的な生き方」とは",
            "死を意識することで得られる自由"
        ]
    },
    {
        "philosopher": "スピノザ",
        "famous_quote": "感情の奴隷",
        "theme": "感情に振り回されない生き方",
        "target_keyword": "感情 コントロール",
        "overview_items": [
            "なぜ私たちは感情に振り回されてしまうのか",
            "スピノザが語る「感情の奴隷」からの解放",
            "理性によって感情を理解し、自由になる方法"
        ]
    },
    {
        "philosopher": "セネカ",
        "famous_quote": "人生は短くない",
        "theme": "時間の使い方",
        "target_keyword": "時間 無駄",
        "overview_items": [
            "なぜ私たちは時間を無駄にしてしまうのか",
            "セネカが語る「人生は短くない」の本当の意味",
            "時間を取り戻し、豊かに生きる方法"
        ]
    },
    {
        "philosopher": "マルクス・アウレリウス",
        "famous_quote": "自分でコントロールできること",
        "theme": "ストア哲学の実践",
        "target_keyword": "ストレス 対処法",
        "overview_items": [
            "なぜ私たちはコントロールできないことに悩むのか",
            "マルクス・アウレリウスが実践したストア哲学",
            "心の平穏を取り戻す二分法の思考"
        ]
    }
]


class BatchPhilosophyBot:
    """SEO強化版 哲学記事一括投稿ボット"""
    
    def __init__(self, generate_thumbnails=True):
        """
        初期化
        
        Args:
            generate_thumbnails: AI画像生成でアイキャッチを作成するか
        """
        self.article_generator = ArticleGeneratorSEO()
        self.thumbnail_generator = AIThumbnailGenerator()
        self.wp_api = WordPressAPI(WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD)
        self.output_dir = '/home/ubuntu/philosophy_bot/output'
        self.generate_thumbnails = generate_thumbnails
        os.makedirs(self.output_dir, exist_ok=True)
    
    def process_philosopher(
        self,
        philosopher_data: dict,
        status: str = 'draft'
    ) -> dict:
        """
        1人の哲学者の記事を生成・投稿
        
        Args:
            philosopher_data: 哲学者データ
            status: 投稿ステータス
            
        Returns:
            投稿結果
        """
        philosopher = philosopher_data['philosopher']
        
        print(f"\n{'='*60}")
        print(f"記事生成開始: {philosopher}")
        print(f"{'='*60}\n")
        
        # 1. 記事生成
        print("1. 記事を生成中...")
        article_data = self.article_generator.generate_article(
            philosopher=philosopher,
            famous_quote=philosopher_data['famous_quote'],
            theme=philosopher_data['theme'],
            overview_items=philosopher_data['overview_items'],
            target_keyword=philosopher_data.get('target_keyword')
        )
        
        if not article_data:
            return {'success': False, 'philosopher': philosopher, 'error': '記事生成失敗'}
        
        print(f"✅ 記事生成完了: {article_data['title']}")
        
        # 2. HTMLを生成
        print("2. HTMLを構築中...")
        full_html = self.article_generator.create_full_html(
            article_data=article_data,
            overview_items=philosopher_data['overview_items']
        )
        
        # 3. アイキャッチ画像を生成（オプション）
        thumbnail_id = None
        if self.generate_thumbnails:
            print("3. AI画像生成でアイキャッチを作成中...")
            print("   注意: この機能を使うには手動で generate_image を実行してください")
            print("   スキップして投稿を続行します")
        
        # 4. WordPressに投稿
        print("4. WordPressに投稿中...")
        category_id = self.wp_api.get_category_id('philosophy')
        
        result = self.wp_api.create_post(
            title=article_data['title'],
            content=full_html,
            category_ids=[category_id] if category_id else None,
            featured_media_id=thumbnail_id,
            status=status
        )
        
        if result:
            print(f"✅ 投稿成功: {WP_SITE_URL}/?p={result['id']}\n")
            return {
                'success': True,
                'philosopher': philosopher,
                'post_id': result['id'],
                'url': result.get('link', f"{WP_SITE_URL}/?p={result['id']}"),
                'title': article_data['title'],
                'target_keyword': article_data.get('target_keyword')
            }
        else:
            return {'success': False, 'philosopher': philosopher, 'error': '投稿失敗'}
    
    def batch_process(
        self,
        philosophers: list = None,
        status: str = 'draft',
        delay: int = 5
    ) -> list:
        """
        複数の哲学者の記事を一括処理
        
        Args:
            philosophers: 哲学者データのリスト（省略時はデフォルト）
            status: 投稿ステータス
            delay: 各投稿間の待機時間（秒）
            
        Returns:
            投稿結果のリスト
        """
        if philosophers is None:
            philosophers = PHILOSOPHERS
        
        results = []
        total = len(philosophers)
        
        print(f"\n{'='*60}")
        print(f"一括投稿開始: {total}記事")
        print(f"ステータス: {status}")
        print(f"{'='*60}\n")
        
        for i, philosopher_data in enumerate(philosophers, 1):
            print(f"\n[{i}/{total}] {philosopher_data['philosopher']} を処理中...")
            
            result = self.process_philosopher(philosopher_data, status)
            results.append(result)
            
            # 次の投稿まで待機（API制限対策）
            if i < total:
                print(f"\n{delay}秒待機中...")
                time.sleep(delay)
        
        # 結果サマリー
        print(f"\n{'='*60}")
        print("一括投稿完了")
        print(f"{'='*60}\n")
        
        success_count = sum(1 for r in results if r['success'])
        print(f"成功: {success_count}/{total}")
        
        if success_count > 0:
            print("\n【投稿された記事】")
            for r in results:
                if r['success']:
                    print(f"  - {r['philosopher']}: {r['url']}")
                    print(f"    キーワード: {r.get('target_keyword', 'なし')}")
        
        failed_count = total - success_count
        if failed_count > 0:
            print(f"\n【失敗した記事】")
            for r in results:
                if not r['success']:
                    print(f"  - {r['philosopher']}: {r.get('error', '不明なエラー')}")
        
        return results


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='SEO強化版 哲学記事一括投稿')
    parser.add_argument(
        '--publish',
        action='store_true',
        help='公開状態で投稿（デフォルトは下書き）'
    )
    parser.add_argument(
        '--thumbnails',
        action='store_true',
        help='AI画像生成でアイキャッチを作成'
    )
    parser.add_argument(
        '--delay',
        type=int,
        default=5,
        help='各投稿間の待機時間（秒、デフォルト: 5）'
    )
    
    args = parser.parse_args()
    
    status = 'publish' if args.publish else 'draft'
    
    bot = BatchPhilosophyBot(generate_thumbnails=args.thumbnails)
    results = bot.batch_process(
        philosophers=PHILOSOPHERS,
        status=status,
        delay=args.delay
    )
    
    # 終了コード
    success_count = sum(1 for r in results if r['success'])
    sys.exit(0 if success_count == len(results) else 1)


if __name__ == '__main__':
    main()
