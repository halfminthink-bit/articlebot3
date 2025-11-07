#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
哲学記事生成クラス
"""

import os
from openai import OpenAI


class ArticleGenerator:
    """Claude APIを使って哲学記事を生成するクラス"""
    
    def __init__(self, api_key: str = None):
        """
        初期化
        
        Args:
            api_key: OpenAI APIキー（省略時は環境変数から取得）
        """
        # OpenAI clientは環境変数から自動的にAPIキーを取得
        self.client = OpenAI()
    
    def generate_article(
        self,
        philosopher: str,
        famous_quote: str,
        theme: str
    ) -> dict:
        """
        哲学記事を生成
        
        Args:
            philosopher: 哲学者名（例: "ショーペンハウアー"）
            famous_quote: 有名な言葉（例: "人生は振り子"）
            theme: 記事のテーマ（例: "満たされない心の正体"）
            
        Returns:
            {
                'title': 記事タイトル,
                'html_content': HTML形式の記事本文,
                'philosopher_name': 哲学者のフルネーム,
                'philosopher_country': 国籍,
                'philosopher_points': 特徴のリスト
            }
        """
        
        prompt = f"""あなたは哲学記事のライターです。以下の情報を基に、「半分思考」サイトのスタイルで記事を作成してください。

【哲学者】{philosopher}
【有名な言葉】{famous_quote}
【テーマ】{theme}

【記事の要件】
1. タイトル形式: {philosopher}｜「{famous_quote}」から考える{theme}
2. 構成:
   - 導入部: 共感を呼ぶ問いかけで始める
   - 哲学者プロフィール情報（フルネーム、国籍、3つの特徴）
   - 「この記事で分かること」3項目
   - 著者の体験談
   - 第1章: 問題提起（具体例、心理学との関連）
   - 第2章: 哲学的解説（Coffee Break含む）
   - 第3章: 実践的アドバイス
   - 終章: まとめと希望のメッセージ

3. 文体:
   - 短い段落（1-3行）
   - 語りかけるような優しいトーン
   - 「ありませんか？」「そう思いませんか？」などの問いかけ
   - 強調したい部分は<span class="emphasis">で囲む
   - 引用は<div class="quote-box">で囲む

4. HTMLタグ使用:
   - 大見出し: <h2 class="section-title">
   - 小見出し: <h3 class="section-subtitle">
   - 強調: <span class="emphasis">
   - 引用: <div class="quote-box">

【出力形式】
以下のJSON形式で出力してください:
{{
  "title": "記事タイトル",
  "philosopher_full_name": "哲学者のフルネーム",
  "philosopher_country": "国籍",
  "philosopher_points": ["特徴1", "特徴2", "特徴3"],
  "html_content": "HTML形式の記事本文（哲学者プロフィールカードと概要ボックスは除く、本文のみ）"
}}

注意: html_contentには、導入部の文章から終章までを含めてください。哲学者プロフィールカードと「この記事で分かること」ボックスは別途生成するので含めないでください。"""

        try:
            response = self.client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=8000,
                temperature=0.7
            )
            
            # レスポンスからJSONを抽出
            response_text = response.choices[0].message.content
            
            # JSONブロックを抽出（```json ... ```の形式を想定）
            import json
            import re
            
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # ```がない場合は全体をJSONとして扱う
                json_str = response_text
            
            result = json.loads(json_str)
            return result
        
        except Exception as e:
            print(f"記事生成エラー: {e}")
            return None
    
    def create_full_html(
        self,
        article_data: dict,
        overview_items: list,
        author_experience: str,
        philosopher_image_url: str = None
    ) -> str:
        """
        完全なHTML記事を生成（プロフィールカードと概要ボックスを含む）
        
        Args:
            article_data: generate_articleの戻り値
            overview_items: 「この記事で分かること」の項目リスト
            author_experience: 著者の体験談
            philosopher_image_url: 哲学者の画像URL（省略可）
            
        Returns:
            完全なHTML
        """
        # 哲学者プロフィールカード
        profile_html = f'''<div class="hist-figure-card">
        <div class="hist-figure-image-area">
            <div class="hist-figure-portrait-placeholder">'''
        
        if philosopher_image_url:
            profile_html += f'<img src="{philosopher_image_url}" alt="{article_data["philosopher_full_name"]}" class="alignnone size-large" />'
        
        profile_html += f'''
            </div>
        </div>
        <div class="hist-figure-info-section">
            <div class="hist-figure-name">{article_data["philosopher_full_name"]}</div>
            <div class="hist-figure-subtitle">{article_data["philosopher_country"]}の哲学者</div>
            <ul class="hist-figure-points">'''
        
        for point in article_data["philosopher_points"]:
            profile_html += f'\n                <li>{point}</li>'
        
        profile_html += '''
            </ul>
        </div>
</div>'''
        
        # 概要ボックス
        overview_html = '''
<div class="overview">
この記事で分かること
<div class="overview-list">'''
        
        for item in overview_items:
            overview_html += f'\n<div class="overview-item">{item}</div>'
        
        overview_html += '''
</div>
</div>'''
        
        # 著者の体験談
        experience_html = f'''
{author_experience}

だから、<span class="emphasis">あなたの悩みも半分くらいにはなりますように。</span>'''
        
        # 完全なHTMLを組み立て
        full_html = article_data['html_content']
        
        # プロフィールカードを適切な位置に挿入（最初のquote-boxの後）
        full_html = full_html.replace(
            '</div>',
            f'</div>\n{profile_html}\n{overview_html}\n{experience_html}\n',
            1  # 最初の1回だけ置換
        )
        
        return full_html


if __name__ == '__main__':
    # テスト用コード
    generator = ArticleGenerator()
    article = generator.generate_article(
        philosopher="ショーペンハウアー",
        famous_quote="人生は振り子",
        theme="満たされない心の正体"
    )
    
    if article:
        print("タイトル:", article['title'])
        print("哲学者:", article['philosopher_full_name'])
        print("国籍:", article['philosopher_country'])
        print("特徴:", article['philosopher_points'])
        print("本文の長さ:", len(article['html_content']), "文字")
