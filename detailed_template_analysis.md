# 詳細HTMLテンプレート分析

## 記事の構造パターン（修正版）

### 1. 導入部
```html
<div class="main-quote">哲学者の有名な言葉</div>
<div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>
<span class="emphasis">共感を呼ぶ問いかけ</span>

日常的なシーン描写（短い段落）

<span class="emphasis">強調したいメッセージ</span>
<div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>
<div class="quote-box">重要な引用</div>
<div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>
```

### 2. 哲学者プロフィールカード
```html
<div class="hist-figure-card">
    <div class="hist-figure-image-area">
        <div class="hist-figure-portrait-placeholder">
            <img src="画像URL" alt="哲学者名">
        </div>
    </div>
    <div class="hist-figure-info-section">
        <div class="hist-figure-name">哲学者のフルネーム</div>
        <div class="hist-figure-subtitle">国籍・時代</div>
        <ul class="hist-figure-points">
            <li>特徴1</li>
            <li>特徴2</li>
            <li>特徴3</li>
        </ul>
    </div>
</div>
```

### 3. 目次（この記事で分かることの後）
```html
<div class="toc">
    <div class="toc-title">目次</div>
    <ul>
        <li><a class="toc-link" href="#s1">1. セクション1タイトル</a></li>
        <li><a class="toc-link" href="#s2">2. セクション2タイトル</a></li>
        ...
    </ul>
</div>
```

### 4. 「この記事で分かること」ボックス（目次の前）
```html
<div class="overview">
    <p>この記事で分かること</p>
    <div class="overview-list">
        <div class="overview-item">項目1</div>
        <div class="overview-item">項目2</div>
        <div class="overview-item">項目3</div>
    </div>
</div>
```

### 5. 本文セクション
```html
<h2 id="s1" class="section-title">1. セクションタイトル</h2>
<img class="alignnone size-large wp-image-XXX" src="画像URL" alt="セクション1" width="1000" height="563" />

本文（短い段落で構成）

<span class="emphasis">強調したいテキスト</span>
<span class="positive">ポジティブな内容</span>
<span class="negative">ネガティブな内容</span>

<div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>
<div class="quote-box">引用文</div>
<div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>
```

### 6. Coffee Break
```html
<div class="coffee-break">
    <h3><span class="coffee-icon">☕</span>【Coffee Break】タイトル</h3>
    本文
</div>
```

### 7. 関連記事カード
```html
<section class="recommended-articles-section" aria-labelledby="recommended-heading">
    <div class="recommended-grid-container">
        <div class="recommended-grid-item" data-category="relationships">
            <a class="custom-blog-card" href="URL" target="_blank">
                <span class="card-image">
                    <img src="画像URL" alt="記事の画像" />
                </span>
                <span class="card-title">
                    記事タイトル
                </span>
            </a>
        </div>
    </div>
</section>
```

## 重要な修正点

1. **「この記事で分かること」の位置**: 
   - ❌ 旧: 哲学者プロフィールの後
   - ✅ 新: 哲学者プロフィールの後、目次の前

2. **main-quoteの使用**:
   - 導入部の最初に大きな引用として使用
   - quote-boxとは別物

3. **spacerの使用**:
   - 引用の前後に必ず入れる
   - `<div class="wp-block-spacer" style="height: 21px;" aria-hidden="true"></div>`

4. **強調の種類**:
   - `emphasis`: 通常の強調（青色）
   - `positive`: ポジティブな内容（緑色）
   - `negative`: ネガティブな内容（赤色）

5. **画像の配置**:
   - 各セクションの冒頭に必ず配置
   - クラス: `alignnone size-large wp-image-XXX`
   - サイズ: width="1000" height="563"

## 正しい記事構成順序

1. main-quote（大きな引用）
2. spacer
3. 導入部の文章（emphasis使用）
4. spacer
5. quote-box
6. spacer
7. 哲学者プロフィールカード
8. **「この記事で分かること」ボックス** ← 重要！
9. 目次
10. spacer
11. 本文セクション1（h2 + 画像 + 本文）
12. 本文セクション2
13. Coffee Break（適宜）
14. 本文セクション3
15. 関連記事カード（適宜）
16. 終章

## 文体の特徴

- 1〜3行の短い段落
- 「〜ませんか？」「〜だろう？」などの問いかけ
- 「〜のです」「〜なのです」という丁寧な語尾
- 具体例を豊富に使用
- 読者の体験に寄り添う語り口
