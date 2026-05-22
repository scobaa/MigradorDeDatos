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
import xmlrpc.client
from dataclasses import dataclass, field
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from transformers.partners import transform_partner

log = logging.getLogger(__name__)

PARTNER_MODEL = "res.partner"

# Códigos ISO 3166-1 numérico → alfa-2 para los países más habituales en
# bases de datos de ERPs españoles (FactuSOL guarda PAICLI como numérico).
_ISO_NUMERIC: dict[str, str] = {
    "004": "AF", "008": "AL", "012": "DZ", "020": "AD", "024": "AO",
    "032": "AR", "036": "AU", "040": "AT", "056": "BE", "068": "BO",
    "076": "BR", "100": "BG", "116": "KH", "124": "CA", "144": "LK",
    "152": "CL", "156": "CN", "170": "CO", "188": "CR", "191": "HR",
    "192": "CU", "196": "CY", "203": "CZ", "208": "DK", "218": "EC",
    "818": "EG", "222": "SV", "231": "ET", "233": "EE", "246": "FI",
    "250": "FR", "276": "DE", "300": "GR", "320": "GT", "332": "HT",
    "340": "HN", "348": "HU", "356": "IN", "360": "ID", "364": "IR",
    "368": "IQ", "372": "IE", "376": "IL", "380": "IT", "388": "JM",
    "392": "JP", "400": "JO", "404": "KE", "410": "KR", "414": "KW",
    "422": "LB", "428": "LV", "440": "LT", "442": "LU", "484": "MX",
    "504": "MA", "528": "NL", "554": "NZ", "558": "NI", "566": "NG",
    "578": "NO", "586": "PK", "591": "PA", "598": "PG", "600": "PY",
    "604": "PE", "608": "PH", "616": "PL", "620": "PT", "630": "PR",
    "634": "QA", "642": "RO", "643": "RU", "682": "SA", "694": "SL",
    "703": "SK", "705": "SI", "706": "SO", "710": "ZA", "724": "ES",
    "752": "SE", "756": "CH", "760": "SY", "764": "TH", "780": "TT",
    "788": "TN", "792": "TR", "804": "UA", "784": "AE", "826": "GB",
    "840": "US", "858": "UY", "862": "VE", "704": "VN", "887": "YE",
    "716": "ZW",
}


@dataclass
class MigrationOptions:
    """Opciones de una migración de partners."""
    default_country: str = "ES"
    customer_rank: int = 1
    supplier_rank: int = 0
    infer_company: bool = True
    update_existing: bool = True  # si False, los duplicados se omiten
    ref_prefix: str = ""          # prefijo para el campo ref (ej. "cli_" en FactuSOL)


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

    # Alias de provincias: nombres que FactuSOL (u otros ERPs) usan de forma
    # no estándar y que Odoo no reconocería ni con normalización de tildes.
    # Clave: nombre en minúsculas tal como viene del origen.
    _STATE_ALIASES: dict[str, str] = {
        # Ciudades usadas como nombre de provincia (FactuSOL y otros ERPs)
        "santander": "Cantabria",
        "san sebastian": "Gipuzkoa",
        "san sebastián": "Gipuzkoa",
        "vitoria": "Araba/Álava",
        "vitoria-gasteiz": "Araba/Álava",
        "pamplona": "Navarra",
        "logroño": "La Rioja",
        # Nombres cortos / alternativos frecuentes
        "baleares": "Illes Balears (Islas Baleares)",
        "islas baleares": "Illes Balears (Islas Baleares)",
        "mallorca": "Illes Balears (Islas Baleares)",
        "tenerife": "Santa Cruz de Tenerife",
        "isla de la palma": "Santa Cruz de Tenerife",
        "la palma": "Santa Cruz de Tenerife",
        "gran canaria": "Las Palmas",
        "lanzarote": "Las Palmas",
        "fuerteventura": "Las Palmas",
        # Cadenas largas con ciudad+provincia (coger la parte de provincia)
        "lanzarote - las palmas de gran canaria": "Las Palmas",
        # Variantes de La Coruña
        "coruña": "A Coruña (La Coruña)",
        "la coruña": "A Coruña (La Coruña)",
        "a coruña": "A Coruña (La Coruña)",
    }

    def _resolve_geo(self, vals: dict[str, Any]) -> None:
        """Convierte _country/_state (texto) en country_id/state_id (in place)."""
        country_text = vals.pop("_country", None)
        state_text = vals.pop("_state", None)

        # FactuSOL guarda el país como código ISO numérico (ej. "724" = España).
        # Convertimos a alfa-2 antes de buscar en Odoo.
        if country_text and country_text.strip().isdigit():
            numeric = country_text.strip().zfill(3)
            alpha2 = _ISO_NUMERIC.get(numeric)
            if alpha2:
                country_text = alpha2
            else:
                log.warning("Código ISO numérico desconocido: %r", country_text)
                country_text = None

        country_id = None
        if country_text:
            country_id = self.odoo.get_country_id(country_text)
            if country_id:
                vals["country_id"] = country_id
            else:
                log.warning("País no encontrado en Odoo: %r", country_text)

        # Si no hay país explícito pero sí provincia, intentar con default_country
        # (caso habitual: PAICLI vacío en registros españoles de FactuSOL).
        if state_text and not country_id:
            country_id = self.odoo.get_country_id(self.options.default_country)

        if state_text and country_id:
            resolved_state = self._STATE_ALIASES.get(state_text.lower(), state_text)
            state_id = self.odoo.get_state_id(country_id, resolved_state)
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
        if self.options.ref_prefix and "ref" in vals:
            vals["ref"] = f"{self.options.ref_prefix}{vals['ref']}"
        self._resolve_geo(vals)
        vals = self.odoo.filter_vals(PARTNER_MODEL, vals)

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
            self._create_with_vat_fallback(vals)
        return "created"

    def _create_with_vat_fallback(self, vals: dict[str, Any]) -> int:
        """
        Intenta crear el partner. Si Odoo rechaza el VAT por inválido,
        lo elimina de los vals y reintenta — el partner entra sin NIF
        para que el consultor lo revise manualmente.
        """
        try:
            return self.odoo.create(PARTNER_MODEL, vals)
        except xmlrpc.client.Fault as e:
            if "vat" in str(e).lower() or "nif" in str(e).lower():
                bad_vat = vals.pop("vat", None)
                log.warning(
                    "VAT inválido para Odoo (%r), creando sin NIF: %s",
                    bad_vat,
                    vals.get("name"),
                )
                return self.odoo.create(PARTNER_MODEL, vals)
            raise
