"""
Tests del migrador de product.template.

Verifica la compatibilidad con Odoo 17+ (con y sin modulo stock) y versiones anteriores para productos almacenables.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from migrator.products import ProductMigrator, MigrationOptions


def test_product_migrator_storable_odoo17_with_stock():
    # Setup mock odoo client
    mock_odoo = MagicMock()
    # Mock get_valid_fields to return "is_storable"
    mock_odoo.get_valid_fields.return_value = {"name", "type", "is_storable", "categ_id"}
    mock_odoo.search.return_value = [1]  # Category search fallback
    
    # Mock selection options for type field (product is NOT present)
    mock_odoo.execute.return_value = {
        "type": {
            "selection": [["consu", "Consumable"], ["service", "Service"], ["combo", "Combo"]]
        }
    }

    migrator = ProductMigrator(
        odoo=mock_odoo,
        mapping={"Codigo": "default_code", "Nombre": "name", "Tipo": "type"},
    )

    # Test resolving storable product
    vals = {
        "name": "Producto Prueba",
        "type": "product",
    }

    migrator._resolve_fields_in_place(vals)

    # Assert type converted to consu and is_storable is True
    assert vals["type"] == "consu"
    assert vals.get("is_storable") is True
    mock_odoo.execute.assert_called_with(
        "product.template", "fields_get", allfields=["type"], attributes=["selection"]
    )


def test_product_migrator_storable_odoo17_without_stock():
    # Setup mock odoo client
    mock_odoo = MagicMock()
    # Mock get_valid_fields to NOT return "is_storable"
    mock_odoo.get_valid_fields.return_value = {"name", "type", "categ_id"}
    mock_odoo.search.return_value = [1]  # Category search fallback
    
    # Mock selection options for type field (product is NOT present)
    mock_odoo.execute.return_value = {
        "type": {
            "selection": [["consu", "Consumable"], ["service", "Service"], ["combo", "Combo"]]
        }
    }

    migrator = ProductMigrator(
        odoo=mock_odoo,
        mapping={"Codigo": "default_code", "Nombre": "name", "Tipo": "type"},
    )

    # Test resolving storable product
    vals = {
        "name": "Producto Prueba",
        "type": "product",
    }

    migrator._resolve_fields_in_place(vals)

    # Assert type converted to consu and is_storable is NOT set
    assert vals["type"] == "consu"
    assert "is_storable" not in vals


def test_product_migrator_storable_odoo16():
    # Setup mock odoo client
    mock_odoo = MagicMock()
    # Mock get_valid_fields to NOT return "is_storable"
    mock_odoo.get_valid_fields.return_value = {"name", "type", "categ_id"}
    mock_odoo.search.return_value = [1]  # Category search fallback
    
    # Mock selection options for type field (product IS present)
    mock_odoo.execute.return_value = {
        "type": {
            "selection": [["consu", "Consumable"], ["service", "Service"], ["product", "Storable Product"]]
        }
    }

    migrator = ProductMigrator(
        odoo=mock_odoo,
        mapping={"Codigo": "default_code", "Nombre": "name", "Tipo": "type"},
    )

    # Test resolving storable product
    vals = {
        "name": "Producto Prueba",
        "type": "product",
    }

    migrator._resolve_fields_in_place(vals)

    # Assert type remains product and is_storable is not set
    assert vals["type"] == "product"
    assert "is_storable" not in vals


def test_product_migrator_xml_id_fallback():
    # Setup mock odoo client
    mock_odoo = MagicMock()
    mock_odoo.get_valid_fields.return_value = {"name", "default_code", "type", "categ_id"}
    mock_odoo.search.return_value = [1]
    
    # Mock execute to return different values depending on method called
    def mock_execute(model, method, *args, **kwargs):
        if method == "fields_get":
            return {
                "type": {
                    "selection": [["consu", "Consumable"], ["service", "Service"], ["product", "Storable Product"]]
                }
            }
        elif method == "create":
            return [42]
        return None
    mock_odoo.execute.side_effect = mock_execute
    mock_odoo.filter_vals.side_effect = lambda model, vals: vals
    mock_odoo.search_read.return_value = []

    # Mapping default_code but NO __external_id
    migrator = ProductMigrator(
        odoo=mock_odoo,
        mapping={"Codigo": "default_code", "Nombre": "name"},
    )
    
    # Simular ejecución de lote de 1 fila
    batch = [{"Codigo": "1001.0", "Nombre": "Producto Con Fallback"}]
    
    # Mock OdooClient response for create to return 42
    mock_odoo.create.return_value = 42
    
    # Ejecutamos la migración
    stats = migrator.run(batch, total=1, dry_run=False)
    
    # Verificar que se llamó a create_or_update_xml_id con el fallback (art_1001)
    mock_odoo.create_or_update_xml_id.assert_called_with(
        "art_1001", "product.template", 42
    )


def test_product_migrator_xml_id_option():
    # Setup mock odoo client
    mock_odoo = MagicMock()
    mock_odoo.get_valid_fields.return_value = {"name", "default_code", "type", "categ_id"}
    mock_odoo.search.return_value = [1]
    
    # Mock execute/create to return different values depending on method called
    def mock_execute(model, method, *args, **kwargs):
        if method == "fields_get":
            return {
                "type": {
                    "selection": [["consu", "Consumable"], ["service", "Service"], ["product", "Storable Product"]]
                }
            }
        elif method == "create":
            return [42]
        return None
    mock_odoo.execute.side_effect = mock_execute
    mock_odoo.filter_vals.side_effect = lambda model, vals: vals
    mock_odoo.search_read.return_value = []

    # Map only default_code, but set external_id_column to "RefInterna"
    options = MigrationOptions(
        external_id_column="RefInterna"
    )
    migrator = ProductMigrator(
        odoo=mock_odoo,
        mapping={"Codigo": "default_code", "Nombre": "name"},
        options=options,
    )
    
    batch = [{"Codigo": "1001.0", "RefInterna": "EXT_999", "Nombre": "Producto Prueba"}]
    
    # Ejecutamos la migración
    stats = migrator.run(batch, total=1, dry_run=False)
    
    # Verificar que se llamó a create_or_update_xml_id con el valor de la opción
    mock_odoo.create_or_update_xml_id.assert_called_with(
        "art_EXT_999", "product.template", 42
    )


def test_product_migrator_hierarchical_category():
    mock_odoo = MagicMock()
    
    # Mock search calls:
    # 1. Search for first level "Ferretería": returns [] (not found)
    # 2. Search for All/Todos parent: returns [1] (found All)
    # 3. Search for second level "Tornillos" under parent 10: returns [] (not found)
    search_calls = []
    def mock_search(model, domain, *args, **kwargs):
        search_calls.append((model, domain))
        if model == "product.category":
            if "Ferretería" in str(domain):
                return []
            if "All" in str(domain) or "Todos" in str(domain):
                return [1]
            if "Tornillos" in str(domain):
                return []
        return []
    mock_odoo.search.side_effect = mock_search

    # Mock create calls:
    # 1. Create first level "Ferretería": returns 10
    # 2. Create second level "Tornillos": returns 20
    create_calls = []
    def mock_create(model, vals):
        create_calls.append((model, vals))
        if model == "product.category":
            if vals.get("name") == "Ferretería":
                return 10
            if vals.get("name") == "Tornillos":
                return 20
        return 99
    mock_odoo.create.side_effect = mock_create

    migrator = ProductMigrator(
        odoo=mock_odoo,
        mapping={"Codigo": "default_code", "Nombre": "name"},
    )

    # Resolving path with /
    cat_id = migrator._resolve_category("Ferretería / Tornillos")

    # Assert correct category ID returned (leaf category: 20)
    assert cat_id == 20
    
    # Assert Odoo create was called for both categories in hierarchy
    assert len(create_calls) == 2
    assert create_calls[0] == ("product.category", {"name": "Ferretería", "parent_id": 1})
    assert create_calls[1] == ("product.category", {"name": "Tornillos", "parent_id": 10})

def test_product_migrator_category_translation():
    mock_odoo = MagicMock()
    mock_odoo.search.return_value = [100]  # Found category tools
    
    families = {
        "01": "Herramientas de mano",
        "A-2": "Jardinería"
    }

    migrator = ProductMigrator(
        odoo=mock_odoo,
        mapping={"Codigo": "default_code", "Nombre": "name"},
        families=families
    )

    # Resolve "01" (Herramientas de mano)
    migrator._resolve_category("01")
    # Verify odoo search was called for "Herramientas de mano", not "01"
    mock_odoo.search.assert_any_call("product.category", [("name", "=ilike", "Herramientas de mano")])

    # Resolve "A-2.0" (Excel float conversion string) -> should strip .0 and resolve to "Jardinería"
    migrator._resolve_category("A-2.0")
    # Verify odoo search was called for "Jardinería"
    mock_odoo.search.assert_any_call("product.category", [("name", "=ilike", "Jardinería")])
