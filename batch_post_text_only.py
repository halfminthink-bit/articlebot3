'''
日本一の哲学ブログを目指すための、最終版バッチ投稿スクリプト（テキストオンリー版）
'''

import os
import json
import re
from openai import OpenAI
from wordpress_api import WordPressAPI

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
        "name": "セーレン・キルケゴール",
        "theme": "不安と向き合い、本当の自分になるための「実存」の哲学",
        "keywords": "不安、実存主義、主体性、自己選択",
    },
    {
        "name": "ハンナ・アーレント",
        "theme": "「悪の陳腐さ」から考える、思考停止しないことの重要性",
        "keywords": "悪の陳腐さ、思考、公共性、活動",
    },
    {
        "name": "シモーヌ・ド・ボーヴォワール",
        "theme": "「人は女に生まれるのではない、女になるのだ」から学ぶ、自分を定義する自由",
        "keywords": "第二の性、ジェンダー、自由、自己創造",
    }
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
- **HTMLタグは一切含めないでください。** プレーンテキストのみでお願いします。
- 各セクションの見出しは `## ` で始めてください。
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

def format_html(article_text):
    '''MarkdownをHTMLに変換する'''
    # 見出しをH2タグに変換
    html_content = re.sub(r"^##\s*(.*)", r'<h2 class="section-header">\1</h2>', article_text, flags=re.MULTILINE)
    # 段落をPタグに変換
    # 見出しタグで始まらない、空でない行を段落として扱う
    lines = html_content.split('\n')
    p_tags = []
    for line in lines:
        stripped_line = line.strip()
        if stripped_line and not stripped_line.startswith('<h2'):
            p_tags.append(f'<p>{stripped_line}</p>')
        elif stripped_line.startswith('<h2'):
            p_tags.append(line) # h2タグはそのまま追加
    html_content = '\n'.join(p_tags)
    return HTML_TEMPLATE.format(article_content=html_content)

def main():
    wp = WordPressAPI(WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD)
    category_id = wp.get_category_id('philosophy')

    if not category_id:
        print("❌ カテゴリ「philosophy」が見つかりません。")
        return

    for philosopher in PHILOSOPHERS:
        print(f"\n{'='*50}")
        print(f"▶️  哲学者: {philosopher['name']}")
        print(f"{'='*50}")

        # 1. 記事本文の生成
        article_md = generate_article(philosopher)
        if not article_md:
            continue

        # 2. HTMLの整形
        final_html = format_html(article_md)

        # 3. WordPressへ投稿
        print(f"🚀 [{philosopher['name']}] の記事をWordPressに投稿中...")
        
        post_title = f"{philosopher['name']} | {philosopher['theme']}"
        post_id = wp.create_post(
            title=post_title,
            content=final_html,
            category_ids=[category_id],
            status='draft' # 安全のため下書きとして投稿
        )

        if post_id and 'id' in post_id:
            print(f"✅ 投稿成功！ (下書き)")
            print(f"   URL: {WP_SITE_URL}/?p={post_id['id']}")
        else:
            print(f"❌ 投稿に失敗しました。レスポンス: {post_id}")

if __name__ == "__main__":
    main()
