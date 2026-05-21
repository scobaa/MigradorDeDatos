"""
Conector de lectura para bases de datos Microsoft Access (.mdb / .accdb).

Usa pyodbc con el driver "Microsoft Access Driver (*.mdb, *.accdb)" que forma
parte del Microsoft Access Database Engine (en Windows). Si el driver no está
instalado, se lanza un error con instrucciones claras.

Patrón de uso:

    with AccessConnector(path) as conn:
        tablas = conn.list_tables()
        meta = conn.analyze("Clientes")          # columnas + nº filas + muestra
        for fila in conn.iter_rows("Clientes"):  # streaming, fila a fila
            ...

Responsabilidad única: LEER. No limpia ni transforma datos (eso es de
transformers/), no escribe en Odoo (eso es de migrator/).
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

log = logging.getLogger(__name__)

# Nombre del driver ODBC de Access en Windows.
ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"

# Número de filas de muestra que devuelve analyze() por defecto.
DEFAULT_SAMPLE_SIZE = 10


class AccessDriverNotFound(RuntimeError):
    """El driver ODBC de Access no está instalado en el sistema."""


class AccessConnector:
    """Lectura de tablas de un fichero Access vía ODBC."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: Any = None  # pyodbc.Connection (import perezoso)

    # ─── Ciclo de vida / conexión ──────────────────────────────

    def connect(self) -> None:
        """Abre la conexión ODBC. Lanza AccessDriverNotFound o FileNotFoundError."""
        import os

        if not os.path.isfile(self.path):
            raise FileNotFoundError(f"No existe el fichero Access: {self.path}")

        try:
            import pyodbc
        except ImportError as e:  # pragma: no cover - entorno sin pyodbc
            raise RuntimeError(
                "pyodbc no está instalado. Ejecuta: pip install pyodbc"
            ) from e

        if ACCESS_DRIVER not in pyodbc.drivers():
            disponibles = ", ".join(pyodbc.drivers()) or "(ninguno)"
            raise AccessDriverNotFound(
                f"No se encontró el driver '{ACCESS_DRIVER}'. "
                "Instala 'Microsoft Access Database Engine 2016 Redistributable' "
                "(misma arquitectura que tu Python: 64-bit). "
                f"Drivers ODBC disponibles: {disponibles}"
            )

        conn_str = f"DRIVER={{{ACCESS_DRIVER}}};DBQ={self.path};"
        log.info("Conectando a Access: %s", self.path)
        self._conn = pyodbc.connect(conn_str, readonly=True)

        # El driver de Access devuelve texto como UTF-16; algunos ERPs (FactuSOL,
        # etc.) guardan registros con bytes corruptos (surrogates sueltos) que
        # rompen la decodificación estricta de pyodbc. Registramos conversores
        # tolerantes (errors="replace") para los tipos de texto ancho.
        def _decode_wide(raw: bytes) -> str:
            return raw.decode("utf-16-le", errors="replace") if raw else ""

        for sql_wide_type in (
            pyodbc.SQL_WCHAR,
            pyodbc.SQL_WVARCHAR,
            pyodbc.SQL_WLONGVARCHAR,
        ):
            self._conn.add_output_converter(sql_wide_type, _decode_wide)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "AccessConnector":
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _require_conn(self) -> Any:
        if self._conn is None:
            raise RuntimeError("Llamar connect() (o usar 'with') antes de leer")
        return self._conn

    # ─── Metadatos ─────────────────────────────────────────────

    def list_tables(self) -> list[str]:
        """Devuelve los nombres de tablas de usuario (excluye tablas de sistema)."""
        conn = self._require_conn()
        cursor = conn.cursor()
        tablas = [
            row.table_name
            for row in cursor.tables(tableType="TABLE")
            if not row.table_name.startswith("MSys")
        ]
        log.info("Tablas encontradas en %s: %s", self.path, tablas)
        return tablas

    def get_columns(self, table: str) -> list[str]:
        """Nombres de columna de una tabla, en orden."""
        conn = self._require_conn()
        cursor = conn.cursor()
        cols = [row.column_name for row in cursor.columns(table=table)]
        if not cols:
            raise ValueError(f"La tabla '{table}' no existe o no tiene columnas")
        return cols

    def count_rows(self, table: str) -> int:
        """Número total de filas de la tabla."""
        conn = self._require_conn()
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
        return int(cursor.fetchone()[0])

    # ─── Lectura de filas ──────────────────────────────────────

    def iter_rows(
        self, table: str, columns: list[str] | None = None, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """
        Itera las filas de una tabla como dicts {columna: valor}, en streaming.

        Preferir esto a read_table() para tablas grandes: no carga todo en memoria.
        """
        conn = self._require_conn()
        cursor = conn.cursor()

        col_sql = (
            ", ".join(f"[{c}]" for c in columns) if columns else "*"
        )
        top = f"TOP {int(limit)} " if limit else ""
        cursor.execute(f"SELECT {top}{col_sql} FROM [{table}]")

        col_names = [d[0] for d in cursor.description]
        for row in cursor:
            yield dict(zip(col_names, row))

    def read_table(
        self, table: str, columns: list[str] | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Lee la tabla entera (o hasta `limit`) en una lista de dicts."""
        return list(self.iter_rows(table, columns=columns, limit=limit))

    def analyze(
        self, table: str, sample_size: int = DEFAULT_SAMPLE_SIZE
    ) -> dict[str, Any]:
        """
        Devuelve metadatos de una tabla para el wizard de migración:
        columnas, nº total de filas y una muestra de las primeras `sample_size`.
        """
        columns = self.get_columns(table)
        row_count = self.count_rows(table)
        sample = self.read_table(table, limit=sample_size)
        return {
            "table": table,
            "columns": columns,
            "row_count": row_count,
            "sample_rows": sample,
        }
