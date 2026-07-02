@echo off
cd /d C:\Users\dlawrence\Documents\bs-organic

echo Pulling latest from GitHub...
git pull --rebase

echo Adding refreshed data files...
git add data/

git commit -m "Data refresh %date% %time%"
if errorlevel 1 (
    echo Nothing to commit - data unchanged.
    pause
    exit /b 0
)

echo Pushing to GitHub...
git push

echo.
echo Done! GitHub Pages will update in 1-2 minutes.
pause
