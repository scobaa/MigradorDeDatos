"""
Migrador de inventario físico: ajusta stock.quant en Odoo.

Soporta el formato de Hoja2 del Excel de inventario:
    id | location_id | product_id | inventory_quantity

Flujo:
    1. Para cada fila, resuelve product_id (por default_code) y location_id (por complete_name).
    2. Busca si existe un stock.quant para esa combinación.
    3. Si existe → escribe inventory_quantity.
    4. Si no existe → crea el quant.
    5. Al terminar, opcionalmente llama action_apply_inventory() para confirmar.

Reporta progreso por stderr (línea JSON por evento):
    {"event": "progress", "done": 12, "total": 340, "action": "updated", "name": "..."}
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

from migrator.odoo_client import OdooClient

log = logging.getLogger(__name__)

QUANT_MODEL = "stock.quant"
PRODUCT_MODEL = "product.product"
LOCATION_MODEL = "stock.location"


def _emit_progress(event: dict[str, Any]) -> None:
    """Escribe un evento de progreso como línea JSON en stderr."""
    sys.stderr.write(json.dumps({"event": "progress", **event}, ensure_ascii=False))
    sys.stderr.write("\n")
    sys.stderr.flush()


@dataclass
class MigrationOptions:
    """Opciones de una migración de inventario."""
    apply_inventory: bool = True   # Si True, llama action_apply_inventory() al finalizar
    update_existing: bool = True   # Si False, omite quants ya existentes
    batch_size: int = 100
    external_id_prefix: str = "inv_"


@dataclass
class MigrationStats:
    """Resultado acumulado de una migración de inventario."""
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


class InventoryMigrator:
    """Migra ajustes de inventario físico a stock.quant en Odoo."""

    def __init__(
        self,
        odoo: OdooClient,
        mapping: dict[str, str],
        options: MigrationOptions | None = None,
    ) -> None:
        self.odoo = odoo
        self.mapping = mapping
        self.options = options or MigrationOptions()

        # Cachés para evitar búsquedas repetidas en Odoo
        self._location_cache: dict[str, int | None] = {}
        self._product_cache: dict[str, int | None] = {}

    # ─── Resolución de Many2one ─────────────────────────────────

    def _resolve_location(self, name: str) -> int | None:
        """Busca una ubicación por complete_name, con caché."""
        if name not in self._location_cache:
            # Primero buscamos por complete_name exacto
            ids = self.odoo.search(LOCATION_MODEL, [("complete_name", "=", name)], limit=1)
            if not ids:
                # Fallback: por name
                ids = self.odoo.search(LOCATION_MODEL, [("name", "=", name)], limit=1)
            self._location_cache[name] = ids[0] if ids else None
            if not ids:
                log.warning("Ubicación no encontrada en Odoo: %r", name)
        return self._location_cache[name]

    def _resolve_product(self, code: str) -> int | None:
        """Busca un product.product por default_code, con caché."""
        code_clean = str(code).strip()
        if code_clean.endswith(".0"):
            code_clean = code_clean[:-2]
        if code_clean not in self._product_cache:
            ids = self.odoo.search(PRODUCT_MODEL, [("default_code", "=", code_clean)], limit=1)
            self._product_cache[code_clean] = ids[0] if ids else None
            if not ids:
                log.warning("Producto no encontrado en Odoo por default_code: %r", code_clean)
        return self._product_cache[code_clean]

    # ─── Orquestación ──────────────────────────────────────────

    def run(
        self,
        rows: Iterable[dict[str, Any]],
        total: int = 0,
        dry_run: bool = False,
    ) -> MigrationStats:
        """Procesa todas las filas de inventario."""
        stats = MigrationStats()
        rev_mapping = {v: k for k, v in self.mapping.items()}

        # Columnas de origen según el mapeo
        col_product = rev_mapping.get("product_id")
        col_location = rev_mapping.get("location_id")
        col_qty = rev_mapping.get("inventory_quantity")

        if not col_product:
            raise ValueError("El mapeo no contiene el campo 'product_id' (código del producto).")
        if not col_qty:
            raise ValueError("El mapeo no contiene el campo 'inventory_quantity' (cantidad).")

        quant_ids_modified: list[int] = []

        for idx, row in enumerate(rows, start=1):
            try:
                # Extraer valores de la fila
                product_raw = row.get(col_product)
                qty_raw = row.get(col_qty)

                if product_raw is None:
                    log.warning("Fila %s: product_id vacío, omitida.", idx)
                    stats.skipped += 1
                    _emit_progress({"done": idx, "total": total, "action": "skipped", "name": f"Fila {idx}"})
                    continue

                product_key = str(product_raw).strip()
                if product_key.endswith(".0"):
                    product_key = product_key[:-2]

                # Convertir cantidad
                try:
                    qty = float(str(qty_raw).replace(",", ".").strip()) if qty_raw is not None else 0.0
                except (ValueError, TypeError):
                    log.warning("Fila %s: cantidad inválida %r, usando 0.", idx, qty_raw)
                    qty = 0.0

                name_display = product_key

                if dry_run:
                    stats.created += 1
                    _emit_progress({"done": idx, "total": total, "action": "created", "name": name_display})
                    continue

                # Resolver IDs en Odoo
                product_id = self._resolve_product(product_key)
                if product_id is None:
                    stats.errors.append({
                        "row": idx,
                        "error": f"Producto no encontrado: {product_key}",
                        "data": row,
                    })
                    _emit_progress({"done": idx, "total": total, "action": "error", "name": name_display,
                                    "message": f"Producto no encontrado: {product_key}"})
                    continue

                location_id = None
                if col_location:
                    location_raw = row.get(col_location)
                    if location_raw:
                        location_id = self._resolve_location(str(location_raw).strip())

                # Buscar quant existente
                domain = [("product_id", "=", product_id)]
                if location_id:
                    domain.append(("location_id", "=", location_id))

                existing_ids = self.odoo.search(QUANT_MODEL, domain, limit=1)

                if existing_ids:
                    if not self.options.update_existing:
                        stats.skipped += 1
                        _emit_progress({"done": idx, "total": total, "action": "skipped", "name": name_display})
                        continue

                    quant_id = existing_ids[0]
                    self.odoo.write(QUANT_MODEL, [quant_id], {"inventory_quantity": qty})
                    quant_ids_modified.append(quant_id)
                    stats.updated += 1
                    _emit_progress({"done": idx, "total": total, "action": "updated", "name": name_display})
                else:
                    # Crear quant nuevo
                    create_vals: dict[str, Any] = {
                        "product_id": product_id,
                        "inventory_quantity": qty,
                    }
                    if location_id:
                        create_vals["location_id"] = location_id

                    new_id = self.odoo.execute(QUANT_MODEL, "create", [create_vals])
                    if isinstance(new_id, list):
                        new_id = new_id[0]
                    quant_ids_modified.append(new_id)
                    stats.created += 1
                    _emit_progress({"done": idx, "total": total, "action": "created", "name": name_display})

            except Exception as e:
                log.exception("Error en fila %s de inventario", idx)
                stats.errors.append({"row": idx, "error": str(e), "data": row})
                _emit_progress({"done": idx, "total": total, "action": "error",
                                "name": f"Fila {idx}", "message": str(e)})

        # Aplicar ajuste de inventario si se solicita
        if not dry_run and quant_ids_modified and self.options.apply_inventory:
            log.info("Aplicando ajuste de inventario para %d quants...", len(quant_ids_modified))
            try:
                self.odoo.execute(QUANT_MODEL, "action_apply_inventory", quant_ids_modified)
                log.info("Ajuste de inventario aplicado correctamente.")
            except Exception as e:
                log.warning("No se pudo aplicar el inventario automáticamente: %s. "
                            "Por favor, aplícalo manualmente desde Odoo.", e)

        log.info("Migración de inventario terminada: %s", stats.as_dict())
        return stats
