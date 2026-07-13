import logging
from dataclasses import dataclass
from typing import Any, Generator

from migrator.base import BaseMigrator, MigrationStats
from migrator.odoo_client import OdooClient
from migrator.odoo_source import _emit_progress

log = logging.getLogger(__name__)

ACCOUNT_MODEL = "account.account"


@dataclass
class MigrationOptions:
    update_existing: bool = True
    batch_size: int = 100


class AccountMigrator(BaseMigrator):
    def __init__(self, odoo: OdooClient, mapping: dict[str, str], options: MigrationOptions) -> None:
        super().__init__(odoo, mapping)
        self.options = options
        self._cache_accounts: dict[str, int] = {}  # code -> id

    def _preload_cache(self) -> None:
        log.info("Pre-cargando cuentas contables en destino...")
        try:
            records = self.odoo.search_read(ACCOUNT_MODEL, [], ["code"])
            for r in records:
                if r.get("code"):
                    self._cache_accounts[str(r["code"])] = r["id"]
        except Exception as e:
            log.warning("No se pudo pre-cargar las cuentas del destino: %s", e)
            
    def run(
        self,
        rows: Generator[dict[str, Any], None, None],
        total: int = 0,
        dry_run: bool = False
    ) -> MigrationStats:
        stats = MigrationStats()
        self._preload_cache()

        for idx, row in enumerate(rows, 1):
            vals = self.transform_row(row)
            
            code = vals.get("code")
            if not code:
                log.warning("Fila %s no tiene código de cuenta. Se ignora.", idx)
                _emit_progress({
                    "action": "skipped", "done": idx, "total": total,
                    "name": vals.get("name", "Desconocido"),
                    "message": "Falta el código de cuenta"
                })
                stats.skipped += 1
                continue
                
            code_str = str(code)
            existing_id = self._cache_accounts.get(code_str)

            if existing_id:
                if self.options.update_existing:
                    # En Odoo 15+ "user_type_id" se reemplaza por "account_type",
                    # pero intentaremos mandar lo que tengamos limpiando vacíos
                    update_vals = {k: v for k, v in vals.items() if v is not None}
                    
                    if not dry_run:
                        try:
                            self.odoo.write(ACCOUNT_MODEL, [existing_id], update_vals)
                            _emit_progress({
                                "action": "updated", "done": idx, "total": total,
                                "name": f"[{code_str}] {vals.get('name', '')}"
                            })
                            stats.updated += 1
                        except Exception as e:
                            log.error("Error actualizando cuenta %s: %s", code_str, e)
                            _emit_progress({
                                "action": "error", "done": idx, "total": total,
                                "name": f"[{code_str}] {vals.get('name', '')}",
                                "message": str(e)
                            })
                            stats.errors += 1
                            stats.error_details.append({"row": idx, "error": str(e)})
                    else:
                        _emit_progress({
                            "action": "updated", "done": idx, "total": total,
                            "name": f"[{code_str}] {vals.get('name', '')}"
                        })
                        stats.updated += 1
                else:
                    _emit_progress({
                        "action": "skipped", "done": idx, "total": total,
                        "name": f"[{code_str}] {vals.get('name', '')}",
                        "message": "La cuenta ya existe y update_existing es False"
                    })
                    stats.skipped += 1
            else:
                create_vals = {k: v for k, v in vals.items() if v is not None}
                
                if not dry_run:
                    try:
                        new_id = self.odoo.create(ACCOUNT_MODEL, create_vals)
                        self._cache_accounts[code_str] = new_id
                        _emit_progress({
                            "action": "created", "done": idx, "total": total,
                            "name": f"[{code_str}] {vals.get('name', '')}"
                        })
                        stats.created += 1
                    except Exception as e:
                        log.error("Error creando cuenta %s: %s", code_str, e)
                        _emit_progress({
                            "action": "error", "done": idx, "total": total,
                            "name": f"[{code_str}] {vals.get('name', '')}",
                            "message": str(e)
                        })
                        stats.errors += 1
                        stats.error_details.append({"row": idx, "error": str(e)})
                else:
                    _emit_progress({
                        "action": "created", "done": idx, "total": total,
                        "name": f"[{code_str}] {vals.get('name', '')}"
                    })
                    stats.created += 1

        return stats
