# =============================================================================
# MigradorDeDatos — Actualización en Windows Server
# Ejecutar como Administrador en PowerShell:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\deploy\update-windows.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$APP_DIR     = "C:\migrador"
$NSSM_DIR    = "C:\nssm"
$PYTHON_SVC  = "MigradorPython"
$NGINX_SVC   = "MigradorNginx"

# Verificar Administrador
$cur = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $cur.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Debes ejecutar este script como Administrador." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  Actualizando MigradorDeDatos..." -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# ── 1. Descargar ultimos cambios de GitHub ────────────────────────────────────
Write-Host ""
Write-Host "[1/3] Descargando ultimos cambios de GitHub..." -ForegroundColor Cyan
Set-Location $APP_DIR
git fetch --all
git reset --hard origin/main
Write-Host "  Codigo actualizado." -ForegroundColor Green

# ── 2. Recompilar Frontend ────────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/3] Recompilando el Frontend (React)..." -ForegroundColor Cyan
Set-Location $APP_DIR
npm install --silent
npm run build
Write-Host "  Frontend recompilado." -ForegroundColor Green

# ── 3. Actualizar dependencias Python y reiniciar servicio ────────────────────
Write-Host ""
Write-Host "[3/3] Actualizando dependencias Python y reiniciando servicios..." -ForegroundColor Cyan

$venvPip = "$APP_DIR\venv\Scripts\pip.exe"
& $venvPip install -r "$APP_DIR\python-engine\requirements.txt" -q

# Reiniciar backend Python
if (Get-Service -Name $PYTHON_SVC -ErrorAction SilentlyContinue) {
    Restart-Service -Name $PYTHON_SVC -Force
    Write-Host "  Servicio $PYTHON_SVC reiniciado." -ForegroundColor Green
} else {
    Write-Host "  AVISO: Servicio $PYTHON_SVC no encontrado. Ejecuta setup-windows.ps1 primero." -ForegroundColor Yellow
}

# Recargar Nginx (parar + arrancar porque nginx en Windows no soporta reload)
if (Get-Service -Name $NGINX_SVC -ErrorAction SilentlyContinue) {
    Restart-Service -Name $NGINX_SVC -Force
    Write-Host "  Servicio $NGINX_SVC reiniciado." -ForegroundColor Green
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  ACTUALIZACION COMPLETADA CON EXITO" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
