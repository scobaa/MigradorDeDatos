"""
Tests del transformador de res.partner.

Cubre las limpiezas atómicas (NIF, email, teléfono), la heurística empresa/persona
y la transformación de fila completa. No requiere Access ni Odoo.

Ejecutar desde python-engine/:  pytest
"""

from __future__ import annotations

import pytest

from transformers.partners import (
    clean_email,
    clean_phone,
    clean_str,
    clean_vat,
    guess_is_company,
    transform_partner,
)


# ─── clean_str ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value,expected",
    [
        ("  Hola   mundo ", "Hola mundo"),
        ("\tACME\n", "ACME"),
        ("", None),
        ("   ", None),
        (None, None),
        (123, "123"),
    ],
)
def test_clean_str(value, expected):
    assert clean_str(value) == expected


# ─── clean_vat ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "value,expected",
    [
        ("B-12.345.678", "ESB12345678"),
        ("b12345678", "ESB12345678"),
        ("  12345678 A ", "ES12345678A"),
        ("ES B12345678", "ESB12345678"),
        ("FR12345678901", "FR12345678901"),  # ya trae prefijo país
        ("", None),
        (None, None),
    ],
)
def test_clean_vat(value, expected):
    assert clean_vat(value) == expected


def test_clean_vat_prefijo_personalizado():
    assert clean_vat("12345678A", country_prefix="pt") == "PT12345678A"


# ─── clean_email ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "value,expected",
    [
        ("  Info@ACME.com ", "info@acme.com"),
        ("a@b.es; c@d.es", "a@b.es"),  # se queda con el primero
        ("no-es-un-email", None),
        ("falta@dominio", None),
        ("", None),
        (None, None),
    ],
)
def test_clean_email(value, expected):
    assert clean_email(value) == expected


# ─── clean_phone ───────────────────────────────────────────────

def test_clean_phone_quita_extension():
    # Independientemente de si phonenumbers está instalado, la extensión se va
    # y el resultado no debe contener el "ext 123".
    out = clean_phone("912345678 ext 123")
    assert out is not None
    assert "ext" not in out.lower()
    assert "123" not in out.replace("912345678", "")


def test_clean_phone_vacio():
    assert clean_phone("") is None
    assert clean_phone(None) is None


def test_clean_phone_conserva_digitos():
    out = clean_phone("600 123 456")
    assert out is not None
    assert "600123456" in out.replace(" ", "")


# ─── guess_is_company ──────────────────────────────────────────

@pytest.mark.parametrize(
    "name,vat,expected",
    [
        ("Construcciones ACME S.L.", None, True),
        ("Talleres López SA", None, True),
        ("Juan Pérez García", None, False),
        ("ACME", "ESB12345678", True),       # CIF empieza por B → empresa
        ("Juan Pérez", "ES12345678Z", False),  # DNI → persona
        ("María", "ESX1234567L", False),       # NIE → persona
        ("Cooperativa del Sur", "ESF12345678", True),  # F → empresa
        ("Persona sin nada", None, False),
    ],
)
def test_guess_is_company(name, vat, expected):
    assert guess_is_company(name, vat) is expected


# ─── transform_partner ─────────────────────────────────────────

def test_transform_partner_completo():
    row = {
        "RazonSocial": "Construcciones ACME S.L.",
        "CIF": "b-12.345.678",
        "Correo": "INFO@acme.COM",
        "Tel": "912345678",
        "Direccion": "C/ Mayor 1",
        "Poblacion": "Madrid",
        "CP": "28013",
        "Pais": "España",
    }
    mapping = {
        "RazonSocial": "name",
        "CIF": "vat",
        "Correo": "email",
        "Tel": "phone",
        "Direccion": "street",
        "Poblacion": "city",
        "CP": "zip",
        "Pais": "_country",
    }
    vals = transform_partner(row, mapping)

    assert vals["name"] == "Construcciones ACME S.L."
    assert vals["vat"] == "ESB12345678"
    assert vals["email"] == "info@acme.com"
    assert vals["city"] == "Madrid"
    assert vals["zip"] == "28013"
    assert vals["is_company"] is True          # inferido por CIF + keyword
    assert vals["customer_rank"] == 1
    assert vals["supplier_rank"] == 0
    assert vals["_country"] == "España"        # auxiliar, lo resuelve el migrador


def test_transform_partner_sin_name_falla():
    row = {"CIF": "B12345678"}
    mapping = {"CIF": "vat"}
    with pytest.raises(ValueError, match="name"):
        transform_partner(row, mapping)


def test_transform_partner_ignora_campos_no_soportados():
    row = {"Nombre": "Juan", "Inventado": "x"}
    mapping = {"Nombre": "name", "Inventado": "campo_que_no_existe"}
    vals = transform_partner(row, mapping)
    assert vals["name"] == "Juan"
    assert "campo_que_no_existe" not in vals


def test_transform_partner_respeta_ranks_personalizados():
    row = {"Nombre": "Proveedor X SL"}
    mapping = {"Nombre": "name"}
    vals = transform_partner(row, mapping, customer_rank=0, supplier_rank=1)
    assert vals["customer_rank"] == 0
    assert vals["supplier_rank"] == 1


def test_transform_partner_omite_campos_vacios():
    row = {"Nombre": "Juan", "Email": "", "Tel": None}
    mapping = {"Nombre": "name", "Email": "email", "Tel": "phone"}
    vals = transform_partner(row, mapping)
    assert "email" not in vals
    assert "phone" not in vals
