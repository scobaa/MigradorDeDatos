"""
Mapeo automático de columnas con IA (Claude).

Hace una única llamada a la API de Claude que:
  1. Detecta el ERP / sistema origen por los nombres de columna.
  2. Sugiere el mapeo {columna_origen → campo_odoo} con nivel de confianza.

Regla de privacidad: NUNCA se envían valores de celdas, solo nombres de columna.

Uso desde main.py:
    result = suggest_mapping(
        columns=["NOFCLI", "NIFCLI", "DOMCLI", ...],
        target_model="res.partner",
        api_key="sk-ant-...",
    )

Devuelve:
    {
        "erp_detected": "FactuSOL",
        "erp_confidence": 0.98,
        "mapping": {
            "NOFCLI": {"odoo_field": "name",    "confidence": 0.99, "reasoning": "..."},
            "NIFCLI": {"odoo_field": "vat",     "confidence": 0.97, "reasoning": "..."},
            "EMACLI": {"odoo_field": "email",   "confidence": 0.99, "reasoning": "..."},
            ...
        },
        "unmapped": ["CCOCLI", "AGECLI", ...],   # columnas sin campo Odoo relevante
        "usage": {"input_tokens": N, "output_tokens": M, "cache_read_tokens": K}
    }
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# ─── Esquema de modelos Odoo (system prompt cacheado) ─────────
# Este bloque es estático y se cachea en los servidores de Anthropic.
# Solo se recalcula si cambia el contenido (TTL ~5 minutos).

_ODOO_MODELS: dict[str, dict[str, str]] = {
    "res.partner": {
        "name":          "Razón social o nombre completo (OBLIGATORIO)",
        "vat":           "NIF/CIF con prefijo país: ES12345678A, ESB12345678",
        "email":         "Correo electrónico",
        "phone":         "Teléfono fijo",
        "mobile":        "Teléfono móvil",
        "website":       "Sitio web (URL)",
        "street":        "Dirección (calle y número)",
        "street2":       "Dirección línea 2 (piso, puerta, etc.)",
        "city":          "Ciudad / población",
        "zip":           "Código postal",
        "state_id":      "Provincia (Many2one → res.country.state)",
        "country_id":    "País (Many2one → res.country)",
        "ref":           "Referencia externa / código en el sistema origen",
        "comment":       "Notas u observaciones internas",
        "is_company":    "True si es empresa, False si es persona física",
        "customer_rank": "1 si es cliente (0 si no)",
        "supplier_rank": "1 si es proveedor (0 si no)",
        "lang":          "Idioma (ej. es_ES, ca_ES)",
        "tz":            "Zona horaria (ej. Europe/Madrid)",
    },
    "product.template": {
        "name":           "Nombre del producto (OBLIGATORIO)",
        "default_code":   "Referencia interna / SKU",
        "barcode":        "Código de barras EAN/UPC",
        "description":    "Descripción del producto",
        "list_price":     "Precio de venta (PVP)",
        "standard_price": "Precio de coste",
        "type":           "Tipo: consu (consumible), service, product (almacenable)",
        "categ_id":       "Categoría del producto",
        "uom_id":         "Unidad de medida",
        "active":         "True si está activo",
        "sale_ok":        "True si se puede vender",
        "purchase_ok":    "True si se puede comprar",
    },
}

_KNOWN_ERPS: dict[str, dict] = {
    "FactuSOL": {
        "description": "ERP español de Software del Sol. Tablas con prefijo F_. "
                       "Columnas con sufijo CLI (clientes), PRO (proveedores), ART (artículos).",
        "signature_columns": ["NOFCLI", "NIFCLI", "DOMCLI", "POBCLI", "EMACLI", "PAICLI"],
        "auto_mapping": {
            "NOFCLI": "name", "NIFCLI": "vat", "CODCLI": "ref",
            "DOMCLI": "street", "POBCLI": "city", "CPOCLI": "zip",
            "PROCLI": "state_id", "PAICLI": "country_id",
            "TELCLI": "phone", "MOVCLI": "mobile",
            "EMACLI": "email", "WEBCLI": "website", "OBSCLI": "comment",
        },
    },
    "Sage 50": {
        "description": "ERP español Sage 50 (antes ContaPlus/FacturaPlus). "
                       "Columnas descriptivas en inglés o castellano.",
        "signature_columns": ["CodigoEmpresa", "RazonSocial", "CifNif", "DireccionFiscal"],
        "auto_mapping": {
            "RazonSocial": "name", "CifNif": "vat", "CodigoCliente": "ref",
            "DireccionFiscal": "street", "Poblacion": "city",
            "CodigoPostal": "zip", "Provincia": "state_id",
            "Pais": "country_id", "Telefono": "phone",
            "Movil": "mobile", "Email": "email",
        },
    },
    "Contasol": {
        "description": "ERP español Contasol / Factusol de Software del Sol (versión anterior).",
        "signature_columns": ["CODIGO", "NOMBRE", "DOMICILIO", "POBLACION", "NIFCIF"],
        "auto_mapping": {
            "NOMBRE": "name", "NIFCIF": "vat", "CODIGO": "ref",
            "DOMICILIO": "street", "POBLACION": "city",
            "CODPOST": "zip", "PROVINCIA": "state_id",
            "PAIS": "country_id", "TELEFONO": "phone",
            "MOVIL": "mobile", "EMAIL": "email",
        },
    },
    "A3ERP / A3con": {
        "description": "Suite ERP española A3 Software (Wolters Kluwer).",
        "signature_columns": ["COD_CLI", "NOM_FISCAL", "NIF", "DIR_FISCAL"],
        "auto_mapping": {
            "NOM_FISCAL": "name", "NIF": "vat", "COD_CLI": "ref",
            "DIR_FISCAL": "street", "POBLACION": "city",
            "C_POSTAL": "zip", "PROVINCIA": "state_id",
            "PAIS": "country_id", "TELEFONO1": "phone",
            "MOVIL": "mobile", "EMAIL": "email",
        },
    },
    "Holded": {
        "description": "ERP SaaS español Holded. Exporta CSVs con cabeceras en inglés.",
        "signature_columns": ["customerId", "name", "taxId", "address", "zipCode"],
        "auto_mapping": {
            "name": "name", "taxId": "vat", "customerId": "ref",
            "address": "street", "city": "city",
            "zipCode": "zip", "province": "state_id",
            "country": "country_id", "phone": "phone",
            "mobile": "mobile", "email": "email", "website": "website",
            "notes": "comment",
        },
    },
}


def _build_system_prompt(target_model: str) -> str:
    """Genera el system prompt estático (candidato a caché de Anthropic)."""
    fields = _ODOO_MODELS.get(target_model, {})
    fields_text = "\n".join(
        f"  - {field}: {desc}" for field, desc in fields.items()
    )

    erps_text = "\n".join(
        f"  - {name}: {info['description']}"
        for name, info in _KNOWN_ERPS.items()
    )

    return f"""Eres un experto en migración de datos a Odoo ERP. Tu tarea es:
1. Identificar de qué ERP o sistema provienen las columnas recibidas.
2. Sugerir el mapeo óptimo de cada columna origen al campo Odoo correspondiente.

## Modelo Odoo destino: `{target_model}`

Campos disponibles:
{fields_text}

Usa el campo especial `"_country"` para columnas de país (texto) y `"_state"` para
columnas de provincia (texto). El migrador los resuelve a Many2one automáticamente.
Para columnas que no tienen campo Odoo relevante, ponlas en `"unmapped"`.

## ERPs conocidos (detectar por nombre de columnas)
{erps_text}

## Formato de respuesta (JSON estricto, sin texto adicional)

```json
{{
  "erp_detected": "nombre del ERP o 'Desconocido'",
  "erp_confidence": 0.0,
  "mapping": {{
    "COLUMNA_ORIGEN": {{
      "odoo_field": "nombre_campo_odoo",
      "confidence": 0.0,
      "reasoning": "explicación breve en español"
    }}
  }},
  "unmapped": ["COL1", "COL2"]
}}
```

Reglas:
- `confidence` entre 0.0 y 1.0 (usa >0.85 solo cuando estés seguro).
- Incluye en `mapping` TODAS las columnas que tengan campo Odoo razonable.
- Las que no tengan correspondencia clara van en `unmapped`.
- El campo `name` es el único OBLIGATORIO; si no hay columna para él, indica confidence 0.
- Devuelve SOLO el JSON, sin bloques markdown ni explicaciones fuera del JSON."""


def suggest_mapping(
    columns: list[str],
    target_model: str = "res.partner",
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Llama a Claude para detectar el ERP y sugerir el mapeo de columnas.

    Args:
        columns: lista de nombres de columna del origen (sin valores).
        target_model: modelo Odoo destino (ej. "res.partner").
        api_key: clave API de Anthropic. Si None, lee ANTHROPIC_API_KEY del entorno.

    Returns:
        dict con erp_detected, erp_confidence, mapping, unmapped y usage.

    Raises:
        ValueError: si no hay API key.
        anthropic.APIError: si la llamada a Claude falla.
    """
    import anthropic

    resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not resolved_key:
        raise ValueError(
            "Falta la API key de Anthropic. "
            "Pásala como argumento o define la variable ANTHROPIC_API_KEY."
        )

    client = anthropic.Anthropic(api_key=resolved_key)

    system_prompt = _build_system_prompt(target_model)
    user_message = (
        f"Columnas del fichero origen ({len(columns)} columnas):\n"
        + json.dumps(columns, ensure_ascii=False)
    )

    log.info(
        "Llamando a Claude para mapeo de %d columnas → %s",
        len(columns),
        target_model,
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                # El system prompt es estático → se cachea en Anthropic
                # (TTL ~5 min; ahorra tokens y reduce latencia en llamadas repetidas)
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    # Limpiar posibles bloques markdown si Claude los añade igualmente
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("Respuesta de Claude no es JSON válido: %s", raw[:300])
        raise ValueError(f"Claude devolvió JSON inválido: {e}") from e

    usage = response.usage
    result["usage"] = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0),
        "cache_creation_tokens": getattr(usage, "cache_creation_input_tokens", 0),
    }

    log.info(
        "Mapeo completado. ERP: %s (%.0f%%). Tokens: in=%d out=%d cache_read=%d",
        result.get("erp_detected", "?"),
        result.get("erp_confidence", 0) * 100,
        result["usage"]["input_tokens"],
        result["usage"]["output_tokens"],
        result["usage"]["cache_read_tokens"],
    )

    return result
