@echo off
REM =============================================================================
REM MigradorDeDatos — Script de despliegue desde Windows al VPS
REM Compila el frontend y lo sube al servidor via SCP (requiere OpenSSH o PuTTY)
REM Uso: deploy.bat TU_IP_VPS tu_usuario_ssh
REM =============================================================================

setlocal

set VPS_IP=%1
set VPS_USER=%2
set REMOTE_DIR=/opt/migrador

if "%VPS_IP%"=="" (
    echo.
    echo  Uso: deploy.bat ^<IP_DEL_SERVIDOR^> ^<USUARIO_SSH^>
    echo  Ejemplo: deploy.bat 51.12.34.56 root
    echo.
    pause
    exit /b 1
)

if "%VPS_USER%"=="" set VPS_USER=root

echo.
echo =============================================
echo   MigradorDeDatos - Despliegue al servidor
echo   Servidor: %VPS_USER%@%VPS_IP%
echo =============================================
echo.

REM --- 1. Compilar el frontend ---
echo [1/3] Compilando frontend (npm run build)...
call npm run build
if errorlevel 1 (
    echo ERROR: La compilacion del frontend ha fallado.
    pause
    exit /b 1
)
echo   Frontend compilado en dist/

REM --- 2. Subir frontend al servidor ---
echo.
echo [2/3] Subiendo frontend al servidor...
scp -r dist\* %VPS_USER%@%VPS_IP%:%REMOTE_DIR%/frontend/
if errorlevel 1 (
    echo ERROR: No se pudo subir el frontend. Comprueba la conexion SSH.
    pause
    exit /b 1
)
echo   Frontend subido correctamente.

REM --- 3. Subir motor Python ---
echo.
echo [3/3] Subiendo motor Python...
scp -r python-engine\* %VPS_USER%@%VPS_IP%:%REMOTE_DIR%/python-engine/
if errorlevel 1 (
    echo ERROR: No se pudo subir el motor Python.
    pause
    exit /b 1
)
echo   Motor Python subido correctamente.

REM --- Reiniciar servicio Python en el servidor ---
echo.
echo Reiniciando servicio en el servidor...
ssh %VPS_USER%@%VPS_IP% "systemctl restart migrador-python && systemctl reload nginx"

echo.
echo =============================================
echo   Despliegue completado
echo   Accede a: http://%VPS_IP%
echo =============================================
echo.
pause
