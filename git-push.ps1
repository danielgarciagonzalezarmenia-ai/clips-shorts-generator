param(
    [Parameter(Mandatory=$true)]
    [string]$message
)

cd $PSScriptRoot
git add -A
git commit -m "$message"
git push
if ($?) {
    Write-Host "✓ Subido a GitHub" -ForegroundColor Green
} else {
    Write-Host "✗ Error al subir" -ForegroundColor Red
}
