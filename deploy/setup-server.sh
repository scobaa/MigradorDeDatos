#!/bin/bash
# =============================================================================
# MigradorDeDatos — Instalación desde GitHub en Ubuntu/Debian
# Ejecutar como root o con sudo:  bash setup-server.sh
# =============================================================================

set -e

echo "=============================================="
echo "  MigradorDeDatos - Instalación desde GitHub"
echo "=============================================="

REPO_URL="https://github.com/scobaa/MigradorDeDatos.git"
APP_DIR="/opt/migrador"
SERVICE_USER="migrador"
PYTHON_PORT=8000
NGINX_PORT=80

echo ""
echo "[1/6] Instalando dependencias del sistema y Node.js..."
# Limpiar posible conflicto previo de repositorios de Node antes de hacer update
rm -f /etc/apt/sources.list.d/nodesource.list
rm -f /etc/apt/sources.list.d/nodesource.sources
rm -f /usr/share/keyrings/nodesource*

apt-get update -q
apt-get install -y -q curl git nginx python3 python3-pip python3-venv unixodbc unixodbc-dev
# Instalar Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y -q nodejs

echo ""
echo "[2/6] Creando usuario de servicio..."
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -d "$APP_DIR" "$SERVICE_USER"
fi

echo ""
echo "[3/6] Clonando repositorio desde GitHub..."
if [ -d "$APP_DIR" ]; then
    echo "  El directorio $APP_DIR ya existe. Actualizando..."
    cd "$APP_DIR"
    git pull
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

echo ""
echo "[4/6] Compilando el Frontend (React)..."
npm install
npm run build
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo ""
echo "[5/6] Configurando Motor Python..."
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/python-engine/requirements.txt" -q
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/venv"

echo ""
echo "[6/6] Configurando Servicios (Nginx y Systemd)..."

# Systemd
cat > /etc/systemd/system/migrador-python.service << EOF
[Unit]
Description=MigradorDeDatos - Motor Python
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR/python-engine
Environment="PYTHONPATH=$APP_DIR/python-engine"
ExecStart=$APP_DIR/venv/bin/python server.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable migrador-python
systemctl start migrador-python

# Nginx
cat > /etc/nginx/sites-available/migrador << EOF
server {
    listen $NGINX_PORT;
    server_name _;

    root $APP_DIR/dist;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api {
        proxy_pass http://127.0.0.1:$PYTHON_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        client_max_body_size 200M;
    }

    location /api/logs {
        proxy_pass http://127.0.0.1:$PYTHON_PORT;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/migrador /etc/nginx/sites-enabled/migrador
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

SERVER_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "=============================================="
echo "  ✅ Instalación completada con éxito"
echo "=============================================="
echo "  Accede a la app en: http://$SERVER_IP"
echo ""
echo "  Para actualizar en el futuro, simplemente ejecuta:"
echo "  bash /opt/migrador/deploy/update-server.sh"
echo "=============================================="
