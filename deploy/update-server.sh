#!/bin/bash
# =============================================================================
# MigradorDeDatos — Actualización desde GitHub
# Ejecutar como root o con sudo:  bash /opt/migrador/deploy/update-server.sh
# =============================================================================

set -e

APP_DIR="/opt/migrador"
SERVICE_USER="migrador"

echo "=============================================="
echo "  Actualizando MigradorDeDatos..."
echo "=============================================="

cd "$APP_DIR"

echo "[1/3] Descargando últimos cambios de GitHub..."
git pull

echo ""
echo "[2/3] Recompilando el Frontend..."
npm install
npm run build
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

echo ""
echo "[3/3] Actualizando Python y reiniciando servicio..."
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/python-engine/requirements.txt" -q
systemctl restart migrador-python
systemctl reload nginx

echo ""
echo "=============================================="
echo "  ✅ Actualización completada con éxito."
echo "=============================================="
