from __future__ import annotations

import logging
import os
from typing import Any, Iterator

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_SIZE = 10


class CsvConnector:
    """Lectura de un fichero CSV (.csv) usando Pandas con auto-detección de delimitador."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._sep: str = ","

    def connect(self) -> None:
        if not os.path.isfile(self.path):
            raise FileNotFoundError(f"No existe el fichero CSV: {self.path}")
        
        # Detectar el delimitador leyendo la primera línea
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                first_line = f.readline()
            
            delims = {";": first_line.count(";"), ",": first_line.count(","), "\t": first_line.count("\t")}
            best_delim = max(delims, key=delims.get)
            self._sep = best_delim if delims[best_delim] > 0 else ","
            log.info("Separador detectado para CSV '%s': '%s'", self.path, self._sep)
        except Exception as e:
            log.warning("Fallo al auto-detectar separador de CSV, usando coma: %s", e)
            self._sep = ","

    def close(self) -> None:
        pass

    def __enter__(self) -> CsvConnector:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_tables(self) -> list[str]:
        """El CSV tiene una única tabla virtual llamada 'CSV'."""
        return ["CSV"]

    def get_columns(self, table: str) -> list[str]:
        """Nombres de columna del fichero CSV."""
        import pandas as pd
        df = pd.read_csv(self.path, sep=self._sep, nrows=0, encoding="utf-8")
        return list(df.columns)

    def count_rows(self, table: str) -> int:
        """Número total de registros (filas de datos)."""
        import pandas as pd
        df = pd.read_csv(self.path, sep=self._sep, usecols=[0], encoding="utf-8")
        return len(df)

    def iter_rows(
        self, table: str, columns: list[str] | None = None, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Itera las filas del CSV como dicts {columna: valor}."""
        import pandas as pd

        df = pd.read_csv(self.path, sep=self._sep, encoding="utf-8")
        
        if columns:
            cols_to_use = [c for c in columns if c in df.columns]
            df = df[cols_to_use]
        
        if limit:
            df = df.head(limit)

        # Reemplazar NaN con None
        df = df.where(pd.notnull(df), None)

        for _, row in df.iterrows():
            yield row.to_dict()

    def read_table(
        self, table: str, columns: list[str] | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        return list(self.iter_rows(table, columns=columns, limit=limit))

    def analyze(
        self, table: str, sample_size: int = DEFAULT_SAMPLE_SIZE
    ) -> dict[str, Any]:
        columns = self.get_columns(table)
        row_count = self.count_rows(table)
        sample = self.read_table(table, limit=sample_size)
        return {
            "table": table,
            "columns": columns,
            "row_count": row_count,
            "sample_rows": sample,
        }
