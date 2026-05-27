"""
Tests del transformador de sale.order (Pedidos de Venta).
"""

from __future__ import annotations

import pytest
from transformers.sales import (
    transform_sales_line,
    transform_sales_order,
)


def test_transform_sales_line():
    line_row = {
        "ARTLPE": "PROD001.0",
        "DESLPE": "Articulo de prueba",
        "CANLPE": "5.5",
        "PRELPE": "15,50 €",
        "IVALPE": "21.0",
    }
    line_vals = transform_sales_line(line_row)
    assert line_vals["product_code"] == "PROD001"
    assert line_vals["name"] == "Articulo de prueba"
    assert line_vals["quantity"] == 5.5
    assert line_vals["price_unit"] == 15.50
    assert line_vals["tax_value"] == "21"


def test_transform_sales_order():
    row = {
        "CODPED": "PED-982",
        "FECPED": "27/05/2026",
        "CLIPED": "2005.0",
        "OBSPED": "Entregar urgente",
        "_lines": [
            {
                "ARTLPE": "ART01",
                "DESLPE": "Caja",
                "CANLPE": 3,
                "PRELPE": 10,
                "IVALPE": "21"
            }
        ]
    }
    mapping = {
        "CODPED": "name",
        "FECPED": "date_order",
        "CLIPED": "_partner_code",
        "OBSPED": "note",
    }
    
    vals = transform_sales_order(row, mapping)
    assert vals["name"] == "SO/2026/PED/982"
    assert vals["date_order"] == "2026-05-27 12:00:00"
    assert vals["_partner_code"] == "2005"
    assert vals["note"] == "Entregar urgente"
    
    assert len(vals["_lines"]) == 1
    assert vals["_lines"][0]["product_code"] == "ART01"
    assert vals["_lines"][0]["name"] == "Caja"
    assert vals["_lines"][0]["quantity"] == 3.0
    assert vals["_lines"][0]["price_unit"] == 10.0
    assert vals["_lines"][0]["tax_value"] == "21"
