# WordPress記事削除

$ErrorActionPreference = "Stop"

Write-Host "WordPress記事削除を開始します..." -ForegroundColor Yellow
Write-Host "注意: この操作は記事を削除します。続行しますか？" -ForegroundColor Yellow

$confirmation = Read-Host "続行する場合は 'yes' と入力してください"
if ($confirmation -ne "yes") {
    Write-Host "操作をキャンセルしました" -ForegroundColor Cyan
    exit 0
}

python wordpress/wp-auto-delete.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "WordPress記事削除中にエラーが発生しました"
    exit $LASTEXITCODE
}

Write-Host "WordPress記事削除が完了しました" -ForegroundColor Green






