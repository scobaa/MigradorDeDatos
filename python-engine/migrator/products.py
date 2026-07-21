"""
Migrador de product.template: orquesta la importación de productos en Odoo.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from transformers.products import transform_product

log = logging.getLogger(__name__)

PRODUCT_TEMPLATE_MODEL = "product.template"


@dataclass
class MigrationOptions:
    """Opciones de la migración de productos."""
    update_existing: bool = True
    batch_size: int = 100
    external_id_prefix: str = "art_"
    external_id_column: str | None = None


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


class ProductMigrator:
    """Migra artículos hacia el modelo product.template de Odoo."""

    def __init__(
        self,
        odoo: OdooClient,
        mapping: dict[str, str],
        options: MigrationOptions | None = None,
        families: dict[str, str] | None = None,
    ) -> None:
        self.odoo = odoo
        self.mapping = mapping
        self.options = options or MigrationOptions()
        self.families = families or {}

        # Cachés locales
        self._categ_cache: dict[str, int] = {}
        self._uom_cache: dict[str, int] = {}
        self._tax_cache: dict[tuple[str, str], int | None] = {}
        self._type_selection: list[str] | None = None

    # ─── Resoluciones Many2one e Impuestos ─────────────────────

    def _resolve_category(self, cat_name: str | None) -> int:
        """Busca categoría de producto por nombre (soporta jerarquías con '/') o la crea si no existe."""
        if not cat_name:
            cat_name = "All"

        cleaned_cat = str(cat_name).strip()
        if cleaned_cat.endswith(".0"):
            cleaned_cat = cleaned_cat[:-2]

        # Traducir código de familia a nombre real usando el diccionario pre-cargado
        if self.families and cleaned_cat in self.families:
            cat_name = self.families[cleaned_cat]
        else:
            cat_name = cleaned_cat

        cat_name = cat_name.strip()

        # Si es una ruta jerárquica (ej: "Ferretería / Tornillos"), resolver de nivel a nivel
        if "/" in cat_name:
            parts = [p.strip() for p in cat_name.split("/") if p.strip()]
            parent_id = None
            accumulated_path = ""
            for part in parts:
                if accumulated_path:
                    accumulated_path += " / " + part
                else:
                    accumulated_path = part
                parent_id = self._resolve_single_category(part, parent_id, accumulated_path)
            return parent_id or 1
        else:
            return self._resolve_single_category(cat_name, None, cat_name)

    def _resolve_single_category(self, name: str, parent_id: int | None, full_path: str) -> int:
        """Busca o crea una única categoría dado su nombre y su categoría padre."""
        key = full_path.lower()
        if key in self._categ_cache:
            return self._categ_cache[key]

        try:
            domain = [("name", "=ilike", name)]
            if parent_id is not None:
                domain.append(("parent_id", "=", parent_id))

            ids = self.odoo.search("product.category", domain)
            if ids:
                self._categ_cache[key] = ids[0]
                return ids[0]

            # Crear categoría si no existe
            vals = {"name": name}
            if parent_id is not None:
                vals["parent_id"] = parent_id
            else:
                # Si es el primer nivel, buscar categoría padre por defecto
                parent_ids = self.odoo.search(
                    "product.category", [("name", "in", ("All", "Todos", "All / Saleable"))]
                )
                if parent_ids:
                    vals["parent_id"] = parent_ids[0]

            cat_id = self.odoo.create("product.category", vals)
            self._categ_cache[key] = cat_id
            log.info("Categoría creada: %s (id=%s, parent=%s)", name, cat_id, parent_id)
            return cat_id
        except Exception as e:
            log.warning("No se pudo resolver o crear categoría '%s' (parent=%s): %s. Usando fallback.", name, parent_id, e)
            if parent_id is not None:
                return parent_id
            fallback_ids = self.odoo.search("product.category", [], limit=1)
            if fallback_ids:
                return fallback_ids[0]
            raise RuntimeError("No hay categorías disponibles en Odoo para productos.")

    def _resolve_uom(self, uom_name: str | None) -> int:
        """Busca Unidad de Medida en Odoo: ID externo → nombre exacto → ilike → fallback ID 1."""
        if not uom_name:
            return 1

        key = uom_name.strip().lower()
        if key in self._uom_cache:
            return self._uom_cache[key]

        try:
            # 1. ID externo + nombre exacto (via resolve_many2one)
            result = self.odoo.resolve_many2one(uom_name, "uom.uom", cache=self._uom_cache)
            if result:
                return result

            # 2. Coincidencia ilike (insensible a mayúsculas y tildes)
            ids = self.odoo.search("uom.uom", [("name", "ilike", uom_name)])
            if ids:
                self._uom_cache[key] = ids[0]
                return ids[0]
        except Exception as e:
            log.warning("Fallo al buscar UoM '%s': %s", uom_name, e)

        self._uom_cache[key] = 1
        return 1

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

    def _get_type_selection(self) -> list[str]:
        """Obtiene las opciones de selección del campo 'type' en product.template."""
        if self._type_selection is None:
            try:
                res = self.odoo.execute(
                    PRODUCT_TEMPLATE_MODEL,
                    "fields_get",
                    allfields=["type"],
                    attributes=["selection"],
                )
                if "type" in res and "selection" in res["type"]:
                    self._type_selection = [opt[0] for opt in res["type"]["selection"]]
                else:
                    self._type_selection = ["consu", "service", "product"]
            except Exception as e:
                log.warning("Fallo al obtener la selección del campo type: %s. Usando fallback.", e)
                self._type_selection = ["consu", "service", "product"]
        return self._type_selection

    def _resolve_fields_in_place(self, vals: dict[str, Any]) -> None:
        """Resuelve los campos de relación Many2one y Many2many in-place."""
        log.info("DEBUG VALS ANTES DE RESOLVER: %s", vals)
        
        # Categoría: soporta mapeo via "_category" (recomendado) o directamente "categ_id" como string
        category_name = vals.pop("_category", None)
        if not category_name:
            # El usuario puede haber mapeado la columna directamente a "categ_id"
            raw_categ = vals.get("categ_id")
            if isinstance(raw_categ, str):
                category_name = raw_categ
                vals.pop("categ_id", None)
                
        log.info("DEBUG CATEGORY_NAME RESUELTO: %s", category_name)
        vals["categ_id"] = self._resolve_category(category_name)

        # Unidades de medida: soporta "_uom" o "uom_id" directamente como string
        uom_name = vals.pop("_uom", None)
        if not uom_name:
            raw_uom = vals.get("uom_id")
            if isinstance(raw_uom, str):
                uom_name = raw_uom
                vals.pop("uom_id", None)
        if uom_name:
            uom_id = self._resolve_uom(uom_name)
            vals["uom_id"] = uom_id
            vals["uom_po_id"] = uom_id

        uom_po_name = vals.pop("_uom_po", None)
        if not uom_po_name:
            raw_uom_po = vals.get("uom_po_id")
            if isinstance(raw_uom_po, str):
                uom_po_name = raw_uom_po
                vals.pop("uom_po_id", None)
        if uom_po_name:
            vals["uom_po_id"] = self._resolve_uom(uom_po_name)

        # Impuestos de cliente (Many2many)
        tax_str = vals.pop("_taxes", None)
        if tax_str:
            tax_id = self._resolve_tax(tax_str, "sale")
            if tax_id:
                vals["taxes_id"] = [(6, 0, [tax_id])]

        # Impuestos de proveedor (Many2many)
        supplier_tax_str = vals.pop("_supplier_taxes", None)
        if supplier_tax_str:
            supplier_tax_id = self._resolve_tax(supplier_tax_str, "purchase")
            if supplier_tax_id:
                vals["supplier_taxes_id"] = [(6, 0, [supplier_tax_id])]

        # Compatibilidad con Odoo 17+ para productos almacenables
        try:
            valid_fields = self.odoo.get_valid_fields(PRODUCT_TEMPLATE_MODEL)
            type_selection = self._get_type_selection()
            if vals.get("type") == "product" and "product" not in type_selection:
                if "consu" in type_selection:
                    vals["type"] = "consu"
                if "is_storable" in valid_fields:
                    vals["is_storable"] = True
        except Exception as e:
            log.warning("Fallo al verificar compatibilidad de Odoo 17+ storable: %s", e)

    # ─── Orquestación del proceso ──────────────────────────────

    def run(
        self,
        rows: Iterable[dict[str, Any]],
        total: int = 0,
        dry_run: bool = False,
    ) -> MigrationStats:
        """Procesa y migra productos en bloques (lotes)."""
        stats = MigrationStats()
        log.info(
            "Iniciando migración de productos en lotes (dry_run=%s, total=%s, batch_size=%s)",
            dry_run,
            total,
            self.options.batch_size,
        )

        def chunked(iterable, n):
            iterator = iter(iterable)
            while True:
                chunk = []
                for _ in range(n):
                    try:
                        chunk.append(next(iterator))
                    except StopIteration:
                        break
                if not chunk:
                    break
                yield chunk

        batch_size = self.options.batch_size or 100
        current_done = 0

        for batch in chunked(rows, batch_size):
            self._process_batch(batch, current_done, total, dry_run, stats)
            current_done += len(batch)

        log.info("Migración de productos finalizada: %s", stats.as_dict())
        return stats

    def _process_batch(
        self,
        batch_rows: list[dict[str, Any]],
        start_idx: int,
        total: int,
        dry_run: bool,
        stats: MigrationStats,
    ) -> None:
        records = []
        rev_mapping = {v: k for k, v in self.mapping.items()}
        external_id_col = self.options.external_id_column
        if not external_id_col:
            external_id_col = rev_mapping.get("__external_id")

        # 1. Transformación inicial de filas en memoria
        for idx_offset, row in enumerate(batch_rows):
            row_idx = start_idx + idx_offset + 1
            try:
                vals = transform_product(row, self.mapping)
                self._resolve_fields_in_place(vals)

                # Limpieza con el esquema dinámico de Odoo
                vals = self.odoo.filter_vals(PRODUCT_TEMPLATE_MODEL, vals)

                product_xml_id = None
                if external_id_col:
                    raw_ext_id = row.get(external_id_col)
                    if raw_ext_id is not None:
                        cleaned_ext_id = str(raw_ext_id).strip()
                        if cleaned_ext_id.endswith(".0"):
                            cleaned_ext_id = cleaned_ext_id[:-2]
                        if cleaned_ext_id:
                            prefix = self.options.external_id_prefix or ""
                            product_xml_id = f"{prefix}{cleaned_ext_id}"

                # Fallback: usar el código de artículo (default_code/SKU) como ID externo si no hay mapeo explícito
                if not product_xml_id and vals.get("default_code"):
                    cleaned_code = str(vals["default_code"]).strip()
                    if cleaned_code.endswith(".0"):
                        cleaned_code = cleaned_code[:-2]
                    if cleaned_code:
                        prefix = self.options.external_id_prefix or ""
                        product_xml_id = f"{prefix}{cleaned_code}"

                records.append({
                    "idx": row_idx,
                    "row": row,
                    "vals": vals,
                    "product_xml_id": product_xml_id,
                    "existing_id": None,
                    "action": None,
                })
            except Exception as e:
                log.exception("Error de transformación en fila de producto %s", row_idx)
                stats.errors.append({"row": row_idx, "error": str(e), "data": row})
                _emit_progress(
                    {"done": row_idx, "total": total, "action": "error", "message": str(e)}
                )

        if not records:
            return

        # 2. Deduplicación masiva en bloque
        # 2.1 Buscar por XML IDs en ir.model.data
        xml_id_to_res_id = {}
        product_xml_ids = [r["product_xml_id"] for r in records if r["product_xml_id"]]
        if product_xml_ids:
            domain_xml = [
                ("module", "=", "__import__"),
                ("name", "in", product_xml_ids),
                ("model", "=", PRODUCT_TEMPLATE_MODEL),
            ]
            try:
                xml_recs = self.odoo.search_read("ir.model.data", domain_xml, ["name", "res_id"])
                xml_id_to_res_id = {x["name"]: x["res_id"] for x in xml_recs}
            except Exception as e:
                log.warning("Fallo al buscar XML IDs de productos en lote: %s", e)

        records_to_check = []
        for r in records:
            xml_id = r["product_xml_id"]
            if xml_id and xml_id in xml_id_to_res_id:
                r["existing_id"] = xml_id_to_res_id[xml_id]
            else:
                records_to_check.append(r)

        # 2.2 Buscar por SKU (default_code), Barcode y Nombre
        if records_to_check:
            skus = list(set([r["vals"]["default_code"] for r in records_to_check if r["vals"].get("default_code")]))
            barcodes = list(set([r["vals"]["barcode"] for r in records_to_check if r["vals"].get("barcode")]))
            names = list(set([r["vals"]["name"] for r in records_to_check if r["vals"].get("name")]))

            existing_skus = {}
            if skus:
                try:
                    recs = self.odoo.search_read(PRODUCT_TEMPLATE_MODEL, [("default_code", "in", skus)], ["default_code", "id"])
                    existing_skus = {x["default_code"]: x["id"] for x in recs}
                except Exception as e:
                    log.warning("Fallo al buscar SKUs de productos en lote: %s", e)

            existing_barcodes = {}
            if barcodes:
                try:
                    recs = self.odoo.search_read(PRODUCT_TEMPLATE_MODEL, [("barcode", "in", barcodes)], ["barcode", "id"])
                    existing_barcodes = {x["barcode"]: x["id"] for x in recs}
                except Exception as e:
                    log.warning("Fallo al buscar códigos de barras en lote: %s", e)

            existing_names = {}
            if names:
                try:
                    recs = self.odoo.search_read(PRODUCT_TEMPLATE_MODEL, [("name", "in", names)], ["name", "id"])
                    existing_names = {x["name"]: x["id"] for x in recs}
                except Exception as e:
                    log.warning("Fallo al buscar nombres de productos en lote: %s", e)

            for r in records_to_check:
                sku = r["vals"].get("default_code")
                barcode = r["vals"].get("barcode")
                name = r["vals"].get("name")

                if sku and sku in existing_skus:
                    r["existing_id"] = existing_skus[sku]
                elif barcode and barcode in existing_barcodes:
                    r["existing_id"] = existing_barcodes[barcode]
                elif name and name in existing_names:
                    r["existing_id"] = existing_names[name]

        # 3. Separar en Creaciones y Actualizaciones
        creations = []
        updates = []

        for r in records:
            if r["existing_id"]:
                if self.options.update_existing:
                    r["action"] = "update"
                    updates.append(r)
                else:
                    r["action"] = "skip"
                    stats.skipped += 1
                    _emit_progress({
                        "done": r["idx"],
                        "total": total,
                        "action": "skipped",
                        "name": r["vals"]["name"],
                    })
            else:
                r["action"] = "create"
                creations.append(r)

        # 3.1 Procesar Actualizaciones
        for r in updates:
            try:
                if not dry_run:
                    self.odoo.write(PRODUCT_TEMPLATE_MODEL, [r["existing_id"]], r["vals"])
                    if r["product_xml_id"]:
                        self.odoo.create_or_update_xml_id(
                            r["product_xml_id"], PRODUCT_TEMPLATE_MODEL, r["existing_id"]
                        )
                stats.updated += 1
                _emit_progress({
                    "done": r["idx"],
                    "total": total,
                    "action": "updated",
                    "name": r["vals"]["name"],
                })
            except Exception as e:
                log.exception("Error al actualizar producto en fila %s", r["idx"])
                stats.errors.append({"row": r["idx"], "error": str(e), "data": r["row"]})
                _emit_progress({
                    "done": r["idx"],
                    "total": total,
                    "action": "error",
                    "message": f"Error de actualización: {e}",
                })

        # 3.2 Procesar Creaciones en Bloque con Fallback resiliente
        if creations:
            if dry_run:
                for r in creations:
                    stats.created += 1
                    _emit_progress({
                        "done": r["idx"],
                        "total": total,
                        "action": "created",
                        "name": r["vals"]["name"],
                    })
            else:
                # Intentar crear todo el bloque
                try:
                    create_vals_list = [r["vals"] for r in creations]
                    res = self.odoo.execute(PRODUCT_TEMPLATE_MODEL, "create", create_vals_list)
                    new_ids = res if isinstance(res, list) else [res]

                    for offset, new_id in enumerate(new_ids):
                        r = creations[offset]
                        r["existing_id"] = new_id
                        if r["product_xml_id"]:
                            self.odoo.create_or_update_xml_id(
                                r["product_xml_id"], PRODUCT_TEMPLATE_MODEL, new_id
                            )
                        stats.created += 1
                        _emit_progress({
                            "done": r["idx"],
                            "total": total,
                            "action": "created",
                            "name": r["vals"]["name"],
                        })
                except Exception as bulk_err:
                    log.warning(
                        "Error en creación masiva de productos: %s. Reintentando fila a fila para este lote.",
                        bulk_err,
                    )
                    # Fallback fila a fila
                    for r in creations:
                        try:
                            new_id = self.odoo.create(PRODUCT_TEMPLATE_MODEL, r["vals"])
                            if r["product_xml_id"]:
                                self.odoo.create_or_update_xml_id(
                                    r["product_xml_id"], PRODUCT_TEMPLATE_MODEL, new_id
                                )
                            stats.created += 1
                            _emit_progress({
                                "done": r["idx"],
                                "total": total,
                                "action": "created",
                                "name": r["vals"]["name"],
                            })
                        except Exception as row_err:
                            log.exception("Error de fallback al crear producto en fila %s", r["idx"])
                            stats.errors.append({"row": r["idx"], "error": str(row_err), "data": r["row"]})
                            _emit_progress({
                                "done": r["idx"],
                                "total": total,
                                "action": "error",
                                "message": f"Error de creación: {row_err}",
                            })

        # Notificar fin de bloque
        last_row_idx = batch_rows[-1]["idx"] if "idx" in batch_rows[-1] else start_idx + len(batch_rows)
        _emit_progress({
            "done": last_row_idx,
            "total": total,
            "action": "batch_completed",
            "count": len(batch_rows),
        })
