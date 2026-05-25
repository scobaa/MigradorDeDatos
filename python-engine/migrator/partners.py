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
import re
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
    external_id_prefix: str = "cli_"


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
        Transforma y escribe una fila de la empresa y su contacto relacionado si existe.
        Devuelve la acción realizada para la empresa principal:
        'created' | 'updated' | 'skipped'.
        """
        # 1. Obtener mapeo inverso para los campos virtuales especiales
        rev_mapping = {v: k for k, v in self.mapping.items()}

        external_id_col = rev_mapping.get("__external_id")
        contact_name_col = rev_mapping.get("contact_name")
        contact_email_col = rev_mapping.get("contact_email")
        contact_phone_col = rev_mapping.get("contact_phone")
        contact_mobile_col = rev_mapping.get("contact_mobile")

        # 2. Extraer valor de ID externa si está mapeada
        raw_ext_id = None
        if external_id_col:
            raw_ext_id = row.get(external_id_col)

        company_xml_id = None
        if raw_ext_id is not None:
            # Limpiar el valor para evitar decimales si Excel lo leyó como float (ej: "15.0" -> "15")
            cleaned_ext_id = str(raw_ext_id).strip()
            if cleaned_ext_id.endswith(".0"):
                cleaned_ext_id = cleaned_ext_id[:-2]
            if cleaned_ext_id:
                prefix = self.options.external_id_prefix or ""
                company_xml_id = f"{prefix}{cleaned_ext_id}"

        # 3. Buscar duplicado por ID externa primero
        existing_id = None
        if company_xml_id:
            existing_id = self.odoo.get_xml_id_res_id(company_xml_id, PARTNER_MODEL)

        # 4. Transformar los datos de la empresa principal
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

        # 5. Si no se encontró por ID externa, buscar por deduplicación normal (NIF, nombre, ref)
        if not existing_id:
            existing_id = self.find_duplicate(vals)

        # 6. Crear o actualizar la empresa
        action = "created"
        company_id = existing_id

        if existing_id:
            if not self.options.update_existing:
                action = "skipped"
            else:
                if not dry_run:
                    # No pisar customer/supplier_rank de un partner ya existente.
                    update_vals = {
                        k: v for k, v in vals.items()
                        if k not in ("customer_rank", "supplier_rank")
                    }
                    self.odoo.write(PARTNER_MODEL, [existing_id], update_vals)
                action = "updated"
        else:
            if not dry_run:
                company_id = self._create_with_vat_fallback(vals)
            action = "created"

        # 7. Vincular XML ID de la empresa en ir.model.data si no existía ya
        if not dry_run and company_xml_id and company_id:
            self.odoo.create_or_update_xml_id(company_xml_id, PARTNER_MODEL, company_id)

        # 8. Procesar contacto relacionado si está mapeado
        if contact_name_col:
            from transformers.partners import clean_str, clean_email, clean_phone
            raw_contact_name = row.get(contact_name_col)
            contact_name = clean_str(raw_contact_name)

            if contact_name:
                contact_email = clean_email(row.get(contact_email_col)) if contact_email_col else None
                contact_phone = clean_phone(row.get(contact_phone_col), self.options.default_country) if contact_phone_col else None
                contact_mobile = clean_phone(row.get(contact_mobile_col), self.options.default_country) if contact_mobile_col else None

                contact_vals = {
                    "name": contact_name,
                    "is_company": False,
                    "type": "contact",
                }
                if company_id:
                    contact_vals["parent_id"] = company_id
                if contact_email:
                    contact_vals["email"] = contact_email
                if contact_phone:
                    contact_vals["phone"] = contact_phone
                if contact_mobile:
                    contact_vals["mobile"] = contact_mobile

                contact_vals = self.odoo.filter_vals(PARTNER_MODEL, contact_vals)

                # Deduplicar el contacto
                contact_id = None
                contact_xml_id = None

                if company_xml_id:
                    contact_xml_id = f"{company_xml_id}_contact"
                    contact_id = self.odoo.get_xml_id_res_id(contact_xml_id, PARTNER_MODEL)

                # Si no se encuentra por XML ID pero tenemos ID de empresa, buscar por nombre bajo la empresa
                if not contact_id and company_id:
                    domain = [
                        ("parent_id", "=", company_id),
                        ("name", "=", contact_name),
                        ("is_company", "=", False),
                    ]
                    c_ids = self.odoo.search(PARTNER_MODEL, domain, limit=1)
                    if c_ids:
                        contact_id = c_ids[0]

                # Crear o actualizar contacto relacionado
                if contact_id:
                    if self.options.update_existing and not dry_run:
                        self.odoo.write(PARTNER_MODEL, [contact_id], contact_vals)
                else:
                    if not dry_run:
                        contact_id = self.odoo.create(PARTNER_MODEL, contact_vals)

                # Registrar XML ID del contacto
                if not dry_run and contact_xml_id and contact_id:
                    self.odoo.create_or_update_xml_id(contact_xml_id, PARTNER_MODEL, contact_id)

        # 9. Procesar cuenta bancaria si está mapeada
        bank_acc_col = rev_mapping.get("bank_acc_number")
        bank_name_col = rev_mapping.get("bank_name")

        if bank_acc_col:
            raw_acc_num = row.get(bank_acc_col)
            if raw_acc_num is not None:
                # Limpieza básica de la cuenta bancaria (sin espacios ni guiones)
                cleaned_acc_num = str(raw_acc_num).strip().upper()
                cleaned_acc_num = re.sub(r"[\s\-]", "", cleaned_acc_num)
                # Si Excel leyó como float con .0 al final
                if cleaned_acc_num.endswith(".0"):
                    cleaned_acc_num = cleaned_acc_num[:-2]

                if cleaned_acc_num and company_id:
                    bank_xml_id = None
                    if company_xml_id:
                        bank_xml_id = f"{company_xml_id}_bank"

                    # 1. Buscar si la cuenta ya existe
                    bank_acc_id = None
                    if bank_xml_id:
                        bank_acc_id = self.odoo.get_xml_id_res_id(bank_xml_id, "res.partner.bank")

                    if not bank_acc_id:
                        # Buscar por número de cuenta exacto bajo el mismo partner
                        domain = [
                            ("partner_id", "=", company_id),
                            ("acc_number", "=", cleaned_acc_num)
                        ]
                        b_ids = self.odoo.search("res.partner.bank", domain, limit=1)
                        if b_ids:
                            bank_acc_id = b_ids[0]

                    # 2. Crear o actualizar cuenta bancaria
                    if not bank_acc_id:
                        # Resolver banco id si existe bank_name
                        bank_id = None
                        if bank_name_col:
                            raw_bank_name = row.get(bank_name_col)
                            if raw_bank_name:
                                bank_id = self.odoo.get_or_create_bank(str(raw_bank_name))

                        bank_vals = {
                            "acc_number": cleaned_acc_num,
                            "partner_id": company_id,
                        }
                        if bank_id:
                            bank_vals["bank_id"] = bank_id

                        if not dry_run:
                            try:
                                log.info("Creando cuenta bancaria para partner_id=%s: %s", company_id, cleaned_acc_num)
                                bank_acc_id = self.odoo.create("res.partner.bank", bank_vals)
                            except Exception as e:
                                # Capturar fallos (ej. validación estricta de IBAN en Odoo) y no interrumpir
                                log.warning("No se pudo crear la cuenta bancaria %r: %s", cleaned_acc_num, e)

                    # Vincular XML ID del banco
                    if not dry_run and bank_xml_id and bank_acc_id:
                        self.odoo.create_or_update_xml_id(bank_xml_id, "res.partner.bank", bank_acc_id)

        return action

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
