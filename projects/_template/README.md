# 新規案件の始め方

## 1. このテンプレートをコピー
```bash
cp -r projects/_template projects/your_project_name
```

## 2. 設定ファイルを編集

### info.json
- `primary_keyword`: メインキーワード
- `persona_label`: ペルソナ名
- `target_name`: ターゲット名
- `affiliate_url`: アフィリエイトURL（オプション）

### prompts/
- `title.txt`: タイトル生成プロンプト
- `outline.txt`: アウトライン生成プロンプト
- `draft.txt`: 本文生成プロンプト

### personas/
- ペルソナファイルを配置

### keywords/
- `keywords.csv`: キーワードリスト

## 3. スプレッドシート設定

.env に以下を設定：
```
SHEET_ID=your_sheet_id
```

recipesスクリプトで `--sheet-tab` を指定

## 4. 実行
```bash
./recipes/batch_generate.sh your_project_name
```
