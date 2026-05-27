"""
Tests del migrador de asientos contables (Journal Entries).
"""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from migrator.journal import JournalEntryMigrator, MigrationOptions


def test_resolve_account():
    mock_odoo = MagicMock()
    migrator = JournalEntryMigrator(
        odoo=mock_odoo,
        mapping={"CUEAPU": "line_ids/account_id"}
    )

    # 1. Resolver por código exacto
    mock_odoo.search.return_value = [4001]
    assert migrator._resolve_account("43000028") == 4001
    mock_odoo.search.assert_called_with("account.account", [("code", "=", "43000028")])

    # 2. Verificar caché local
    mock_odoo.search.reset_mock()
    assert migrator._resolve_account("43000028") == 4001
    mock_odoo.search.assert_not_called()


def test_extract_partner_code_from_account():
    migrator = JournalEntryMigrator(odoo=MagicMock(), mapping={})
    
    assert migrator._extract_partner_code_from_account("43000028") == ("client", "28")
    assert migrator._extract_partner_code_from_account("430.0.0.105") == ("client", "105")
    assert migrator._extract_partner_code_from_account("40000005") == ("supplier", "5")
    assert migrator._extract_partner_code_from_account("41000012") == ("supplier", "12")
    assert migrator._extract_partner_code_from_account("60000000") is None


def test_resolve_partner_implicit():
    mock_odoo = MagicMock()
    migrator = JournalEntryMigrator(
        odoo=mock_odoo,
        mapping={}
    )

    # Buscar implicitamente cliente
    mock_odoo.get_xml_id_res_id.return_value = 888
    # 43000028 -> cliente 28 -> busca cli_28
    partner_id = migrator._resolve_partner("28", is_supplier=False)
    assert partner_id == 888
    mock_odoo.get_xml_id_res_id.assert_called_with("cli_28", "res.partner")


def test_migrator_run_creation():
    mock_odoo = MagicMock()
    
    # Mocks de Odoo:
    # 1. No existe el asiento (get_xml_id_res_id -> None)
    # 2. Cuentas contables resolviendo a IDs
    # 3. Cliente resolviendo a ID
    def mock_xml_id(xml_id, model):
        if model == "res.partner" and xml_id == "cli_28":
            return 208
        return None
    mock_odoo.get_xml_id_res_id.side_effect = mock_xml_id
    
    def mock_search(model, domain):
        if model == "account.account":
            if "43000028" in str(domain):
                return [4300]
            if "70000000" in str(domain):
                return [7000]
        return []
    mock_odoo.search.side_effect = mock_search
    mock_odoo.filter_vals.side_effect = lambda model, vals: vals
    mock_odoo.create.return_value = 5001

    migrator = JournalEntryMigrator(
        odoo=mock_odoo,
        mapping={
            "ASIAPU": "name",
            "FECAPU": "date",
            "DOCAPU": "ref",
            "CUEAPU": "line_ids/account_id",
            "CONAPU": "line_ids/name",
            "IMP": "_line_amount",
            "LADO": "_line_side",
        },
        options=MigrationOptions(post_entries=True)
    )

    rows = [{
        "ASIAPU": "AS-100",
        "FECAPU": "2026-05-27",
        "DOCAPU": "REF-ABC",
        "_lines": [
            {"CUEAPU": "43000028", "CONAPU": "Cliente 28", "IMP": "100", "LADO": "D"},
            {"CUEAPU": "70000000", "CONAPU": "Ventas", "IMP": "100", "LADO": "H"}
        ]
    }]

    stats = migrator.run(rows, total=1, dry_run=False)

    assert stats.created == 1
    assert len(stats.errors) == 0

    mock_odoo.create.assert_called_once()
    created_vals = mock_odoo.create.call_args[0][1]
    assert created_vals["name"] == "AS-100"
    assert created_vals["date"] == "2026-05-27"
    assert created_vals["ref"] == "REF-ABC"
    
    # 2 líneas contables
    assert len(created_vals["line_ids"]) == 2
    # Debe
    assert created_vals["line_ids"][0][2]["account_id"] == 4300
    assert created_vals["line_ids"][0][2]["debit"] == 100.0
    assert created_vals["line_ids"][0][2]["credit"] == 0.0
    assert created_vals["line_ids"][0][2]["partner_id"] == 208 # Resuelto implícitamente
    # Haber
    assert created_vals["line_ids"][1][2]["account_id"] == 7000
    assert created_vals["line_ids"][1][2]["debit"] == 0.0
    assert created_vals["line_ids"][1][2]["credit"] == 100.0

    mock_odoo.create_or_update_xml_id.assert_called_with("asi_AS-100", "account.move", 5001)
    mock_odoo.execute.assert_any_call("account.move", "action_post", [5001])


def test_migrator_run_update_existing_posted():
    mock_odoo = MagicMock()
    
    # Mocks de Odoo:
    # 1. Asiento ya existe -> 5001
    def mock_xml_id(xml_id, model):
        if model == "account.move" and xml_id == "asi_AS-100":
            return 5001
        return None
    mock_odoo.get_xml_id_res_id.side_effect = mock_xml_id
    
    # 2. Resuelve cuentas
    mock_odoo.search.side_effect = lambda model, domain: [4300] if "430" in str(domain) else [7000]
    
    # 3. Read state -> 'posted'
    mock_odoo.read.return_value = [{"state": "posted"}]
    mock_odoo.filter_vals.side_effect = lambda model, vals: vals

    migrator = JournalEntryMigrator(
        odoo=mock_odoo,
        mapping={
            "ASIAPU": "name",
            "FECAPU": "date",
            "CUEAPU": "line_ids/account_id",
            "CONAPU": "line_ids/name",
            "IMP": "_line_amount",
            "LADO": "_line_side",
        },
        options=MigrationOptions(update_existing=True, post_entries=True)
    )

    rows = [{
        "ASIAPU": "AS-100",
        "FECAPU": "2026-05-27",
        "_lines": [
            {"CUEAPU": "43000028", "CONAPU": "Cliente", "IMP": "100", "LADO": "D"},
            {"CUEAPU": "70000000", "CONAPU": "Ventas", "IMP": "100", "LADO": "H"}
        ]
    }]

    stats = migrator.run(rows, total=1, dry_run=False)

    assert stats.updated == 1
    assert len(stats.errors) == 0

    # Cambia a borrador para poder escribir
    mock_odoo.execute.assert_any_call("account.move", "button_draft", [5001])
    
    # Escribe con purga (5, 0, 0)
    mock_odoo.write.assert_called_once()
    write_vals = mock_odoo.write.call_args[0][2]
    assert write_vals["line_ids"][0] == (5, 0, 0)
    
    # Vuelve a publicar
    mock_odoo.execute.assert_any_call("account.move", "action_post", [5001])
