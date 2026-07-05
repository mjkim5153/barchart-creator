$NGROK = "C:\Users\admin\AppData\Local\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"

Write-Host "Starting BarChart Creator..."
Write-Host ""

# Start FastAPI in background
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $scriptPath -WindowStyle Normal

# Wait for server startup
Start-Sleep -Seconds 3

# Open ngrok tunnel
Write-Host ""
Write-Host "FastAPI server started."
Write-Host "Connecting ngrok tunnel... Access via the Forwarding URL below."
Write-Host ""
& $NGROK http 8000

