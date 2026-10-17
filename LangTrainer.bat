@echo off
rem Language Trainer launcher for Windows: double-click to start the server and open the page in the browser.
rem Close this window (or press Ctrl+C) to stop the server.
rem   LangTrainer.bat --shortcut   puts a "Language Trainer" shortcut on the desktop.
setlocal
cd /d "%~dp0"
title Language Trainer
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
set "URL=http://127.0.0.1:8000/"

if /i "%~1"=="--shortcut" goto shortcut

rem If something already answers (for example a server started from a terminal), just open the page.
curl.exe -s -o NUL --max-time 1 %URL% && (
    start "" %URL%
    exit /b 0
)

where uv >NUL 2>&1 && goto have_uv
echo uv is not installed. Installing it now from https://astral.sh/uv ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
where uv >NUL 2>&1 || (
    echo.
    echo Could not install uv. Install it manually from https://docs.astral.sh/uv/ and run this file again.
    pause
    exit /b 1
)

:have_uv
echo Preparing Language Trainer (the first run downloads about 1.3 GB, please wait) ...
uv sync --quiet || (
    if not exist ".venv\Scripts\langtrainer.exe" (
        echo.
        echo Setup failed, see the messages above.
        pause
        exit /b 1
    )
    echo Setup failed, starting with the installed version.
)

mkdir data 2>NUL
echo Starting Language Trainer. The page opens in your browser. Close this window to stop it.
echo Log: %CD%\data\server.log
echo.
".venv\Scripts\langtrainer.exe" 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath 'data\server.log' -Append"
echo.
echo Language Trainer stopped.
pause
exit /b 0

:shortcut
set "LT_LINK=%USERPROFILE%\Desktop\Language Trainer.lnk"
set "LT_TARGET=%~f0"
set "LT_DIR=%~dp0"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LT_LINK); $s.TargetPath=$env:LT_TARGET; $s.WorkingDirectory=$env:LT_DIR; $s.Save()"
echo Shortcut created: %LT_LINK%
pause
exit /b 0
