@echo off
chcp 65001 > nul
set NGROK="C:\Users\admin\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"

echo BarChart Creator 시작 중...

:: FastAPI 백그라운드 실행
start "FastAPI Server" cmd /c "cd /d "%~dp0" && python -m uvicorn app:app --host 127.0.0.1 --port 8000"

:: 서버 기동 대기
timeout /t 3 /nobreak > nul

:: ngrok 터널 오픈 (이 창에 접속 URL 표시됨)
echo.
echo FastAPI 서버 기동 완료.
echo ngrok 터널 연결 중... 아래 Forwarding URL로 접속하세요.
echo.
%NGROK% http 8000
