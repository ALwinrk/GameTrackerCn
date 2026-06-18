@echo off
echo === 国内游戏新游排查系统 — 打包为 EXE ===

REM 构建前端
cd /d "%~dp0frontend"
call npm install
call npm run build
if %ERRORLEVEL% NEQ 0 (
    echo 前端构建失败!
    pause
    exit /b 1
)
cd /d "%~dp0"

REM PyInstaller 打包
pyinstaller --onefile ^
    --name "ChinaGameTracker" ^
    --add-data "frontend/dist;frontend/dist" ^
    --add-data "config.json;." ^
    --hidden-import backend.main ^
    --hidden-import backend.api.routes ^
    --hidden-import backend.cron.domestic_tracker ^
    --hidden-import backend.db.database ^
    --hidden-import backend.core.http_client ^
    --hidden-import backend.core.browser_manager ^
    launcher.py

echo === 打包完成 ===
echo 输出文件: dist\ChinaGameTracker.exe
pause
