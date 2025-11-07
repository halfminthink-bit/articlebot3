#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
日本一の哲学ブログを目指すための、本番用バッチ投稿スクリプト
- スラッグを英語に設定
- 投稿日時を2025年5月〜今日までランダムに分散
- 重要な部分を太字に
- 文字ベースのアイキャッチ画像付き
'''

import os
import json
import re
import random
from datetime import datetime, timedelta
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

# 投稿する哲学者リスト（大幅に拡充）
PHILOSOPHERS = [
    {
        "name": "アルベール・カミュ",
        "slug": "albert-camus-absurdism",
        "theme": "不条理な世界を生き抜く「反抗」という愛の形",
        "keywords": "不条理、シーシュポスの神話、反抗、実存主義",
    },
    {
        "name": "ジャン=ポール・サルトル",
        "slug": "jean-paul-sartre-existence-precedes-essence",
        "theme": "「実存は本質に先立つ」から学ぶ、自由と責任の哲学",
        "keywords": "実存主義、自由、アンガージュマン、他者の眼差し",
    },
    {
        "name": "イマヌエル・カント",
        "slug": "immanuel-kant-categorical-imperative",
        "theme": "「定言命法」から考える、普遍的な道徳の基準",
        "keywords": "定言命法、純粋理性批判、道徳法則、自律",
    },
    {
        "name": "アリストテレス",
        "slug": "aristotle-eudaimonia-virtue-ethics",
        "theme": "「エウダイモニア（幸福）」を実現する、徳の倫理学",
        "keywords": "エウダイモニア、中庸、徳、実践知",
    },
    {
        "name": "プラトン",
        "slug": "plato-theory-of-forms-cave-allegory",
        "theme": "「イデア論」と「洞窟の比喩」から学ぶ、真実を見抜く力",
        "keywords": "イデア論、洞窟の比喩、真実、哲人王",
    },
    {
        "name": "ルネ・デカルト",
        "slug": "rene-descartes-cogito-ergo-sum",
        "theme": "「我思う、ゆえに我あり」から始まる、確実な知識の探求",
        "keywords": "コギト、方法的懐疑、心身二元論、理性",
    },
    {
        "name": "バールーフ・デ・スピノザ",
        "slug": "baruch-spinoza-ethics-emotions",
        "theme": "感情をコントロールし、自由を手に入れる「エチカ」の知恵",
        "keywords": "エチカ、感情、理性、神即自然",
    },
    {
        "name": "ルキウス・アンナエウス・セネカ",
        "slug": "seneca-stoicism-time-management",
        "theme": "ストア哲学から学ぶ、時間の使い方と人生の意味",
        "keywords": "ストア哲学、時間、死生観、運命愛",
    },
    {
        "name": "マルクス・アウレリウス",
        "slug": "marcus-aurelius-meditations-stoicism",
        "theme": "「自省録」から学ぶ、ストレスに負けない心の作り方",
        "keywords": "自省録、ストア哲学、内的平静、自己統制",
    },
    {
        "name": "ジョン・スチュアート・ミル",
        "slug": "john-stuart-mill-utilitarianism",
        "theme": "「最大多数の最大幸福」を目指す、功利主義の倫理学",
        "keywords": "功利主義、自由論、幸福、質的功利主義",
    },
    {
        "name": "ハンナ・アーレント",
        "slug": "hannah-arendt-banality-of-evil",
        "theme": "「悪の陳腐さ」から考える、思考停止しないことの重要性",
        "keywords": "悪の陳腐さ、全体主義、思考、公共性",
    },
    {
        "name": "シモーヌ・ド・ボーヴォワール",
        "slug": "simone-de-beauvoir-second-sex",
        "theme": "「人は女に生まれるのではない、女になるのだ」から学ぶ自由",
        "keywords": "第二の性、実存主義、フェミニズム、主体性",
    },
    {
        "name": "ミシェル・フーコー",
        "slug": "michel-foucault-power-knowledge",
        "theme": "「権力と知」の関係から、社会の仕組みを見抜く",
        "keywords": "権力、知、監獄、生権力",
    },
    {
        "name": "ジル・ドゥルーズ",
        "slug": "gilles-deleuze-difference-repetition",
        "theme": "「差異と反復」から学ぶ、創造的に生きる哲学",
        "keywords": "差異、反復、リゾーム、生成変化",
    },
    {
        "name": "ジャック・デリダ",
        "slug": "jacques-derrida-deconstruction",
        "theme": "「脱構築」から学ぶ、固定観念を疑う思考法",
        "keywords": "脱構築、差延、他者、正義",
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
- 半分思考さんの文体を意識しつつ、最高の品質を目指す。

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

# --- ヘルパー関数 ---

def generate_random_date():
    '''2025年5月1日から今日までのランダムな日時を生成'''
    start_date = datetime(2025, 5, 1)
    end_date = datetime.now()
    time_between = end_date - start_date
    days_between = time_between.days
    random_days = random.randint(0, days_between)
    random_date = start_date + timedelta(days=random_days)
    
    # ランダムな時刻を追加（9:00〜21:00の間）
    random_hour = random.randint(9, 21)
    random_minute = random.randint(0, 59)
    random_date = random_date.replace(hour=random_hour, minute=random_minute)
    
    return random_date.isoformat()

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

# --- メイン処理 ---

def main():
    wp = WordPressAPI(WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD)
    thumb_gen = TextThumbnailGenerator()
    category_id = wp.get_category_id('philosophy')

    if not category_id:
        print("❌ カテゴリ「philosophy」が見つかりません。")
        return

    # 哲学者リストをシャッフル（投稿順をランダムに）
    philosophers_shuffled = PHILOSOPHERS.copy()
    random.shuffle(philosophers_shuffled)

    for philosopher in philosophers_shuffled:
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

        # 4. ランダムな投稿日時を生成
        post_date = generate_random_date()
        print(f"📅 投稿日時: {post_date}")

        # 5. WordPressへ投稿
        print(f"🚀 [{philosopher['name']}] の記事をWordPressに投稿中...")
        
        # 5a. 画像のアップロード
        thumbnail_id = None
        if image_path:
            thumbnail_id = wp.upload_media(image_path, title=f"{philosopher['name']}の哲学")
            if not thumbnail_id:
                print("⚠️  画像アップロードに失敗しましたが、記事は投稿します。")

        # 5b. 記事の投稿（公開、スラッグ指定、日時指定）
        post_title = f"{philosopher['name']} | {philosopher['theme']}"
        post_id = wp.create_post_with_slug_and_date(
            title=post_title,
            content=final_html,
            slug=philosopher['slug'],
            category_ids=[category_id],
            featured_media_id=thumbnail_id,
            post_date=post_date,
            status='publish'
        )

        if post_id and 'id' in post_id:
            print(f"✅ 投稿成功！ (公開)")
            link = post_id.get('link', f"{WP_SITE_URL}/?p={post_id['id']}")
            print(f"   URL: {link}")
        else:
            print(f"❌ 投稿に失敗しました。レスポンス: {post_id}")

if __name__ == "__main__":
    main()
