"""
Migrador de sale.order (Pedidos de Venta).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from transformers.sales import transform_sales_order

log = logging.getLogger(__name__)

SALES_ORDER_MODEL = "sale.order"


@dataclass
class MigrationOptions:
    """Opciones de la migración de pedidos."""
    update_existing: bool = True
    batch_size: int = 50
    external_id_prefix: str = "so_"
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


class SalesOrderMigrator:
    """Migra pedidos de venta hacia el modelo sale.order de Odoo."""

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
        """Busca el ID del partner en Odoo: ID externo → ref → nombre."""
        return self.odoo.resolve_many2one(
            partner_code,
            "res.partner",
            xml_id_prefix="cli_",
            extra_fields=["ref"],
            cache=self._partner_cache,
        )

    def _resolve_product(self, product_code: str | None, product_name: str | None = None) -> int | None:
        """Busca el ID del producto (variante) en Odoo: ID externo → default_code → barcode → nombre."""
        if not product_code and not product_name:
            return None

        # Si hay código, usamos resolve_many2one (ID externo → default_code → barcode → name)
        if product_code:
            result = self.odoo.resolve_many2one(
                product_code,
                "product.product",
                xml_id_prefix="art_",
                extra_fields=["default_code", "barcode"],
                cache=self._product_cache,
            )
            if result:
                return result
            
            # IMPORTANTE: No usamos self._product_cache aquí porque resolve_many2one
            # ya guardó None en caché para product_code. Buscamos directo en Odoo.
            log.info("DEBUG _resolve_product: '%s' no encontrado como código/ID. Buscando por nombre...", product_code)
            try:
                # Buscar primero por nombre en product.template (más fiable que product.product)
                tmpl_ids = self.odoo.search("product.template", [("name", "=", product_code)], limit=1)
                if not tmpl_ids:
                    tmpl_ids = self.odoo.search("product.template", [("name", "ilike", product_code)], limit=1)
                if tmpl_ids:
                    p_ids = self.odoo.search("product.product", [("product_tmpl_id", "=", tmpl_ids[0])], limit=1)
                    if p_ids:
                        log.info("DEBUG: Encontrado via plantilla id=%s → variante id=%s", tmpl_ids[0], p_ids[0])
                        self._product_cache[product_code] = p_ids[0]
                        return p_ids[0]
                # Fallback: buscar directamente en product.product por nombre
                ids = self.odoo.search("product.product", [("name", "ilike", product_code)], limit=1)
                if ids:
                    log.info("DEBUG: Encontrado en product.product por nombre ilike, id=%s", ids[0])
                    self._product_cache[product_code] = ids[0]
                    return ids[0]
                log.info("DEBUG: '%s' no encontrado ni por nombre en activos.", product_code)
            except Exception as e:
                log.warning("Error al resolver producto por nombre (code como nombre) '%s': %s", product_code, e)

        # Fallback por nombre (ilike en product.product y product.template)
        if product_name:
            name_clean = " ".join(str(product_name).split())
            cache_key = f"__name__{name_clean}"
            if cache_key in self._product_cache:
                return self._product_cache[cache_key]
            try:
                # Exacto en product.product
                ids = self.odoo.search("product.product", [("name", "=", name_clean)], limit=1)
                if ids:
                    self._product_cache[cache_key] = ids[0]
                    return ids[0]

                # ilike en product.product
                ids = self.odoo.search("product.product", [("name", "ilike", name_clean)], limit=1)
                if ids:
                    self._product_cache[cache_key] = ids[0]
                    return ids[0]

                # ilike en product.template
                tmpl_ids = self.odoo.search("product.template", [("name", "ilike", name_clean)], limit=1)
                if tmpl_ids:
                    p_ids = self.odoo.search("product.product", [("product_tmpl_id", "=", tmpl_ids[0])], limit=1)
                    if p_ids:
                        self._product_cache[cache_key] = p_ids[0]
                        return p_ids[0]
            except Exception as e:
                log.warning("Error al resolver producto por nombre '%s': %s", name_clean, e)
            self._product_cache[cache_key] = None

        # Si llegamos aquí, no lo hemos encontrado activo. Busquemos en los archivados.
        try:
            # Construir lista de condiciones candidatas (OR entre ellas)
            conditions = []
            if product_code:
                conditions.append(("default_code", "=", product_code))
                conditions.append(("barcode", "=", product_code))
                conditions.append(("name", "ilike", product_code))
            if product_name:
                name_clean = " ".join(str(product_name).split())
                conditions.append(("name", "ilike", name_clean))

            if conditions:
                # Construir dominio: active=False AND (cond1 OR cond2 OR ...)
                # En Odoo: ['&', ('active','=',False), '|', cond1, '|', cond2, cond3]
                if len(conditions) == 1:
                    domain = [("active", "=", False), conditions[0]]
                else:
                    # N condiciones necesitan N-1 operadores '|'
                    or_chain = []
                    for _ in range(len(conditions) - 1):
                        or_chain.append("|")
                    or_chain.extend(conditions)
                    domain = ["&", ("active", "=", False)] + or_chain

                archived_ids = self.odoo.search("product.product", domain, limit=1)
                if archived_ids:
                    arch_id = archived_ids[0]
                    self.odoo.write("product.product", [arch_id], {"active": True})
                    log.info("Producto archivado encontrado y reactivado: ID %s (código: %s)", arch_id, product_code or product_name)
                    cache_key = product_code or f"__name__{product_name}"
                    self._product_cache[cache_key] = arch_id
                    return arch_id

                # Variante no encontrada → buscar plantilla archivada por nombre
                search_name = None
                if product_code:
                    search_name = product_code
                if product_name:
                    search_name = " ".join(str(product_name).split())

                if search_name:
                    tmpl_domain = ["&", ("active", "=", False), ("name", "ilike", search_name)]
                    tmpl_ids = self.odoo.search("product.template", tmpl_domain, limit=1)
                    if tmpl_ids:
                        self.odoo.write("product.template", [tmpl_ids[0]], {"active": True})
                        log.info("Plantilla archivada reactivada: ID %s (nombre: %s)", tmpl_ids[0], search_name)
                        # Buscar variante activa (puede haberse activado con la plantilla)
                        p_ids = self.odoo.search("product.product", [("product_tmpl_id", "=", tmpl_ids[0])], limit=1)
                        if not p_ids:
                            # Si sigue archivada la variante, activarla también
                            p_ids = self.odoo.search("product.product", ["&", ("active", "=", False), ("product_tmpl_id", "=", tmpl_ids[0])], limit=1)
                        if p_ids:
                            self.odoo.write("product.product", [p_ids[0]], {"active": True})
                            cache_key = product_code or f"__name__{search_name}"
                            self._product_cache[cache_key] = p_ids[0]
                            return p_ids[0]
        except Exception as e:
            log.warning("Error al buscar/reactivar producto archivado: %s", e)

        return None

    def _resolve_tax(self, tax_value: str | None) -> int | None:
        """Busca un impuesto de venta en Odoo por nombre, porcentaje o aproximación."""
        if not tax_value:
            return None

        val = str(tax_value).strip()
        key = (val.lower(), "sale")
        if key in self._tax_cache:
            return self._tax_cache[key]

        try:
            # 1. Coincidencia exacta
            tax_id = self.odoo.get_tax_id(val, "sale")
            if tax_id:
                self._tax_cache[key] = tax_id
                return tax_id

            # 2. Coincidencia parcial (ilike)
            ids = self.odoo.search(
                "account.tax", [("name", "ilike", val), ("type_tax_use", "=", "sale")]
            )
            if ids:
                self._tax_cache[key] = ids[0]
                return ids[0]

            # 3. Búsqueda por porcentaje numérico
            digits_match = re.search(r"(\d+(?:\.\d+)?)", val)
            if digits_match:
                pct = float(digits_match.group(1))
                domain = [
                    ("type_tax_use", "=", "sale"),
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
        vals = transform_sales_order(row, self.mapping, format_name=self.options.format_name)

        # 1. Resolver partner
        partner_code = vals.pop("_partner_code", None)
        partner_id = self._resolve_partner(partner_code)
        if not partner_id:
            raise ValueError(
                f"No se pudo encontrar ningún cliente en Odoo para el código '{partner_code}'."
            )
        vals["partner_id"] = partner_id

        # 2. Resolver líneas de pedido
        lines = vals.pop("_lines", [])
        order_line_ids = []

        for line in lines:
            product_code = line.pop("product_code", None)
            product_name = line.get("name")  # ORDER_IDS/NAME — usado como fallback de búsqueda
            product_id = self._resolve_product(product_code, product_name)

            line_vals = {
                "name": line["name"],
                "product_uom_qty": line["quantity"],
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
                    line_vals["tax_ids"] = [(6, 0, [tax_id])]

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
            "Iniciando migración de pedidos de venta (dry_run=%s, total=%s)",
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
                    raise ValueError("El código de pedido original (campo 'name') es obligatorio.")

                # Generar XML ID único para el pedido usando el prefijo configurado
                # NOTA: usamos comparación explícita con None para que prefijo "" (vacío) también funcione
                prefix = self.options.external_id_prefix if self.options.external_id_prefix is not None else "so_"
                clean_name = clean_xml_id(name)
                # Solo añadir prefijo si no está ya incluido en el nombre limpio
                if prefix and not clean_name.startswith(prefix):
                    xml_id = f"{prefix}{clean_name}"
                else:
                    xml_id = clean_name

                # 2. Comprobar si ya existe
                existing_id = self.odoo.get_xml_id_res_id(xml_id, SALES_ORDER_MODEL)

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
                        # Mover a borrador si está confirmado (sale / done) o cancelado
                        order_data = self.odoo.read(SALES_ORDER_MODEL, [existing_id], ["state"])
                        if order_data and order_data[0]["state"] in ("sale", "done", "cancel"):
                            try:
                                # Si está confirmado, primero cancelar y luego a draft
                                if order_data[0]["state"] in ("sale", "done"):
                                    self.odoo.execute(SALES_ORDER_MODEL, "action_cancel", [existing_id])
                                self.odoo.execute(SALES_ORDER_MODEL, "action_draft", [existing_id])
                            except Exception as e:
                                log.warning("Fallo al cambiar estado a draft para actualizar pedido: %s", e)

                        # Reemplazar líneas: (5, 0, 0) borra las existentes, luego agregamos las nuevas
                        vals["order_line"] = [(5, 0, 0)] + vals["order_line"]
                        
                        # Limpiar campos Odoo
                        clean_vals = self.odoo.filter_vals(SALES_ORDER_MODEL, vals)
                        self.odoo.write(SALES_ORDER_MODEL, [existing_id], clean_vals)

                        # Volver a confirmar si la opción está activa
                        if self.options.confirm_orders:
                            try:
                                self.odoo.execute(SALES_ORDER_MODEL, "action_confirm", [existing_id])
                                # Restaurar la fecha original ya que action_confirm la sobrescribe con la actual
                                if "date_order" in clean_vals:
                                    self.odoo.write(SALES_ORDER_MODEL, [existing_id], {"date_order": clean_vals["date_order"]})
                                # Marcar como facturado si está activa la opción
                                if self.options.force_invoiced:
                                    try:
                                        self.odoo.write(SALES_ORDER_MODEL, [existing_id], {"force_invoiced": True})
                                    except Exception as e_fi:
                                        log.warning("No se pudo marcar force_invoiced en pedido '%s': %s", name, e_fi)
                            except Exception as e:
                                log.warning("[CONFIRM FALLIDO] Pedido '%s' (fila %s) no se pudo confirmar: %s", name, row_idx, e)
                                _emit_progress({
                                    "done": row_idx,
                                    "total": total,
                                    "action": "warning",
                                    "name": name,
                                    "message": f"Pedido '{name}' actualizado pero NO confirmado: {e}",
                                })

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
                        clean_vals = self.odoo.filter_vals(SALES_ORDER_MODEL, vals)
                        new_id = self.odoo.create(SALES_ORDER_MODEL, clean_vals)
                        self.odoo.create_or_update_xml_id(xml_id, SALES_ORDER_MODEL, new_id)

                        # Confirmar pedido si está activa la opción
                        if self.options.confirm_orders:
                            try:
                                self.odoo.execute(SALES_ORDER_MODEL, "action_confirm", [new_id])
                                # Restaurar la fecha original ya que action_confirm la sobrescribe con la actual
                                if "date_order" in clean_vals:
                                    self.odoo.write(SALES_ORDER_MODEL, [new_id], {"date_order": clean_vals["date_order"]})
                                # Marcar como facturado si está activa la opción
                                if self.options.force_invoiced:
                                    try:
                                        self.odoo.write(SALES_ORDER_MODEL, [new_id], {"force_invoiced": True})
                                    except Exception as e_fi:
                                        log.warning("No se pudo marcar force_invoiced en pedido '%s': %s", name, e_fi)
                            except Exception as e:
                                log.warning("[CONFIRM FALLIDO] Pedido '%s' (fila %s) no se pudo confirmar: %s", name, row_idx, e)
                                _emit_progress({
                                    "done": row_idx,
                                    "total": total,
                                    "action": "warning",
                                    "name": name,
                                    "message": f"Pedido '{name}' creado pero NO confirmado: {e}",
                                })

                    stats.created += 1
                    _emit_progress({
                        "done": row_idx,
                        "total": total,
                        "action": "created",
                        "name": name,
                    })

            except Exception as e:
                log.exception("Error procesando pedido '%s' en fila %s", vals.get("name", "desconocido") if 'vals' in dir() else "desconocido", row_idx)
                error_name = None
                try:
                    # Intentar sacar el nombre del pedido de la fila original para facilitar búsqueda
                    for src_col, odoo_field in self.mapping.items():
                        if odoo_field == "name":
                            error_name = str(row.get(src_col, "")).strip()
                            if error_name.endswith(".0"):
                                error_name = error_name[:-2]
                            break
                except Exception:
                    pass
                stats.errors.append({
                    "row": row_idx,
                    "name": error_name or f"fila_{row_idx}",
                    "error": str(e),
                    "data": row,
                })
                _emit_progress({
                    "done": row_idx,
                    "total": total,
                    "action": "error",
                    "name": error_name,
                    "message": str(e),
                })

        log.info("Migración de pedidos finalizada: %s", stats.as_dict())
        return stats
