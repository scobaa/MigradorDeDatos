import json
import os
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from datetime import datetime

# ─── Servidor HTTP multihilo ───────────────────────────────────────────────────
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

PORT = 8000

# ─── Cola de logs del migrador de Excel (compatibilidad) ──────────────────────
LOG_QUEUE = []

# ─── Sistema de Jobs en segundo plano ─────────────────────────────────────────
class Job:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = "running"   # "running" | "done" | "error"
        self.logs: list[str] = []
        self.result: dict | None = None
        self.error: str | None = None
        self.progress: dict = {"done": 0, "total": 0, "model": ""}
        self._lock = threading.Lock()

    def append_log(self, line: str):
        with self._lock:
            self.logs.append(line)

    def get_logs_from(self, offset: int) -> list[str]:
        with self._lock:
            return self.logs[offset:]

    def finish_ok(self, result: dict):
        with self._lock:
            self.result = result
            self.status = "done"

    def finish_error(self, error: str):
        with self._lock:
            self.error = error
            self.status = "error"

    def update_progress(self, done: int, total: int, model: str = ""):
        with self._lock:
            self.progress = {"done": done, "total": total, "model": model}

    def to_status_dict(self, log_offset: int = 0) -> dict:
        with self._lock:
            new_logs = self.logs[log_offset:]
            return {
                "job_id": self.job_id,
                "status": self.status,
                "progress": dict(self.progress),
                "logs": new_logs,
                "next_log_offset": log_offset + len(new_logs),
                "result": self.result,
                "error": self.error,
            }


# Diccionario global de jobs activos
JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()
 

def _run_job_in_background(job: Job, payload: dict, engine_dir: str, python_exe: str, main_script: str, to_email: str | None = None):
    """Ejecuta main.py en un hilo daemon y actualiza el Job en tiempo real."""
    started_at = datetime.now()
    logs_dir = os.path.join(engine_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    cmd_name = payload.get("command", "unknown")
    log_file_path = os.path.join(logs_dir, f"{cmd_name}_{timestamp}.log")

    try:
        process = subprocess.Popen(
            [python_exe, main_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        process.stdin.write(json.dumps(payload))
        process.stdin.close()

        def capture_stderr(pipe):
            try:
                with open(log_file_path, "a", encoding="utf-8") as log_file:
                    for line in iter(pipe.readline, ""):
                        sys.stderr.write(line)
                        sys.stderr.flush()
                        stripped = line.strip()
                        job.append_log(stripped)
                        log_file.write(line)
                        log_file.flush()
                        # Actualizar progreso en tiempo real desde los eventos JSON
                        if stripped.startswith("{") and stripped.endswith("}"):
                            try:
                                evt = json.loads(stripped)
                                if evt.get("event") == "progress" and evt.get("total", 0) > 0:
                                    job.update_progress(evt["done"], evt["total"], evt.get("model", ""))
                            except Exception:
                                pass
            except Exception:
                pass

        stderr_thread = threading.Thread(target=capture_stderr, args=(process.stderr,), daemon=True)
        stderr_thread.start()

        stdout_data = process.stdout.read()
        process.wait()
        stderr_thread.join(timeout=2.0)

        # Parsear el resultado del proceso
        stdout_data = stdout_data.strip()
        finished_at = datetime.now()
        duration_seconds = (finished_at - started_at).total_seconds()

        if stdout_data:
            try:
                result = json.loads(stdout_data)
                if result.get("status") == "ok":
                    job.finish_ok(result.get("data", {}))
                    if cmd_name in ("run_migration", "run_odoo_migration"):
                        _send_summary_email(
                            to_email=to_email,
                            status="done",
                            payload=payload,
                            result=result.get("data", {}),
                            log_file_path=log_file_path,
                            started_at=started_at,
                            finished_at=finished_at,
                            duration_seconds=duration_seconds,
                        )
                else:
                    job.finish_error(result.get("error", "Error desconocido del proceso"))
                    if cmd_name in ("run_migration", "run_odoo_migration"):
                        _send_summary_email(
                            to_email=to_email,
                            status="error",
                            payload=payload,
                            result={},
                            log_file_path=log_file_path,
                            started_at=started_at,
                            finished_at=finished_at,
                            duration_seconds=duration_seconds,
                            error=result.get("error", "Error desconocido"),
                        )
            except json.JSONDecodeError:
                job.finish_error(f"Respuesta inválida del proceso: {stdout_data[:200]}")
        else:
            job.finish_error("El proceso terminó sin producir respuesta")

    except Exception as e:
        job.finish_error(f"Error lanzando el proceso: {str(e)}")


def _send_summary_email(
    to_email: str | None,
    status: str,
    payload: dict,
    result: dict,
    log_file_path: str,
    started_at: datetime,
    finished_at: datetime,
    duration_seconds: float,
    error: str | None = None,
):
    """Envía el email de resumen si to_email está disponible y SMTP configurado."""
    args = payload.get("args", {})
    opts = args.get("options", {})

    # Si send_email está explícitamente desactivado en las opciones
    if "send_email" in opts and not opts["send_email"]:
        sys.stderr.write("[INFO] Envío de email deshabilitado para esta migración.\n")
        return

    if not to_email:
        return

    try:
        from email_notifier import send_migration_summary, is_configured
        if not is_configured():
            sys.stderr.write("[INFO] SMTP no configurado, email de resumen omitido.\n")
            return

        args = payload.get("args", {})
        model = args.get("model", payload.get("command", "migración"))
        MODEL_LABELS = {
            "res.partner": "Contactos", "product.template": "Productos",
            "stock.quant": "Inventario", "account.move": "Facturas (cliente)",
            "account.move.supplier": "Facturas (proveedor)", "sale.order": "Pedidos de venta",
            "purchase.order": "Pedidos de compra", "account.move.entry": "Asientos contables",
            "account.account": "Plan contable", "all": "Todos los modelos",
        }

        summary = {
            "status": status,
            "model": model,
            "model_label": MODEL_LABELS.get(model, model),
            "src_url": args.get("odoo_source", {}).get("url", "-"),
            "dst_url": args.get("odoo_dest", {}).get("url", "-"),
            "dry_run": args.get("dry_run", False),
            "started_at": started_at.strftime("%d/%m/%Y %H:%M:%S"),
            "finished_at": finished_at.strftime("%d/%m/%Y %H:%M:%S"),
            "duration_seconds": duration_seconds,
            "stats": result.get("stats"),
            "per_model": result.get("per_model"),
            "error": error,
        }

        send_migration_summary(
            to_email=to_email,
            summary=summary,
            log_file_path=log_file_path,
        )
    except Exception as e:
        sys.stderr.write(f"[WARNING] No se pudo enviar el email de resumen: {e}\n")


# ─── Handler HTTP ──────────────────────────────────────────────────────────────

class PythonBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suprimir logs de acceso a /api/job para no saturar la consola
        if "/api/job/" in (args[0] if args else ""):
            return
        super().log_message(format, *args)

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Connection", "close")
        self.end_headers()

    # ── GET ───────────────────────────────────────────────────────────────────

    def do_GET(self):
        import urllib.parse

        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        # ── GET /api/job/<job_id>  (nuevo: estado de un job en segundo plano)
        if parsed.path.startswith("/api/job/"):
            job_id = parsed.path[len("/api/job/"):]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
            if job is None:
                self._send_json(404, {"error": f"Job '{job_id}' no encontrado"})
                return
            log_offset = 0
            try:
                log_offset = int(query.get("log_offset", [0])[0])
            except Exception:
                pass
            self._send_json(200, job.to_status_dict(log_offset))
            return

        # ── GET /api/logs  (compatibilidad con MigrationWizard / migrador Excel)
        if parsed.path.startswith("/api/logs"):
            global LOG_QUEUE
            offset = 0
            try:
                offset = int(query.get("offset", [0])[0])
            except Exception:
                pass
            logs_to_send = LOG_QUEUE[offset:]
            self._send_json(200, {"logs": logs_to_send, "next_offset": offset + len(logs_to_send)})
            return

        self.send_response(404)
        self.end_headers()

    # ── POST ──────────────────────────────────────────────────────────────────

    def do_POST(self):
        import urllib.parse

        # ── POST /api/upload  (subida de ficheros)
        if self.path == "/api/upload":
            file_name = self.headers.get("X-File-Name", "upload.bin")
            file_name = urllib.parse.unquote(file_name)
            file_name = os.path.basename(file_name)

            content_length = int(self.headers.get("Content-Length", 0))
            file_data = self.rfile.read(content_length)

            engine_dir = os.path.dirname(os.path.abspath(__file__))
            app_dir = os.path.dirname(engine_dir)
            uploads_dir = os.path.join(app_dir, "uploads")
            if not os.path.exists(uploads_dir):
                uploads_dir = engine_dir

            file_path = os.path.join(uploads_dir, file_name)
            try:
                with open(file_path, "wb") as f:
                    f.write(file_data)
                self._send_json(200, {"status": "ok", "path": file_path})
            except Exception as e:
                self._send_json(500, {"status": "error", "error": str(e)})
            return

        # ── POST /api/start_job  (NUEVO: lanza migración en segundo plano)
        if self.path == "/api/start_job":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)
            try:
                payload = json.loads(post_data.decode("utf-8"))
            except Exception as e:
                self._send_json(400, {"error": f"JSON inválido: {e}"})
                return

            engine_dir = os.path.dirname(os.path.abspath(__file__))
            venv_python = (
                os.path.join(engine_dir, ".venv", "Scripts", "python.exe")
                if sys.platform == "win32"
                else os.path.join(engine_dir, ".venv", "bin", "python")
            )
            python_exe = venv_python if os.path.exists(venv_python) else sys.executable
            main_script = os.path.join(engine_dir, "main.py")

            # Resolver el email del usuario a partir del token de sesión
            to_email: str | None = None
            session_token = payload.get("session_token")
            if session_token:
                try:
                    import db_manager
                    to_email = db_manager.get_user_email(session_token)
                    if to_email:
                        sys.stderr.write(f"[INFO] Email de resumen se enviará a: {to_email}\n")
                except Exception as e:
                    sys.stderr.write(f"[WARNING] No se pudo resolver el email del usuario: {e}\n")

            job_id = str(uuid.uuid4())
            job = Job(job_id)
            with JOBS_LOCK:
                JOBS[job_id] = job

            t = threading.Thread(
                target=_run_job_in_background,
                args=(job, payload, engine_dir, python_exe, main_script, to_email),
                daemon=True,
            )
            t.start()

            self._send_json(200, {"status": "ok", "job_id": job_id})
            return

        # ── POST /api  (compatibilidad con MigrationWizard / migrador Excel)
        if self.path == "/api":
            global LOG_QUEUE
            LOG_QUEUE = []

            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)

            try:
                payload = json.loads(post_data.decode("utf-8"))

                # Resolver el email del usuario a partir del token de sesión (opcional)
                to_email: str | None = None
                session_token = payload.get("session_token")
                if session_token:
                    try:
                        import db_manager
                        to_email = db_manager.get_user_email(session_token)
                    except Exception:
                        pass

                started_at = datetime.now()

                engine_dir = os.path.dirname(os.path.abspath(__file__))
                try:
                    cmd_name = payload.get("command", "unknown")
                    with open(os.path.join(engine_dir, f"_req_{cmd_name}.json"), "w", encoding="utf-8") as req_file:
                        json.dump(payload, req_file, ensure_ascii=False, indent=2)
                except Exception as write_err:
                    sys.stderr.write(f"No se pudo escribir _req: {write_err}\n")

                venv_python = (
                    os.path.join(engine_dir, ".venv", "Scripts", "python.exe")
                    if sys.platform == "win32"
                    else os.path.join(engine_dir, ".venv", "bin", "python")
                )
                python_exe = venv_python if os.path.exists(venv_python) else sys.executable
                main_script = os.path.join(engine_dir, "main.py")

                process = subprocess.Popen(
                    [python_exe, main_script],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
                process.stdin.write(json.dumps(payload))
                process.stdin.close()

                logs_dir = os.path.join(engine_dir, "logs")
                os.makedirs(logs_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
                cmd_name = payload.get("command", "unknown")
                log_file_path = os.path.join(logs_dir, f"{cmd_name}_{timestamp}.log")

                def log_stderr(pipe):
                    try:
                        with open(log_file_path, "a", encoding="utf-8") as log_file:
                            for line in iter(pipe.readline, ""):
                                sys.stderr.write(line)
                                sys.stderr.flush()
                                global LOG_QUEUE
                                LOG_QUEUE.append(line.strip())
                                log_file.write(line)
                                log_file.flush()
                    except Exception:
                        pass

                stderr_thread = threading.Thread(target=log_stderr, args=(process.stderr,), daemon=True)
                stderr_thread.start()

                stdout_data = process.stdout.read()
                process.wait()
                stderr_thread.join(timeout=1.0)
                
                finished_at = datetime.now()
                duration_seconds = (finished_at - started_at).total_seconds()

                if stdout_data.strip():
                    try:
                        result_dict = json.loads(stdout_data)
                        if result_dict.get("status") == "ok":
                            if cmd_name in ("run_migration", "run_odoo_migration"):
                                _send_summary_email(
                                    to_email=to_email,
                                    status="done",
                                    payload=payload,
                                    result=result_dict.get("data", {}),
                                    log_file_path=log_file_path,
                                    started_at=started_at,
                                    finished_at=finished_at,
                                    duration_seconds=duration_seconds,
                                )
                        else:
                            if cmd_name in ("run_migration", "run_odoo_migration"):
                                _send_summary_email(
                                    to_email=to_email,
                                    status="error",
                                    payload=payload,
                                    result={},
                                    log_file_path=log_file_path,
                                    started_at=started_at,
                                    finished_at=finished_at,
                                    duration_seconds=duration_seconds,
                                    error=result_dict.get("error", "Error desconocido"),
                                )
                        self._send_json(200, result_dict)
                    except json.JSONDecodeError:
                        self._send_json(200, {"status": "error", "error": "Respuesta JSON inválida"})
                else:
                    self._send_json(200, {"status": "error", "error": "Sin respuesta"})

            except Exception as e:
                self._send_json(500, {"status": "error", "error": f"Error en el servidor bridge: {str(e)}"})
            return

        self.send_response(404)
        self.end_headers()


# ─── Arranque ──────────────────────────────────────────────────────────────────

def run_server():
    server_address = ("", PORT)
    httpd = ThreadingHTTPServer(server_address, PythonBridgeHandler)
    print("=" * 60)
    print(f" Servidor del Motor Python activo en: http://localhost:{PORT}")
    print(f" Endpoints disponibles:")
    print(f"   POST /api            → migración síncrona (Excel / CSV)")
    print(f"   POST /api/start_job  → lanza migración en segundo plano")
    print(f"   GET  /api/job/<id>   → estado de un job en segundo plano")
    print(f"   GET  /api/logs       → logs del proceso síncrono actual")
    print(f"   POST /api/upload     → sube un archivo al servidor")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor apagado.")


if __name__ == "__main__":
    run_server()
