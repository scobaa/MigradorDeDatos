"""
Migrador Odoo→Odoo para facturas (account.move).
"""

import logging
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from migrator.invoices import InvoiceMigrator, MigrationOptions, MigrationStats, _emit_progress

log = logging.getLogger(__name__)

class OdooInvoiceMigrator(InvoiceMigrator):
    """
    Extiende InvoiceMigrator para migrar de Odoo a Odoo.
    A diferencia de Excel, aquí recibimos las facturas (cabeceras) desde iter_rows
    y consultamos las líneas (account.move.line) directamente al Odoo origen.
    """
    def __init__(
        self,
        odoo: OdooClient,
        odoo_src: OdooClient,
        mapping: dict[str, str],
        options: MigrationOptions | None = None,
        move_type: str = "out_invoice",
    ) -> None:
        super().__init__(odoo, mapping, options, move_type)
        self.odoo_src = odoo_src

    def run(self, rows: Iterable[dict[str, Any]], total: int = 0, dry_run: bool = False) -> MigrationStats:
        stats = MigrationStats()

        for idx, header in enumerate(rows, 1):
            name = header.get("name", "Desconocida")
            line_ids = header.get("invoice_line_ids", [])
            
            # 1. Obtener líneas del origen
            lines_data = []
            try:
                if line_ids:
                    lines_data = self.odoo_src.execute(
                        "account.move.line",
                        "read",
                        line_ids,
                        ["product_id", "name", "quantity", "price_unit", "discount", "tax_ids", "account_id", "display_type"]
                    )
            except Exception as e:
                log.warning("Factura %s (%s): Error leyendo líneas: %s", idx, name, e)
                _emit_progress({"action": "error", "done": idx, "total": total, "name": name, "error": f"Error leyendo líneas: {e}"})
                stats.errors.append({"row": idx, "error": f"Error leyendo líneas: {e}"})
                stats.error_count = getattr(stats, "error_count", 0) + 1 if hasattr(stats, "error_count") else len(stats.errors)
                continue

            vals = self.transform_row(header)
            
            # 2. Construir la cabecera + líneas para crear en destino
            partner_name = vals.get("partner_id")
            partner_id = self._resolve_partner(partner_name)
            if not partner_id:
                log.warning("Factura %s (%s): Partner '%s' no encontrado. Ignorada.", idx, name, partner_name)
                _emit_progress({
                    "action": "skipped", "done": idx, "total": total,
                    "name": name, "message": f"Partner '{partner_name}' no encontrado"
                })
                stats.skipped += 1
                stats.errors.append({"row": idx, "error": f"Partner '{partner_name}' no encontrado"})
                continue

            # Preparar líneas
            odoo_lines = []
            for line in lines_data:
                # Si es una sección o nota
                display_type = line.get("display_type")
                if display_type in ("line_section", "line_note"):
                    odoo_lines.append((0, 0, {
                        "display_type": display_type,
                        "name": line.get("name", ""),
                    }))
                    continue

                product_code = None
                if line.get("product_id"):
                    product_code = line["product_id"][1]
                
                prod_id = self._resolve_product(product_code)
                
                # taxes
                tax_ids = []
                src_tax_ids = line.get("tax_ids", [])
                if src_tax_ids:
                    try:
                        src_taxes = self.odoo_src.execute("account.tax", "read", src_tax_ids, ["name"])
                        for st in src_taxes:
                            t_id = self._resolve_tax(st.get("name"), tax_use="sale" if self.move_type == "out_invoice" else "purchase")
                            if t_id:
                                tax_ids.append((4, t_id))
                    except Exception as e:
                        log.warning("Factura %s (%s): Error leyendo impuestos: %s", idx, name, e)

                line_vals = {
                    "name": line.get("name", ""),
                    "quantity": line.get("quantity", 1),
                    "price_unit": line.get("price_unit", 0),
                    "discount": line.get("discount", 0),
                    "tax_ids": tax_ids,
                }
                if prod_id:
                    line_vals["product_id"] = prod_id
                
                odoo_lines.append((0, 0, line_vals))

            invoice_vals = {
                "move_type": self.move_type,
                "partner_id": partner_id,
                "invoice_date": vals.get("invoice_date"),
                "invoice_date_due": vals.get("invoice_date_due"),
                "ref": vals.get("ref"),
                "narration": vals.get("narration"),
                "invoice_line_ids": odoo_lines,
            }
            if self.options.format_name and name and name != "/":
                invoice_vals["name"] = name

            if dry_run:
                _emit_progress({"action": "created", "done": idx, "total": total, "name": name})
                stats.created += 1
                continue

            try:
                existing_id = None
                if name and name != "/":
                    ids = self.odoo.search("account.move", [("name", "=", name), ("move_type", "=", self.move_type)])
                    if ids:
                        existing_id = ids[0]

                if existing_id and self.options.update_existing:
                    state = self.odoo.execute("account.move", "read", [existing_id], ["state"])[0].get("state")
                    if state == "posted":
                        _emit_progress({
                            "action": "skipped", "done": idx, "total": total,
                            "name": name, "message": "Factura ya existe y está publicada"
                        })
                        stats.skipped += 1
                    else:
                        self.odoo.execute("account.move", "write", [existing_id], {"invoice_line_ids": [(5, 0, 0)] + odoo_lines})
                        self.odoo.execute("account.move", "write", [existing_id], invoice_vals)
                        _emit_progress({"action": "updated", "done": idx, "total": total, "name": name})
                        stats.updated += 1
                elif not existing_id:
                    new_id = self.odoo.execute("account.move", "create", invoice_vals)
                    _emit_progress({"action": "created", "done": idx, "total": total, "name": name})
                    stats.created += 1
                else:
                    _emit_progress({
                        "action": "skipped", "done": idx, "total": total,
                        "name": name, "message": "Ya existe y update_existing=False"
                    })
                    stats.skipped += 1
            except Exception as e:
                log.warning("Factura %s (%s): Error: %s", idx, name, e)
                _emit_progress({"action": "error", "done": idx, "total": total, "name": name, "error": str(e)})
                stats.errors.append({"row": idx, "error": str(e)})

        return stats
