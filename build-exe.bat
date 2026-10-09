@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   打包「国内期货行情面板」为单文件 EXE
echo ============================================================
echo.

set PY=C:\Python314\python.exe
if not exist "%PY%" (
  where python >nul 2>nul || (echo [错误] 未找到 Python，请先安装 Python 3.10+ & pause & exit /b 1)
  set PY=python
)

echo [1/3] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/3] 开始打包（约 1~2 分钟）...
"%PY%" -m PyInstaller --clean --noconfirm 期货行情面板.spec
if errorlevel 1 (
  echo.
  echo [失败] 打包出错，请查看上方日志。
  pause
  exit /b 1
)

echo.
echo [3/3] 复制启动脚本...
if not exist dist mkdir dist
copy /y "dist_启动面板.bat" "dist\启动面板.bat" >nul

echo.
echo ============================================================
echo   打包完成！
echo   产物：dist\期货行情面板.exe
echo   双击运行，或使用 dist\启动面板.bat
echo ============================================================
pause
