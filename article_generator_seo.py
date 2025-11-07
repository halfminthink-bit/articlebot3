#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEO最適化された哲学記事生成クラス
"""

import os
import json
import re
from openai import OpenAI


class ArticleGeneratorSEO:
    """SEO最適化されたGemini APIを使った哲学記事生成クラス"""
    
    def __init__(self):
        """初期化"""
        self.client = OpenAI()
        
        # 内部リンク用の哲学者マッピング
        self.philosopher_relations = {
            "ショーペンハウアー": {
                "related": ["ニーチェ", "仏教哲学"],
                "theme": "厭世主義、意志"
            },
            "ニーチェ": {
                "related": ["ショーペンハウアー", "キルケゴール"],
                "theme": "超人、永劫回帰"
            },
            "キルケゴール": {
                "related": ["ニーチェ", "ハイデガー"],
                "theme": "実存、不安"
            },
            "カミュ": {
                "related": ["サルトル", "キルケゴール"],
                "theme": "不条理、反抗"
            },
            "ハイデガー": {
                "related": ["キルケゴール", "サルトル"],
                "theme": "存在、死"
            },
            "エピクテトス": {
                "related": ["マルクス・アウレリウス", "セネカ"],
                "theme": "ストア哲学、自由"
            },
            "セネカ": {
                "related": ["エピクテトス", "マルクス・アウレリウス"],
                "theme": "ストア哲学、時間"
            },
            "スピノザ": {
                "related": ["デカルト", "ストア哲学"],
                "theme": "感情、理性"
            },
            "サルトル": {
                "related": ["カミュ", "ハイデガー"],
                "theme": "実存主義、自由"
            },
            "カント": {
                "related": ["エピクテトス", "デカルト"],
                "theme": "自律、道徳"
            }
        }
        
        # 信頼できる外部リンク
        self.external_links = {
            "wikipedia": "https://ja.wikipedia.org/wiki/",
            "stanford": "https://plato.stanford.edu/entries/",
            "iep": "https://iep.utm.edu/"
        }
    
    def generate_seo_title(
        self,
        philosopher: str,
        famous_quote: str,
        theme: str,
        target_keyword: str = None
    ) -> str:
        """
        SEO最適化されたタイトルを生成
        
        Args:
            philosopher: 哲学者名
            famous_quote: 有名な言葉
            theme: テーマ
            target_keyword: ターゲットキーワード（省略可）
            
        Returns:
            SEO最適化されたタイトル
        """
        if target_keyword:
            # キーワード優先型
            return f"{target_keyword}とは？{philosopher}の「{famous_quote}」で解く{theme}"
        else:
            # 疑問形型
            return f"【{theme}】{philosopher}が教える「{famous_quote}」の哲学"
    
    def generate_meta_description(
        self,
        philosopher: str,
        theme: str,
        overview_items: list
    ) -> str:
        """
        メタディスクリプションを生成
        
        Args:
            philosopher: 哲学者名
            theme: テーマ
            overview_items: 記事で分かることのリスト
            
        Returns:
            メタディスクリプション（120文字以内）
        """
        first_item = overview_items[0] if overview_items else theme
        desc = f"{first_item}？{philosopher}の哲学から{theme}を解説。"
        
        # 120文字以内に収める
        if len(desc) > 120:
            desc = desc[:117] + "..."
        
        return desc
    
    def generate_article(
        self,
        philosopher: str,
        famous_quote: str,
        theme: str,
        overview_items: list,
        target_keyword: str = None,
        related_articles: list = None
    ) -> dict:
        """
        SEO最適化された哲学記事を生成
        
        Args:
            philosopher: 哲学者名
            famous_quote: 有名な言葉
            theme: テーマ
            overview_items: 「この記事で分かること」の項目リスト
            target_keyword: ターゲットキーワード（省略可）
            related_articles: 関連記事のリスト（省略可）
            
        Returns:
            記事データの辞書
        """
        
        # SEOタイトル生成
        seo_title = self.generate_seo_title(
            philosopher, famous_quote, theme, target_keyword
        )
        
        # メタディスクリプション生成
        meta_description = self.generate_meta_description(
            philosopher, theme, overview_items
        )
        
        # 関連哲学者を取得
        related_philosophers = self.philosopher_relations.get(
            philosopher, {}
        ).get("related", [])
        
        overview_text = '\n'.join([f'- {item}' for item in overview_items])
        related_text = '\n'.join([f'- {p}' for p in related_philosophers])
        
        prompt = f"""あなたは日本一の哲学ブログ「半分思考」のSEOライターです。以下の情報を基に、SEO最適化された記事を作成してください。

【哲学者】{philosopher}
【有名な言葉】{famous_quote}
【テーマ】{theme}
【ターゲットキーワード】{target_keyword or theme}

【この記事で分かること】
{overview_text}

【関連する哲学者】（内部リンク用）
{related_text}

【SEO要件】
1. ターゲットキーワードを自然に本文に含める（3-5回）
2. 見出しにキーワードを含める
3. 読者の悩みに寄り添う文体
4. 具体例を豊富に使用
5. 検索行動の「終点」となる内容

【記事の構成】
1. 導入部
   - main-quoteで有名な言葉を提示
   - spacer
   - 読者の悩みに共感する問いかけ（emphasis使用）
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
   - ターゲットキーワードを自然に含める

4. Coffee Break（1箇所、関連哲学者を紹介）
   - 関連する哲学者への内部リンクを示唆
   - 「〇〇についてはこちらの記事で詳しく解説しています」のような文言

5. 終章
   - まとめと希望のメッセージ
   - 行動喚起

【HTMLタグの使用ルール】
- 大きな引用: <div class="main-quote">テキスト</div>
- 通常の引用: <div class="quote-box">テキスト</div>
- 区切り: <div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>
- 強調: <span class="emphasis">テキスト</span>
- ポジティブ: <span class="positive">テキスト</span>
- ネガティブ: <span class="negative">テキスト</span>
- 大見出し: <h2 id="s1" class="section-title">1. タイトル</h2>
- Coffee Break: <div class="coffee-break"><h3><span class="coffee-icon">☕</span>【Coffee Break】タイトル</h3>本文</div>

【文体の特徴】
- 1-3行の短い段落で構成
- 「〜ませんか？」「〜だろう？」などの問いかけを多用
- 「〜のです」「〜なのです」という丁寧な語尾
- 読者の体験に寄り添う優しいトーン
- 具体例を豊富に使用

【重要な注意事項】
- 画像タグは含めないでください
- 目次は含めないでください
- 「この記事で分かること」ボックスは含めないでください
- 哲学者プロフィールカードは含めないでください
- セクションIDは s1, s2, s3... の形式で
- 内部リンクは {{{{INTERNAL_LINK:哲学者名}}}} の形式で示してください
- 外部リンクは {{{{EXTERNAL_LINK:URL|テキスト}}}} の形式で示してください

【出力形式】
以下のJSON形式で出力してください:
{{
  "title": "SEO最適化されたタイトル",
  "meta_description": "メタディスクリプション（120文字以内）",
  "target_keyword": "ターゲットキーワード",
  "philosopher_full_name": "哲学者のフルネーム",
  "philosopher_subtitle": "国籍・時代",
  "philosopher_points": ["特徴1", "特徴2", "特徴3"],
  "section_titles": ["セクション1タイトル", "セクション2タイトル", ...],
  "html_content": "HTML形式の記事本文",
  "internal_links": [
    {{"philosopher": "関連哲学者名", "context": "リンクする文脈"}}
  ],
  "external_links": [
    {{"url": "URL", "text": "リンクテキスト", "context": "リンクする文脈"}}
  ]
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
            json_match = re.search(r'```json\s*({.*?})\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # マークダウンブロックがない場合、最初の { から最後の } までを抽出
                start = response_text.find('{')
                end = response_text.rfind('}')
                if start != -1 and end != -1:
                    json_str = response_text[start:end+1]
                else:
                    json_str = response_text
            
            result = json.loads(json_str)
            
            # SEOタイトルとメタディスクリプションを追加
            if 'title' not in result:
                result['title'] = seo_title
            if 'meta_description' not in result:
                result['meta_description'] = meta_description
            
            return result
        
        except Exception as e:
            print(f"記事生成エラー: {e}")
            print(f"レスポンス: {response_text if 'response_text' in locals() else 'N/A'}")
            return None
    
    def process_internal_links(
        self,
        html_content: str,
        site_url: str = "https://halfminthinking.com"
    ) -> str:
        """
        内部リンクプレースホルダーを実際のリンクに変換
        
        Args:
            html_content: HTML本文
            site_url: サイトURL
            
        Returns:
            リンク処理済みHTML
        """
        # {{INTERNAL_LINK:哲学者名}} を実際のリンクに変換
        def replace_internal_link(match):
            philosopher = match.group(1)
            # URLスラッグを生成（簡易版）
            slug = philosopher.lower().replace(" ", "-")
            return f'<a href="{site_url}/{slug}/" target="_blank">{philosopher}の記事</a>'
        
        html_content = re.sub(
            r'\{\{INTERNAL_LINK:(.*?)\}\}',
            replace_internal_link,
            html_content
        )
        
        return html_content
    
    def process_external_links(self, html_content: str) -> str:
        """
        外部リンクプレースホルダーを実際のリンクに変換
        
        Args:
            html_content: HTML本文
            
        Returns:
            リンク処理済みHTML
        """
        # {{EXTERNAL_LINK:URL|テキスト}} を実際のリンクに変換
        def replace_external_link(match):
            url = match.group(1)
            text = match.group(2)
            return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{text}</a>'
        
        html_content = re.sub(
            r'\{\{EXTERNAL_LINK:(.*?)\|(.*?)\}\}',
            replace_external_link,
            html_content
        )
        
        return html_content
    
    def create_full_html(
        self,
        article_data: dict,
        overview_items: list,
        philosopher_image_url: str = None
    ) -> str:
        """
        完全なHTML記事を生成（SEO最適化版）
        
        Args:
            article_data: generate_articleの戻り値
            overview_items: 「この記事で分かること」の項目リスト
            philosopher_image_url: 哲学者の画像URL（省略可）
            
        Returns:
            完全なHTML
        """
        html_parts = []
        
        # 1. 導入部
        content = article_data['html_content']
        
        # 内部リンク・外部リンクを処理
        content = self.process_internal_links(content)
        content = self.process_external_links(content)
        
        # 哲学者プロフィールカードを挿入する位置を見つける
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
        
        # 5. 本文の残り
        remaining_content = content[insert_pos:]
        
        # セクション画像を挿入
        section_num = 1
        def add_section_image(match):
            nonlocal section_num
            h2_tag = match.group(0)
            img_tag = f'\n<img class="alignnone size-large wp-image-765" src="http://halfminthinking.com/wp-content/uploads/2025/05/s{section_num}-1-1000x563.jpg" alt="セクション{section_num}" width="1000" height="563" />\n'
            section_num += 1
            return h2_tag + img_tag
        
        remaining_content = re.sub(r'<h2[^>]*>.*?</h2>', add_section_image, remaining_content)
        
        html_parts.append(remaining_content)
        
        return ''.join(html_parts)


if __name__ == '__main__':
    # テスト用コード
    generator = ArticleGeneratorSEO()
    article = generator.generate_article(
        philosopher="ショーペンハウアー",
        famous_quote="人生は振り子",
        theme="満たされない心の正体",
        target_keyword="人生 虚しい",
        overview_items=[
            "なぜ目標を達成しても、すぐに虚しくなってしまうのか",
            "私たちを常に駆り立てる「満たされない心」の正体とは何か",
            "どうすれば、心の平穏を少しでも取り戻せるのか"
        ]
    )
    
    if article:
        print("タイトル:", article['title'])
        print("メタディスクリプション:", article['meta_description'])
        print("ターゲットキーワード:", article.get('target_keyword'))
        print("内部リンク:", article.get('internal_links'))
        print("外部リンク:", article.get('external_links'))
