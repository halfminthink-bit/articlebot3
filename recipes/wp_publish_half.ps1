# WordPress公開（half用）

$ErrorActionPreference = "Stop"

Write-Host "WordPress公開（half用）を開始します..." -ForegroundColor Green

python wordpress/wp-auto_half.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "WordPress公開中にエラーが発生しました"
    exit $LASTEXITCODE
}

Write-Host "WordPress公開が完了しました" -ForegroundColor Green






