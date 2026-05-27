"""
Transformador de product.template.

Recibe una fila cruda y un mapeo, y devuelve un diccionario limpio listo
para product.template en Odoo.
"""

from __future__ import annotations

import re
from typing import Any

# Campos soportados (directa o indirectamente a través de resolución externa en migrador)
SUPPORTED_FIELDS = {
    "name",
    "default_code",
    "type",
    "list_price",
    "standard_price",
    "barcode",
    "_category",       # → categ_id
    "_uom",            # → uom_id
    "_uom_po",         # → uom_po_id
    "_taxes",          # → taxes_id (M2M)
    "_supplier_taxes", # → supplier_taxes_id (M2M)
}


def clean_str(value: Any) -> str | None:
    """Normaliza y limpia espacios en un string, retorna None si está vacío."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def clean_float(value: Any) -> float:
    """Normaliza y convierte a float positivo, retorna 0.0 si falla."""
    if value is None:
        return 0.0
    try:
        text = str(value).replace(",", ".").strip()
        # Quitar caracteres no numéricos excepto el punto decimal
        text = re.sub(r"[^\d.]", "", text)
        if not text:
            return 0.0
        return max(0.0, float(text))
    except (ValueError, TypeError):
        return 0.0


def clean_barcode(value: Any) -> str | None:
    """Limpia el código de barras y elimina sufijos .0 de conversión de Excel."""
    text = clean_str(value)
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text or None


def clean_type(value: Any) -> str:
    """Mapea valores de texto al tipo admitido por Odoo (consu, service, product)."""
    text = clean_str(value)
    if not text:
        return "product"

    val = text.lower()
    if any(k in val for k in ("servicio", "mano de obra", "service", "horas", "h.")):
        return "service"
    if any(k in val for k in ("consumible", "consu", "gasto")):
        return "consu"
    return "product"


def transform_product(
    row: dict[str, Any],
    mapping: dict[str, str],
) -> dict[str, Any]:
    """
    Transforma una fila del origen en valores limpios de product.template.
    """
    vals: dict[str, Any] = {}

    for source_col, odoo_field in mapping.items():
        if not odoo_field:
            continue
        raw = row.get(source_col)
        if raw is None:
            continue

        if odoo_field in ("list_price", "standard_price"):
            vals[odoo_field] = clean_float(raw)
        elif odoo_field == "barcode":
            vals[odoo_field] = clean_barcode(raw)
        elif odoo_field == "type":
            vals[odoo_field] = clean_type(raw)
        else:
            cleaned = clean_str(raw)
            if cleaned is not None:
                vals[odoo_field] = cleaned

    if not vals.get("name"):
        raise ValueError(
            "La fila no tiene 'name' (Nombre de producto) tras la transformación; "
            "comprueba que el mapeo del nombre esté configurado correctamente."
        )

    # Asegurar tipo almacenable por defecto si no viene
    if "type" not in vals:
        vals["type"] = "product"

    return vals
