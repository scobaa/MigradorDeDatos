"""
Módulo de notificación por email para el Migrador de Datos.

Envía un email de resumen cuando finaliza una migración, con el archivo
de logs adjunto.

Configuración via variables de entorno (o archivo .env en el mismo directorio):
    SMTP_HOST      — servidor SMTP (ej: smtp.gmail.com)
    SMTP_PORT      — puerto (587 para STARTTLS, 465 para SSL)
    SMTP_USER      — usuario de la cuenta remitente
    SMTP_PASSWORD  — contraseña o app-password
    SMTP_FROM      — dirección "De:" (si no se indica, se usa SMTP_USER)
    SMTP_USE_TLS   — "true" para usar STARTTLS (por defecto), "false" para SSL directo
"""

from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

log = logging.getLogger(__name__)

# Intentar cargar .env si python-dotenv está disponible
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

# ─── Lectura de configuración ──────────────────────────────────────────────────

def _get_smtp_config() -> dict[str, Any] | None:
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()

    if not host or not user or not password:
        return None  # SMTP no configurado

    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": user,
        "password": password,
        "from_addr": os.environ.get("SMTP_FROM", user).strip(),
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").strip().lower() != "false",
    }


def is_configured() -> bool:
    """Devuelve True si el SMTP está configurado y listo para enviar."""
    return _get_smtp_config() is not None


# ─── Construcción del email ────────────────────────────────────────────────────

def _build_email_body(summary: dict) -> str:
    """Genera el cuerpo HTML del email de resumen."""
    model_label = summary.get("model_label", summary.get("model", "Desconocido"))
    src_url = summary.get("src_url", "-")
    dst_url = summary.get("dst_url", "-")
    started_at = summary.get("started_at", "-")
    finished_at = summary.get("finished_at", "-")
    duration = summary.get("duration_seconds", 0)
    is_dry_run = summary.get("dry_run", False)

    stats = summary.get("stats", {}) or {}
    created = stats.get("created", 0)
    updated = stats.get("updated", 0)
    skipped = stats.get("skipped", 0)
    errors = stats.get("error_count", 0)

    status = summary.get("status", "done")
    status_label = "✅ Completada" if status == "done" else "❌ Error"
    status_color = "#22c55e" if status == "done" else "#ef4444"

    dry_badge = '<span style="background:#f59e0b;color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;margin-left:8px;">SIMULACIÓN</span>' if is_dry_run else ""

    per_model_html = ""
    per_model = summary.get("per_model", {})
    if per_model:
        per_model_html = "<h3 style='margin-top:24px;margin-bottom:8px;font-size:14px;color:#94a3b8;'>Detalle por modelo</h3><table style='width:100%;border-collapse:collapse;font-size:13px;'><thead><tr style='background:#1e293b;'><th style='text-align:left;padding:6px 10px;color:#94a3b8;border-radius:4px;'>Modelo</th><th style='text-align:right;padding:6px 10px;color:#94a3b8;'>Creados</th><th style='text-align:right;padding:6px 10px;color:#94a3b8;'>Actualizados</th><th style='text-align:right;padding:6px 10px;color:#94a3b8;'>Omitidos</th><th style='text-align:right;padding:6px 10px;color:#94a3b8;'>Errores</th></tr></thead><tbody>"
        for mname, mstats in per_model.items():
            per_model_html += f"<tr style='border-bottom:1px solid #1e293b;'><td style='padding:6px 10px;color:#e2e8f0;'>{mname}</td><td style='text-align:right;padding:6px 10px;color:#22c55e;'>{mstats.get('created',0)}</td><td style='text-align:right;padding:6px 10px;color:#3b82f6;'>{mstats.get('updated',0)}</td><td style='text-align:right;padding:6px 10px;color:#94a3b8;'>{mstats.get('skipped',0)}</td><td style='text-align:right;padding:6px 10px;color:#ef4444;'>{mstats.get('error_count',0)}</td></tr>"
        per_model_html += "</tbody></table>"

    minutes = int(duration) // 60
    seconds = int(duration) % 60
    duration_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="background:#0f172a;color:#e2e8f0;font-family:Inter,Arial,sans-serif;margin:0;padding:0;">
  <div style="max-width:600px;margin:32px auto;background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155;">
    
    <!-- Cabecera -->
    <div style="background:linear-gradient(135deg,#6366f1,#06b6d4);padding:28px 32px;">
      <h1 style="margin:0;font-size:22px;font-weight:700;color:#fff;">
        Migración {status_label}{dry_badge}
      </h1>
      <p style="margin:6px 0 0;font-size:13px;color:rgba(255,255,255,0.8);">
        {model_label} · {src_url} → {dst_url}
      </p>
    </div>

    <!-- Cuerpo -->
    <div style="padding:28px 32px;">

      <!-- Métricas principales -->
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;">
        <div style="background:#0f172a;border-radius:8px;padding:14px 10px;text-align:center;">
          <div style="font-size:24px;font-weight:700;color:#22c55e;">{created}</div>
          <div style="font-size:11px;color:#64748b;margin-top:4px;">Creados</div>
        </div>
        <div style="background:#0f172a;border-radius:8px;padding:14px 10px;text-align:center;">
          <div style="font-size:24px;font-weight:700;color:#3b82f6;">{updated}</div>
          <div style="font-size:11px;color:#64748b;margin-top:4px;">Actualizados</div>
        </div>
        <div style="background:#0f172a;border-radius:8px;padding:14px 10px;text-align:center;">
          <div style="font-size:24px;font-weight:700;color:#94a3b8;">{skipped}</div>
          <div style="font-size:11px;color:#64748b;margin-top:4px;">Omitidos</div>
        </div>
        <div style="background:#0f172a;border-radius:8px;padding:14px 10px;text-align:center;">
          <div style="font-size:24px;font-weight:700;color:#ef4444;">{errors}</div>
          <div style="font-size:11px;color:#64748b;margin-top:4px;">Errores</div>
        </div>
      </div>

      <!-- Info de tiempo -->
      <table style="width:100%;font-size:13px;border-collapse:collapse;margin-bottom:16px;">
        <tr>
          <td style="padding:6px 0;color:#64748b;width:140px;">Inicio</td>
          <td style="color:#e2e8f0;">{started_at}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:#64748b;">Fin</td>
          <td style="color:#e2e8f0;">{finished_at}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:#64748b;">Duración</td>
          <td style="color:#e2e8f0;">{duration_str}</td>
        </tr>
        <tr>
          <td style="padding:6px 0;color:#64748b;">Estado</td>
          <td style="color:{status_color};font-weight:600;">{status_label}</td>
        </tr>
      </table>

      {per_model_html}

      <p style="font-size:12px;color:#475569;margin-top:24px;">
        El archivo de logs completo está adjunto a este email.<br>
        Este mensaje es generado automáticamente por el Migrador de Datos de Tecniloop.
      </p>
    </div>
  </div>
</body>
</html>
"""


# ─── Envío ─────────────────────────────────────────────────────────────────────

def send_migration_summary(
    to_email: str,
    summary: dict,
    log_file_path: str | None = None,
) -> bool:
    """
    Envía el email de resumen de migración.

    Args:
        to_email: dirección de destino.
        summary: dict con los datos del resumen (ver _build_email_body).
        log_file_path: ruta al archivo de log para adjuntar (opcional).

    Returns:
        True si se envió correctamente, False si hubo error o SMTP no configurado.
    """
    cfg = _get_smtp_config()
    if cfg is None:
        log.warning("SMTP no configurado. El email de resumen no se enviará.")
        return False

    model_label = summary.get("model_label", summary.get("model", "migración"))
    status = summary.get("status", "done")
    dry_label = " [SIMULACIÓN]" if summary.get("dry_run") else ""
    status_emoji = "✅" if status == "done" else "❌"
    subject = f"{status_emoji} Migración {model_label}{dry_label} finalizada"

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_email

    html_body = _build_email_body(summary)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # Adjuntar log si existe y no es demasiado grande (máx 10 MB)
    if log_file_path and os.path.isfile(log_file_path):
        try:
            file_size = os.path.getsize(log_file_path)
            if file_size <= 10 * 1024 * 1024:
                with open(log_file_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                fname = os.path.basename(log_file_path)
                part.add_header("Content-Disposition", "attachment", filename=fname)
                msg.attach(part)
            else:
                log.warning("Archivo de log demasiado grande (%d bytes). No se adjuntará.", file_size)
        except Exception as e:
            log.warning("No se pudo adjuntar el log: %s", e)

    # Enviar
    try:
        if cfg["use_tls"]:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
                server.ehlo()
                server.starttls()
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from_addr"], [to_email], msg.as_bytes())
        else:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15) as server:
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["from_addr"], [to_email], msg.as_bytes())

        log.info("Email de resumen enviado a %s", to_email)
        return True

    except Exception as e:
        log.error("Error enviando email de resumen a %s: %s", to_email, e)
        return False
