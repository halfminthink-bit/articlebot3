#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
哲学記事生成クラス（改善版）
"""

import os
import json
import re
from openai import OpenAI


class ArticleGeneratorV2:
    """Gemini APIを使って哲学記事を生成するクラス（改善版）"""
    
    def __init__(self):
        """初期化"""
        self.client = OpenAI()
    
    def generate_article(
        self,
        philosopher: str,
        famous_quote: str,
        theme: str,
        overview_items: list
    ) -> dict:
        """
        哲学記事を生成
        
        Args:
            philosopher: 哲学者名（例: "ショーペンハウアー"）
            famous_quote: 有名な言葉（例: "人生は振り子"）
            theme: 記事のテーマ（例: "満たされない心の正体"）
            overview_items: 「この記事で分かること」の項目リスト
            
        Returns:
            {
                'title': 記事タイトル,
                'html_content': HTML形式の記事本文,
                'philosopher_full_name': 哲学者のフルネーム,
                'philosopher_subtitle': サブタイトル（国籍・時代）,
                'philosopher_points': 特徴のリスト,
                'section_titles': セクションタイトルのリスト
            }
        """
        
        overview_text = '\n'.join([f'- {item}' for item in overview_items])
        
        prompt = f"""あなたは「半分思考」サイトの哲学記事ライターです。以下の情報を基に、サイトのスタイルに完全に合致した記事を作成してください。

【哲学者】{philosopher}
【有名な言葉】{famous_quote}
【テーマ】{theme}

【この記事で分かること】
{overview_text}

【記事の構成】
1. 導入部
   - main-quoteで有名な言葉を提示
   - spacer
   - 共感を呼ぶ問いかけ（emphasis使用）
   - 日常的なシーン描写（1-3行の短い段落）
   - spacer
   - quote-boxで重要な引用
   - spacer
   - 哲学者の紹介文

2. 哲学者プロフィール情報（JSON形式で別途出力）

3. 本文（3-4セクション）
   - 各セクションは h2.section-title で開始
   - 具体例と心理学的知見を含める
   - emphasis, positive, negativeを適切に使用
   - quote-boxで重要な引用を挿入（前後にspacer）

4. Coffee Break（1箇所、適切な位置に）

5. 終章
   - まとめと希望のメッセージ

【HTMLタグの使用ルール】
- 大きな引用: <div class="main-quote">テキスト</div>
- 通常の引用: <div class="quote-box">テキスト</div>
- 区切り: <div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>
- 強調: <span class="emphasis">テキスト</span>
- ポジティブ: <span class="positive">テキスト</span>
- ネガティブ: <span class="negative">テキスト</span>
- 大見出し: <h2 id="s1" class="section-title">1. タイトル</h2>
- 小見出し: <h3 class="section-subtitle">タイトル</h3>
- Coffee Break: <div class="coffee-break"><h3><span class="coffee-icon">☕</span>【Coffee Break】タイトル</h3>本文</div>

【文体の特徴】
- 1-3行の短い段落で構成
- 「〜ませんか？」「〜だろう？」などの問いかけを多用
- 「〜のです」「〜なのです」という丁寧な語尾
- 読者の体験に寄り添う優しいトーン
- 具体例を豊富に使用

【重要な注意事項】
- 画像タグは含めないでください（別途挿入します）
- 目次は含めないでください（別途生成します）
- 「この記事で分かること」ボックスは含めないでください
- 哲学者プロフィールカードは含めないでください
- セクションIDは s1, s2, s3... の形式で

【出力形式】
以下のJSON形式で出力してください:
{{
  "title": "{philosopher}｜「{famous_quote}」から考える{theme}",
  "philosopher_full_name": "哲学者のフルネーム",
  "philosopher_subtitle": "国籍・時代（例: ドイツの哲学者、西暦50年-135年など）",
  "philosopher_points": ["特徴1", "特徴2", "特徴3"],
  "section_titles": ["セクション1タイトル", "セクション2タイトル", ...],
  "html_content": "HTML形式の記事本文（導入部から終章まで）"
}}

注意: html_contentには、main-quoteから始まる完全なHTMLを含めてください。"""

        try:
            response = self.client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=8000,
                temperature=0.7
            )
            
            response_text = response.choices[0].message.content
            
            # JSONブロックを抽出
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
            print(f"レスポンス: {response_text if 'response_text' in locals() else 'N/A'}")
            return None
    
    def create_full_html(
        self,
        article_data: dict,
        overview_items: list,
        philosopher_image_url: str = None
    ) -> str:
        """
        完全なHTML記事を生成
        
        Args:
            article_data: generate_articleの戻り値
            overview_items: 「この記事で分かること」の項目リスト
            philosopher_image_url: 哲学者の画像URL（省略可）
            
        Returns:
            完全なHTML
        """
        html_parts = []
        
        # 1. 導入部（article_dataのhtml_contentから抽出）
        # main-quoteから哲学者プロフィールの前まで
        content = article_data['html_content']
        
        # 哲学者プロフィールカードを挿入する位置を見つける
        # 最初のh2タグの前に挿入
        h2_match = re.search(r'<h2', content)
        if h2_match:
            insert_pos = h2_match.start()
            intro_part = content[:insert_pos]
        else:
            intro_part = content
            insert_pos = len(content)
        
        html_parts.append(intro_part)
        
        # 2. 哲学者プロフィールカード
        profile_html = '<div class="hist-figure-card">\n'
        profile_html += '    <div class="hist-figure-image-area">\n'
        profile_html += '        <div class="hist-figure-portrait-placeholder">\n'
        
        if philosopher_image_url:
            profile_html += f'            <img src="{philosopher_image_url}" alt="{article_data["philosopher_full_name"]}">\n'
        
        profile_html += '        </div>\n'
        profile_html += '    </div>\n'
        profile_html += '    <div class="hist-figure-info-section">\n'
        profile_html += f'        <div class="hist-figure-name">{article_data["philosopher_full_name"]}</div>\n'
        profile_html += f'        <div class="hist-figure-subtitle">{article_data["philosopher_subtitle"]}</div>\n'
        profile_html += '        <ul class="hist-figure-points">\n'
        
        for point in article_data["philosopher_points"]:
            profile_html += f'            <li>{point}</li>\n'
        
        profile_html += '        </ul>\n'
        profile_html += '    </div>\n'
        profile_html += '</div>\n'
        
        html_parts.append(profile_html)
        
        # 3. 「この記事で分かること」ボックス
        overview_html = '<div class="overview">\n'
        overview_html += '    <p>この記事で分かること</p>\n'
        overview_html += '    <div class="overview-list">\n'
        
        for item in overview_items:
            overview_html += f'        <div class="overview-item">{item}</div>\n'
        
        overview_html += '    </div>\n'
        overview_html += '</div>\n'
        
        html_parts.append(overview_html)
        
        # 4. 目次
        toc_html = '<div class="toc">\n'
        toc_html += '    <div class="toc-title">目次</div>\n'
        toc_html += '    <ul>\n'
        
        for i, title in enumerate(article_data.get('section_titles', []), 1):
            toc_html += f'        <li><a class="toc-link" href="#s{i}">{i}. {title}</a></li>\n'
        
        toc_html += '    </ul>\n'
        toc_html += '</div>\n'
        toc_html += '<div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>\n'
        
        html_parts.append(toc_html)
        
        # 5. 本文の残り（最初のh2から最後まで）
        remaining_content = content[insert_pos:]
        
        # セクション画像を挿入
        # 各h2タグの直後に画像を挿入
        section_num = 1
        def add_section_image(match):
            nonlocal section_num
            h2_tag = match.group(0)
            # セクション画像のプレースホルダー
            img_tag = f'\n<img class="alignnone size-large wp-image-765" src="http://halfminthinking.com/wp-content/uploads/2025/05/s{section_num}-1-1000x563.jpg" alt="セクション{section_num}" width="1000" height="563" />\n'
            section_num += 1
            return h2_tag + img_tag
        
        remaining_content = re.sub(r'<h2[^>]*>.*?</h2>', add_section_image, remaining_content)
        
        html_parts.append(remaining_content)
        
        return ''.join(html_parts)


if __name__ == '__main__':
    # テスト用コード
    generator = ArticleGeneratorV2()
    article = generator.generate_article(
        philosopher="ショーペンハウアー",
        famous_quote="人生は振り子",
        theme="満たされない心の正体",
        overview_items=[
            "なぜ目標を達成しても、すぐに虚しくなってしまうのか",
            "私たちを常に駆り立てる「満たされない心」の正体とは何か",
            "どうすれば、心の平穏を少しでも取り戻せるのか"
        ]
    )
    
    if article:
        print("タイトル:", article['title'])
        print("哲学者:", article['philosopher_full_name'])
        print("サブタイトル:", article['philosopher_subtitle'])
        print("特徴:", article['philosopher_points'])
        print("セクション:", article.get('section_titles', []))
        print("本文の長さ:", len(article['html_content']), "文字")
