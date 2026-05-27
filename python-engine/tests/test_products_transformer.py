"""
Tests del transformador de product.template.

Cubre las limpiezas de precios, códigos de barras, tipos de productos
y la transformación de fila completa.
"""

from __future__ import annotations

import pytest

from transformers.products import (
    clean_barcode,
    clean_float,
    clean_str,
    clean_type,
    transform_product,
)


def test_clean_str():
    assert clean_str("  Artículo de   prueba ") == "Artículo de prueba"
    assert clean_str("") is None
    assert clean_str("   ") is None
    assert clean_str(None) is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("12,34", 12.34),
        (" 120.50 € ", 120.50),
        ("50", 50.0),
        ("-10.50", 10.50),  # toma el valor positivo quitando el guión
        ("gratis", 0.0),
        ("", 0.0),
        (None, 0.0),
    ],
)
def test_clean_float(value, expected):
    assert clean_float(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("8412345678901", "8412345678901"),
        ("8412345678901.0", "8412345678901"),  # quita el .0 de conversión float de Excel
        ("   ", None),
        (None, None),
    ],
)
def test_clean_barcode(value, expected):
    assert clean_barcode(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Servicio técnico", "service"),
        ("Mano de obra 1 hora", "service"),
        ("Artículo almacenable", "product"),
        ("Consumible oficina", "consu"),
        ("consu", "consu"),
        ("", "product"),
        (None, "product"),
    ],
)
def test_clean_type(value, expected):
    assert clean_type(value) == expected


def test_transform_product_completo():
    row = {
        "Codigo": "ART001",
        "EAN": "841234500012.0",
        "Descripcion": "Tornillos de acero inoxidable 10mm",
        "Coste": " 1,25 €",
        "PVP": " 2.99 ",
        "Familia": "Ferretería / Tornillos",
        "Tipo": "Almacenable",
    }
    mapping = {
        "Codigo": "default_code",
        "EAN": "barcode",
        "Descripcion": "name",
        "Coste": "standard_price",
        "PVP": "list_price",
        "Familia": "_category",
        "Tipo": "type",
    }
    vals = transform_product(row, mapping)

    assert vals["default_code"] == "ART001"
    assert vals["barcode"] == "841234500012"
    assert vals["name"] == "Tornillos de acero inoxidable 10mm"
    assert vals["standard_price"] == 1.25
    assert vals["list_price"] == 2.99
    assert vals["_category"] == "Ferretería / Tornillos"
    assert vals["type"] == "product"


def test_transform_product_sin_nombre_falla():
    row = {"Codigo": "ART001"}
    mapping = {"Codigo": "default_code"}
    with pytest.raises(ValueError, match="name"):
        transform_product(row, mapping)
