$env:PATH = "$env:LOCALAPPDATA\hermes\tools\ffmpeg-9.0.1-win32-x64\bin;" + $env:PATH
$d = "$env:TEMP\cbv"
Remove-Item -Recurse -Force "$d\src" -ErrorAction SilentlyContinue
git clone -q -b main "$env:USERPROFILE\cb.bundle" "$d\src" 2>&1 | Out-Null
Set-Location "$d\src"
& powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\verify.ps1 -Python "$d\venv\Scripts\python.exe" -Scratch "$d\scratch" 2>&1 | Select-Object -Last 45
"EXIT=$LASTEXITCODE"
