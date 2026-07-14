"""
Migrador Odoo→Odoo para pedidos (sale.order y purchase.order).
"""

import logging
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from migrator.sales import SalesMigrator, MigrationOptions as SalesOptions, MigrationStats as SalesStats, _emit_progress as _emit_sales_progress
from migrator.purchases import PurchaseMigrator, MigrationOptions as PurchaseOptions, MigrationStats as PurchaseStats, _emit_progress as _emit_purchase_progress

log = logging.getLogger(__name__)

class OdooOrderMigrator:
    """
    Migra pedidos de venta (sale.order) y compra (purchase.order) de Odoo a Odoo.
    """
    def __init__(
        self,
        odoo: OdooClient,
        odoo_src: OdooClient,
        mapping: dict[str, str],
        model: str,
        options: dict | None = None,
    ) -> None:
        self.odoo = odoo
        self.odoo_src = odoo_src
        self.mapping = mapping
        self.model = model
        self.options = options or {}
        
        if self.model == "sale.order":
            self.base_migrator = SalesMigrator(odoo, mapping, SalesOptions(**{k:v for k,v in self.options.items() if hasattr(SalesOptions, k)}))
        else:
            self.base_migrator = PurchaseMigrator(odoo, mapping, PurchaseOptions(**{k:v for k,v in self.options.items() if hasattr(PurchaseOptions, k)}))

    def run(self, rows: Iterable[dict[str, Any]], total: int = 0, dry_run: bool = False) -> Any:
        if self.model == "sale.order":
            return self._run_sale(rows, total, dry_run)
        else:
            return self._run_purchase(rows, total, dry_run)

    def _run_sale(self, rows: Iterable[dict[str, Any]], total: int, dry_run: bool) -> SalesStats:
        stats = SalesStats()
        for idx, header in enumerate(rows, 1):
            name = header.get("name", "Desconocido")
            line_ids = header.get("order_line", [])
            
            lines_data = []
            if line_ids:
                lines_data = self.odoo_src.execute(
                    "sale.order.line",
                    "read",
                    line_ids,
                    ["product_id", "name", "product_uom_qty", "price_unit", "discount", "tax_id", "display_type"]
                )

            vals = self.base_migrator.transform_row(header)

            partner_name = vals.get("partner_id")
            partner_id = self.base_migrator._resolve_partner(partner_name)
            if not partner_id:
                log.warning("Pedido Venta %s (%s): Partner '%s' no encontrado. Ignorado.", idx, name, partner_name)
                _emit_sales_progress({
                    "action": "skipped", "done": idx, "total": total,
                    "name": name, "message": f"Partner '{partner_name}' no encontrado"
                })
                stats.skipped += 1
                stats.errors.append({"row": idx, "error": f"Partner '{partner_name}' no encontrado"})
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

                product_code = None
                if line.get("product_id"):
                    product_code = line["product_id"][1]
                
                prod_id = self.base_migrator._resolve_product(product_code)
                
                tax_ids = []
                src_tax_ids = line.get("tax_id", [])
                if src_tax_ids:
                    src_taxes = self.odoo_src.execute("account.tax", "read", src_tax_ids, ["name"])
                    for st in src_taxes:
                        t_id = self.base_migrator._resolve_tax(st.get("name"), tax_use="sale")
                        if t_id:
                            tax_ids.append((4, t_id))

                line_vals = {
                    "name": line.get("name", ""),
                    "product_uom_qty": line.get("product_uom_qty", 1),
                    "price_unit": line.get("price_unit", 0),
                    "discount": line.get("discount", 0),
                    "tax_id": tax_ids,
                }
                if prod_id:
                    line_vals["product_id"] = prod_id
                
                odoo_lines.append((0, 0, line_vals))

            order_vals = {
                "partner_id": partner_id,
                "date_order": vals.get("date_order"),
                "client_order_ref": vals.get("client_order_ref"),
                "note": vals.get("note"),
                "order_line": odoo_lines,
            }
            if name and name != "/":
                order_vals["name"] = name

            if dry_run:
                _emit_sales_progress({"action": "created", "done": idx, "total": total, "name": name})
                stats.created += 1
                continue

            try:
                existing_id = None
                if name and name != "/":
                    ids = self.odoo.search("sale.order", [("name", "=", name)])
                    if ids:
                        existing_id = ids[0]

                if existing_id and self.base_migrator.options.update_existing:
                    state = self.odoo.execute("sale.order", "read", [existing_id], ["state"])[0].get("state")
                    if state not in ("draft", "sent"):
                        _emit_sales_progress({
                            "action": "skipped", "done": idx, "total": total,
                            "name": name, "message": f"Pedido ya existe y está en estado {state}"
                        })
                        stats.skipped += 1
                    else:
                        self.odoo.execute("sale.order", "write", [existing_id], {"order_line": [(5, 0, 0)] + odoo_lines})
                        self.odoo.execute("sale.order", "write", [existing_id], order_vals)
                        _emit_sales_progress({"action": "updated", "done": idx, "total": total, "name": name})
                        stats.updated += 1
                elif not existing_id:
                    new_id = self.odoo.execute("sale.order", "create", order_vals)
                    _emit_sales_progress({"action": "created", "done": idx, "total": total, "name": name})
                    stats.created += 1
                else:
                    _emit_sales_progress({
                        "action": "skipped", "done": idx, "total": total,
                        "name": name, "message": "Ya existe y update_existing=False"
                    })
                    stats.skipped += 1
            except Exception as e:
                log.warning("Pedido Venta %s (%s): Error: %s", idx, name, e)
                _emit_sales_progress({"action": "error", "done": idx, "total": total, "name": name, "error": str(e)})
                stats.errors.append({"row": idx, "error": str(e)})

        return stats

    def _run_purchase(self, rows: Iterable[dict[str, Any]], total: int, dry_run: bool) -> PurchaseStats:
        stats = PurchaseStats()
        for idx, header in enumerate(rows, 1):
            name = header.get("name", "Desconocido")
            line_ids = header.get("order_line", [])
            
            lines_data = []
            if line_ids:
                lines_data = self.odoo_src.execute(
                    "purchase.order.line",
                    "read",
                    line_ids,
                    ["product_id", "name", "product_qty", "price_unit", "taxes_id", "display_type"]
                )

            vals = self.base_migrator.transform_row(header)

            partner_name = vals.get("partner_id")
            partner_id = self.base_migrator._resolve_partner(partner_name)
            if not partner_id:
                log.warning("Pedido Compra %s (%s): Partner '%s' no encontrado. Ignorado.", idx, name, partner_name)
                _emit_purchase_progress({
                    "status": "skipped", "done": idx, "total": total,
                    "name": name, "error_info": f"Partner '{partner_name}' no encontrado"
                })
                stats.skipped += 1
                stats.errors.append({"row": idx, "error": f"Partner '{partner_name}' no encontrado"})
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

                product_code = None
                if line.get("product_id"):
                    product_code = line["product_id"][1]
                
                prod_id = self.base_migrator._resolve_product(product_code)
                
                tax_ids = []
                src_tax_ids = line.get("taxes_id", [])
                if src_tax_ids:
                    src_taxes = self.odoo_src.execute("account.tax", "read", src_tax_ids, ["name"])
                    for st in src_taxes:
                        t_id = self.base_migrator._resolve_tax(st.get("name"), tax_use="purchase")
                        if t_id:
                            tax_ids.append((4, t_id))

                line_vals = {
                    "name": line.get("name", ""),
                    "product_qty": line.get("product_qty", 1),
                    "price_unit": line.get("price_unit", 0),
                    "taxes_id": tax_ids,
                }
                if prod_id:
                    line_vals["product_id"] = prod_id
                
                odoo_lines.append((0, 0, line_vals))

            order_vals = {
                "partner_id": partner_id,
                "date_order": vals.get("date_order"),
                "partner_ref": vals.get("partner_ref"),
                "notes": vals.get("notes"),
                "order_line": odoo_lines,
            }
            if name and name != "/":
                order_vals["name"] = name

            if dry_run:
                _emit_purchase_progress({"status": "created", "done": idx, "total": total, "name": name})
                stats.created += 1
                continue

            try:
                existing_id = None
                if name and name != "/":
                    ids = self.odoo.search("purchase.order", [("name", "=", name)])
                    if ids:
                        existing_id = ids[0]

                if existing_id and self.base_migrator.options.update_existing:
                    state = self.odoo.execute("purchase.order", "read", [existing_id], ["state"])[0].get("state")
                    if state not in ("draft", "sent"):
                        _emit_purchase_progress({
                            "status": "skipped", "done": idx, "total": total,
                            "name": name, "error_info": f"Pedido ya existe y está en estado {state}"
                        })
                        stats.skipped += 1
                    else:
                        self.odoo.execute("purchase.order", "write", [existing_id], {"order_line": [(5, 0, 0)] + odoo_lines})
                        self.odoo.execute("purchase.order", "write", [existing_id], order_vals)
                        _emit_purchase_progress({"status": "updated", "done": idx, "total": total, "name": name})
                        stats.updated += 1
                elif not existing_id:
                    new_id = self.odoo.execute("purchase.order", "create", order_vals)
                    _emit_purchase_progress({"status": "created", "done": idx, "total": total, "name": name})
                    stats.created += 1
                else:
                    _emit_purchase_progress({
                        "status": "skipped", "done": idx, "total": total,
                        "name": name, "error_info": "Ya existe y update_existing=False"
                    })
                    stats.skipped += 1
            except Exception as e:
                log.warning("Pedido Compra %s (%s): Error: %s", idx, name, e)
                _emit_purchase_progress({"status": "error", "done": idx, "total": total, "name": name, "error_info": str(e)})
                stats.errors.append({"row": idx, "error": str(e)})

        return stats
