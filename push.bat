@echo off
cd /d "%~dp0"
echo Pushing main and claude-a/business to GitHub...
git push origin main claude-a/business
echo.
echo Done. Tell Claude B: "CP0 done. Pull main into claude-b/trust and read notes/a_to_b.md".
pause
