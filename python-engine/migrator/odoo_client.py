"""
Cliente XML-RPC para Odoo — base reutilizable para todos los migradores.

Encapsula la autenticación, la caché de catálogos (países, impuestos, cuentas)
y los métodos CRUD básicos. Cada migrador específico (partners, products, etc.)
recibe una instancia de esta clase.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import socket
import xmlrpc.client
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

_PAREN_RE = re.compile(r"\s*\([^)]*\)")


def _ascii_lower(text: str) -> str:
    """Quita tildes/diacríticos y pasa a minúsculas ('Álava' → 'alava')."""
    return (
        unicodedata.normalize("NFD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def _state_name_variants(name: str) -> set[str]:
    """
    Genera todas las claves de búsqueda para el nombre de una provincia/estado.

    Odoo 19 usa nombres bilingües/oficiales como 'Araba/Álava',
    'Bizkaia (Vizcaya)' o 'Alacant (Alicante)'. Este helper produce variantes
    sin tildes y fragmentos individuales para que una búsqueda por 'ALAVA'
    o 'ALICANTE' resuelva aunque el nombre oficial sea diferente.
    """
    keys: set[str] = set()

    def _add(s: str) -> None:
        s = s.strip()
        if s:
            keys.add(s.lower())
            keys.add(_ascii_lower(s))

    _add(name)
    # Fragmentar por "/" (ej. "Araba/Álava" → ["Araba", "Álava"])
    for part in name.split("/"):
        _add(part)
    # Contenido entre paréntesis (ej. "Bizkaia (Vizcaya)" → "Vizcaya")
    for m in re.finditer(r"\(([^)]+)\)", name):
        _add(m.group(1))
    # Nombre sin el paréntesis (ej. "Bizkaia (Vizcaya)" → "Bizkaia")
    _add(_PAREN_RE.sub("", name))

    return keys


@dataclass
class OdooConfig:
    """Configuración de conexión a una instancia Odoo."""
    url: str
    db: str
    username: str
    password: str

    def __post_init__(self) -> None:
        # Normalizar URL: sin barra al final
        self.url = self.url.rstrip("/")


class OdooClient:
    """Cliente XML-RPC con caché interna de catálogos."""

    def __init__(self, config: OdooConfig) -> None:
        self.config = config
        self.uid: int | None = None
        self._models: xmlrpc.client.ServerProxy | None = None

        # Cachés
        self._countries: dict[str, int] = {}
        self._states: dict[tuple[int, str], int] = {}
        self._accounts: dict[str, int] = {}
        self._taxes: dict[tuple[str, str], int] = {}
        self._valid_fields: dict[str, set[str]] = {}
        self._fields_info: dict[str, dict] = {}  # model → {field: {type, relation, ...}}

    # ─── Conexión ──────────────────────────────────────────

    def connect(self) -> None:
        """Autentica contra Odoo. Lanza ConnectionError si falla."""
        # Establecer el timeout predeterminado a nivel de socket para compatibilidad con todas las versiones de Python
        socket.setdefaulttimeout(15.0)
        common = xmlrpc.client.ServerProxy(f"{self.config.url}/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(
            self.config.db, self.config.username, self.config.password, {}
        )
        if not self.uid:
            raise ConnectionError("Credenciales incorrectas o Odoo inaccesible")

        self._models = xmlrpc.client.ServerProxy(
            f"{self.config.url}/xmlrpc/2/object", allow_none=True
        )
        log.info("Conectado a Odoo db=%s uid=%s", self.config.db, self.uid)

    def test_connection(self) -> tuple[bool, str]:
        """Prueba la conexión sin lanzar excepción. Retorna (ok, mensaje)."""
        try:
            self.connect()
            # Comprobar que tenemos acceso a res.partner
            self.execute("res.partner", "check_access_rights", "read", raise_exception=False)
            return True, "Conexión OK"
        except Exception as e:
            return False, f"Error: {e}"

    # ─── CRUD básico ────────────────────────────────────────

    def execute(
        self,
        model: str,
        method: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Llamada genérica execute_kw."""
        if self._models is None or self.uid is None:
            raise RuntimeError("Llamar connect() antes de execute()")
        return self._models.execute_kw(
            self.config.db,
            self.uid,
            self.config.password,
            model,
            method,
            list(args),
            kwargs,
        )

    def create(self, model: str, vals: dict) -> int:
        """Crea un registro y retorna su ID."""
        result = self.execute(model, "create", [vals])
        # create() devuelve lista de IDs en Odoo 12+
        return result[0] if isinstance(result, list) else result

    def write(self, model: str, ids: list[int], vals: dict) -> bool:
        return self.execute(model, "write", ids, vals)

    def search(
        self,
        model: str,
        domain: list,
        limit: int = 0,
        offset: int = 0,
    ) -> list[int]:
        return self.execute(model, "search", domain, limit=limit, offset=offset)

    def search_all_companies(
        self,
        model: str,
        domain: list,
        limit: int = 0,
    ) -> list[int]:
        """Búsqueda sin filtro de compañía activa.
        
        Útil cuando un producto/contacto puede pertenecer a cualquier compañía
        y queremos encontrarlo independientemente del contexto actual del usuario.
        """
        return self.execute(
            model, "search", domain,
            limit=limit,
            context={"allowed_company_ids": False},
        )

    def search_read(
        self,
        model: str,
        domain: list,
        fields: list[str],
        limit: int = 0,
    ) -> list[dict]:
        return self.execute(model, "search_read", domain, fields, limit=limit)

    def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict]:
        return self.execute(model, "read", ids, fields)

    def unlink(self, model: str, ids: list[int]) -> bool:
        return self.execute(model, "unlink", ids)

    # ─── Catálogos cacheados ───────────────────────────────

    def get_country_id(self, value: str | None) -> int | None:
        """Resuelve ID de país por nombre o código ISO. Cachea resultados."""
        if not value:
            return None
        key = value.strip().lower()
        if not self._countries:
            self._load_countries()
        return self._countries.get(key)

    def _load_countries(self) -> None:
        log.debug("Cargando catálogo res.country")
        recs = self.search_read("res.country", [], ["id", "name", "code"])
        for r in recs:
            self._countries[r["name"].lower()] = r["id"]
            self._countries[r["code"].lower()] = r["id"]

    def get_state_id(self, country_id: int, value: str | None) -> int | None:
        if not value or not country_id:
            return None
        if not self._states:
            self._load_states()
        # Buscar primero por el valor tal cual, luego sin tildes.
        for key in (value.strip().lower(), _ascii_lower(value.strip())):
            sid = self._states.get((country_id, key))
            if sid:
                return sid
        return None

    def _load_states(self) -> None:
        log.debug("Cargando catálogo res.country.state")
        recs = self.search_read(
            "res.country.state", [], ["id", "name", "code", "country_id"]
        )
        for r in recs:
            cid = r["country_id"][0]
            sid = r["id"]
            for key in _state_name_variants(r["name"]):
                self._states.setdefault((cid, key), sid)
            self._states.setdefault((cid, r["code"].lower()), sid)
            self._states.setdefault((cid, _ascii_lower(r["code"])), sid)

    def get_valid_fields(self, model: str) -> set[str]:
        """Retorna el conjunto de campos válidos del modelo (cacheado)."""
        if model not in self._valid_fields:
            self.get_fields_info(model)  # pobla la caché de campos
        return self._valid_fields[model]

    def get_fields_info(self, model: str) -> dict:
        """Retorna metadatos de campos del modelo: tipo, modelo relacionado, etc. (cacheado)."""
        if model not in self._fields_info:
            info = self.execute(model, "fields_get", attributes=["type", "relation", "string"])
            self._fields_info[model] = info
            self._valid_fields[model] = set(info.keys())
            log.debug("Campos de %s: %d", model, len(info))
        return self._fields_info[model]

    def filter_vals(self, model: str, vals: dict) -> dict:
        """Elimina de vals los campos que no existen en el modelo Odoo y normaliza None a False."""
        valid = self.get_valid_fields(model)
        filtered = {k: v for k, v in vals.items() if k in valid}
        
        # Convertir None a False para evitar errores de serialización XML-RPC
        for k, v in filtered.items():
            if v is None:
                filtered[k] = False
                
        removed = set(vals) - set(filtered)
        if removed:
            log.warning("Campos eliminados por no existir en %s: %s", model, sorted(removed))
        return filtered

    def get_account_id(self, code: str) -> int | None:
        """Cuenta contable por código (ej '700', '430')."""
        if not code:
            return None
        if code not in self._accounts:
            ids = self.search("account.account", [("code", "=", code)])
            self._accounts[code] = ids[0] if ids else None
        return self._accounts[code]

    def get_tax_id(self, name: str, tax_use: str = "sale") -> int | None:
        """Impuesto por nombre + tipo de uso ('sale' o 'purchase')."""
        if not name:
            return None
        key = (name.strip().lower(), tax_use)
        if key not in self._taxes:
            ids = self.search(
                "account.tax",
                [("name", "=", name), ("type_tax_use", "=", tax_use)],
            )
            self._taxes[key] = ids[0] if ids else None
        return self._taxes[key]

    def get_xml_id_res_id(self, xml_id: str, model: str) -> int | None:
        """Busca el ID de base de datos para una ID externa (XML ID) en ir.model.data."""
        if not xml_id:
            return None
        module = "__import__"
        name = xml_id
        if "." in xml_id:
            parts = xml_id.split(".", 1)
            module = parts[0]
            name = parts[1]

        domain = [
            ("module", "=", module),
            ("name", "=", name),
            ("model", "=", model),
        ]
        recs = self.search_read("ir.model.data", domain, ["res_id"], limit=1)
        return recs[0]["res_id"] if recs else None

    def resolve_many2one(
        self,
        value: str | None,
        model: str,
        *,
        xml_id_prefix: str = "",
        name_field: str = "name",
        extra_fields: list[str] | None = None,
        cache: dict | None = None,
    ) -> int | None:
        """Resolución universal de un campo Many2one con prioridad:
        1. ID externo (ir.model.data) — con prefijo y sin prefijo.
        2. Campos de código extra (ref, default_code, barcode, …).
        3. Nombre exacto (name_field).

        Args:
            value:        Valor a resolver (código, nombre, XML ID…).
            model:        Modelo Odoo destino (ej. 'res.partner').
            xml_id_prefix: Prefijo para construir el XML ID (ej. 'cli_').
            name_field:   Campo de nombre a usar en el fallback (por defecto 'name').
            extra_fields: Lista de campos extra a probar antes del nombre
                          (ej. ['ref', 'default_code', 'barcode']).
            cache:        Diccionario mutable compartido por el llamante para
                          evitar consultas repetidas. Si es None no se cachea.

        Returns:
            ID entero del registro en Odoo, o None si no se encuentra.
        """
        if not value:
            return None

        key = str(value).strip()
        if not key:
            return None

        # Consultar caché
        if cache is not None and key in cache:
            return cache[key]

        result: int | None = None

        try:
            # ── 1. Buscar por ID externo ──────────────────────────────────────
            # Intentamos con y sin prefijo para mayor flexibilidad.
            candidates: list[str] = []
            if xml_id_prefix:
                if not key.startswith(xml_id_prefix):
                    candidates.append(f"{xml_id_prefix}{key}")
                candidates.append(key)
            else:
                candidates.append(key)

            for xml_id in candidates:
                result = self.get_xml_id_res_id(xml_id, model)
                if result:
                    break

            # ── 2. Campos de código extra ─────────────────────────────────────
            if not result and extra_fields:
                for field_name in extra_fields:
                    ids = self.search(model, [(field_name, "=", key)], limit=1)
                    if ids:
                        result = ids[0]
                        break

            # ── 3. Fallback por nombre exacto ─────────────────────────────────
            if not result:
                ids = self.search(model, [(name_field, "=", key)], limit=1)
                if ids:
                    result = ids[0]

        except Exception as e:
            log.warning(
                "Error al resolver Many2one '%s' en modelo '%s' con valor '%s': %s",
                name_field, model, key, e,
            )

        # Guardar en caché (incluso None, para no reintentar valores fallidos)
        if cache is not None:
            cache[key] = result

        if not result:
            log.warning(
                "Many2one no encontrado en '%s': valor='%s' (prefijo='%s', extras=%s)",
                model, key, xml_id_prefix, extra_fields,
            )

        return result

    def create_or_update_xml_id(self, xml_id: str, model: str, res_id: int) -> None:
        """Crea o actualiza la vinculación de ID externa en ir.model.data."""
        if not xml_id or not res_id:
            return
        module = "__import__"
        name = xml_id
        if "." in xml_id:
            parts = xml_id.split(".", 1)
            module = parts[0]
            name = parts[1]

        domain = [
            ("module", "=", module),
            ("name", "=", name),
            ("model", "=", model),
        ]
        ids = self.search("ir.model.data", domain, limit=1)

        vals = {
            "module": module,
            "name": name,
            "model": model,
            "res_id": res_id,
        }

        if ids:
            self.write("ir.model.data", ids, vals)
        else:
            self.create("ir.model.data", vals)

    def get_or_create_bank(self, bank_name: str) -> int | None:
        """Busca una entidad bancaria por nombre en res.bank. Si no existe, la crea."""
        if not bank_name:
            return None

        name_clean = bank_name.strip()
        if not name_clean:
            return None

        # Intentar buscar por nombre exacto
        domain = [("name", "=", name_clean)]
        ids = self.search("res.bank", domain, limit=1)
        if ids:
            return ids[0]

        # Si no existe, crear el banco
        try:
            log.info("Creando entidad bancaria en res.bank: %s", name_clean)
            return self.create("res.bank", {"name": name_clean})
        except Exception as e:
            log.warning("No se pudo crear la entidad bancaria %r: %s", name_clean, e)
            return None
