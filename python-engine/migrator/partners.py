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
    external_id_column: str | None = None
    batch_size: int = 100


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

    def _resolve_accounts(self, vals: dict[str, Any]) -> None:
        """Convierte _account_payable/_account_receivable (código) en los IDs de Odoo (in place)."""
        payable_code = vals.pop("_account_payable", None)
        receivable_code = vals.pop("_account_receivable", None)

        if payable_code:
            acc_id = self.odoo.get_account_id(str(payable_code).strip())
            if acc_id:
                vals["property_account_payable_id"] = acc_id
                log.debug("Cuenta por pagar resuelta: %s → id=%s", payable_code, acc_id)
            else:
                log.warning("Cuenta por pagar no encontrada en Odoo: %r", payable_code)

        if receivable_code:
            acc_id = self.odoo.get_account_id(str(receivable_code).strip())
            if acc_id:
                vals["property_account_receivable_id"] = acc_id
                log.debug("Cuenta por cobrar resuelta: %s → id=%s", receivable_code, acc_id)
            else:
                log.warning("Cuenta por cobrar no encontrada en Odoo: %r", receivable_code)

    # Campos extra a probar por modelo relacionado (además del nombre)
    _EXTRA_SEARCH_FIELDS: dict[str, list[str]] = {
        "account.account": ["code"],
        "product.product": ["default_code", "barcode"],
        "product.template": ["default_code"],
        "res.partner": ["ref", "vat"],
        "account.tax": ["name"],
        "uom.uom": [],
    }

    def _resolve_many2one_fields(self, vals: dict[str, Any]) -> None:
        """Resuelve automáticamente cualquier campo Many2one que tenga un valor en texto.

        Consulta los metadatos del modelo para saber el tipo y el modelo relacionado de
        cada campo, y llama a resolve_many2one para buscar por ID externo o nombre.
        Los campos que no se puedan resolver se eliminan de vals para no causar errores.
        """
        try:
            fields_info = self.odoo.get_fields_info(PARTNER_MODEL)
        except Exception as e:
            log.warning("No se pudo obtener metadatos de campos de %s: %s", PARTNER_MODEL, e)
            return

        for field_name in list(vals.keys()):
            value = vals[field_name]
            # Si ya es un entero (ID resuelto) o está vacío, nada que hacer
            if isinstance(value, int) or not value:
                continue

            field_meta = fields_info.get(field_name, {})
            if field_meta.get("type") != "many2one":
                continue

            related_model = field_meta.get("relation")
            if not related_model:
                continue

            str_value = str(value).strip()
            extra_fields = self._EXTRA_SEARCH_FIELDS.get(related_model, [])

            resolved_id = self.odoo.resolve_many2one(
                str_value,
                related_model,
                extra_fields=extra_fields,
            )

            if resolved_id:
                vals[field_name] = resolved_id
                log.debug("Campo Many2one '%s' resuelto: %r → id=%s (modelo: %s)", field_name, str_value, resolved_id, related_model)
            else:
                log.warning("No se pudo resolver campo '%s' con valor %r en modelo '%s'. Se omitirá.", field_name, str_value, related_model)
                del vals[field_name]





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
        Procesa todas las filas en lotes (batching) para optimizar el rendimiento.
        """
        stats = MigrationStats()
        log.info("Iniciando migración de partners en lotes (dry_run=%s, total=%s, batch_size=%s)", 
                 dry_run, total, self.options.batch_size)

        # Función auxiliar para agrupar en lotes
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

        log.info("Migración terminada: %s", stats.as_dict())
        return stats

    def _process_batch(
        self,
        batch_rows: list[dict[str, Any]],
        start_idx: int,
        total: int,
        dry_run: bool,
        stats: MigrationStats,
    ) -> None:
        # 1. Preparación de datos y limpieza inicial en memoria
        records = []
        rev_mapping = {v: k for k, v in self.mapping.items()}

        external_id_col = self.options.external_id_column
        if not external_id_col:
            external_id_col = rev_mapping.get("__external_id")
        contact_name_col = rev_mapping.get("contact_name")
        contact_email_col = rev_mapping.get("contact_email")
        contact_phone_col = rev_mapping.get("contact_phone")
        contact_mobile_col = rev_mapping.get("contact_mobile")
        bank_acc_col = rev_mapping.get("bank_acc_number")
        bank_name_col = rev_mapping.get("bank_name")

        for idx_offset, row in enumerate(batch_rows):
            row_idx = start_idx + idx_offset + 1
            try:
                # Transformar datos de empresa principal
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
                self._resolve_accounts(vals)
                self._resolve_many2one_fields(vals)
                vals = self.odoo.filter_vals(PARTNER_MODEL, vals)

                # Extraer XML ID si aplica
                company_xml_id = None
                if external_id_col:
                    raw_ext_id = row.get(external_id_col)
                    if raw_ext_id is not None:
                        cleaned_ext_id = str(raw_ext_id).strip()
                        if cleaned_ext_id.endswith(".0"):
                            cleaned_ext_id = cleaned_ext_id[:-2]
                        if cleaned_ext_id:
                            prefix = self.options.external_id_prefix or ""
                            company_xml_id = f"{prefix}{cleaned_ext_id}"

                records.append({
                    "idx": row_idx,
                    "row": row,
                    "vals": vals,
                    "company_xml_id": company_xml_id,
                    "existing_id": None,
                    "action": None,
                    "company_id": None,
                    "error_msg": None,
                })
            except Exception as e:
                # Fila corrupta antes de Odoo
                log.exception("Error de transformación en fila %s", row_idx)
                stats.errors.append({"row": row_idx, "error": str(e), "data": row})
                _emit_progress(
                    {"done": row_idx, "total": total, "action": "error", "message": str(e)}
                )

        # Si no hay registros válidos que procesar en este lote, terminamos
        if not records:
            return

        # 2. Búsqueda de duplicados en bloque (Deduplicación masiva)
        # 2.1 Buscar por XML IDs en ir.model.data
        xml_id_to_res_id = {}
        company_xml_ids = [r["company_xml_id"] for r in records if r["company_xml_id"]]
        if company_xml_ids:
            domain_xml = [
                ("module", "=", "__import__"),
                ("name", "in", company_xml_ids),
                ("model", "=", PARTNER_MODEL),
            ]
            try:
                xml_recs = self.odoo.search_read("ir.model.data", domain_xml, ["name", "res_id"])
                xml_id_to_res_id = {x["name"]: x["res_id"] for x in xml_recs}
            except Exception as e:
                log.warning("Fallo al buscar XML IDs en lote: %s", e)

        # Asignar IDs encontrados por XML ID
        records_to_check = []
        for r in records:
            xml_id = r["company_xml_id"]
            if xml_id and xml_id in xml_id_to_res_id:
                r["existing_id"] = xml_id_to_res_id[xml_id]
            else:
                records_to_check.append(r)

        # 2.2 Buscar por NIF, Nombre y Ref para los registros restantes
        if records_to_check:
            vats = list(set([r["vals"]["vat"] for r in records_to_check if r["vals"].get("vat")]))
            names = list(set([r["vals"]["name"] for r in records_to_check if r["vals"].get("name")]))
            refs = list(set([r["vals"]["ref"] for r in records_to_check if r["vals"].get("ref")]))

            vat_to_id = {}
            name_to_id = {}
            ref_to_id = {}

            if vats:
                try:
                    res_vat = self.odoo.search_read(PARTNER_MODEL, [("vat", "in", vats)], ["id", "vat"])
                    vat_to_id = {x["vat"]: x["id"] for x in res_vat}
                except Exception as e:
                    log.warning("Fallo al buscar NIFs en lote: %s", e)

            if names:
                try:
                    res_name = self.odoo.search_read(PARTNER_MODEL, [("name", "in", names)], ["id", "name"])
                    name_to_id = {x["name"]: x["id"] for x in res_name}
                except Exception as e:
                    log.warning("Fallo al buscar nombres en lote: %s", e)

            if refs:
                try:
                    res_ref = self.odoo.search_read(PARTNER_MODEL, [("ref", "in", refs)], ["id", "ref"])
                    ref_to_id = {x["ref"]: x["id"] for x in res_ref}
                except Exception as e:
                    log.warning("Fallo al buscar referencias en lote: %s", e)

            # Asignar IDs basados en coincidencia normal
            for r in records_to_check:
                vat = r["vals"].get("vat")
                name = r["vals"].get("name")
                ref = r["vals"].get("ref")

                if vat and vat in vat_to_id:
                    r["existing_id"] = vat_to_id[vat]
                elif name and name in name_to_id:
                    r["existing_id"] = name_to_id[name]
                elif ref and ref in ref_to_id:
                    r["existing_id"] = ref_to_id[ref]

        # 2.5. Resolver parent_id si está mapeado
        for r in records:
            parent_key = r["vals"].get("parent_id")
            if parent_key and not isinstance(parent_key, int):
                parent_key_str = str(parent_key).strip()
                # Buscar padre en Odoo por NIF, Ref o Nombre
                domain = ["|", "|", ("vat", "=", parent_key_str), ("ref", "=", parent_key_str), ("name", "=", parent_key_str)]
                p_ids = self.odoo.search(PARTNER_MODEL, domain, limit=1)
                if p_ids:
                    r["vals"]["parent_id"] = p_ids[0]
                else:
                    log.warning("No se encontró empresa padre en Odoo para la clave: %s (Ignorando parent_id en fila %s)", parent_key_str, r["idx"])
                    r["vals"].pop("parent_id", None)

        # 3. Separar en Actualizaciones vs Creaciones
        updates_records = []
        creates_records = []

        for r in records:
            if r["existing_id"]:
                if not self.options.update_existing:
                    r["action"] = "skipped"
                    r["company_id"] = r["existing_id"]
                else:
                    updates_records.append(r)
            else:
                creates_records.append(r)

        # 4. Procesar Actualizaciones (uno a uno ya que Odoo write no permite bulk heterogéneo)
        for r in updates_records:
            r["company_id"] = r["existing_id"]
            r["action"] = "updated"
            if not dry_run:
                try:
                    update_vals = {
                        k: v for k, v in r["vals"].items()
                        if k not in ("customer_rank", "supplier_rank", "parent_id")
                        # parent_id se excluye en actualizaciones: si el registro ya existe
                        # en el destino, Odoo puede lanzar "recursive Partner hierarchies"
                        # al intentar reasignar la empresa padre.
                    }
                    self.odoo.write(PARTNER_MODEL, [r["existing_id"]], update_vals)
                except Exception as e:
                    log.exception("Error al actualizar fila %s", r["idx"])
                    r["action"] = "error"
                    r["error_msg"] = str(e)

        # 5. Procesar Creaciones
        if creates_records:
            if dry_run:
                for r in creates_records:
                    r["action"] = "created"
            else:
                # Creación masiva en un solo RPC call (Bulk Create)
                vals_list = [r["vals"] for r in creates_records]
                try:
                    log.info("Creando lote de %s partners en Odoo", len(vals_list))
                    created_ids = self.odoo.execute(PARTNER_MODEL, "create", vals_list)
                    # Si Odoo devuelve un solo ID en versiones viejas (aunque le pasamos lista), o lista de IDs
                    if isinstance(created_ids, int):
                        created_ids = [created_ids]
                    
                    for r, cid in zip(creates_records, created_ids):
                        r["company_id"] = cid
                        r["action"] = "created"
                except Exception as bulk_err:
                    log.warning("Fallo en creación masiva (haciendo fallback fila a fila): %s", bulk_err)
                    # Fallback fila a fila para aislar fallos
                    for r in creates_records:
                        try:
                            cid = self._create_with_vat_fallback(r["vals"])
                            r["company_id"] = cid
                            r["action"] = "created"
                        except Exception as row_err:
                            log.exception("Error al crear fila %s en el fallback", r["idx"])
                            r["action"] = "error"
                            r["error_msg"] = str(row_err)

        # 6. Vincular XML IDs, Contactos Relacionados y Cuentas Bancarias de forma individual
        for r in records:
            if r["action"] == "error":
                continue

            company_id = r["company_id"]
            company_xml_id = r["company_xml_id"]
            row = r["row"]

            # 6.1 Vincular XML ID de la empresa principal
            if not dry_run and company_xml_id and company_id and r["action"] == "created":
                try:
                    self.odoo.create_or_update_xml_id(company_xml_id, PARTNER_MODEL, company_id)
                except Exception as e:
                    log.warning("No se pudo asociar XML ID para la empresa %s: %s", company_xml_id, e)

            # 6.2 Procesar contacto relacionado si está mapeado
            if contact_name_col and company_id:
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
                        "parent_id": company_id,
                    }
                    if contact_email:
                        contact_vals["email"] = contact_email
                    if contact_phone:
                        contact_vals["phone"] = contact_phone
                    if contact_mobile:
                        contact_vals["mobile"] = contact_mobile

                    contact_vals = self.odoo.filter_vals(PARTNER_MODEL, contact_vals)

                    contact_id = None
                    contact_xml_id = None

                    if company_xml_id:
                        contact_xml_id = f"{company_xml_id}_contact"
                        try:
                            contact_id = self.odoo.get_xml_id_res_id(contact_xml_id, PARTNER_MODEL)
                        except Exception:
                            pass

                    if not contact_id:
                        try:
                            domain_c = [
                                ("parent_id", "=", company_id),
                                ("name", "=", contact_name),
                                ("is_company", "=", False),
                            ]
                            c_ids = self.odoo.search(PARTNER_MODEL, domain_c, limit=1)
                            if c_ids:
                                contact_id = c_ids[0]
                        except Exception:
                            pass

                    # Crear o actualizar contacto
                    if not dry_run:
                        try:
                            if contact_id:
                                if self.options.update_existing:
                                    self.odoo.write(PARTNER_MODEL, [contact_id], contact_vals)
                            else:
                                contact_id = self.odoo.create(PARTNER_MODEL, contact_vals)

                            if contact_xml_id and contact_id:
                                self.odoo.create_or_update_xml_id(contact_xml_id, PARTNER_MODEL, contact_id)
                        except Exception as e:
                            log.warning("No se pudo procesar el contacto para fila %s: %s", r["idx"], e)

            # 6.3 Procesar cuenta bancaria si está mapeada
            if bank_acc_col and company_id:
                raw_acc_num = row.get(bank_acc_col)
                if raw_acc_num is not None:
                    cleaned_acc_num = str(raw_acc_num).strip().upper()
                    cleaned_acc_num = re.sub(r"[\s\-]", "", cleaned_acc_num)
                    if cleaned_acc_num.endswith(".0"):
                        cleaned_acc_num = cleaned_acc_num[:-2]

                    if cleaned_acc_num:
                        bank_xml_id = None
                        if company_xml_id:
                            bank_xml_id = f"{company_xml_id}_bank"

                        bank_acc_id = None
                        if bank_xml_id:
                            try:
                                bank_acc_id = self.odoo.get_xml_id_res_id(bank_xml_id, "res.partner.bank")
                            except Exception:
                                pass

                        if not bank_acc_id:
                            try:
                                domain_b = [
                                    ("partner_id", "=", company_id),
                                    ("acc_number", "=", cleaned_acc_num)
                                ]
                                b_ids = self.odoo.search("res.partner.bank", domain_b, limit=1)
                                if b_ids:
                                    bank_acc_id = b_ids[0]
                            except Exception:
                                pass

                        # Crear o actualizar banco
                        if not bank_acc_id and not dry_run:
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

                            try:
                                bank_acc_id = self.odoo.create("res.partner.bank", bank_vals)
                                if bank_xml_id and bank_acc_id:
                                    self.odoo.create_or_update_xml_id(bank_xml_id, "res.partner.bank", bank_acc_id)
                            except Exception as e:
                                log.warning("No se pudo crear la cuenta bancaria %r: %s", cleaned_acc_num, e)

        # 7. Registrar estadísticas finales y emitir progreso
        for r in records:
            row_idx = r["idx"]
            action = r["action"]
            error_msg = r["error_msg"]
            row = r["row"]

            if action == "error":
                stats.errors.append({"row": row_idx, "error": error_msg, "data": row})
                _emit_progress(
                    {"done": row_idx, "total": total, "action": "error", "message": error_msg}
                )
            else:
                setattr(stats, action, getattr(stats, action) + 1)
                _emit_progress(
                    {"done": row_idx, "total": total, "action": action}
                )

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
