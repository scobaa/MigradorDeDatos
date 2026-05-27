"""
Tests del transformador de account.move (Facturas).
"""

from __future__ import annotations

import pytest

from transformers.invoices import (
    clean_date,
    transform_invoice_line,
    transform_invoice,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-05-26", "2026-05-26"),
        ("2026-05-26 12:30:15", "2026-05-26"),
        ("26/05/2026", "2026-05-26"),
        ("26-05-2026", "2026-05-26"),
        ("   ", None),
        (None, None),
    ],
)
def test_clean_date(value, expected):
    assert clean_date(value) == expected


def test_transform_invoice_line():
    line_row = {
        "ARTLFA": "ART001.0",
        "DESLFA": "Tornillos cabeza plana",
        "CANLFA": "10.5",
        "PRELFA": "2,50 €",
        "IVALFA": "21.0",
    }
    line_vals = transform_invoice_line(line_row)
    assert line_vals["product_code"] == "ART001"
    assert line_vals["name"] == "Tornillos cabeza plana"
    assert line_vals["quantity"] == 10.5
    assert line_vals["price_unit"] == 2.50
    assert line_vals["tax_value"] == "21"


def test_transform_invoice():
    row = {
        "CODFAC": "FAC-1234",
        "FECFAC": "26/05/2026",
        "CLIFAC": "1005.0",
        "OBSFAC": "Entregar por la tarde",
        "_lines": [
            {
                "ARTLFA": "ART01",
                "DESLFA": "Tornillos",
                "CANLFA": 10,
                "PRELFA": 1.5,
                "IVALFA": "21"
            }
        ]
    }
    mapping = {
        "CODFAC": "name",
        "FECFAC": "invoice_date",
        "CLIFAC": "_partner_code",
        "OBSFAC": "narration",
    }
    
    vals = transform_invoice(row, mapping, move_type="out_invoice")
    assert vals["move_type"] == "out_invoice"
    assert vals["name"] == "SO/2026/FAC/1234"
    assert vals["invoice_date"] == "2026-05-26"
    assert vals["_partner_code"] == "1005"
    assert vals["narration"] == "Entregar por la tarde"
    
    assert len(vals["_lines"]) == 1
    assert vals["_lines"][0]["product_code"] == "ART01"
    assert vals["_lines"][0]["name"] == "Tornillos"
    assert vals["_lines"][0]["quantity"] == 10.0
    assert vals["_lines"][0]["price_unit"] == 1.5
    assert vals["_lines"][0]["tax_value"] == "21"
