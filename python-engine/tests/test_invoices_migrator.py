"""
Tests del migrador de account.move (Facturas).
Actualizados para usar el nuevo método resolve_many2one centralizado.
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

    # 1. Resolver por ID externo (via resolve_many2one)
    mock_odoo.resolve_many2one.return_value = 101
    assert migrator._resolve_partner("C001") == 101
    mock_odoo.resolve_many2one.assert_called_with(
        "C001", "res.partner",
        xml_id_prefix="cli_",
        extra_fields=["ref"],
        cache=migrator._partner_cache,
    )

    migrator._partner_cache.clear()

    # 2. Resolver por ref (simulado dentro de resolve_many2one)
    mock_odoo.resolve_many2one.return_value = 102
    assert migrator._resolve_partner("C001") == 102

    migrator._partner_cache.clear()

    # 3. Sin resultado → None
    mock_odoo.resolve_many2one.return_value = None
    assert migrator._resolve_partner("C001") is None

    # 4. Valor vacío → None
    assert migrator._resolve_partner(None) is None
    assert migrator._resolve_partner("") is None


def test_resolve_product():
    mock_odoo = MagicMock()
    migrator = InvoiceMigrator(
        odoo=mock_odoo,
        mapping={"CODFAC": "name"}
    )

    # 1. Resolver por SKU / XML ID / barcode (via resolve_many2one)
    mock_odoo.resolve_many2one.return_value = 201
    assert migrator._resolve_product("PROD01") == 201
    mock_odoo.resolve_many2one.assert_called_with(
        "PROD01", "product.product",
        xml_id_prefix="art_",
        extra_fields=["default_code", "barcode"],
        cache=migrator._product_cache,
    )

    migrator._product_cache.clear()

    # 2. Sin resultado → None
    mock_odoo.resolve_many2one.return_value = None
    assert migrator._resolve_product("PROD01") is None

    # 3. Valor vacío → None
    assert migrator._resolve_product(None) is None


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
    # resolve_many2one devuelve partner 101 para partners, None para facturas existentes
    def mock_resolve(value, model, **kwargs):
        if model == "res.partner":
            return 101
        return None
    mock_odoo.resolve_many2one.side_effect = mock_resolve
    mock_odoo.get_xml_id_res_id.return_value = None  # No hay factura existente
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
    mock_odoo.resolve_many2one.return_value = 101
    mock_odoo.get_xml_id_res_id.return_value = None  # no existing invoice
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
    mock_odoo.resolve_many2one.return_value = 101

    def mock_get_xml_id(xml_id, model):
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

    mock_odoo.execute.assert_any_call("account.move", "button_draft", [1001])
    mock_odoo.write.assert_called_once()
    write_vals = mock_odoo.write.call_args[0][2]
    assert write_vals["invoice_line_ids"][0] == (5, 0, 0)
    mock_odoo.execute.assert_any_call("account.move", "action_post", [1001])


def test_migrator_run_validation_errors():
    mock_odoo = MagicMock()
    # Partner not found
    mock_odoo.resolve_many2one.return_value = None
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
    mock_odoo.resolve_many2one.return_value = 101
    mock_odoo.get_xml_id_res_id.return_value = None
    rows = [{"CODFAC": "FAC-ERR", "CLIFAC": "C001", "_lines": []}]
    stats = migrator.run(rows, total=1, dry_run=False)
    assert len(stats.errors) == 1
    assert "La factura debe contener al menos una línea" in stats.errors[0]["error"]
