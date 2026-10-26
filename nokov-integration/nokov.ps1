$nokovPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $nokovPython (Join-Path $PSScriptRoot 'nokov_cli.py') @args
exit $LASTEXITCODE
