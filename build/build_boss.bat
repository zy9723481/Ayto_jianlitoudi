@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo ============================================
echo   BOSS直聘投递助手 — 打包发布
echo ============================================
echo.

REM ═══════════════════════════════════════════════
REM  步骤0: 打包前检查
REM ═══════════════════════════════════════════════
if not exist "boss_only.py" (
    echo [错误] 找不到 boss_only.py，请在项目根目录运行此脚本。
    pause
    exit /b 1
)

REM ═══════════════════════════════════════════════
REM  步骤1: 备份你的个人 config.py，替换为发布版模板
REM ═══════════════════════════════════════════════
echo [1/6] 备份个人config.py，替换为发布模板...
if exist "config.py" (
    copy /y "config.py" "config_my_backup.py" >nul
    echo       已备份为 config_my_backup.py（打包完会自动恢复）
)
copy /y "config_template.py" "config.py" >nul
echo       已替换为发布模板（占位符配置）

REM ═══════════════════════════════════════════════
REM  步骤2: 清理旧的打包产物
REM ═══════════════════════════════════════════════
echo [2/6] 清理旧的打包产物...
if exist "build\dist" rmdir /s /q "build\dist"
if exist "build\build" rmdir /s /q "build\build"
if exist "*.spec" del /q "*.spec"

REM ═══════════════════════════════════════════════
REM  步骤3: 安装依赖
REM ═══════════════════════════════════════════════
echo [3/6] 安装依赖...
pip install DrissionPage openai PyPDF2 python-docx bcrypt pymysql Pillow -q

REM ═══════════════════════════════════════════════
REM  步骤4: PyInstaller 打包
REM ═══════════════════════════════════════════════
echo [4/6] PyInstaller 打包中（需要几分钟）...
pyinstaller --onefile --windowed --name "BOSS直聘投递助手" ^
  --hidden-import DrissionPage ^
  --hidden-import DrissionPage._configs.chromium_options ^
  --hidden-import openai ^
  --hidden-import PyPDF2 ^
  --hidden-import docx ^
  --hidden-import pymysql ^
  --hidden-import bcrypt ^
  --hidden-import babel.numbers ^
  --collect-all DrissionPage ^
  --distpath "build\dist" ^
  --workpath "build\build" ^
  --specpath "build" ^
  boss_only.py

if errorlevel 1 (
    echo [失败] 打包出错，请检查是否安装了 PyInstaller: pip install pyinstaller
    goto :restore
)

REM ═══════════════════════════════════════════════
REM  步骤5: 复制发布文件到输出目录
REM ═══════════════════════════════════════════════
echo [5/6] 整理发布文件...
copy "config_template.py" "build\dist\config.py" >nul
echo       build\dist\BOSS直聘投递助手.exe
echo       build\dist\config.py（买家需编辑配置）

REM ═══════════════════════════════════════════════
REM  步骤6: 恢复你的个人 config.py
REM ═══════════════════════════════════════════════
:restore
echo [6/6] 恢复你的个人config.py...
if exist "config_my_backup.py" (
    copy /y "config_my_backup.py" "config.py" >nul
    del /q "config_my_backup.py"
    echo       已恢复为你的个人配置
)

echo.
echo ============================================
echo   打包完成！
echo.
echo   发布文件在 build\dist\ 目录下：
echo     - BOSS直聘投递助手.exe
echo     - config.py（买家编辑后放EXE同目录）
echo ============================================
echo.
echo   【发给买家时包含以下文件】
echo     1. BOSS直聘投递助手.exe      主程序
echo     2. config.py                 配置文件（买家需编辑）
echo     3. 使用说明.txt              简要说明
echo.
echo   【买家首次使用步骤】
echo     1. 安装Chrome浏览器
echo     2. 编辑config.py填写数据库和API Key
echo     3. 双击EXE运行
echo     4. 注册账号 + 登录
echo.
echo   【注意】config.py 内的数据库和API Key是占位符，
echo   买家必须替换为自己的真实配置才能正常使用。
echo ============================================
pause
