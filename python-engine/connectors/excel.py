from __future__ import annotations

import logging
import os
from typing import Any, Iterator

log = logging.getLogger(__name__)

DEFAULT_SAMPLE_SIZE = 10


class ExcelConnector:
    """Lectura de hojas (sheets) de un fichero Excel (.xlsx / .xls) usando Pandas."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._excel_file: Any = None

    def connect(self) -> None:
        if not os.path.isfile(self.path):
            raise FileNotFoundError(f"No existe el fichero Excel: {self.path}")
        
        try:
            import pandas as pd  # noqa: F401 - validación de instalación
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "pandas u openpyxl no están instalados. Ejecuta: pip install pandas openpyxl"
            ) from e

        import pandas as pd
        log.info("Abriendo archivo Excel: %s", self.path)
        self._excel_file = pd.ExcelFile(self.path)

    def close(self) -> None:
        self._excel_file = None

    def __enter__(self) -> ExcelConnector:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _require_file(self) -> Any:
        if self._excel_file is None:
            raise RuntimeError("Llamar connect() antes de leer")
        return self._excel_file

    def list_tables(self) -> list[str]:
        """Devuelve los nombres de las hojas (sheets) en el Excel."""
        excel = self._require_file()
        sheets = excel.sheet_names
        log.info("Hojas encontradas en Excel: %s", sheets)
        return sheets

    def get_columns(self, table: str) -> list[str]:
        """Nombres de columna de una hoja."""
        import pandas as pd
        excel = self._require_file()
        if table not in excel.sheet_names:
            raise ValueError(f"La hoja '{table}' no existe en el archivo Excel")
        
        df = pd.read_excel(self.path, sheet_name=table, nrows=0)
        return list(df.columns)

    def count_rows(self, table: str) -> int:
        """Número total de filas de datos (excluyendo cabecera)."""
        import pandas as pd
        excel = self._require_file()
        if table not in excel.sheet_names:
            raise ValueError(f"La hoja '{table}' no existe en el archivo Excel")
        
        df = pd.read_excel(self.path, sheet_name=table)
        return len(df)

    def iter_rows(
        self, table: str, columns: list[str] | None = None, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Itera las filas de una hoja de Excel como dicts {columna: valor}."""
        import pandas as pd
        excel = self._require_file()
        if table not in excel.sheet_names:
            raise ValueError(f"La hoja '{table}' no existe en el archivo Excel")

        # Cargar los datos
        df = pd.read_excel(self.path, sheet_name=table)
        
        if columns:
            cols_to_use = [c for c in columns if c in df.columns]
            df = df[cols_to_use]
        
        if limit:
            df = df.head(limit)

        for row in df.to_dict(orient="records"):
            clean_row = {}
            for k, v in row.items():
                if pd.isna(v):
                    clean_row[k] = None
                else:
                    clean_row[k] = v
            yield clean_row

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
