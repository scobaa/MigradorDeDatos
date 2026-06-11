"""
Transformador de purchase.order (Pedidos de Compra).
"""

from __future__ import annotations

from typing import Any
from transformers.invoices import clean_str, clean_float, clean_date, parse_factusol_invoice_code


def transform_purchase_line(line_row: dict[str, Any]) -> dict[str, Any]:
    """
    Detecta y normaliza heurísticamente los campos de una línea de pedido de compra.
    """
    product_code = None
    description = "Línea de compra"
    quantity = 1.0
    price_unit = 0.0
    discount = 0.0
    tax_value = None

    for k, v in line_row.items():
        kl = k.lower()
        if kl in ("artlpe", "artlfa", "articulo", "product", "sku", "code", "referencia", "ref", "order_ids/product_id", "invoice_line_ids/product_id", "order_line/product_id"):
            product_code = clean_str(v)
            if product_code and product_code.endswith(".0"):
                product_code = product_code[:-2]
        elif kl in ("deslpe", "deslfa", "descripcion", "description", "name", "nombre", "order_ids/name", "invoice_line_ids/name", "order_line/name"):
            description = clean_str(v) or description
        elif kl in ("canlpe", "canlfa", "cantidad", "quantity", "qty", "unidades", "order_ids/product_qty", "invoice_line_ids/quantity", "order_line/product_qty"):
            quantity = clean_float(v)
        elif kl in ("prelpe", "prelfa", "precio", "price", "price_unit", "importe", "order_ids/price_unit", "invoice_line_ids/price_unit", "order_line/price_unit"):
            price_unit = clean_float(v)
        elif kl in ("descuento", "dto", "discount", "order_ids/discount", "invoice_line_ids/discount"):
            discount = clean_float(v)
        elif kl in ("ivalpe", "ivalfa", "iva", "tax", "pct", "porcentaje", "order_ids/taxes_id", "invoice_line_ids/tax_ids", "order_line/taxes_id"):
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


def transform_purchase_order(
    row: dict[str, Any],
    mapping: dict[str, str],
    format_name: bool = True,
) -> dict[str, Any]:
    """
    Transforma la cabecera y las líneas de un pedido de compra al esquema de Odoo.
    """
    vals: dict[str, Any] = {}

    # 1. Procesar campos de la cabecera mapeados
    for source_col, odoo_field in mapping.items():
        if not odoo_field:
            continue
        raw = row.get(source_col)
        if raw is None:
            continue

        if odoo_field == "date_order":
            date_clean = clean_date(raw)
            if date_clean:
                vals[odoo_field] = f"{date_clean} 12:00:00"
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
        vals["name"] = "/"
    elif format_name:
        # Formatear el nombre con el año, serie y número
        # Formato: PO/YEAR/SERIES/NUMBER
        year = "2026"
        if vals.get("date_order"):
            year = vals["date_order"][:4]
            
        series, number = parse_factusol_invoice_code(vals["name"])
        vals["name"] = f"PO/{year}/{series}/{number}"

    # 2. Procesar líneas virtuales (_lines)
    raw_lines = row.get("_lines") or []
    transformed_lines = []
    for line in raw_lines:
        transformed_lines.append(transform_purchase_line(line))

    vals["_lines"] = transformed_lines
    return vals
