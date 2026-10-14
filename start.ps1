$root = $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\backend'; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\frontend'; npm run dev"
Start-Sleep -Seconds 6
Start-Process "http://localhost:5173"