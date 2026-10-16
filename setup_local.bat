@echo off
setlocal
cd /d "%~dp0"

python -m venv venv
call venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python init_db.py
python baixar_deps.py

if not exist "static\css\bootstrap.min.css" (
  echo.
  echo ERRO: Bootstrap nao foi baixado. Verifique a conexao com a internet.
  pause
  exit /b 1
)

python app.py
