"""
Tests del migrador de account.move (Facturas).
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from migrator.invoices import InvoiceMigrator, MigrationOptions


def test_resolve_partner():
    mock_odoo = MagicMock()
    migrator = InvoiceMigrator(
        odoo=mock_odoo,
        mapping={"CODFAC": "name"},
        move_type="out_invoice"
    )

    # 1. Resolver por XML ID
    mock_odoo.get_xml_id_res_id.return_value = 101
    assert migrator._resolve_partner("C001") == 101
    mock_odoo.get_xml_id_res_id.assert_called_with("cli_C001", "res.partner")

    # Limpiar caché para forzar búsqueda
    migrator._partner_cache.clear()

    # 2. Resolver por ref
    mock_odoo.get_xml_id_res_id.return_value = None
    mock_odoo.search.side_effect = lambda model, domain: [102] if domain == [("ref", "=", "C001")] else []
    assert migrator._resolve_partner("C001") == 102

    migrator._partner_cache.clear()

    # 3. Resolver por name
    mock_odoo.get_xml_id_res_id.return_value = None
    mock_odoo.search.side_effect = lambda model, domain: [103] if domain == [("name", "=", "C001")] else []
    assert migrator._resolve_partner("C001") == 103


def test_resolve_product():
    mock_odoo = MagicMock()
    migrator = InvoiceMigrator(
        odoo=mock_odoo,
        mapping={"CODFAC": "name"}
    )

    # 1. Resolver por SKU (default_code)
    mock_odoo.search.side_effect = lambda model, domain: [201] if "default_code" in str(domain) else []
    assert migrator._resolve_product("PROD01") == 201

    migrator._product_cache.clear()

    # 2. Resolver por XML ID de product.template
    def mock_get_xml_id(xml_id, model):
        if xml_id == "art_PROD01" and model == "product.template":
            return 301
        return None
    
    def mock_search_product(model, domain):
        if "product_tmpl_id" in str(domain):
            return [202]
        return []

    mock_odoo.get_xml_id_res_id.side_effect = mock_get_xml_id
    mock_odoo.search.side_effect = mock_search_product
    assert migrator._resolve_product("PROD01") == 202

    migrator._product_cache.clear()

    # 3. Resolver por barcode
    mock_odoo.get_xml_id_res_id.side_effect = lambda xml_id, model: None
    mock_odoo.search.side_effect = lambda model, domain: [203] if "barcode" in str(domain) else []
    assert migrator._resolve_product("PROD01") == 203


def test_resolve_tax():
    mock_odoo = MagicMock()
    migrator = InvoiceMigrator(
        odoo=mock_odoo,
        mapping={"CODFAC": "name"}
    )

    # 1. Exact match via get_tax_id
    mock_odoo.get_tax_id.return_value = 501
    assert migrator._resolve_tax("21", "sale") == 501
    mock_odoo.get_tax_id.assert_called_with("21", "sale")

    migrator._tax_cache.clear()

    # 2. ilike name search
    mock_odoo.get_tax_id.return_value = None
    mock_odoo.search.side_effect = lambda model, domain: [502] if "ilike" in str(domain) else []
    assert migrator._resolve_tax("21", "sale") == 502

    migrator._tax_cache.clear()

    # 3. Numeric percent search
    mock_odoo.get_tax_id.return_value = None
    def mock_search_tax(model, domain):
        if "amount" in str(domain):
            return [503]
        return []
    mock_odoo.search.side_effect = mock_search_tax
    assert migrator._resolve_tax("21.0%", "sale") == 503


def test_migrator_run_dry_run():
    mock_odoo = MagicMock()
    # Mock partner resolution
    def mock_get_xml_id(xml_id, model):
        if model == "res.partner":
            return 101
        return None
    mock_odoo.get_xml_id_res_id.side_effect = mock_get_xml_id
    # Mock tax
    mock_odoo.get_tax_id.return_value = 501

    migrator = InvoiceMigrator(
        odoo=mock_odoo,
        mapping={
            "CODFAC": "name",
            "FECFAC": "invoice_date",
            "CLIFAC": "_partner_code",
        }
    )

    rows = [{
        "CODFAC": "FAC-0001",
        "FECFAC": "2026-05-26",
        "CLIFAC": "C001",
        "_lines": [{
            "ARTLFA": "PROD01",
            "DESLFA": "Linea 1",
            "CANLFA": "2.0",
            "PRELFA": "100.0",
            "IVALFA": "21",
        }]
    }]

    stats = migrator.run(rows, total=1, dry_run=True)

    assert stats.created == 1
    assert stats.updated == 0
    assert len(stats.errors) == 0
    mock_odoo.create.assert_not_called()
    mock_odoo.write.assert_not_called()


def test_migrator_run_creation():
    mock_odoo = MagicMock()
    mock_odoo.get_xml_id_res_id.side_effect = lambda xml_id, model: 101 if model == "res.partner" else None
    mock_odoo.get_tax_id.return_value = 501
    mock_odoo.filter_vals.side_effect = lambda model, vals: vals
    mock_odoo.create.return_value = 1001

    migrator = InvoiceMigrator(
        odoo=mock_odoo,
        mapping={
            "CODFAC": "name",
            "FECFAC": "invoice_date",
            "CLIFAC": "_partner_code",
        }
    )

    rows = [{
        "CODFAC": "FAC-0001",
        "FECFAC": "2026-05-26",
        "CLIFAC": "C001",
        "_lines": [{
            "ARTLFA": "PROD01",
            "DESLFA": "Linea 1",
            "CANLFA": 2,
            "PRELFA": 50,
            "IVALFA": "21",
        }]
    }]

    stats = migrator.run(rows, total=1, dry_run=False)

    assert stats.created == 1
    assert len(stats.errors) == 0

    mock_odoo.create.assert_called_once()
    created_vals = mock_odoo.create.call_args[0][1]
    assert created_vals["name"] == "SO/2026/FAC/1"
    assert created_vals["invoice_date"] == "2026-05-26"
    assert created_vals["partner_id"] == 101
    assert len(created_vals["invoice_line_ids"]) == 1
    assert created_vals["invoice_line_ids"][0][2]["price_unit"] == 50.0

    mock_odoo.create_or_update_xml_id.assert_called_with("inv_out_SO_2026_FAC_1", "account.move", 1001)
    mock_odoo.execute.assert_called_with("account.move", "action_post", [1001])


def test_migrator_run_update_existing_posted():
    mock_odoo = MagicMock()
    # Odoo responses:
    # 1. Partner resolution -> 101
    # 2. Existing invoice check -> 1001
    # 3. read state -> [{'state': 'posted'}]
    def mock_get_xml_id(xml_id, model):
        if model == "res.partner":
            return 101
        if model == "account.move" and "SO_2026_FAC_1" in xml_id:
            return 1001
        return None

    mock_odoo.get_xml_id_res_id.side_effect = mock_get_xml_id
    mock_odoo.read.return_value = [{"state": "posted"}]
    mock_odoo.filter_vals.side_effect = lambda model, vals: vals

    migrator = InvoiceMigrator(
        odoo=mock_odoo,
        mapping={
            "CODFAC": "name",
            "FECFAC": "invoice_date",
            "CLIFAC": "_partner_code",
        }
    )

    rows = [{
        "CODFAC": "FAC-0001",
        "FECFAC": "2026-05-26",
        "CLIFAC": "C001",
        "_lines": [{
            "ARTLFA": "PROD01",
            "DESLFA": "Linea 1",
            "CANLFA": 1,
            "PRELFA": 10,
        }]
    }]

    stats = migrator.run(rows, total=1, dry_run=False)

    assert stats.updated == 1
    assert len(stats.errors) == 0

    # Verify button_draft was called to reset to draft
    mock_odoo.execute.assert_any_call("account.move", "button_draft", [1001])
    
    # Verify write was called with replacement lines (5, 0, 0)
    mock_odoo.write.assert_called_once()
    write_vals = mock_odoo.write.call_args[0][2]
    assert write_vals["invoice_line_ids"][0] == (5, 0, 0)
    
    # Verify post was called again
    mock_odoo.execute.assert_any_call("account.move", "action_post", [1001])


def test_migrator_run_validation_errors():
    mock_odoo = MagicMock()
    # Partner not found
    mock_odoo.get_xml_id_res_id.return_value = None
    mock_odoo.search.return_value = []

    migrator = InvoiceMigrator(
        odoo=mock_odoo,
        mapping={"CODFAC": "name", "CLIFAC": "_partner_code"}
    )

    # Row with invalid partner
    rows = [{"CODFAC": "FAC-ERR", "CLIFAC": "UNKNOWN", "_lines": [{"DESLFA": "L"}]}]
    stats = migrator.run(rows, total=1, dry_run=False)
    assert len(stats.errors) == 1
    assert "No se pudo encontrar ningún cliente/proveedor" in stats.errors[0]["error"]

    # Row with no lines
    mock_odoo.get_xml_id_res_id.return_value = 101  # Partner resolved
    rows = [{"CODFAC": "FAC-ERR", "CLIFAC": "C001", "_lines": []}]
    stats = migrator.run(rows, total=1, dry_run=False)
    assert len(stats.errors) == 1
    assert "La factura debe contener al menos una línea" in stats.errors[0]["error"]
