#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI画像生成を使ったアイキャッチ画像生成クラス
"""

import os
import re
from typing import Optional


class AIThumbnailGenerator:
    """AI画像生成を使ったアイキャッチ画像生成クラス"""
    
    def __init__(self):
        """初期化"""
        self.output_dir = '/home/ubuntu/philosophy_bot/output'
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 哲学者ごとのビジュアルスタイル
        self.philosopher_styles = {
            "ショーペンハウアー": {
                "mood": "melancholic, contemplative",
                "colors": "deep blues and grays",
                "symbols": "pendulum, waves, shadows"
            },
            "ニーチェ": {
                "mood": "powerful, intense, dramatic",
                "colors": "bold reds and blacks",
                "symbols": "mountain peaks, lightning, eagle"
            },
            "キルケゴール": {
                "mood": "anxious, introspective",
                "colors": "muted greens and browns",
                "symbols": "crossroads, abyss, solitary figure"
            },
            "カミュ": {
                "mood": "absurd, defiant, sunny",
                "colors": "warm yellows and Mediterranean blues",
                "symbols": "boulder, beach, sun"
            },
            "ハイデガー": {
                "mood": "mysterious, profound",
                "colors": "dark greens and earth tones",
                "symbols": "forest path, clearing, horizon"
            },
            "エピクテトス": {
                "mood": "calm, stoic, disciplined",
                "colors": "stone grays and whites",
                "symbols": "chains breaking, fortress, anchor"
            },
            "セネカ": {
                "mood": "wise, serene, timeless",
                "colors": "golden and marble white",
                "symbols": "hourglass, scroll, Roman columns"
            },
            "スピノザ": {
                "mood": "rational, harmonious",
                "colors": "balanced blues and golds",
                "symbols": "geometric patterns, lens, cosmos"
            },
            "サルトル": {
                "mood": "existential, free, urban",
                "colors": "black and white with red accents",
                "symbols": "cafe, door, empty chair"
            },
            "カント": {
                "mood": "orderly, enlightened, moral",
                "colors": "prussian blue and silver",
                "symbols": "starry sky, compass, scales"
            }
        }
    
    def generate_thumbnail_prompt(
        self,
        philosopher: str,
        title: str,
        theme: str
    ) -> str:
        """
        アイキャッチ画像生成用のプロンプトを作成
        
        Args:
            philosopher: 哲学者名
            title: 記事タイトル
            theme: テーマ
            
        Returns:
            画像生成プロンプト
        """
        style = self.philosopher_styles.get(philosopher, {
            "mood": "philosophical, thoughtful",
            "colors": "deep blues and purples",
            "symbols": "book, light, path"
        })
        
        # タイトルからキーワードを抽出
        title_clean = re.sub(r'[【】｜\[\]]', ' ', title)
        
        prompt = f"""Create a minimalist, modern blog thumbnail image for a philosophy article.

Theme: {theme}
Philosopher: {philosopher}
Article title: {title_clean}

Visual style:
- Mood: {style['mood']}
- Color palette: {style['colors']}
- Symbolic elements: {style['symbols']}

Design requirements:
- Clean, modern aesthetic with ample negative space
- Abstract or symbolic representation (NOT a portrait)
- Suitable for blog header (landscape format)
- Professional and contemplative atmosphere
- Simple geometric shapes or symbolic imagery
- Minimalist Japanese design influence
- Text-free (no text in the image)

Style: Digital illustration, flat design, minimalist, philosophical, contemplative, modern blog aesthetic"""

        return prompt
    
    def generate_thumbnail(
        self,
        philosopher: str,
        title: str,
        theme: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        アイキャッチ画像を生成
        
        Args:
            philosopher: 哲学者名
            title: 記事タイトル
            theme: テーマ
            output_path: 出力パス（省略時は自動生成）
            
        Returns:
            生成された画像のパス
        """
        if output_path is None:
            safe_name = re.sub(r'[^\w\s-]', '', philosopher).strip().replace(' ', '_')
            output_path = os.path.join(self.output_dir, f'{safe_name}_thumbnail.png')
        
        prompt = self.generate_thumbnail_prompt(philosopher, title, theme)
        
        print(f"アイキャッチ画像を生成中: {philosopher}")
        print(f"プロンプト: {prompt[:100]}...")
        
        # 注意: この関数は generate_image ツールを使って呼び出す必要があります
        # ここではパスを返すのみ
        return output_path, prompt
    
    def generate_section_image_prompt(
        self,
        philosopher: str,
        section_title: str,
        section_number: int
    ) -> str:
        """
        セクション画像生成用のプロンプトを作成
        
        Args:
            philosopher: 哲学者名
            section_title: セクションタイトル
            section_number: セクション番号
            
        Returns:
            画像生成プロンプト
        """
        style = self.philosopher_styles.get(philosopher, {
            "mood": "philosophical, thoughtful",
            "colors": "deep blues and purples",
            "symbols": "book, light, path"
        })
        
        prompt = f"""Create a minimalist section illustration for a philosophy blog article.

Section {section_number}: {section_title}
Philosopher: {philosopher}

Visual style:
- Mood: {style['mood']}
- Color palette: {style['colors']}
- Simple, abstract representation of the concept
- Minimalist design with clean lines
- Suitable for article section break
- Professional and contemplative
- Text-free

Style: Digital illustration, flat design, minimalist, philosophical"""

        return prompt


if __name__ == '__main__':
    # テスト用コード
    generator = AIThumbnailGenerator()
    
    output_path, prompt = generator.generate_thumbnail(
        philosopher="ショーペンハウアー",
        title="【満たされない心の正体】ショーペンハウアーが教える「人生は振り子」の哲学",
        theme="満たされない心の正体"
    )
    
    print(f"\n出力パス: {output_path}")
    print(f"\nプロンプト:\n{prompt}")
