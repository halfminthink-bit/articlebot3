# 記事一括生成（bank版：固定セクション付き）

$ErrorActionPreference = "Stop"

# 環境変数の確認
if (-not $env:GDRIVE_FOLDER_ID) {
    Write-Error "環境変数 GDRIVE_FOLDER_ID が設定されていません"
    exit 1
}

if (-not $env:SHEET_ID) {
    Write-Error "環境変数 SHEET_ID が設定されていません"
    exit 1
}

Write-Host "記事一括生成（bank版）を開始します..." -ForegroundColor Green

python batch_orchestrator_bank.py `
    --persona-dir "projects/bank/personas/mama.txt" `
    --keywords_csv "projects/bank/keywords/keywords.csv" `
    --folder-id $env:GDRIVE_FOLDER_ID `
    --sheet-id $env:SHEET_ID `
    --sheet-tab mama

if ($LASTEXITCODE -ne 0) {
    Write-Error "記事生成中にエラーが発生しました"
    exit $LASTEXITCODE
}

Write-Host "記事一括生成が完了しました" -ForegroundColor Green






