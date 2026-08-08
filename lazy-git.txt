@echo off
setlocal enabledelayedexpansion

REM Navigate to the script's directory
cd /d "%~dp0"

echo 🔍 Checking status...
git status -s

REM 1. Pull latest changes to prevent push rejections
echo 📥 Fetching latest changes from GitHub...
git pull origin main
if errorlevel 1 (
    echo ❌ Error: Could not pull updates. You might have a conflict. Ask for help!
    exit /b 1
)

REM 2. Stage EVERYTHING first (including brand new files)
echo 🚀 Staging files...
git add .

REM 3. NOW check if there are any staged changes to commit
git diff --cached --quiet
if not errorlevel 1 (
    echo ✅ Everything is already up to date. Nothing new to push!
    exit /b 0
)

REM 4. Prompt for a commit message
echo ✏️  Enter a quick note on what you changed (e.g., 'fixed login button'):
set /p commit_message=

if "!commit_message!"=="" (
    REM Get current date/time for fallback message
    for /f "tokens=1-5 delims=/:. " %%a in ("%date% %time%") do (
        set commit_message=Update made on %%a-%%b-%%c %%d:%%e
    )
)

REM 5. Commit and Push
echo 💾 Committing changes...
git commit -m "!commit_message!"

echo 📤 Pushing to GitHub...
git push origin main
if not errorlevel 1 (
    echo 🎉 Success! Your changes are live on GitHub.
) else (
    echo ❌ Push failed. Try running the script again.
)

endlocal
pause
