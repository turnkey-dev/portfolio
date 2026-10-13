$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
    Write-Host 'Created .env. Add your BotFather token, then run this script again.'
    exit 1
}
$taskPython = Get-Command python -ErrorAction SilentlyContinue
$taskBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if ($taskPython) {
    & $taskPython.Source bot.py
} elseif (Test-Path -LiteralPath $taskBundledPython) {
    & $taskBundledPython bot.py
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 bot.py
} else {
    Write-Host 'Python 3.10+ is required. Install Python, then run this script again.'
    exit 1
}
exit $LASTEXITCODE
