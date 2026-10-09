@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python server.py %*
) else (
  where py >nul 2>nul
  if %errorlevel%==0 (
    py -3 server.py %*
  ) else (
    echo [错误] 未找到 Python，请先安装 Python 3.8 或更高版本。
  )
)
pause
