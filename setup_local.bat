@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    py -m venv venv
    if errorlevel 1 (
        echo ERRO: nao foi possivel criar o ambiente virtual.
        pause
        exit /b 1
    )
)

set "PYTHON=%CD%\venv\Scripts\python.exe"
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERRO: falha ao instalar dependencias.
    pause
    exit /b 1
)

if not defined SECRET_KEY (
    "%PYTHON%" -c "import secrets; print(secrets.token_urlsafe(32))" > "%TEMP%\ponto-secret-key.txt"
    set /p SECRET_KEY=<"%TEMP%\ponto-secret-key.txt"
    del "%TEMP%\ponto-secret-key.txt"
)

if not defined ADMIN_INITIAL_PASSWORD (
    if not exist "instance\ponto.db" (
        set /p "ADMIN_INITIAL_PASSWORD=Senha inicial do administrador TI (minimo 8 caracteres): "
    ) else (
        "%PYTHON%" -c "import sqlite3,sys; c=sqlite3.connect('instance/ponto.db'); sys.exit(0 if c.execute(\"select 1 from usuarios where matricula='TI001' limit 1\").fetchone() else 1)"
        if errorlevel 1 set /p "ADMIN_INITIAL_PASSWORD=Senha inicial do administrador TI (minimo 8 caracteres): "
    )
)
if not defined ADMIN_INITIAL_PASSWORD set "ADMIN_INITIAL_PASSWORD=unused-local-password"

"%PYTHON%" init_db.py
if errorlevel 1 (
    echo ERRO: falha ao inicializar o banco de dados.
    pause
    exit /b 1
)
"%PYTHON%" baixar_deps.py
if errorlevel 1 (
    echo ERRO: falha ao preparar os arquivos estaticos.
    pause
    exit /b 1
)

if not exist "static\css\bootstrap.min.css" (
  echo.
  echo ERRO: Bootstrap nao foi baixado. Verifique a conexao com a internet.
  pause
  exit /b 1
)

set "FLASK_HOST=0.0.0.0"
set "FLASK_PORT=5000"
set "FLASK_DEBUG=false"
set "SESSION_COOKIE_SECURE=false"

for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /R /C:"IPv4.*:"') do set "LOCAL_IP=%%A"
set "LOCAL_IP=%LOCAL_IP: =%"
echo.
echo Acesso local: http://127.0.0.1:%FLASK_PORT%
echo Acesso na rede: http://%LOCAL_IP%:%FLASK_PORT%
echo.
"%PYTHON%" app.py
