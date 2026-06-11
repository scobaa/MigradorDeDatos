import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

# Servidor HTTP multihilo para permitir peticiones concurrentes (como consultar logs de la migración en curso)
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

PORT = 8000
LOG_QUEUE = []

class PythonBridgeHandler(BaseHTTPRequestHandler):
    def _send_response_json(self, status, data_bytes):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data_bytes)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data_bytes)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/logs":
            global LOG_QUEUE
            data_bytes = json.dumps({"logs": LOG_QUEUE}).encode("utf-8")
            self._send_response_json(200, data_bytes)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/api":
            self.send_response(404)
            self.end_headers()
            return

        global LOG_QUEUE
        LOG_QUEUE = []

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            # Validar que sea JSON
            payload = json.loads(post_data.decode("utf-8"))
            
            # Guardar el payload según el comando para depuración
            engine_dir = os.path.dirname(os.path.abspath(__file__))
            try:
                cmd_name = payload.get("command", "unknown")
                with open(os.path.join(engine_dir, f"_req_{cmd_name}.json"), "w", encoding="utf-8") as req_file:
                    json.dump(payload, req_file, ensure_ascii=False, indent=2)
            except Exception as write_err:
                sys.stderr.write(f"No se pudo escribir _req: {write_err}\n")
            
            # Ejecutar main.py como subproceso
            # Buscamos el ejecutable de Python del venv si existe
            venv_python = os.path.join(engine_dir, ".venv", "Scripts", "python.exe") if sys.platform == "win32" else os.path.join(engine_dir, ".venv", "bin", "python")
            
            python_exe = venv_python if os.path.exists(venv_python) else sys.executable
            main_script = os.path.join(engine_dir, "main.py")

            # Ejecutar
            process = subprocess.Popen(
                [python_exe, main_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8"
            )

            # Escribir payload a stdin y cerrar para comenzar la ejecución
            process.stdin.write(json.dumps(payload))
            process.stdin.close()

            # Leer y volcar stderr en tiempo real a la consola del servidor y a un archivo de log
            import threading
            log_file_path = os.path.join(engine_dir, "migration_debug.log")
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

            stderr_thread = threading.Thread(target=log_stderr, args=(process.stderr,))
            stderr_thread.daemon = True
            stderr_thread.start()

            # Leer la salida del comando (stdout) y esperar a que el proceso termine
            stdout_data = process.stdout.read()
            process.wait()
            stderr_thread.join(timeout=1.0)

            # Devolver respuesta
            response_bytes = stdout_data.encode("utf-8")
            self._send_response_json(200, response_bytes)

        except Exception as e:
            response = {"status": "error", "error": f"Error en el servidor bridge: {str(e)}"}
            response_bytes = json.dumps(response).encode("utf-8")
            self._send_response_json(500, response_bytes)

def run_server():
    server_address = ("", PORT)
    httpd = ThreadingHTTPServer(server_address, PythonBridgeHandler)
    print("=" * 60)
    print(f" Servidor de desarrollo del Motor Python activo en: http://localhost:{PORT}")
    print(f" Ejecuta tu frontend web con: npm run dev")
    print(f" Si tienes problemas con WatchGuard en Tauri, este modo web te permitirá")
    print(f" usar el motor Python y leer tus archivos locales sin restricciones.")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor apagado.")

if __name__ == "__main__":
    run_server()
