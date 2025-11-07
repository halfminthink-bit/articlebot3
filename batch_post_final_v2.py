'''
日本一の哲学ブログを目指すための、最終版バッチ投稿スクリプト
HTMLタグで記事を生成、重要な部分を太字に、文字ベースのアイキャッチ画像付き
'''

import os
import json
import re
from openai import OpenAI
from wordpress_api import WordPressAPI
from text_thumbnail_generator import TextThumbnailGenerator

# --- 設定 ---

# WordPress設定
WP_SITE_URL = 'https://halfminthinking.com'
WP_USERNAME = 'halfminthinking'
WP_APP_PASSWORD = 'iN4H IfZf gt0l Yl2M ZCrO QWyO'

# OpenAI APIクライアント
client = OpenAI()

# 投稿する哲学者リスト
PHILOSOPHERS = [
    {
        "name": "マルティン・ハイデガー",
        "theme": "「死」を見つめることで、本当の人生を取り戻す",
        "keywords": "存在と時間、死への先駆、本来性、世界内存在",
    },
    {
        "name": "エピクテトス",
        "theme": "「コントロールできること」と「できないこと」を分ける、ストア哲学の知恵",
        "keywords": "ストア哲学、自己コントロール、運命愛、内的自由",
    },
    {
        "name": "セーレン・キルケゴール",
        "theme": "不安と向き合い、本当の自分になるための「実存」の哲学",
        "keywords": "不安、実存主義、主体性、自己選択",
    },
]

# --- プロンプトテンプレート ---

ARTICLE_PROMPT_TEMPLATE = '''
あなたは、哲学を深く理解し、読者の心に響く文章を書くプロのライターです。

今回は「{philosopher_name}」についての記事を、以下のテーマとキーワードで執筆してください。

- **テーマ**: {theme}
- **キーワード**: {keywords}

【記事の方針】
- 読者の心に深く響く、詩的でありながらも分かりやすい文章。
- 難解な哲学を、具体的なストーリーや日常の例えで説明する。
- 読者が「自分のことだ」と感じられるような、共感性の高い内容。
- 記事を読んだ後、生きる勇気や新しい視点が得られるような、実用的な知恵を提供する。

【文体】
- 短い段落で構成し、リズム感を重視する。
- 語りかけるような、優しくも力強い口調。
- 読者の経験や感情に寄り添う。
- あなた（半分思考さん）の文体を意識しつつ、最高の品質を目指す。

【構成案】
1.  **導入**: 読者の悩みに寄り添う、心に響く問いかけから始める。
2.  **哲学者の紹介**: 時代背景や人柄が分かるような、短い紹介。
3.  **核心思想の解説**: テーマに沿って、哲学者の最も重要な思想を分かりやすく解説する。（2-3セクションに分けても良い）
4.  **現代への応用**: その思想が、現代を生きる私たちの生活や悩みにどう活かせるかを具体的に示す。
5.  **結論**: 装飾的なボックスは使わず、通常の文章（段落）で、読者の背中をそっと押すような、希望のあるメッセージで締めくくる。

【重要事項】
- **HTMLタグで記事を書いてください。**
- 見出しは `<h2>見出し</h2>` のように書いてください。
- 段落は `<p>段落の内容</p>` のように書いてください。
- **重要な文章や伝えたいポイントは `<strong>重要な文章</strong>` で太字にしてください。**
- 太字は適度に使い、読者の注意を引く重要な部分にのみ使用してください。
- **Markdown記法（`## `、`**太字**`など）は使わないでください。**
- 全体の文字数は3000〜4000字程度でお願いします。

それでは、あなたの最高の記事を執筆してください。
'''

HTML_TEMPLATE = '''
<div class="philosophy-article">
{article_content}
</div>
'''

# --- メイン処理 ---

def generate_article(philosopher_info):
    '''記事本文を生成する'''
    print(f"📄 [{philosopher_info['name']}] の記事を生成中...")
    prompt = ARTICLE_PROMPT_TEMPLATE.format(
        philosopher_name=philosopher_info['name'],
        theme=philosopher_info['theme'],
        keywords=philosopher_info['keywords']
    )
    
    try:
        response = client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.75
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ 記事生成中にエラーが発生しました: {e}")
        return None

def main():
    wp = WordPressAPI(WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD)
    thumb_gen = TextThumbnailGenerator()
    category_id = wp.get_category_id('philosophy')

    if not category_id:
        print("❌ カテゴリ「philosophy」が見つかりません。")
        return

    for philosopher in PHILOSOPHERS:
        print(f"\n{'='*50}")
        print(f"▶️  哲学者: {philosopher['name']}")
        print(f"{'='*50}")

        # 1. 記事本文の生成
        article_html = generate_article(philosopher)
        if not article_html:
            continue

        # 2. アイキャッチ画像の生成
        print(f"🎨 [{philosopher['name']}] のアイキャッチを生成中...")
        try:
            image_path = thumb_gen.generate_thumbnail(
                philosopher_name=philosopher['name'],
                theme=philosopher['theme']
            )
        except Exception as e:
            print(f"❌ アイキャッチ生成中にエラー: {e}")
            image_path = None

        # 3. HTMLを整形
        final_html = HTML_TEMPLATE.format(article_content=article_html)

        # 4. WordPressへ投稿
        print(f"🚀 [{philosopher['name']}] の記事をWordPressに投稿中...")
        
        # 4a. 画像のアップロード
        thumbnail_id = None
        if image_path:
            thumbnail_id = wp.upload_media(image_path, title=f"{philosopher['name']}の哲学")
            if not thumbnail_id:
                print("⚠️  画像アップロードに失敗しましたが、記事は投稿します。")

        # 4b. 記事の投稿（公開）
        post_title = f"{philosopher['name']} | {philosopher['theme']}"
        post_id = wp.create_post(
            title=post_title,
            content=final_html,
            category_ids=[category_id],
            featured_media_id=thumbnail_id,
            status='publish'  # 公開
        )

        if post_id and 'id' in post_id:
            print(f"✅ 投稿成功！ (公開)")
            link = post_id.get('link', f"{WP_SITE_URL}/?p={post_id['id']}")
            print(f"   URL: {link}") 
        else:
            print(f"❌ 投稿に失敗しました。レスポンス: {post_id}")

if __name__ == "__main__":
    main()
