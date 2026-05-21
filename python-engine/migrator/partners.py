"""
Migrador de res.partner: orquesta el proceso completo para clientes.

    fila cruda → transform_partner() → resolver Many2one → buscar duplicado
              → crear o actualizar en Odoo

Reporta progreso por stderr (una línea JSON por evento) para que el contenedor
Tauri lo lea en vivo y actualice la barra de progreso del wizard:

    {"event": "progress", "done": 12, "total": 340, "action": "created", "name": "..."}

Soporta dry-run (no escribe, solo simula y cuenta) y acumula estadísticas
finales: creados / actualizados / omitidos / errores.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from transformers.partners import transform_partner

log = logging.getLogger(__name__)

PARTNER_MODEL = "res.partner"


@dataclass
class MigrationOptions:
    """Opciones de una migración de partners."""
    default_country: str = "ES"
    customer_rank: int = 1
    supplier_rank: int = 0
    infer_company: bool = True
    update_existing: bool = True  # si False, los duplicados se omiten


@dataclass
class MigrationStats:
    """Resultado acumulado de una migración."""
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


class PartnerMigrator:
    """Migra clientes hacia un modelo res.partner de Odoo."""

    def __init__(
        self,
        odoo: OdooClient,
        mapping: dict[str, str],
        options: MigrationOptions | None = None,
    ) -> None:
        self.odoo = odoo
        self.mapping = mapping
        self.options = options or MigrationOptions()

    # ─── Resolución de Many2one geográficos ────────────────────

    def _resolve_geo(self, vals: dict[str, Any]) -> None:
        """Convierte _country/_state (texto) en country_id/state_id (in place)."""
        country_text = vals.pop("_country", None)
        state_text = vals.pop("_state", None)

        country_id = None
        if country_text:
            country_id = self.odoo.get_country_id(country_text)
            if country_id:
                vals["country_id"] = country_id
            else:
                log.warning("País no encontrado en Odoo: %r", country_text)

        if state_text and country_id:
            state_id = self.odoo.get_state_id(country_id, state_text)
            if state_id:
                vals["state_id"] = state_id
            else:
                log.warning("Provincia no encontrada: %r", state_text)

    # ─── Deduplicación ─────────────────────────────────────────

    def find_duplicate(self, vals: dict[str, Any]) -> int | None:
        """
        Busca un partner existente según prioridad (CLAUDE.md):
        1. mismo vat   2. mismo name + is_company   3. mismo ref
        Devuelve el ID o None.
        """
        vat = vals.get("vat")
        if vat:
            ids = self.odoo.search(PARTNER_MODEL, [("vat", "=", vat)], limit=1)
            if ids:
                return ids[0]

        name = vals.get("name")
        if name:
            domain = [("name", "=", name)]
            if "is_company" in vals:
                domain.append(("is_company", "=", vals["is_company"]))
            ids = self.odoo.search(PARTNER_MODEL, domain, limit=1)
            if ids:
                return ids[0]

        ref = vals.get("ref")
        if ref:
            ids = self.odoo.search(PARTNER_MODEL, [("ref", "=", ref)], limit=1)
            if ids:
                return ids[0]

        return None

    # ─── Orquestación ──────────────────────────────────────────

    def run(
        self,
        rows: Iterable[dict[str, Any]],
        total: int = 0,
        dry_run: bool = False,
    ) -> MigrationStats:
        """
        Procesa todas las filas. Si dry_run=True no escribe en Odoo.

        Args:
            rows: filas crudas del origen ({columna: valor}).
            total: nº total de filas (para el % de progreso); 0 si desconocido.
            dry_run: simular sin escribir.
        """
        stats = MigrationStats()
        log.info("Iniciando migración de partners (dry_run=%s, total=%s)", dry_run, total)

        for i, row in enumerate(rows, start=1):
            try:
                action = self._process_row(row, dry_run)
                setattr(stats, action, getattr(stats, action) + 1)
                _emit_progress(
                    {"done": i, "total": total, "action": action}
                )
            except Exception as e:  # noqa: BLE001 - aislamos el fallo por fila
                log.exception("Error en fila %s", i)
                stats.errors.append({"row": i, "error": str(e), "data": row})
                _emit_progress(
                    {"done": i, "total": total, "action": "error", "message": str(e)}
                )

        log.info("Migración terminada: %s", stats.as_dict())
        return stats

    def _process_row(self, row: dict[str, Any], dry_run: bool) -> str:
        """
        Transforma y escribe una fila. Devuelve la acción realizada:
        'created' | 'updated' | 'skipped'.
        """
        vals = transform_partner(
            row,
            self.mapping,
            default_country=self.options.default_country,
            customer_rank=self.options.customer_rank,
            supplier_rank=self.options.supplier_rank,
            infer_company=self.options.infer_company,
        )
        self._resolve_geo(vals)

        existing_id = self.find_duplicate(vals)

        if existing_id:
            if not self.options.update_existing:
                return "skipped"
            if not dry_run:
                # No pisar customer/supplier_rank de un partner ya existente.
                update_vals = {
                    k: v for k, v in vals.items()
                    if k not in ("customer_rank", "supplier_rank")
                }
                self.odoo.write(PARTNER_MODEL, [existing_id], update_vals)
            return "updated"

        if not dry_run:
            self.odoo.create(PARTNER_MODEL, vals)
        return "created"
