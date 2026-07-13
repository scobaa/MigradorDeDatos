import logging
import re
from typing import Any

log = logging.getLogger(__name__)

SUPPORTED_FIELDS = {
    "code",
    "name",
    "account_type",
    "internal_group",
    "internal_type",
    "user_type_id",
    "deprecated",
    "reconcile",
    "note",
}


def get_mapping_template() -> dict[str, str]:
    return {
        "Código": "code",
        "Nombre": "name",
        "Tipo": "account_type",
        "Grupo Interno": "internal_group",
        "Tipo Interno": "internal_type",
        "Permitir conciliación": "reconcile",
        "Obsoleta": "deprecated",
        "Notas": "note",
    }


def get_dependencies() -> list[str]:
    return []


def clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def clean_bool(value: Any) -> bool:
    if not value:
        return False
    text = str(value).strip().lower()
    return text in ("1", "true", "t", "yes", "y", "sí", "si", "verdadero")


def transform_row(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    vals: dict[str, Any] = {}
    
    for src_col, odoo_field in mapping.items():
        if not odoo_field or odoo_field not in SUPPORTED_FIELDS:
            continue
            
        val = row.get(src_col)
        
        if odoo_field in ("code", "name", "account_type", "internal_group", "internal_type", "user_type_id", "note"):
            clean_val = clean_str(val)
            # Remove .0 if excel parsed code as float
            if odoo_field == "code" and clean_val and clean_val.endswith(".0"):
                clean_val = clean_val[:-2]
            vals[odoo_field] = clean_val
        elif odoo_field in ("deprecated", "reconcile"):
            vals[odoo_field] = clean_bool(val)

    return vals
