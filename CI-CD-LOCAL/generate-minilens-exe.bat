@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

REM ============================================================================
REM  GENERATE-MINILENS-EXE.BAT
REM  Genera MiniLens.exe con PyInstaller (GUI windowed, sin consola)
REM  Entry point: Main-GUI.py
REM ============================================================================

REM 1 - EL .bat ESTA EN CI-CD-LOCAL/ PERO LOS ARCHIVOS DEL PROYECTO ESTAN ARRIBA:
cd /d "%~dp0\.."

echo.
echo ============================================================
echo   Build MiniLens.exe
echo ============================================================
echo.

REM ---------------------------------------------------------------------------
REM 2 - VERIFICAR QUE PYTHON ESTA EN EL PATH:
REM ---------------------------------------------------------------------------
echo [1/5] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no encontrado en el PATH.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo       Python !PYVER! OK

REM ---------------------------------------------------------------------------
REM 3 - CREAR/ACTIVAR VIRTUAL ENV E INSTALAR DEPENDENCIAS:
REM ---------------------------------------------------------------------------
echo.
echo [2/5] Verificando virtual environment y dependencias...
if not exist "venv\Scripts\activate.bat" (
    echo       Creando venv...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: No se pudo crear el virtual environment.
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat

REM 3a - INSTALAR TODO LO QUE FALTE (dependencias del proyecto + pyinstaller):
for %%P in (PySide6 kubernetes PyYAML pyinstaller) do (
    pip show %%P >nul 2>&1
    if errorlevel 1 (
        echo       Instalando %%P...
        pip install %%P
        if errorlevel 1 (
            echo ERROR: No se pudo instalar %%P.
            pause
            exit /b 1
        )
    ) else (
        echo       %%P OK
    )
)

REM ---------------------------------------------------------------------------
REM 4 - LIMPIAR BUILDS ANTERIORES DE MINILENS:
REM ---------------------------------------------------------------------------
echo.
echo [3/5] Limpiando build anterior...
if exist "build\MiniLens" rmdir /s /q "build\MiniLens"
if exist "dist\MiniLens" rmdir /s /q "dist\MiniLens"
if exist "MiniLens.spec" del /q "MiniLens.spec"
echo       Limpieza OK

REM ---------------------------------------------------------------------------
REM 5 - CONSTRUIR EL .exe CON PYINSTALLER:
REM ---------------------------------------------------------------------------
echo.
echo [4/5] Construyendo MiniLens.exe...
pyinstaller --noconfirm --windowed --name "MiniLens" ^
    --paths "." ^
    --add-data "ui;ui" ^
    --add-data "models;models" ^
    --add-data "database;database" ^
    --add-data "resources;resources" ^
    --add-data "k8s;k8s" ^
    --hidden-import "database.db" ^
    --hidden-import "PySide6.QtWidgets" ^
    --hidden-import "PySide6.QtCore" ^
    --hidden-import "PySide6.QtGui" ^
    --hidden-import "kubernetes" ^
    --hidden-import "kubernetes.client" ^
    --hidden-import "kubernetes.config" ^
    --hidden-import "kubernetes.client.exceptions" ^
    --hidden-import "yaml" ^
    Main-GUI.py
if errorlevel 1 (
    echo ERROR: Fallo el build de MiniLens.
    pause
    exit /b 1
)

REM ---------------------------------------------------------------------------
REM 6 - COPIAR database/minilens.db JUNTO AL .exe (para que sea editable):
REM ---------------------------------------------------------------------------
echo.
echo [5/5] Copiando database/minilens.db junto al .exe...
if exist "database\minilens.db" (
    if not exist "dist\MiniLens\database" mkdir "dist\MiniLens\database"
    copy /y "database\minilens.db" "dist\MiniLens\database\minilens.db" >nul 2>&1
    echo       minilens.db copiado OK
) else (
    echo       Aviso: no se encontro database\minilens.db, se omitio la copia.
)

REM ---------------------------------------------------------------------------
REM 7 - RESULTADO:
REM ---------------------------------------------------------------------------
echo.
echo ============================================================
echo   BUILD COMPLETADO: MiniLens.exe
echo ============================================================
echo.
echo   Ubicacion: dist\MiniLens\MiniLens.exe
echo.
echo   Para llevar a otra PC:
echo     1. Copia la carpeta dist\MiniLens\ completa
echo     2. Ejecuta MiniLens.exe (doble clic)
echo     3. No necesita Python ni nada instalado
echo.
pause
