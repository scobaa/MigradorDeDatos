"""
Conector de lectura para bases de datos Microsoft Access (.mdb / .accdb).

En Windows: Usa pyodbc con el driver "Microsoft Access Driver (*.mdb, *.accdb)".
En Linux: Usa mdbtools (mdb-tables, mdb-export) vía subprocesos.

Patrón de uso:

    with AccessConnector(path) as conn:
        tablas = conn.list_tables()
        meta = conn.analyze("Clientes")
        for fila in conn.iter_rows("Clientes"):
            ...
"""

from __future__ import annotations

import logging
import os
import subprocess
import csv
from io import StringIO
from typing import Any, Iterator

log = logging.getLogger(__name__)

ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"
DEFAULT_SAMPLE_SIZE = 10

class AccessDriverNotFound(RuntimeError):
    pass

class AccessConnector:
    def __init__(self, path: str) -> None:
        self.path = path
        self.is_windows = os.name == 'nt'
        self._conn: Any = None

    def connect(self) -> None:
        if not os.path.isfile(self.path):
            raise FileNotFoundError(f"No existe el fichero Access: {self.path}")

        if self.is_windows:
            try:
                import pyodbc
            except ImportError as e:
                raise RuntimeError("pyodbc no está instalado. Ejecuta: pip install pyodbc") from e

            if ACCESS_DRIVER not in pyodbc.drivers():
                disponibles = ", ".join(pyodbc.drivers()) or "(ninguno)"
                raise AccessDriverNotFound(
                    f"No se encontró el driver '{ACCESS_DRIVER}'. "
                    "Instala 'Microsoft Access Database Engine 2016 Redistributable'. "
                    f"Drivers ODBC disponibles: {disponibles}"
                )

            conn_str = f"DRIVER={{{ACCESS_DRIVER}}};DBQ={self.path};"
            log.info("Conectando a Access (Windows): %s", self.path)
            self._conn = pyodbc.connect(conn_str, readonly=True, timeout=5)

            def _decode_wide(raw: bytes) -> str:
                return raw.decode("utf-16-le", errors="replace") if raw else ""

            for sql_wide_type in (pyodbc.SQL_WCHAR, pyodbc.SQL_WVARCHAR, pyodbc.SQL_WLONGVARCHAR):
                self._conn.add_output_converter(sql_wide_type, _decode_wide)
        else:
            log.info("Conectando a Access (Linux vía mdbtools): %s", self.path)
            # Verificar que mdbtools está instalado
            try:
                subprocess.run(["mdb-tables", "--version"], capture_output=True, check=False)
            except FileNotFoundError:
                raise AccessDriverNotFound("mdbtools no está instalado. Ejecuta: apt-get install mdbtools")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "AccessConnector":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_tables(self) -> list[str]:
        if self.is_windows:
            if not self._conn:
                raise RuntimeError("Llamar connect() antes de leer")
            cursor = self._conn.cursor()
            tablas = [
                row.table_name
                for row in cursor.tables()
                if not row.table_name.startswith("MSys") and row.table_type in ("TABLE", "VIEW")
            ]
        else:
            res_tables = subprocess.run(["mdb-tables", "-1", "-t", "table", self.path], capture_output=True, text=True, check=True)
            res_queries = subprocess.run(["mdb-tables", "-1", "-t", "query", self.path], capture_output=True, text=True, check=False)
            
            lines = res_tables.stdout.splitlines()
            if res_queries.returncode == 0:
                lines.extend(res_queries.stdout.splitlines())
                
            tablas = [t.strip() for t in lines if t.strip() and not t.startswith("MSys")]
        
        log.info("Tablas encontradas en %s: %s", self.path, tablas)
        return tablas

    def get_columns(self, table: str) -> list[str]:
        if self.is_windows:
            if not self._conn:
                raise RuntimeError("Llamar connect() antes de leer")
            cursor = self._conn.cursor()
            cols = [row.column_name for row in cursor.columns(table=table)]
            if not cols:
                raise ValueError(f"La tabla '{table}' no existe o no tiene columnas")
            return cols
        else:
            proc = subprocess.Popen(["mdb-export", self.path, table], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            reader = csv.reader(proc.stdout)
            try:
                cols = next(reader)
            except StopIteration:
                err_output = proc.stderr.read().strip()
                raise ValueError(f"La tabla/consulta '{table}' no existe, no tiene columnas, o no es soportada por mdbtools. Error interno: {err_output}")
            proc.terminate()
            return cols

    def count_rows(self, table: str) -> int:
        if self.is_windows:
            if not self._conn:
                raise RuntimeError("Llamar connect() antes de leer")
            cursor = self._conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
            return int(cursor.fetchone()[0])
        else:
            proc1 = subprocess.Popen(["mdb-export", self.path, table], stdout=subprocess.PIPE)
            proc2 = subprocess.Popen(["wc", "-l"], stdin=proc1.stdout, stdout=subprocess.PIPE, text=True)
            proc1.stdout.close()
            out, _ = proc2.communicate()
            lines = int(out.strip())
            return max(0, lines - 1)

    def iter_rows(self, table: str, columns: list[str] | None = None, limit: int | None = None) -> Iterator[dict[str, Any]]:
        if self.is_windows:
            if not self._conn:
                raise RuntimeError("Llamar connect() antes de leer")
            cursor = self._conn.cursor()
            col_sql = ", ".join(f"[{c}]" for c in columns) if columns else "*"
            top = f"TOP {int(limit)} " if limit else ""
            cursor.execute(f"SELECT {top}{col_sql} FROM [{table}]")
            col_names = [d[0] for d in cursor.description]
            for row in cursor:
                yield dict(zip(col_names, row))
        else:
            proc = subprocess.Popen(["mdb-export", self.path, table], stdout=subprocess.PIPE, text=True)
            reader = csv.DictReader(proc.stdout)
            count = 0
            for row in reader:
                if columns:
                    yield {k: v for k, v in row.items() if k in columns}
                else:
                    yield dict(row)
                count += 1
                if limit and count >= limit:
                    break
            proc.terminate()

    def read_table(self, table: str, columns: list[str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        return list(self.iter_rows(table, columns=columns, limit=limit))

    def analyze(self, table: str, sample_size: int = DEFAULT_SAMPLE_SIZE) -> dict[str, Any]:
        columns = self.get_columns(table)
        row_count = self.count_rows(table)
        sample = self.read_table(table, limit=sample_size)
        return {
            "table": table,
            "columns": columns,
            "row_count": row_count,
            "sample_rows": sample,
        }
