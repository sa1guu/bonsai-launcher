@echo off
chcp 65001 >nul
echo === Bonsai Launcher 打包脚本 (全部使用国内镜像源) ===
cd /d %~dp0

echo [1/4] 安装依赖 (清华镜像)...
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pyinstaller requests pywebview
if errorlevel 1 goto fail

echo [2/4] 使用 PyInstaller 打包单文件 exe...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name BonsaiLauncher ^
  --add-data "web;web" ^
  --collect-submodules webview ^
  app.py
if errorlevel 1 goto fail

echo [3/4] 制作安装包 (Inno Setup)...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
) else (
  echo 未安装 Inno Setup, 跳过安装包制作 (exe 仍可直接使用)
)

echo [4/4] 完成!
echo 绿色版: %cd%\dist\BonsaiLauncher.exe
echo 安装包: %cd%\installer_output\BonsaiLauncher-Setup.exe
goto end

:fail
echo 打包失败, 请检查上方错误信息
pause
exit /b 1

:end
pause
