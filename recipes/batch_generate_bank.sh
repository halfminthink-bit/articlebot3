#!/bin/bash
# 記事一括生成（bank版：固定セクション付き）

python batch_orchestrator_bank.py \
  --persona-dir projects/bank/personas/mama.txt \
  --keywords_csv projects/bank/keywords/keywords.csv \
  --folder-id ${GDRIVE_FOLDER_ID} \
  --sheet-id ${SHEET_ID} \
  --sheet-tab mama \
