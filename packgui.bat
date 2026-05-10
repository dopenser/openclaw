@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: ========== 配置 ==========
set APP_NAME=SmartTool_GUI
set MAIN_FILE=gui.py
set ICON_FILE=robot.ico

:: ========== 清理旧文件 ==========
echo 清理旧构建...
if exist dist rd /s /q dist
if exist build rd /s /q build
if exist %APP_NAME%.spec del /q %APP_NAME%.spec

:: ========== PyInstaller 打包 ==========
echo 正在打包 GUI 版本（无控制台窗口）...
pyinstaller --onefile --noconsole ^
    --name %APP_NAME% ^
    --icon=%ICON_FILE% ^
    %MAIN_FILE%

:: ========== 提示 ==========
echo.
echo ===================================================
echo 打包完成！exe 位于 dist\%APP_NAME%.exe
echo.
echo 请将以下文件复制到 exe 所在文件夹（dist\）：
echo   - license.dat         (许可证文件)
echo   - private_key.pem     (如需生成许可证)
echo   - public_key.pem      (如需生成许可证)
echo   - api.key             (会自动生成，也可预先放置)
echo ===================================================
pause