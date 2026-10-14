@echo off
REM netflix_accounts/ folder ko GitHub par sync karne ke liye double-click karo.
REM Watch mode: nayi files automatically push hoti rahengi.
cd /d "%~dp0"
python push_accounts.py --watch
pause