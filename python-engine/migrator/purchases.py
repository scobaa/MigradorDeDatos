"""
Migrador de purchase.order (Pedidos de Compra).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from transformers.purchases import transform_purchase_order

log = logging.getLogger(__name__)

PURCHASE_ORDER_MODEL = "purchase.order"


@dataclass
class MigrationOptions:
    """Opciones de la migración de pedidos."""
    update_existing: bool = True
    batch_size: int = 50
    external_id_prefix: str = "po_"
    confirm_orders: bool = True
    force_invoiced: bool = False
    format_name: bool = True


@dataclass
class MigrationStats:
    """Estadísticas acumuladas de la migración."""
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "error_count": len(self.errors),
            "errors": self.errors,
        }


def _emit_progress(event: dict[str, Any]) -> None:
    """Escribe un evento de progreso como línea JSON en stderr."""
    sys.stderr.write(json.dumps({"event": "progress", **event}, ensure_ascii=False))
    sys.stderr.write("\n")
    sys.stderr.flush()


def clean_xml_id(text: str) -> str:
    """Normaliza un texto para usarlo como XML ID válido en Odoo."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)


class PurchaseOrderMigrator:
    """Migra pedidos de compra hacia el modelo purchase.order de Odoo."""

    def __init__(
        self,
        odoo: OdooClient,
        mapping: dict[str, str],
        options: MigrationOptions | None = None,
    ) -> None:
        self.odoo = odoo
        self.mapping = mapping
        self.options = options or MigrationOptions()

        # Cachés locales
        self._partner_cache: dict[str, int | None] = {}
        self._product_cache: dict[str, int | None] = {}
        self._tax_cache: dict[tuple[str, str], int | None] = {}

    def _resolve_partner(self, partner_code: str | None) -> int | None:
        """Busca el ID del partner proveedor en Odoo usando ID externo, ref o nombre."""
        if not partner_code:
            return None

        key = str(partner_code).strip()
        if key in self._partner_cache:
            return self._partner_cache[key]

        try:
            # 1. Buscar por XML ID (proveedores típicamente empiezan por pro_)
            xml_id = key if key.startswith("pro_") else f"pro_{key}"
            partner_id = self.odoo.get_xml_id_res_id(xml_id, "res.partner")
            if partner_id:
                self._partner_cache[key] = partner_id
                return partner_id

            # 2. Buscar por ref
            ids = self.odoo.search("res.partner", [("ref", "=", key)])
            if ids:
                self._partner_cache[key] = ids[0]
                return ids[0]

            # 3. Buscar por name
            ids = self.odoo.search("res.partner", [("name", "=", key)])
            if ids:
                self._partner_cache[key] = ids[0]
                return ids[0]
        except Exception as e:
            log.warning("Error al resolver partner '%s': %s", key, e)

        self._partner_cache[key] = None
        return None

    def _resolve_product(self, product_code: str | None) -> int | None:
        """Busca el ID del producto (variante) en Odoo."""
        if not product_code:
            return None

        key = str(product_code).strip()
        if key in self._product_cache:
            return self._product_cache[key]

        try:
            # 1. Buscar por default_code (SKU)
            ids = self.odoo.search("product.product", [("default_code", "=", key)])
            if ids:
                self._product_cache[key] = ids[0]
                return ids[0]

            # 2. Buscar por XML ID de product.template
            xml_id = key if key.startswith("art_") else f"art_{key}"
            tmpl_id = self.odoo.get_xml_id_res_id(xml_id, "product.template")
            if tmpl_id:
                p_ids = self.odoo.search("product.product", [("product_tmpl_id", "=", tmpl_id)])
                if p_ids:
                    self._product_cache[key] = p_ids[0]
                    return p_ids[0]

            # 3. Buscar por código de barras
            ids = self.odoo.search("product.product", [("barcode", "=", key)])
            if ids:
                self._product_cache[key] = ids[0]
                return ids[0]
        except Exception as e:
            log.warning("Error al resolver producto '%s': %s", key, e)

        self._product_cache[key] = None
        return None

    def _resolve_tax(self, tax_value: str | None) -> int | None:
        """Busca un impuesto de compra en Odoo por nombre, porcentaje o aproximación."""
        if not tax_value:
            return None

        val = str(tax_value).strip()
        key = (val.lower(), "purchase")
        if key in self._tax_cache:
            return self._tax_cache[key]

        try:
            # 1. Coincidencia exacta
            tax_id = self.odoo.get_tax_id(val, "purchase")
            if tax_id:
                self._tax_cache[key] = tax_id
                return tax_id

            # 2. Coincidencia parcial (ilike)
            ids = self.odoo.search(
                "account.tax", [("name", "ilike", val), ("type_tax_use", "=", "purchase")]
            )
            if ids:
                self._tax_cache[key] = ids[0]
                return ids[0]

            # 3. Búsqueda por porcentaje numérico
            digits_match = re.search(r"(\d+(?:\.\d+)?)", val)
            if digits_match:
                pct = float(digits_match.group(1))
                domain = [
                    ("type_tax_use", "=", "purchase"),
                    "|",
                    ("amount", "=", pct),
                    ("amount", "=", pct / 100.0),
                ]
                ids = self.odoo.search("account.tax", domain)
                if ids:
                    self._tax_cache[key] = ids[0]
                    return ids[0]
        except Exception as e:
            log.warning("Error al resolver impuesto '%s': %s", val, e)

        self._tax_cache[key] = None
        return None

    def _process_row(self, row: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        """Transforma una fila cruda y resuelve sus relaciones in-place."""
        vals = transform_purchase_order(row, self.mapping, format_name=self.options.format_name)

        # 1. Resolver partner
        partner_code = vals.pop("_partner_code", None)
        partner_id = self._resolve_partner(partner_code)
        if not partner_id:
            raise ValueError(
                f"No se pudo encontrar ningún proveedor en Odoo para el código '{partner_code}'."
            )
        vals["partner_id"] = partner_id

        # 2. Resolver líneas de pedido
        lines = vals.pop("_lines", [])
        order_line_ids = []

        for line in lines:
            product_code = line.pop("product_code", None)
            product_id = self._resolve_product(product_code)

            # Usar 'product_qty' para purchases en vez de 'product_uom_qty'
            line_vals = {
                "name": line["name"],
                "product_qty": line["quantity"],
                "price_unit": line["price_unit"],
            }
            if "discount" in line:
                line_vals["discount"] = line["discount"]
            if product_id:
                line_vals["product_id"] = product_id

            tax_val = line.pop("tax_value", None)
            if tax_val:
                tax_id = self._resolve_tax(tax_val)
                if tax_id:
                    # Usar 'taxes_id' para purchases en vez de 'tax_ids'
                    line_vals["taxes_id"] = [(6, 0, [tax_id])]

            order_line_ids.append((0, 0, line_vals))

        if not order_line_ids:
            raise ValueError("El pedido debe contener al menos una línea con cantidad e importe.")

        vals["order_line"] = order_line_ids
        return vals

    def run(
        self,
        rows: Iterable[dict[str, Any]],
        total: int = 0,
        dry_run: bool = False,
    ) -> MigrationStats:
        """Migra pedidos ejecutando la inserción/actualización en Odoo."""
        stats = MigrationStats()
        log.info(
            "Iniciando migración de pedidos de compra (dry_run=%s, total=%s)",
            dry_run,
            total,
        )

        for i, row in enumerate(rows, 1):
            _emit_progress({"current": i, "total": total, "status": "processing"})
            try:
                vals = self._process_row(row, dry_run)
                
                raw_id = row.get("__external_id") or vals.get("name")
                if not raw_id or raw_id == "/":
                    raise ValueError("Falta el identificador (__external_id o name)")

                xml_id = clean_xml_id(str(raw_id).strip())
                if self.options.external_id_prefix is not None:
                    # Si no está en blanco y no lo tiene, lo añade
                    prefix = self.options.external_id_prefix
                    if prefix and not xml_id.startswith(prefix):
                        xml_id = f"{prefix}{xml_id}"

                existing_id = self.odoo.get_xml_id_res_id(xml_id, PURCHASE_ORDER_MODEL)

                if existing_id:
                    if self.options.update_existing:
                        if not dry_run:
                            # Limpiar campos Odoo (eliminar __external_id, _lines, etc. que no pertenecen al modelo)
                            clean_vals = self.odoo.filter_vals(PURCHASE_ORDER_MODEL, vals)
                            
                            self.odoo.write(PURCHASE_ORDER_MODEL, [existing_id], {"order_line": [(5, 0, 0)]})
                            self.odoo.write(PURCHASE_ORDER_MODEL, [existing_id], clean_vals)
                            
                            # Confirmar
                            if self.options.confirm_orders:
                                self.odoo.execute(PURCHASE_ORDER_MODEL, "button_confirm", [existing_id])
                                if self.options.force_invoiced:
                                    self.odoo.write(PURCHASE_ORDER_MODEL, [existing_id], {"invoice_status": "invoiced"})
                        
                        log.info("Fila %d: Actualizado pedido %s", i, xml_id)
                        _emit_progress(
                            {"current": i, "total": total, "status": "success", "action": "updated", "xml_id": xml_id}
                        )
                        stats.updated += 1
                    else:
                        log.debug("Fila %d: Omitido pedido %s (ya existe)", i, xml_id)
                        _emit_progress(
                            {"current": i, "total": total, "status": "success", "action": "skipped", "xml_id": xml_id}
                        )
                        stats.skipped += 1
                else:
                    if not dry_run:
                        # Limpiar campos Odoo (eliminar __external_id, _lines, etc. que no pertenecen al modelo)
                        clean_vals = self.odoo.filter_vals(PURCHASE_ORDER_MODEL, vals)
                        
                        new_id = self.odoo.create(PURCHASE_ORDER_MODEL, clean_vals)
                        self.odoo.create_or_update_xml_id(xml_id, PURCHASE_ORDER_MODEL, new_id)
                        
                        # Confirmar
                        if self.options.confirm_orders:
                            self.odoo.execute(PURCHASE_ORDER_MODEL, "button_confirm", [new_id])
                            if self.options.force_invoiced:
                                self.odoo.write(PURCHASE_ORDER_MODEL, [new_id], {"invoice_status": "invoiced"})

                    log.info("Fila %d: Creado pedido %s", i, xml_id)
                    _emit_progress(
                        {"current": i, "total": total, "status": "success", "action": "created", "xml_id": xml_id}
                    )
                    stats.created += 1

            except Exception as e:
                log.error("Error procesando pedido de compra en fila %d", i, exc_info=True)
                # Parsear el raw row para mostrarlo mejor
                row_name = row.get(self.mapping.get("name", "name"))
                if not row_name:
                    row_name = row.get("__external_id", "Desconocido")
                
                error_info = {"row": i, "name": str(row_name), "error": str(e)}
                stats.errors.append(error_info)
                _emit_progress({"current": i, "total": total, "status": "error", "error_info": error_info})

        return stats
