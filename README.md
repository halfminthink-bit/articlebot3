# ArticleBot3

記事生成・公開の自動化ツール

## 🚀 クイックスタート

### 新規案件の作成

```bash
# 1. テンプレートをコピー
cp -r projects/_template projects/my_project

# 2. 設定を編集
vi projects/my_project/info.json
vi projects/my_project/prompts/title.txt
vi projects/my_project/prompts/outline.txt
vi projects/my_project/prompts/draft.txt

# 3. ペルソナとキーワードを配置
# projects/my_project/personas/ にペルソナファイルを配置
# projects/my_project/keywords/ にキーワードCSVを配置
```

詳細は `projects/_template/README.md` を参照してください。

### よく使うコマンド

```bash
# 記事一括生成（汎用版）
./recipes/batch_generate.sh my_project

# 記事一括生成（bank版：固定セクション付き）
./recipes/batch_generate_bank.sh

# Note公開
./recipes/note_publish.sh

# WordPress公開（half用）
./recipes/wp_publish_half.sh

# WordPress記事削除
./recipes/wp_delete.sh
```

詳細は `recipes/` ディレクトリのスクリプトを参照してください。

## 📁 プロジェクト構造

```
articlebot3/
├── recipes/              # よく使うコマンド集
├── projects/             # 案件ごとのデータ
│   ├── _template/       # 新規案件用テンプレート
│   └── bank/            # bank案件の例
├── lib/                 # 共通ライブラリ
├── data/                # データファイル（既存）
├── half_data/           # データファイル（half用）
└── schemas/             # JSONスキーマ
```

## 🔧 環境設定

### .env ファイルの設定

```bash
# LLM設定
PROVIDER=openai  # または anthropic
OPENAI_API_KEY=sk-...
CLAUDE_API_KEY=sk-ant-...

# モデル設定
MODEL_TITLE=gpt-4o
MODEL_OUTLINE=gpt-4o
MODEL_DRAFT=gpt-4o

# プロンプト設定（デフォルト）
PROMPT_DIR=projects/your_project/prompts

# スプレッドシート設定
SHEET_ID=your_sheet_id
SHEET_NAME=Articles

# Google Drive設定
GDRIVE_FOLDER_ID=your_folder_id

# 検索API
BRAVE_API_KEY=your_brave_api_key
```

## 📝 スクリプト一覧

### 記事生成

- `article_generator.py`: 汎用記事生成（単発/CSV一括）
- `article_generator_bank.py`: bank版（固定セクション挿入）

### バッチ処理

- `batch_orchestrator.py`: ペルソナ×キーワード大量生成
- `batch_orchestrator_bank.py`: bank版
- `batch_persona_sweep.py`: 固定キーワード×全ペルソナ

### 情報収集

- `bank_info_collector.py`: 銀行情報収集
- `video_info_collector.py`: YouTube動画情報抽出
- `serp_collect.py`: SERP収集

### 公開

- `document_publisher.py`: Markdown→GDoc公開
- `publish_note/`: Note公開（Selenium版）
- `publish_note_play/`: Note公開（Playwright版）
- `wordpress/`: WordPress公開

## 📦 インストール

```bash
# 依存パッケージのインストール
pip install -r requirements.txt

# Playwright（Note公開用）
playwright install
```

## 🤝 コントリビューション

プルリクエストを歓迎します。大きな変更の場合は、まずissueで議論してください。

## 📄 ライセンス

[MIT](LICENSE)
