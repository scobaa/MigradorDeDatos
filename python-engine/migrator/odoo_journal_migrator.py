"""
Migrador Odoo→Odoo para asientos contables (account.move con move_type=entry).
"""

import logging
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from migrator.journal import JournalMigrator, MigrationOptions, MigrationStats, _emit_progress

log = logging.getLogger(__name__)

class OdooJournalMigrator(JournalMigrator):
    """
    Extiende JournalMigrator para migrar asientos contables de Odoo a Odoo.
    A diferencia de Excel, aquí recibimos los asientos desde iter_rows
    y consultamos los apuntes (account.move.line) directamente al Odoo origen.
    """
    def __init__(
        self,
        odoo: OdooClient,
        odoo_src: OdooClient,
        mapping: dict[str, str],
        options: MigrationOptions | None = None,
    ) -> None:
        super().__init__(odoo, mapping, options)
        self.odoo_src = odoo_src

    def run(self, rows: Iterable[dict[str, Any]], total: int = 0, dry_run: bool = False) -> MigrationStats:
        stats = MigrationStats()

        for idx, header in enumerate(rows, 1):
            name = header.get("name", "Desconocido")
            line_ids = header.get("line_ids", [])
            
            lines_data = []
            if line_ids:
                lines_data = self.odoo_src.execute(
                    "account.move.line",
                    "read",
                    line_ids,
                    ["name", "account_id", "partner_id", "debit", "credit", "amount_currency", "currency_id", "display_type"]
                )

            vals = self.transform_row(header)

            # Para apuntes contables, el Journal es clave
            journal_name = vals.get("journal_id")
            journal_id = self._resolve_journal(journal_name)
            if not journal_id:
                log.warning("Asiento %s (%s): Diario '%s' no encontrado. Ignorado.", idx, name, journal_name)
                _emit_progress({
                    "action": "skipped", "done": idx, "total": total,
                    "name": name, "message": f"Diario '{journal_name}' no encontrado"
                })
                stats.skipped += 1
                stats.errors.append({"row": idx, "error": f"Diario '{journal_name}' no encontrado"})
                continue

            odoo_lines = []
            for line in lines_data:
                display_type = line.get("display_type")
                if display_type in ("line_section", "line_note"):
                    odoo_lines.append((0, 0, {
                        "display_type": display_type,
                        "name": line.get("name", ""),
                    }))
                    continue

                account_code = None
                if line.get("account_id"):
                    # El read da [id, code name]. Extraer código es arriesgado desde el display_name,
                    # así que lo leeremos desde el id.
                    acc_info = self.odoo_src.execute("account.account", "read", [line["account_id"][0]], ["code"])
                    if acc_info:
                        account_code = acc_info[0].get("code")
                
                acc_id = self._resolve_account(account_code)
                if not acc_id:
                    # Fallback a cuenta por defecto si existe (aunque para asientos debería ser obligatorio)
                    log.warning("Cuenta %s no encontrada, omitiendo apunte", account_code)
                    continue
                
                partner_id = None
                if line.get("partner_id"):
                    partner_id = self._resolve_partner(line["partner_id"][1])

                line_vals = {
                    "name": line.get("name", ""),
                    "account_id": acc_id,
                    "debit": line.get("debit", 0),
                    "credit": line.get("credit", 0),
                }
                if partner_id:
                    line_vals["partner_id"] = partner_id
                    
                # Moneda extranjera
                if line.get("amount_currency") and line.get("currency_id"):
                    curr_name = line["currency_id"][1]
                    curr_id = self._resolve_currency(curr_name)
                    if curr_id:
                        line_vals["amount_currency"] = line["amount_currency"]
                        line_vals["currency_id"] = curr_id
                
                odoo_lines.append((0, 0, line_vals))

            if not odoo_lines:
                _emit_progress({
                    "action": "skipped", "done": idx, "total": total,
                    "name": name, "message": "No hay apuntes válidos"
                })
                stats.skipped += 1
                stats.errors.append({"row": idx, "error": "No hay apuntes válidos (o cuentas no encontradas)"})
                continue

            move_vals = {
                "move_type": "entry",
                "journal_id": journal_id,
                "date": vals.get("date"),
                "ref": vals.get("ref"),
                "narration": vals.get("narration"),
                "line_ids": odoo_lines,
            }

            if dry_run:
                _emit_progress({"action": "created", "done": idx, "total": total, "name": name})
                stats.created += 1
                continue

            try:
                existing_id = None
                if name and name != "/":
                    ids = self.odoo.search("account.move", [("name", "=", name), ("move_type", "=", "entry")])
                    if ids:
                        existing_id = ids[0]

                if existing_id and self.options.update_existing:
                    state = self.odoo.execute("account.move", "read", [existing_id], ["state"])[0].get("state")
                    if state == "posted":
                        _emit_progress({
                            "action": "skipped", "done": idx, "total": total,
                            "name": name, "message": "Asiento ya existe y está publicado"
                        })
                        stats.skipped += 1
                    else:
                        self.odoo.execute("account.move", "write", [existing_id], {"line_ids": [(5, 0, 0)] + odoo_lines})
                        self.odoo.execute("account.move", "write", [existing_id], move_vals)
                        _emit_progress({"action": "updated", "done": idx, "total": total, "name": name})
                        stats.updated += 1
                elif not existing_id:
                    new_id = self.odoo.execute("account.move", "create", move_vals)
                    _emit_progress({"action": "created", "done": idx, "total": total, "name": name})
                    stats.created += 1
                else:
                    _emit_progress({
                        "action": "skipped", "done": idx, "total": total,
                        "name": name, "message": "Ya existe y update_existing=False"
                    })
                    stats.skipped += 1
            except Exception as e:
                log.warning("Asiento %s (%s): Error: %s", idx, name, e)
                _emit_progress({"action": "error", "done": idx, "total": total, "name": name, "error": str(e)})
                stats.errors.append({"row": idx, "error": str(e)})

        return stats
