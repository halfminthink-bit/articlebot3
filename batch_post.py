#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
複数哲学者の記事を一括生成・投稿するバッチスクリプト
"""

import sys
from auto_post_v2 import PhilosophyBotV2


# 哲学者リスト（記事データ）
PHILOSOPHERS = [
    {
        "philosopher": "ニーチェ",
        "famous_quote": "神は死んだ",
        "theme": "虚無を超えて生きる力",
        "overview_items": [
            "なぜ現代人は「生きる意味」を見失うのか",
            "ニーチェが語る「神の死」の本当の意味",
            "虚無の中で自分らしく生きる方法"
        ]
    },
    {
        "philosopher": "キルケゴール",
        "famous_quote": "不安は自由のめまい",
        "theme": "選択の重さと向き合う",
        "overview_items": [
            "なぜ選択肢が多いほど不安になるのか",
            "キルケゴールが見抜いた「自由の代償」",
            "不安を力に変える実存的な生き方"
        ]
    },
    {
        "philosopher": "カミュ",
        "famous_quote": "不条理",
        "theme": "意味のない世界で生きる",
        "overview_items": [
            "なぜ人生に意味を求めてしまうのか",
            "カミュが語る「不条理」の正体",
            "意味がなくても生きる価値を見出す方法"
        ]
    },
    {
        "philosopher": "ハイデガー",
        "famous_quote": "死への先駆",
        "theme": "死を意識して本当に生きる",
        "overview_items": [
            "なぜ私たちは「死」から目を背けるのか",
            "ハイデガーが語る「本来的な生き方」",
            "死を意識することで得られる自由"
        ]
    },
    {
        "philosopher": "スピノザ",
        "famous_quote": "感情の奴隷",
        "theme": "感情に振り回されない生き方",
        "overview_items": [
            "なぜ感情をコントロールできないのか",
            "スピノザが教える「感情の幾何学」",
            "理性で感情を理解し、自由になる方法"
        ]
    },
    {
        "philosopher": "セネカ",
        "famous_quote": "時間の使い方",
        "theme": "人生は短いのではなく、無駄にしている",
        "overview_items": [
            "なぜ「時間がない」と感じるのか",
            "セネカが語る「時間の浪費」の正体",
            "本当に大切なことに時間を使う方法"
        ]
    }
]


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
    
    # 投稿ステータス（draft or publish）
    status = 'draft'  # デフォルトは下書き
    
    # コマンドライン引数で公開ステータスを指定可能
    if len(sys.argv) > 1 and sys.argv[1] == '--publish':
        status = 'publish'
        print("⚠️  公開モードで実行します")
    else:
        print("📝 下書きモードで実行します（公開する場合は --publish を指定）")
    
    # 結果を記録
    results = []
    success_count = 0
    fail_count = 0
    
    print(f"\n{'='*60}")
    print(f"一括投稿開始: {len(PHILOSOPHERS)}件の記事を生成します")
    print(f"{'='*60}\n")
    
    # 各哲学者の記事を生成・投稿
    for i, data in enumerate(PHILOSOPHERS, 1):
        print(f"\n[{i}/{len(PHILOSOPHERS)}] {data['philosopher']}の記事を処理中...")
        
        try:
            result = bot.create_and_post_article(
                philosopher=data['philosopher'],
                famous_quote=data['famous_quote'],
                theme=data['theme'],
                overview_items=data['overview_items'],
                status=status
            )
            
            if result:
                results.append({
                    'philosopher': data['philosopher'],
                    'status': 'success',
                    'url': result['url']
                })
                success_count += 1
            else:
                results.append({
                    'philosopher': data['philosopher'],
                    'status': 'failed',
                    'url': None
                })
                fail_count += 1
        
        except Exception as e:
            print(f"❌ エラーが発生しました: {e}")
            results.append({
                'philosopher': data['philosopher'],
                'status': 'error',
                'url': None,
                'error': str(e)
            })
            fail_count += 1
    
    # 結果サマリーを表示
    print(f"\n{'='*60}")
    print(f"一括投稿完了")
    print(f"{'='*60}")
    print(f"成功: {success_count}件")
    print(f"失敗: {fail_count}件")
    print(f"{'='*60}\n")
    
    # 詳細結果
    print("詳細結果:")
    for result in results:
        status_icon = "✅" if result['status'] == 'success' else "❌"
        print(f"{status_icon} {result['philosopher']}: {result.get('url', '失敗')}")
    
    print()
    
    return 0 if fail_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
