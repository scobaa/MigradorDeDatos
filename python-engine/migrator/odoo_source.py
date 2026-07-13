"""
Conector de origen Odoo para migración Odoo → Odoo.

Lee registros de un Odoo de origen y los devuelve como dicts listos para
ser procesados por los migradores existentes (PartnerMigrator, InventoryMigrator, etc.)

Por cada modelo define:
- Qué campos leer del origen.
- Cómo resolver Many2one (devuelve el texto para que el migrador destino lo resuelva).
- Un mapping automático origen → campos Odoo destino.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Generator

from migrator.odoo_client import OdooClient, OdooConfig

log = logging.getLogger(__name__)


# ─── Definición de modelos soportados ─────────────────────────────────────────
# Para cada modelo: campos a leer del origen y cómo mapearlos.

MODEL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "res.partner": {
        "fields": [
            "name", "vat", "ref", "email", "phone", "mobile", "website",
            "street", "street2", "city", "zip",
            "country_id", "state_id",
            "is_company", "customer_rank", "supplier_rank",
            "comment", "lang", "type", "parent_id",
        ],
        # Campos Many2one: {campo: campo_texto_en_el_dict_devuelto_por_read}
        "many2one": {
            "country_id": "_country",
            "state_id": "_state",
            "parent_id": "_parent_name",
        },
        # Mapeo automático origen→destino para el migrador
        # IMPORTANTE: _country y _state se pasan como texto para que
        # PartnerMigrator._resolve_geo() los convierta en IDs en el destino.
        "auto_mapping": {
            "name": "name", "vat": "vat", "ref": "ref",
            "email": "email", "phone": "phone", "mobile": "mobile",
            "website": "website", "street": "street", "street2": "street2",
            "city": "city", "zip": "zip",
            "_country": "_country", "_state": "_state",   # texto → resuelto por _resolve_geo()
            "is_company": "is_company",
            "customer_rank": "customer_rank", "supplier_rank": "supplier_rank",
            "comment": "comment", "lang": "lang",
            "type": "type", "_parent_name": "parent_id",
        },
    },
    "product.template": {
        "fields": [
            "name", "default_code", "barcode", "description",
            "list_price", "standard_price", "type",
            "categ_id", "active", "sale_ok", "purchase_ok",
        ],
        "many2one": {
            "categ_id": "_category",
        },
        "auto_mapping": {
            "name": "name", "default_code": "default_code",
            "barcode": "barcode", "description": "description",
            "list_price": "list_price", "standard_price": "standard_price",
            "type": "type", "_category": "categ_id",
            "active": "active", "sale_ok": "sale_ok", "purchase_ok": "purchase_ok",
        },
    },
    "stock.quant": {
        "fields": ["product_id", "location_id", "quantity"],
        "many2one": {
            "product_id": "_product_code",
            "location_id": "_location_name",
        },
        "auto_mapping": {
            "_product_code": "product_id",
            "_location_name": "location_id",
            "quantity": "inventory_quantity",
        },
    },
    "account.move": {
        "fields": [
            "name", "move_type", "invoice_date", "invoice_date_due",
            "partner_id", "ref", "narration", "state",
            "invoice_line_ids",
        ],
        "many2one": {
            "partner_id": "_partner_name",
        },
        "auto_mapping": {
            "name": "name", "_partner_name": "partner_id",
            "invoice_date": "invoice_date", "invoice_date_due": "invoice_date_due",
            "ref": "ref", "narration": "narration",
        },
    },
    "account.account": {
        "fields": [
            "code", "name", "account_type", "deprecated", "reconcile", "note",
            "internal_group", "internal_type", "user_type_id"
        ],
        "many2one": {},
        "auto_mapping": {
            "code": "code", "name": "name", "account_type": "account_type",
            "deprecated": "deprecated", "reconcile": "reconcile", "note": "note",
            "internal_group": "internal_group", "internal_type": "internal_type",
            "user_type_id": "user_type_id"
        },
    },
}


def _emit_progress(event: dict[str, Any]) -> None:
    sys.stderr.write(json.dumps({"event": "progress", **event}, ensure_ascii=False))
    sys.stderr.write("\n")
    sys.stderr.flush()


class OdooSourceConnector:
    """Lee registros de un Odoo origen en lotes y los adapta para los migradores."""

    def __init__(self, odoo: OdooClient, model: str, batch_size: int = 100) -> None:
        self.odoo = odoo
        self.model = model
        self.batch_size = batch_size
        self._defn = MODEL_DEFINITIONS.get(model)
        if not self._defn:
            raise ValueError(
                f"Modelo '{model}' no soportado para migración Odoo→Odoo. "
                f"Modelos disponibles: {list(MODEL_DEFINITIONS)}"
            )

    def count(self, domain: list | None = None) -> int:
        """Cuenta los registros del origen que cumplen el dominio."""
        return self.odoo.execute(self.model, "search_count", domain or [])

    def _get_available_fields(self, requested: list[str]) -> list[str]:
        """
        Filtra 'requested' contra los campos que realmente existen en el modelo
        del Odoo origen. Cachea el resultado para no repetir la llamada.
        """
        if not hasattr(self, "_available_fields_cache"):
            try:
                fields_meta = self.odoo.execute(self.model, "fields_get", [], {"attributes": ["string"]})
                self._available_fields_cache: set[str] = set(fields_meta.keys())
            except Exception as e:
                log.warning("No se pudo obtener la lista de campos del origen (%s): %s. Usando todos.", self.model, e)
                self._available_fields_cache = set(requested)

        valid = [f for f in requested if f in self._available_fields_cache]
        skipped = set(requested) - set(valid)
        if skipped:
            log.info("Campos no disponibles en el Odoo origen (se omitirán): %s", sorted(skipped))
        return valid

    def iter_rows(
        self, domain: list | None = None
    ) -> Generator[dict[str, Any], None, None]:
        """
        Lee registros del origen en lotes y los devuelve como dicts planos
        con Many2one resueltos como texto (para que el destino los busque por nombre).
        """
        domain = domain or []
        # Filtrar solo los campos que existen realmente en el Odoo origen
        fields = self._get_available_fields(self._defn["fields"])
        many2one_map = self._defn.get("many2one", {})

        offset = 0
        while True:
            batch = self.odoo.execute(
                self.model,
                "search_read",
                domain,
                fields,
                offset=offset,
                limit=self.batch_size,
            )
            if not batch:
                break
            for rec in batch:
                yield self._flatten(rec, many2one_map)
            offset += len(batch)
            if len(batch) < self.batch_size:
                break

    def _flatten(self, rec: dict[str, Any], many2one_map: dict[str, str]) -> dict[str, Any]:
        """
        Convierte el registro de Odoo en un dict plano:
        - Many2one (id, name) → solo el texto relevante.
        - Elimina el campo 'id' de Odoo (no queremos copiarlo al destino).
        """
        out: dict[str, Any] = {}
        for field, value in rec.items():
            if field == "id":
                continue
            if field in many2one_map and isinstance(value, (list, tuple)):
                # Odoo devuelve [id, nombre] para Many2one
                text_key = many2one_map[field]
                if field == "product_id":
                    # Para productos usamos default_code si está disponible
                    # Como aquí solo tenemos el nombre, lo usamos como clave
                    out[text_key] = value[1] if value else None
                else:
                    out[text_key] = value[1] if value else None
            elif isinstance(value, bool) and value is False:
                out[field] = None
            else:
                out[field] = value
        return out

    @property
    def auto_mapping(self) -> dict[str, str]:
        """Devuelve el mapeo automático campo_origen → campo_odoo_destino."""
        return dict(self._defn.get("auto_mapping", {}))
