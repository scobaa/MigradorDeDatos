"""
Migrador de account.move (Facturas y Asientos).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from transformers.invoices import transform_invoice

log = logging.getLogger(__name__)

ACCOUNT_MOVE_MODEL = "account.move"


@dataclass
class MigrationOptions:
    """Opciones de la migración de facturas."""
    update_existing: bool = True
    batch_size: int = 50
    external_id_prefix: str = "inv_"
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


class InvoiceMigrator:
    """Migra facturas hacia el modelo account.move de Odoo."""

    def __init__(
        self,
        odoo: OdooClient,
        mapping: dict[str, str],
        options: MigrationOptions | None = None,
        move_type: str = "out_invoice",
    ) -> None:
        self.odoo = odoo
        self.mapping = mapping
        self.options = options or MigrationOptions()
        self.move_type = move_type

        # Cachés locales
        self._partner_cache: dict[str, int | None] = {}
        self._product_cache: dict[str, int | None] = {}
        self._tax_cache: dict[tuple[str, str], int | None] = {}

    def _resolve_partner(self, partner_code: str | None) -> int | None:
        """Busca el ID del partner en Odoo: ID externo → ref → nombre."""
        prefix = "cli_" if self.move_type == "out_invoice" else "prov_"
        return self.odoo.resolve_many2one(
            partner_code,
            "res.partner",
            xml_id_prefix=prefix,
            extra_fields=["ref"],
            cache=self._partner_cache,
        )

    def _resolve_product(self, product_code: str | None) -> int | None:
        """Busca el ID del producto (variante) en Odoo: ID externo → default_code → barcode → nombre."""
        return self.odoo.resolve_many2one(
            product_code,
            "product.product",
            xml_id_prefix="art_",
            extra_fields=["default_code", "barcode"],
            cache=self._product_cache,
        )

    def _resolve_tax(self, tax_value: str | None, tax_use: str = "sale") -> int | None:
        """Busca un impuesto en Odoo por nombre, porcentaje o aproximación."""
        if not tax_value:
            return None

        val = str(tax_value).strip()
        key = (val.lower(), tax_use)
        if key in self._tax_cache:
            return self._tax_cache[key]

        try:
            # 1. Coincidencia exacta
            tax_id = self.odoo.get_tax_id(val, tax_use)
            if tax_id:
                self._tax_cache[key] = tax_id
                return tax_id

            # 2. Coincidencia parcial (ilike)
            ids = self.odoo.search(
                "account.tax", [("name", "ilike", val), ("type_tax_use", "=", tax_use)]
            )
            if ids:
                self._tax_cache[key] = ids[0]
                return ids[0]

            # 3. Búsqueda por porcentaje numérico (ej. "21" o "21%")
            digits_match = re.search(r"(\d+(?:\.\d+)?)", val)
            if digits_match:
                pct = float(digits_match.group(1))
                domain = [
                    ("type_tax_use", "=", tax_use),
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
        vals = transform_invoice(row, self.mapping, self.move_type, format_name=self.options.format_name)

        # 1. Resolver partner
        partner_code = vals.pop("_partner_code", None)
        partner_id = self._resolve_partner(partner_code)
        if not partner_id:
            raise ValueError(
                f"No se pudo encontrar ningún cliente/proveedor en Odoo para el código '{partner_code}'."
            )
        vals["partner_id"] = partner_id

        # 2. Resolver líneas de factura
        lines = vals.pop("_lines", [])
        invoice_line_ids = []

        tax_use = "sale" if self.move_type == "out_invoice" else "purchase"

        for line in lines:
            product_code = line.pop("product_code", None)
            product_id = self._resolve_product(product_code)

            line_vals = {
                "name": line["name"],
                "quantity": line["quantity"],
                "price_unit": line["price_unit"],
            }
            if "discount" in line:
                line_vals["discount"] = line["discount"]
            if product_id:
                line_vals["product_id"] = product_id

            tax_val = line.pop("tax_value", None)
            if tax_val:
                tax_id = self._resolve_tax(tax_val, tax_use)
                if tax_id:
                    line_vals["tax_ids"] = [(6, 0, [tax_id])]

            invoice_line_ids.append((0, 0, line_vals))

        if not invoice_line_ids:
            raise ValueError("La factura debe contener al menos una línea con importe y descripción.")

        vals["invoice_line_ids"] = invoice_line_ids
        return vals

    def run(
        self,
        rows: Iterable[dict[str, Any]],
        total: int = 0,
        dry_run: bool = False,
    ) -> MigrationStats:
        """Migra facturas ejecutando la inserción/actualización en Odoo."""
        stats = MigrationStats()
        log.info(
            "Iniciando migración de facturas (move_type=%s, dry_run=%s, total=%s)",
            self.move_type,
            dry_run,
            total,
        )

        for idx, row in enumerate(rows):
            row_idx = idx + 1
            try:
                # 1. Transformar y resolver relaciones
                vals = self._process_row(row, dry_run)
                name = vals.get("name")
                if not name or name == "/":
                    raise ValueError("El número de factura original (campo 'name') es obligatorio.")

                # Generar XML ID único para la factura
                clean_name = clean_xml_id(name)
                prefix = "inv_out_" if self.move_type == "out_invoice" else "inv_in_"
                xml_id = f"{prefix}{clean_name}"

                # 2. Comprobar si ya existe
                existing_id = self.odoo.get_xml_id_res_id(xml_id, ACCOUNT_MOVE_MODEL)

                if existing_id:
                    if not self.options.update_existing:
                        stats.skipped += 1
                        _emit_progress({
                            "done": row_idx,
                            "total": total,
                            "action": "skipped",
                            "name": name,
                        })
                        continue

                    # Actualización
                    if not dry_run:
                        # Mover a borrador si está publicada
                        move_data = self.odoo.read(ACCOUNT_MOVE_MODEL, [existing_id], ["state"])
                        if move_data and move_data[0]["state"] == "posted":
                            try:
                                self.odoo.execute(ACCOUNT_MOVE_MODEL, "button_draft", [existing_id])
                            except Exception as e:
                                log.warning("Fallo al cambiar estado a draft para actualizar factura: %s", e)

                        # Reemplazar líneas: (5, 0, 0) borra las existentes, luego agregamos las nuevas
                        vals["invoice_line_ids"] = [(5, 0, 0)] + vals["invoice_line_ids"]
                        
                        # Limpiar campos Odoo
                        clean_vals = self.odoo.filter_vals(ACCOUNT_MOVE_MODEL, vals)
                        self.odoo.write(ACCOUNT_MOVE_MODEL, [existing_id], clean_vals)

                        # Volver a publicar
                        try:
                            self.odoo.execute(ACCOUNT_MOVE_MODEL, "action_post", [existing_id])
                        except Exception as e:
                            log.debug("Excepción silenciada en action_post (posible error serialización): %s", e)

                    stats.updated += 1
                    _emit_progress({
                        "done": row_idx,
                        "total": total,
                        "action": "updated",
                        "name": name,
                    })

                else:
                    # Creación
                    if not dry_run:
                        clean_vals = self.odoo.filter_vals(ACCOUNT_MOVE_MODEL, vals)
                        new_id = self.odoo.create(ACCOUNT_MOVE_MODEL, clean_vals)
                        self.odoo.create_or_update_xml_id(xml_id, ACCOUNT_MOVE_MODEL, new_id)

                        # Publicar la factura recién creada
                        try:
                            self.odoo.execute(ACCOUNT_MOVE_MODEL, "action_post", [new_id])
                        except Exception as e:
                            log.debug("Excepción silenciada en action_post (posible error serialización): %s", e)

                    stats.created += 1
                    _emit_progress({
                        "done": row_idx,
                        "total": total,
                        "action": "created",
                        "name": name,
                    })

            except Exception as e:
                log.exception("Error procesando factura en fila %s", row_idx)
                stats.errors.append({"row": row_idx, "error": str(e), "data": row})
                _emit_progress({
                    "done": row_idx,
                    "total": total,
                    "action": "error",
                    "message": str(e),
                })

        log.info("Migración de facturas finalizada: %s", stats.as_dict())
        return stats
