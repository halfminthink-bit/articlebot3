# Note公開（Playwright版）

$ErrorActionPreference = "Stop"

Write-Host "Note公開を開始します..." -ForegroundColor Green

python publish_note_play/main_playwright.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "Note公開中にエラーが発生しました"
    exit $LASTEXITCODE
}

Write-Host "Note公開が完了しました" -ForegroundColor Green






