#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文字ベースのアイキャッチ画像生成クラス
シンプルでおしゃれな、タイポグラフィを主体としたデザイン
"""

import os
from PIL import Image, ImageDraw, ImageFont
import textwrap

class TextThumbnailGenerator:
    """文字ベースのアイキャッチ画像生成クラス"""
    
    def __init__(self):
        """初期化"""
        self.output_dir = '/home/ubuntu/philosophy_bot/output'
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 画像サイズ（WordPress推奨のアイキャッチサイズ）
        self.width = 1200
        self.height = 630
        
        # 哲学者ごとの配色
        self.color_schemes = {
            "セーレン・キルケゴール": {
                "bg": "#2C3E50",  # 深い青灰色
                "text": "#ECF0F1",  # 明るいグレー
                "accent": "#E74C3C"  # 赤
            },
            "ハンナ・アーレント": {
                "bg": "#34495E",  # 暗い青灰色
                "text": "#FFFFFF",  # 白
                "accent": "#F39C12"  # オレンジ
            },
            "シモーヌ・ド・ボーヴォワール": {
                "bg": "#8E44AD",  # 紫
                "text": "#FFFFFF",  # 白
                "accent": "#F1C40F"  # 黄色
            },
            "default": {
                "bg": "#1A1A2E",  # 深い紺色
                "text": "#EAEAEA",  # 明るいグレー
                "accent": "#16213E"  # 濃い青
            }
        }
    
    def generate_thumbnail(
        self,
        philosopher_name: str,
        theme: str,
        output_path: str = None
    ) -> str:
        """
        文字ベースのアイキャッチ画像を生成
        
        Args:
            philosopher_name: 哲学者名
            theme: テーマ
            output_path: 出力パス（省略時は自動生成）
            
        Returns:
            生成された画像のパス
        """
        if output_path is None:
            safe_name = philosopher_name.replace(' ', '_').replace('・', '_')
            output_path = os.path.join(self.output_dir, f'{safe_name}_thumbnail.png')
        
        # 配色を取得
        colors = self.color_schemes.get(philosopher_name, self.color_schemes["default"])
        
        # 画像を作成
        img = Image.new('RGB', (self.width, self.height), color=colors["bg"])
        draw = ImageDraw.Draw(img)
        
        # フォントを設定（システムフォントを使用）
        try:
            # 日本語フォントを試す
            font_large = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 72)
            font_medium = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 36)
        except:
            try:
                # 代替フォント
                font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
                font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
            except:
                # デフォルトフォント
                font_large = ImageFont.load_default()
                font_medium = ImageFont.load_default()
        
        # 哲学者名を描画（中央上部）
        name_bbox = draw.textbbox((0, 0), philosopher_name, font=font_large)
        name_width = name_bbox[2] - name_bbox[0]
        name_height = name_bbox[3] - name_bbox[1]
        name_x = (self.width - name_width) // 2
        name_y = 150
        
        draw.text((name_x, name_y), philosopher_name, fill=colors["text"], font=font_large)
        
        # アクセントライン（哲学者名の下）
        line_y = name_y + name_height + 30
        line_margin = 100
        draw.line([(line_margin, line_y), (self.width - line_margin, line_y)], 
                  fill=colors["accent"], width=3)
        
        # テーマを描画（中央下部、複数行対応）
        # テーマを適切な長さで折り返す
        max_chars_per_line = 24
        theme_lines = textwrap.wrap(theme, width=max_chars_per_line)
        
        theme_y_start = line_y + 60
        line_spacing = 50
        
        for i, line in enumerate(theme_lines):
            theme_bbox = draw.textbbox((0, 0), line, font=font_medium)
            theme_width = theme_bbox[2] - theme_bbox[0]
            theme_x = (self.width - theme_width) // 2
            theme_y = theme_y_start + (i * line_spacing)
            draw.text((theme_x, theme_y), line, fill=colors["text"], font=font_medium)
        
        # 画像を保存
        img.save(output_path, 'PNG')
        print(f"✅ アイキャッチ画像を生成しました: {output_path}")
        
        return output_path


if __name__ == '__main__':
    # テスト用コード
    generator = TextThumbnailGenerator()
    
    test_cases = [
        {
            "name": "セーレン・キルケゴール",
            "theme": "不安と向き合い、本当の自分になるための「実存」の哲学"
        },
        {
            "name": "ハンナ・アーレント",
            "theme": "「悪の陳腐さ」から考える、思考停止しないことの重要性"
        },
        {
            "name": "シモーヌ・ド・ボーヴォワール",
            "theme": "「人は女に生まれるのではない、女になるのだ」から学ぶ、自分を定義する自由"
        }
    ]
    
    for test in test_cases:
        output_path = generator.generate_thumbnail(
            philosopher_name=test["name"],
            theme=test["theme"]
        )
        print(f"生成完了: {output_path}\n")
