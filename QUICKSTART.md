# クイックスタートガイド

## 📝 哲学記事自動生成システムの使い方

### 🚀 すぐに始める

#### 1. 環境のセットアップ

```bash
cd /home/ubuntu/philosophy_bot
source bin/activate
```

#### 2. テスト投稿（1記事）

```bash
python auto_post_v2.py
```

これでショーペンハウアーの記事が下書きとして投稿されます。

#### 3. 複数記事を一括投稿

```bash
# 下書きとして投稿
python batch_post.py

# 公開状態で投稿
python batch_post.py --publish
```

デフォルトで以下の6人の哲学者の記事が生成されます：
- ニーチェ
- キルケゴール
- カミュ
- ハイデガー
- スピノザ
- セネカ

---

## ✏️ 新しい哲学者を追加する

### 方法1: batch_post.pyを編集

`batch_post.py`を開いて、`PHILOSOPHERS`リストに追加：

```python
{
    "philosopher": "デカルト",
    "famous_quote": "我思う、ゆえに我あり",
    "theme": "疑うことから始まる確実性",
    "overview_items": [
        "なぜ私たちは確実なものを求めるのか",
        "デカルトが見つけた「疑えないもの」",
        "思考することの意味を再発見する"
    ]
}
```

### 方法2: auto_post_v2.pyで個別投稿

`auto_post_v2.py`の`main()`関数を編集：

```python
result = bot.create_and_post_article(
    philosopher="デカルト",
    famous_quote="我思う、ゆえに我あり",
    theme="疑うことから始まる確実性",
    overview_items=[
        "なぜ私たちは確実なものを求めるのか",
        "デカルトが見つけた「疑えないもの」",
        "思考することの意味を再発見する"
    ],
    status='draft'
)
```

---

## 🎨 アイキャッチ画像のカスタマイズ

アイキャッチ画像は`ブルーシンプル資料noteアイキャッチ.pptx`から自動生成されます。

### デザインを変更したい場合

1. PPTXファイルを編集
2. `PPTX_TEMPLATE`のパスを更新

```python
PPTX_TEMPLATE = '/path/to/your/template.pptx'
```

---

## 📊 生成された記事の確認

### 出力ファイル

`philosophy_bot/output/`ディレクトリに以下が保存されます：

- `{哲学者名}_article.html` - 生成されたHTML（デバッグ用）
- `{哲学者名}_thumbnail.png` - アイキャッチ画像

### WordPress管理画面

投稿された記事は下書きとして保存されるので、WordPressの管理画面で確認・編集できます。

---

## ⚙️ 設定のカスタマイズ

### WordPress接続情報の変更

`auto_post_v2.py`と`batch_post.py`の以下を編集：

```python
WP_SITE_URL = 'https://your-site.com'
WP_USERNAME = 'your-username'
WP_APP_PASSWORD = 'xxxx xxxx xxxx xxxx'
```

### 記事の構造を変更

`article_generator_v2.py`のプロンプトを編集して、記事の構成や文体を調整できます。

---

## 🔧 トラブルシューティング

### エラー: 記事生成に失敗

**原因**: Gemini APIの制限
**解決**: 少し時間を置いてから再実行

### エラー: アイキャッチ画像が生成されない

**原因**: LibreOfficeが見つからない
**解決**: 
```bash
which libreoffice
```
で確認。なければインストール。

### エラー: 投稿に失敗

**原因**: WordPress接続情報が間違っている
**解決**: 
1. サイトURLが正しいか確認
2. アプリケーションパスワードが有効か確認
3. カテゴリー「philosophy」が存在するか確認

---

## 💡 ヒント

### 記事の品質を上げる

1. `overview_items`を具体的に書く
2. `theme`を明確にする
3. 生成後に手動で調整する

### 効率的に量産する

1. `batch_post.py`で一括生成
2. 下書きで確認
3. 問題なければ一括公開

### セクション画像を置き換える

生成されたHTMLの画像URLを実際の画像に置き換えてください：

```html
<img src="http://halfminthinking.com/wp-content/uploads/2025/05/s1-1-1000x563.jpg" ...>
```

---

## 📚 さらに詳しく

詳細なドキュメントは`README.md`を参照してください。

---

## 🎯 よくある使い方

### パターン1: 毎週1記事投稿

```bash
# 1. 哲学者を1人選ぶ
# 2. auto_post_v2.pyを編集
# 3. 実行
python auto_post_v2.py

# 4. WordPress管理画面で確認・調整
# 5. 公開
```

### パターン2: まとめて10記事作成

```bash
# 1. batch_post.pyに10人分追加
# 2. 一括生成（下書き）
python batch_post.py

# 3. すべて確認・調整
# 4. WordPress管理画面で一括公開
```

### パターン3: テーマ別シリーズ

同じテーマで複数の哲学者を比較する記事を作成：

```python
# 例: 「自由」をテーマに
- サルトル: 実存的自由
- エピクテトス: 内なる自由
- カント: 自律的自由
```

---

## 🎉 完成！

これであなたも哲学記事を量産できます！

質問があれば、`README.md`を確認するか、システムのコードを直接確認してください。
