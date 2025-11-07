# 哲学記事自動生成・投稿システム

「半分思考」サイト向けの哲学記事を自動生成し、WordPressに投稿するシステムです。

## 機能

- ✅ Gemini APIを使った高品質な記事生成
- ✅ サイトのHTMLスタイルに完全対応
- ✅ PPTXテンプレートから自動でアイキャッチ画像を生成
- ✅ WordPress REST APIで自動投稿
- ✅ 複数記事の一括生成・投稿

## システム構成

```
philosophy_bot/
├── wordpress_api.py          # WordPress API連携
├── thumbnail_generator.py    # アイキャッチ画像生成
├── article_generator_v2.py   # 記事生成（Gemini API）
├── auto_post_v2.py           # 単一記事投稿スクリプト
├── batch_post.py             # 一括投稿スクリプト
├── output/                   # 生成ファイルの出力先
└── README.md                 # このファイル
```

## 使い方

### 1. 環境のアクティベート

```bash
cd /home/ubuntu/philosophy_bot
source bin/activate
```

### 2. 単一記事の投稿

`auto_post_v2.py`を編集して、哲学者の情報を設定してから実行：

```bash
python auto_post_v2.py
```

### 3. 複数記事の一括投稿

#### 下書きとして投稿（デフォルト）

```bash
python batch_post.py
```

#### 公開状態で投稿

```bash
python batch_post.py --publish
```

### 4. 新しい哲学者を追加

`batch_post.py`の`PHILOSOPHERS`リストに追加：

```python
{
    "philosopher": "哲学者名",
    "famous_quote": "有名な言葉",
    "theme": "記事のテーマ",
    "overview_items": [
        "この記事で分かること1",
        "この記事で分かること2",
        "この記事で分かること3"
    ]
}
```

## 記事の構造

生成される記事は以下の構造になります：

1. **導入部**
   - main-quote（大きな引用）
   - 共感を呼ぶ問いかけ
   - 日常的なシーン描写

2. **哲学者プロフィールカード**
   - 画像（オプション）
   - フルネーム
   - 国籍・時代
   - 3つの特徴

3. **「この記事で分かること」ボックス**

4. **目次**

5. **本文（3-4セクション）**
   - 各セクションに画像
   - 具体例と心理学的知見
   - 引用ボックス

6. **Coffee Break**（1箇所）

7. **終章**

## HTMLタグの使用

- `<div class="main-quote">`: 大きな引用
- `<div class="quote-box">`: 通常の引用
- `<span class="emphasis">`: 強調（青色）
- `<span class="positive">`: ポジティブ（緑色）
- `<span class="negative">`: ネガティブ（赤色）
- `<div class="wp-block-spacer" style="height: 21px;">`: 区切り

## アイキャッチ画像

PPTXテンプレート（`ブルーシンプル資料noteアイキャッチ.pptx`）から自動生成されます。
記事タイトルが自動的に挿入されます。

## 設定変更

### WordPress接続情報

`auto_post_v2.py`と`batch_post.py`の以下の部分を編集：

```python
WP_SITE_URL = 'https://halfminthinking.com'
WP_USERNAME = 'halfminthinking'
WP_APP_PASSWORD = 'iN4H IfZf gt0l Yl2M ZCrO QWyO'
```

### PPTXテンプレート

```python
PPTX_TEMPLATE = '/home/ubuntu/upload/ブルーシンプル資料noteアイキャッチ.pptx'
```

## トラブルシューティング

### 記事生成に失敗する

- Gemini APIの制限を確認
- プロンプトが長すぎないか確認

### アイキャッチ画像が生成されない

- LibreOfficeがインストールされているか確認
- PPTXテンプレートのパスが正しいか確認

### 投稿に失敗する

- WordPress接続情報が正しいか確認
- アプリケーションパスワードが有効か確認
- カテゴリー「philosophy」が存在するか確認

## 出力ファイル

`output/`ディレクトリに以下のファイルが生成されます：

- `{哲学者名}_article.html`: 生成されたHTML（デバッグ用）
- `{哲学者名}_thumbnail.png`: アイキャッチ画像

## 注意事項

- 記事は下書きとして投稿されます（`--publish`オプションで公開可能）
- 生成された記事は必ず内容を確認してから公開してください
- APIの利用制限に注意してください
- セクション画像はプレースホルダーです（実際の画像に置き換えてください）

## 今後の改善案

- [ ] セクション画像の自動生成
- [ ] 関連記事カードの自動挿入
- [ ] Coffee Breakの内容をより充実させる
- [ ] 哲学者の画像を自動取得
- [ ] 投稿スケジューリング機能
- [ ] 記事の品質チェック機能

## ライセンス

このシステムは「半分思考」サイト専用です。
