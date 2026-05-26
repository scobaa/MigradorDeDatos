"""
Transformador de res.partner.

Recibe una fila cruda del origen (dict columna→valor) y un mapeo
{columna_origen: campo_odoo}, y devuelve un dict de valores limpios listo
para que el migrador lo convierta en `res.partner.create()`.

Aplica las limpiezas descritas en CLAUDE.md:
  - NIF/CIF: sin espacios/guiones/puntos, mayúsculas, prefijo país.
  - Teléfono: sin extensiones, normalizado.
  - Email: minúsculas, validado.
  - Empresa vs persona: heurística por CIF y por palabras clave.

Diseño: este módulo es PURO. No conecta a Odoo ni resuelve IDs Many2one.
Los campos geográficos se devuelven como texto en las claves auxiliares
`_country` y `_state`; el migrador los resuelve a `country_id` / `state_id`.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Campos de res.partner que aceptamos como destino del mapeo.
# Los que empiezan por "_" son auxiliares que el migrador resuelve a Many2one.
SUPPORTED_FIELDS = {
    "name",
    "vat",
    "email",
    "phone",
    "mobile",
    "website",
    "street",
    "street2",
    "city",
    "zip",
    "ref",
    "comment",
    "_country",  # → country_id
    "_state",    # → state_id
}

# Palabras clave que delatan una persona jurídica (empresa).
COMPANY_KEYWORDS = (
    "s.l.u", "slu", "s.l.l", "sll", "s.l", "sl",
    "s.a.u", "sau", "s.a", "sa",
    "s.c", "sc", "s.coop", "coop", "scoop",
    "c.b", "cb", "s.r.l", "srl",
    "sociedad", "asociados", "& asociados",
    "ltd", "inc", "gmbh", "b.v", "bv", "sarl", "sas",
)

# Letras iniciales de CIF que corresponden a entidades (empresa).
# K, L, M y X/Y/Z son personas físicas (NIF/NIE), el resto entidades.
CIF_COMPANY_LETTERS = set("ABCDEFGHJNPQRSUVW")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_NON_VAT = re.compile(r"[\s\-.\/]")
_PHONE_EXT = re.compile(r"\s*(ext\.?|x|extensi[oó]n)\s*\d+\s*$", re.IGNORECASE)


# ─── Limpiezas atómicas ────────────────────────────────────────

def clean_str(value: Any) -> str | None:
    """Normaliza a str: strip, colapsa espacios internos, None si queda vacío."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def clean_vat(value: Any, country_prefix: str = "ES") -> str | None:
    """
    Normaliza un NIF/CIF: quita espacios/guiones/puntos, mayúsculas y antepone
    el prefijo de país ISO si no lo trae ya (formato esperado por Odoo: 'ES12345678A').
    """
    text = clean_str(value)
    if not text:
        return None
    text = _NON_VAT.sub("", text).upper()
    if not text:
        return None
    # ¿Ya empieza por prefijo de país (2 letras seguidas de un dígito/letra)?
    if re.match(r"^[A-Z]{2}[0-9A-Z]", text) and text[:2].isalpha():
        return text
    return f"{country_prefix.upper()}{text}"


def clean_email(value: Any) -> str | None:
    """Minúsculas y validación de formato. Devuelve None si no es un email válido."""
    text = clean_str(value)
    if not text:
        return None
    text = text.lower()
    # Puede venir más de uno separado por ; o , → quedarnos con el primero.
    text = re.split(r"[;,]", text)[0].strip()
    if not _EMAIL_RE.match(text):
        log.warning("Email descartado por formato inválido: %r", value)
        return None
    return text


def clean_phone(value: Any, region: str = "ES") -> str | None:
    """
    Quita extensiones y normaliza el teléfono. Usa la librería `phonenumbers`
    si está disponible (formato internacional E.164); si no, limpieza básica.
    """
    text = clean_str(value)
    if not text:
        return None
    text = _PHONE_EXT.sub("", text).strip()
    if not text:
        return None

    try:
        import phonenumbers

        parsed = phonenumbers.parse(text, region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
        log.warning("Teléfono no válido para región %s: %r", region, value)
    except Exception:  # noqa: BLE001 - phonenumbers lanza varios tipos
        log.debug("phonenumbers no pudo parsear %r, uso limpieza básica", text)

    # Fallback: conservar dígitos y el '+' inicial.
    cleaned = re.sub(r"(?!^\+)[^\d]", "", text)
    return cleaned or None


def guess_is_company(name: str | None, vat: str | None) -> bool:
    """
    Heurística empresa vs persona:
    1. Por el CIF/NIF (la letra inicial del documento español es definitiva).
    2. Por palabras clave en el nombre (S.L., S.A., etc.).
    Por defecto, persona física (False).
    """
    if vat:
        # Quitar prefijo de país de 2 letras para mirar el carácter del documento.
        doc = vat[2:] if vat[:2].isalpha() and len(vat) > 2 else vat
        doc = doc.upper()
        if doc:
            first = doc[0]
            if first in CIF_COMPANY_LETTERS:
                return True
            if first.isdigit() or first in "KLMXYZ":
                return False  # DNI/NIE → persona

    if name:
        tokens = re.split(r"[\s,]+", name.lower())
        normalized = {t.strip(".") for t in tokens}
        for kw in COMPANY_KEYWORDS:
            if kw in name.lower() or kw.replace(".", "") in normalized:
                return True

    return False


# ─── Transformación de fila completa ───────────────────────────

def transform_partner(
    row: dict[str, Any],
    mapping: dict[str, str],
    *,
    default_country: str = "ES",
    customer_rank: int = 1,
    supplier_rank: int = 0,
    infer_company: bool = True,
) -> dict[str, Any]:
    """
    Transforma una fila de origen en valores limpios de res.partner.

    Args:
        row: fila cruda {columna_origen: valor}.
        mapping: {columna_origen: campo_odoo}. Solo se usan campos de SUPPORTED_FIELDS.
        default_country: prefijo ISO para NIFs sin prefijo (y país por defecto).
        customer_rank / supplier_rank: marcan el partner como cliente/proveedor.
        infer_company: si True y no se mapeó is_company, se deduce por heurística.

    Returns:
        dict de valores limpios. Las claves `_country`/`_state` son auxiliares
        (texto) que el migrador convierte a country_id/state_id.

    Raises:
        ValueError: si la fila resultante no tiene `name` (campo obligatorio).
    """
    vals: dict[str, Any] = {}

    for source_col, odoo_field in mapping.items():
        if not odoo_field:
            continue
        if odoo_field in (
            "__external_id",
            "contact_name",
            "contact_email",
            "contact_phone",
            "contact_mobile",
            "bank_acc_number",
            "bank_name",
        ):
            continue
        raw = row.get(source_col)

        if odoo_field == "vat":
            cleaned = clean_vat(raw, default_country)
        elif odoo_field == "email":
            cleaned = clean_email(raw)
        elif odoo_field in ("phone", "mobile"):
            cleaned = clean_phone(raw, default_country)
        else:
            cleaned = clean_str(raw)

        if cleaned is not None:
            vals[odoo_field] = cleaned

    name = vals.get("name")
    if not name:
        raise ValueError(
            "La fila no tiene 'name' tras la transformación; "
            "revisa el mapeo (el campo name es obligatorio en res.partner)."
        )

    if infer_company and "is_company" not in vals:
        vals["is_company"] = guess_is_company(name, vals.get("vat"))

    vals["customer_rank"] = customer_rank
    vals["supplier_rank"] = supplier_rank

    return vals
