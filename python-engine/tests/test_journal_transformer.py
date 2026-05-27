"""
Tests del transformador de account.move (Asientos Contables).
"""

from __future__ import annotations

import pytest
from transformers.journal import (
    transform_journal_line,
    transform_journal_entry,
)


def test_transform_journal_line_split_debit_credit():
    row = {
        "CUEAPU": "43000028",
        "CONAPU": "Concepto 1",
        "DEB": "123,45",
        "CRE": "0.0",
        "CLI": "28",
    }
    mapping = {
        "CUEAPU": "line_ids/account_id",
        "CONAPU": "line_ids/name",
        "DEB": "line_ids/debit",
        "CRE": "line_ids/credit",
        "CLI": "line_ids/partner_id",
    }
    vals = transform_journal_line(row, mapping)
    assert vals["_account_code"] == "43000028"
    assert vals["name"] == "Concepto 1"
    assert vals["debit"] == 123.45
    assert vals["credit"] == 0.0
    assert vals["_partner_code"] == "28"


def test_transform_journal_line_amount_and_side():
    mapping = {
        "CUEAPU": "line_ids/account_id",
        "CONAPU": "line_ids/name",
        "IMP": "_line_amount",
        "LADO": "_line_side",
    }

    # Caso Debe (D)
    row_d = {
        "CUEAPU": "43000028",
        "CONAPU": "Apunte Debe",
        "IMP": "500.00",
        "LADO": "D",
    }
    vals_d = transform_journal_line(row_d, mapping)
    assert vals_d["debit"] == 500.0
    assert vals_d["credit"] == 0.0

    # Caso Haber (H)
    row_h = {
        "CUEAPU": "70000000",
        "CONAPU": "Apunte Haber",
        "IMP": "500.00",
        "LADO": "H",
    }
    vals_h = transform_journal_line(row_h, mapping)
    assert vals_h["debit"] == 0.0
    assert vals_h["credit"] == 500.0

    # Caso Haber descriptivo (Haber)
    row_haber = {
        "CUEAPU": "70000000",
        "CONAPU": "Apunte Haber",
        "IMP": "250.50",
        "LADO": "Haber",
    }
    vals_haber = transform_journal_line(row_haber, mapping)
    assert vals_haber["debit"] == 0.0
    assert vals_haber["credit"] == 250.5


def test_transform_journal_entry():
    row = {
        "ASIAPU": "1",
        "FECAPU": "27/05/2026",
        "DOCAPU": "DOC-99",
        "DIAAPU": "01",
        "_lines": [
            {
                "CUEAPU": "43000028",
                "CONAPU": "Cliente 28",
                "IMP": "121.00",
                "LADO": "D",
            },
            {
                "CUEAPU": "70000000",
                "CONAPU": "Venta mercaderias",
                "IMP": "100.00",
                "LADO": "H",
            },
            {
                "CUEAPU": "47700000",
                "CONAPU": "IVA repercutido",
                "IMP": "21.00",
                "LADO": "H",
            }
        ]
    }
    mapping = {
        "ASIAPU": "name",
        "FECAPU": "date",
        "DOCAPU": "ref",
        "DIAAPU": "journal_id",
        "CUEAPU": "line_ids/account_id",
        "CONAPU": "line_ids/name",
        "IMP": "_line_amount",
        "LADO": "_line_side",
    }
    
    vals = transform_journal_entry(row, mapping)
    assert vals["move_type"] == "entry"
    assert vals["name"] == "1"
    assert vals["date"] == "2026-05-27"
    assert vals["ref"] == "DOC-99"
    assert vals["journal_id"] == "01"
    
    lines = vals["_lines"]
    assert len(lines) == 3
    assert lines[0]["_account_code"] == "43000028"
    assert lines[0]["debit"] == 121.0
    assert lines[0]["credit"] == 0.0
    
    assert lines[1]["_account_code"] == "70000000"
    assert lines[1]["debit"] == 0.0
    assert lines[1]["credit"] == 100.0
    
    assert lines[2]["_account_code"] == "47700000"
    assert lines[2]["debit"] == 0.0
    assert lines[2]["credit"] == 21.0
