# =============================================================================
# MigradorDeDatos — Instalación en Windows Server
# Ejecutar como Administrador en PowerShell:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\deploy\setup-windows.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

$REPO_URL    = "https://github.com/scobaa/MigradorDeDatos.git"
$APP_DIR     = "C:\migrador"
$PYTHON_PORT = 8000
$NGINX_PORT  = 80
$NSSM_URL    = "https://nssm.cc/release/nssm-2.24.zip"
$NSSM_DIR    = "C:\nssm"

function Write-Step($n, $msg) {
    Write-Host ""
    Write-Host "[$n] $msg" -ForegroundColor Cyan
}

# Verificar que se ejecuta como Administrador
$cur = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $cur.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Debes ejecutar este script como Administrador." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  MigradorDeDatos - Instalacion en Windows" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green

# ── 1. Instalar Chocolatey ─────────────────────────────────────────────────────
Write-Step "1/7" "Verificando Chocolatey (gestor de paquetes)..."
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "  Instalando Chocolatey..." -ForegroundColor Yellow
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
} else {
    Write-Host "  Chocolatey ya instalado." -ForegroundColor Green
}

# ── 2. Instalar Node.js, Python, Git, Nginx ───────────────────────────────────
Write-Step "2/7" "Instalando Node.js 20, Python 3.11, Git y Nginx..."

choco install nodejs            -y --no-progress --version=20.18.0 2>&1 | Out-Null
choco install python311         -y --no-progress 2>&1 | Out-Null
choco install git               -y --no-progress 2>&1 | Out-Null
choco install nginx-win         -y --no-progress 2>&1 | Out-Null

# Recargar PATH para usar los nuevos comandos
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
Write-Host "  Dependencias instaladas." -ForegroundColor Green

# ── 3. Instalar NSSM (para registrar como servicio Windows) ───────────────────
Write-Step "3/7" "Instalando NSSM..."
if (-not (Test-Path "$NSSM_DIR\nssm.exe")) {
    $nssmZip = "$env:TEMP\nssm.zip"
    Write-Host "  Descargando NSSM..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $NSSM_URL -OutFile $nssmZip -UseBasicParsing
    Expand-Archive -Path $nssmZip -DestinationPath "$env:TEMP\nssm_extract" -Force
    New-Item -ItemType Directory -Path $NSSM_DIR -Force | Out-Null
    Copy-Item "$env:TEMP\nssm_extract\nssm-2.24\win64\nssm.exe" "$NSSM_DIR\nssm.exe" -Force
    Remove-Item $nssmZip -Force
    Remove-Item "$env:TEMP\nssm_extract" -Recurse -Force
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path","Machine")
    if ($machinePath -notlike "*$NSSM_DIR*") {
        [System.Environment]::SetEnvironmentVariable("Path", "$machinePath;$NSSM_DIR", "Machine")
        $env:Path = $env:Path + ";$NSSM_DIR"
    }
    Write-Host "  NSSM instalado en $NSSM_DIR" -ForegroundColor Green
} else {
    Write-Host "  NSSM ya instalado." -ForegroundColor Green
}

# ── 4. Clonar o actualizar el repositorio ─────────────────────────────────────
Write-Step "4/7" "Obteniendo codigo desde GitHub..."
if (Test-Path $APP_DIR) {
    Write-Host "  El directorio ya existe. Actualizando..." -ForegroundColor Yellow
    Set-Location $APP_DIR
    git fetch --all
    git reset --hard origin/main
} else {
    git clone $REPO_URL $APP_DIR
}
Set-Location $APP_DIR
Write-Host "  Repositorio listo en $APP_DIR" -ForegroundColor Green

# ── 5. Compilar Frontend React ─────────────────────────────────────────────────
Write-Step "5/7" "Compilando el Frontend (React)..."
Set-Location $APP_DIR
npm install --silent
npm run build
Write-Host "  Frontend compilado en $APP_DIR\dist" -ForegroundColor Green

# ── 6. Configurar entorno Python ──────────────────────────────────────────────
Write-Step "6/7" "Configurando Motor Python..."

# Localizar python.exe (compatible con PowerShell 5)
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    $pythonExe = $pythonCmd.Source
} else {
    $pythonExe = "C:\Python311\python.exe"
}
if (-not (Test-Path $pythonExe)) {
    $found = Get-ChildItem "C:\Python*" -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $pythonExe = $found.FullName }
}
Write-Host "  Usando Python: $pythonExe" -ForegroundColor Gray

$venvPath = "$APP_DIR\venv"
if (-not (Test-Path $venvPath)) {
    & $pythonExe -m venv $venvPath
}
& "$venvPath\Scripts\pip.exe" install --upgrade pip -q
& "$venvPath\Scripts\pip.exe" install -r "$APP_DIR\python-engine\requirements.txt" -q

# Crear .env si no existe
if (-not (Test-Path "$APP_DIR\python-engine\.env")) {
    @"
# =====================================================
# Configuracion de MigradorDeDatos
# Edita este archivo con tus valores reales y reinicia
# el servicio MigradorPython desde Servicios de Windows
# =====================================================

# SMTP para notificaciones por correo (opcional)
SMTP_HOST=smtp.tuempresa.com
SMTP_PORT=587
SMTP_USER=migrador@tuempresa.com
SMTP_PASSWORD=tu_password_smtp
SMTP_FROM=migrador@tuempresa.com

# Clave de Anthropic para mapeo automatico con IA (opcional)
ANTHROPIC_API_KEY=
"@ | Out-File -FilePath "$APP_DIR\python-engine\.env" -Encoding UTF8
    Write-Host "  .env creado. EDITALO antes de usar la app." -ForegroundColor Yellow
}

# Crear directorio de logs
New-Item -ItemType Directory -Path "$APP_DIR\logs" -Force | Out-Null

# ── 7. Registrar servicios Windows ────────────────────────────────────────────
Write-Step "7/7" "Registrando servicios Windows (NSSM)..."

# --- Servicio Backend Python ---
$pythonSvc = "MigradorPython"
if (Get-Service -Name $pythonSvc -ErrorAction SilentlyContinue) {
    Stop-Service -Name $pythonSvc -Force -ErrorAction SilentlyContinue
    & "$NSSM_DIR\nssm.exe" remove $pythonSvc confirm 2>&1 | Out-Null
}
& "$NSSM_DIR\nssm.exe" install    $pythonSvc "$venvPath\Scripts\python.exe"
& "$NSSM_DIR\nssm.exe" set        $pythonSvc AppParameters    "server.py"
& "$NSSM_DIR\nssm.exe" set        $pythonSvc AppDirectory     "$APP_DIR\python-engine"
& "$NSSM_DIR\nssm.exe" set        $pythonSvc AppEnvironmentExtra "PYTHONPATH=$APP_DIR\python-engine"
& "$NSSM_DIR\nssm.exe" set        $pythonSvc DisplayName      "MigradorDeDatos - Motor Python"
& "$NSSM_DIR\nssm.exe" set        $pythonSvc Description      "Backend del sistema MigradorDeDatos"
& "$NSSM_DIR\nssm.exe" set        $pythonSvc Start            SERVICE_AUTO_START
& "$NSSM_DIR\nssm.exe" set        $pythonSvc AppStdout        "$APP_DIR\logs\python-stdout.log"
& "$NSSM_DIR\nssm.exe" set        $pythonSvc AppStderr        "$APP_DIR\logs\python-stderr.log"
& "$NSSM_DIR\nssm.exe" set        $pythonSvc AppRotateFiles   1
& "$NSSM_DIR\nssm.exe" set        $pythonSvc AppRotateBytes   10485760
Start-Service -Name $pythonSvc
Write-Host "  Servicio $pythonSvc iniciado." -ForegroundColor Green

# --- Configurar y registrar Nginx ---
# Buscar donde choco instalo nginx
$nginxExeObj = Get-ChildItem "C:\ProgramData\chocolatey" -Recurse -Filter "nginx.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
$nginxExe = if ($nginxExeObj) { $nginxExeObj.FullName } else { $null }
$nginxBase = if ($nginxExe) { Split-Path $nginxExe -Parent } else { $null }

if ($nginxBase -and (Test-Path $nginxExe)) {
    # Ruta con barras normales para nginx.conf
    $distPath = ($APP_DIR + "\dist").Replace("\", "/")

    @"
worker_processes 1;
events { worker_connections 1024; }

http {
    include       mime.types;
    default_type  application/octet-stream;
    sendfile      on;
    keepalive_timeout 65;

    server {
        listen $NGINX_PORT;
        server_name _;

        root $distPath;
        index index.html;

        location / {
            try_files `$uri `$uri/ /index.html;
        }

        location /api {
            proxy_pass http://127.0.0.1:$PYTHON_PORT;
            proxy_http_version 1.1;
            proxy_set_header Host `$host;
            proxy_set_header X-Real-IP `$remote_addr;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
            client_max_body_size 200M;
        }
    }
}
"@ | Out-File -FilePath "$nginxBase\conf\nginx.conf" -Encoding ASCII -Force

    $nginxSvc = "MigradorNginx"
    if (Get-Service -Name $nginxSvc -ErrorAction SilentlyContinue) {
        Stop-Service -Name $nginxSvc -Force -ErrorAction SilentlyContinue
        & "$NSSM_DIR\nssm.exe" remove $nginxSvc confirm 2>&1 | Out-Null
    }
    & "$NSSM_DIR\nssm.exe" install $nginxSvc $nginxExe
    & "$NSSM_DIR\nssm.exe" set    $nginxSvc AppDirectory $nginxBase
    & "$NSSM_DIR\nssm.exe" set    $nginxSvc DisplayName  "MigradorDeDatos - Nginx"
    & "$NSSM_DIR\nssm.exe" set    $nginxSvc Start        SERVICE_AUTO_START
    Start-Service -Name $nginxSvc
    Write-Host "  Nginx iniciado." -ForegroundColor Green
} else {
    Write-Host "  AVISO: No se encontro nginx.exe. Revisa la instalacion de Nginx." -ForegroundColor Yellow
}

# ── Firewall ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Abriendo puerto $NGINX_PORT en el Firewall de Windows..." -ForegroundColor Gray
netsh advfirewall firewall delete rule name="MigradorDeDatos HTTP" 2>&1 | Out-Null
netsh advfirewall firewall add rule name="MigradorDeDatos HTTP" protocol=TCP dir=in localport=$NGINX_PORT action=allow | Out-Null

# ── Resumen final ──────────────────────────────────────────────────────────────
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
       Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.IPAddress -notlike "169.*" } |
       Select-Object -First 1).IPAddress

Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  INSTALACION COMPLETADA CON EXITO" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host "  La app esta disponible en:  http://$ip" -ForegroundColor White
Write-Host ""
Write-Host "  SIGUIENTE PASO - Edita el archivo .env:" -ForegroundColor Yellow
Write-Host "  notepad $APP_DIR\python-engine\.env" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Para actualizar en el futuro ejecuta:" -ForegroundColor Gray
Write-Host "  .\deploy\update-windows.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "  Servicios registrados:" -ForegroundColor Gray
Write-Host "   - MigradorPython  (backend en puerto $PYTHON_PORT)" -ForegroundColor Gray
Write-Host "   - MigradorNginx   (web en puerto $NGINX_PORT)" -ForegroundColor Gray
Write-Host "=============================================" -ForegroundColor Green
