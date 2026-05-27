"""
Transformador de account.move (Asientos Contables).

Recibe una fila agrupada (cabecera + _lines virtuales) y un mapeo,
y devuelve un diccionario estructurado listo para ser procesado por el migrador.
"""

from __future__ import annotations

import re
from typing import Any


def clean_str(value: Any) -> str | None:
    """Normaliza y limpia espacios en un string, retorna None si está vacío."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def clean_float(value: Any) -> float:
    """Normaliza y convierte a float, retorna 0.0 si falla."""
    if value is None:
        return 0.0
    try:
        text = str(value).replace(",", ".").strip()
        text = re.sub(r"[^\d.-]", "", text)
        if not text:
            return 0.0
        return float(text)
    except (ValueError, TypeError):
        return 0.0


def clean_date(value: Any) -> str | None:
    """Normaliza fechas al formato AAAA-MM-DD de Odoo."""
    if not value:
        return None
    text = str(value).strip()
    # Si ya tiene formato AAAA-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text[:10]
    # Si viene con formato DD/MM/AAAA o similar
    match = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if match:
        d, m, y = match.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    return text[:10] if len(text) >= 10 else None


def transform_journal_line(line_row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """
    Normaliza y limpia una línea/apunte de asiento contable.
    Soporta debit/credit separados o cantidad única + indicador de lado.
    """
    account_code = None
    name = "Apunte contable"
    debit = 0.0
    credit = 0.0
    partner_code = None

    # Columnas especiales para el caso de importe y lado
    amount_col = None
    side_col = None

    for src_col, odoo_field in mapping.items():
        if not odoo_field:
            continue
        val = line_row.get(src_col)

        if odoo_field == "line_ids/account_id":
            account_code = clean_str(val)
            if account_code and account_code.endswith(".0"):
                account_code = account_code[:-2]
        elif odoo_field == "line_ids/name":
            name = clean_str(val) or name
        elif odoo_field == "line_ids/debit":
            debit = clean_float(val)
        elif odoo_field == "line_ids/credit":
            credit = clean_float(val)
        elif odoo_field == "line_ids/partner_id":
            partner_code = clean_str(val)
            if partner_code and partner_code.endswith(".0"):
                partner_code = partner_code[:-2]
        elif odoo_field == "_line_amount":
            amount_col = src_col
        elif odoo_field == "_line_side":
            side_col = src_col

    # Si se especificó el modo de importe único + lado (ej: IMEAPU y D-HAPU)
    if amount_col is not None and side_col is not None:
        amount_val = clean_float(line_row.get(amount_col))
        side_val = str(line_row.get(side_col) or "").strip().upper()
        # Interpretación del lado: Debe (D, DEBE, DEBIT, 1, +) / Haber (H, HABER, CREDIT, 2, -)
        if side_val in ("D", "DEBE", "DEBIT", "1", "+"):
            debit = amount_val
            credit = 0.0
        elif side_val in ("H", "HABER", "CREDIT", "2", "-"):
            credit = amount_val
            debit = 0.0
        else:
            # Fallback en caso de que el valor no sea claro: si es positivo va al debe
            if amount_val >= 0:
                debit = amount_val
                credit = 0.0
            else:
                debit = 0.0
                credit = abs(amount_val)

    return {
        "_account_code": account_code,
        "name": name,
        "debit": debit,
        "credit": credit,
        "_partner_code": partner_code,
    }


def transform_journal_entry(row: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """
    Transforma la cabecera y líneas de un asiento contable.
    """
    vals: dict[str, Any] = {
        "move_type": "entry",
    }

    # 1. Mapear cabecera
    for source_col, odoo_field in mapping.items():
        if not odoo_field or odoo_field.startswith("line_ids/") or odoo_field.startswith("_line_"):
            continue
        raw = row.get(source_col)
        if raw is None:
            continue

        if odoo_field == "date":
            vals[odoo_field] = clean_date(raw)
        else:
            cleaned = clean_str(raw)
            if cleaned is not None:
                vals[odoo_field] = cleaned

    if not vals.get("name"):
        vals["name"] = "/"

    # 2. Mapear líneas
    raw_lines = row.get("_lines") or []
    transformed_lines = []
    for line_row in raw_lines:
        line_vals = transform_journal_line(line_row, mapping)
        # Solo agregar apuntes con cuenta válida
        if line_vals["_account_code"]:
            transformed_lines.append(line_vals)

    vals["_lines"] = transformed_lines
    return vals
