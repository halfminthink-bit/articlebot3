#!/bin/bash
# 記事一括生成（汎用版）
# 使い方: ./recipes/batch_generate.sh <project_name>

PROJECT=${1:-bank}

python batch_orchestrator.py \
  --persona-dir projects/$PROJECT/personas/mama.txt \
  --keywords_csv projects/$PROJECT/keywords/keywords.csv \
  --folder-id ${GDRIVE_FOLDER_ID} \
  --sheet-id ${SHEET_ID} \
  --sheet-tab mama \
  --last-cta-text "まずは相談をしてみる！"
