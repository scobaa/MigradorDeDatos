"""
Transformador de account.move (Facturas y Asientos).

Recibe una fila cruda (cabecera + _lines virtuales) y un mapeo,
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


def transform_invoice_line(line_row: dict[str, Any]) -> dict[str, Any]:
    """
    Detecta y normaliza heurísticamente los campos de una línea de factura.
    """
    product_code = None
    description = "Línea de factura"
    quantity = 1.0
    price_unit = 0.0
    discount = 0.0
    tax_value = None

    for k, v in line_row.items():
        kl = k.lower()
        if kl in ("artlfa", "artlfr", "articulo", "product", "sku", "code", "referencia", "ref", "order_ids/product_id", "invoice_line_ids/product_id"):
            product_code = clean_str(v)
            if product_code and product_code.endswith(".0"):
                product_code = product_code[:-2]
        elif kl in ("deslfa", "deslfr", "descripcion", "description", "name", "nombre", "order_ids/name", "invoice_line_ids/name"):
            description = clean_str(v) or description
        elif kl in ("canlfa", "canlfr", "cantidad", "quantity", "qty", "unidades", "order_ids/product_uom_qty", "invoice_line_ids/quantity"):
            quantity = clean_float(v)
        elif kl in ("prelfa", "prelfr", "precio", "price", "price_unit", "importe", "order_ids/price", "order_ids/price_unit", "invoice_line_ids/price_unit"):
            price_unit = clean_float(v)
        elif kl in ("descuento", "dto", "discount", "order_ids/discount", "invoice_line_ids/discount"):
            discount = clean_float(v)
        elif kl in ("ivalfa", "ivalfr", "iva", "tax", "pct", "porcentaje", "order_ids/tax_id", "invoice_line_ids/tax_ids", "order_ids/tax_id/id"):
            tax_value = clean_str(v)
            if tax_value and tax_value.endswith(".0"):
                tax_value = tax_value[:-2]

    return {
        "product_code": product_code,
        "name": description,
        "quantity": quantity,
        "price_unit": price_unit,
        "discount": discount,
        "tax_value": tax_value,
    }


def parse_factusol_invoice_code(code: str) -> tuple[str, str]:
    """
    Dado un código de factura de Factusol (ej. '1000982' o 'A000123'),
    separa la serie (1er caracter) y el número (restante sin ceros a la izquierda).
    """
    code_str = str(code).strip()
    
    # Si tiene formato con guion, ej. FAC-0001 o FAC-1234
    if "-" in code_str:
        parts = code_str.split("-")
        series = parts[0]
        number = "-".join(parts[1:]).lstrip("0")
        return series, number or "0"
        
    # Si tiene formato con barra, ej. FAC/0001 o FAC/1234
    if "/" in code_str:
        parts = code_str.split("/")
        series = parts[0]
        number = "/".join(parts[1:]).lstrip("0")
        return series, number or "0"
        
    # Si es puramente numérico y de longitud >= 6 (típico de Factusol: Serie 1 digito + Número 6 digitos)
    if len(code_str) >= 6 and code_str.isdigit():
        series = code_str[0]
        number = code_str[1:].lstrip("0")
        return series, number or "0"
        
    # Si empieza por letra y sigue con números (típico de Factusol con serie alfabética, ej: A000123)
    if len(code_str) >= 6 and code_str[0].isalpha() and code_str[1:].isdigit():
        series = code_str[0]
        number = code_str[1:].lstrip("0")
        return series, number or "0"
        
    # Fallback general
    return "1", code_str


def transform_invoice(
    row: dict[str, Any],
    mapping: dict[str, str],
    move_type: str = "out_invoice",
    format_name: bool = True,
) -> dict[str, Any]:
    """
    Transforma la cabecera y las líneas de una factura al esquema de Odoo.
    """
    vals: dict[str, Any] = {
        "move_type": move_type,
    }

    # 1. Procesar campos de la cabecera mapeados
    for source_col, odoo_field in mapping.items():
        if not odoo_field:
            continue
        raw = row.get(source_col)
        if raw is None:
            continue

        if odoo_field == "invoice_date":
            vals[odoo_field] = clean_date(raw)
        elif odoo_field == "_partner_code":
            partner_code = clean_str(raw)
            if partner_code and partner_code.endswith(".0"):
                partner_code = partner_code[:-2]
            vals[odoo_field] = partner_code
        else:
            cleaned = clean_str(raw)
            if cleaned is not None:
                vals[odoo_field] = cleaned

    if not vals.get("name"):
        # Generar un nombre temporal si no viene número de factura mapeado
        vals["name"] = "/"
    elif format_name:
        # Formatear el nombre para incluir prefijo, año, serie y número
        # Formato: PREFIX/YEAR/SERIES/NUMBER, ej: SO/2026/1/982
        year = "2026"
        if vals.get("invoice_date"):
            # YYYY-MM-DD
            year = vals["invoice_date"][:4]
            
        series, number = parse_factusol_invoice_code(vals["name"])
        prefix = "SO" if move_type == "out_invoice" else "BILL"
        vals["name"] = f"{prefix}/{year}/{series}/{number}"

    # 2. Procesar líneas virtuales (_lines)
    raw_lines = row.get("_lines") or []
    transformed_lines = []
    for line in raw_lines:
        transformed_lines.append(transform_invoice_line(line))

    vals["_lines"] = transformed_lines
    return vals
