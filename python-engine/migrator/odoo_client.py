"""
Cliente XML-RPC para Odoo — base reutilizable para todos los migradores.

Encapsula la autenticación, la caché de catálogos (países, impuestos, cuentas)
y los métodos CRUD básicos. Cada migrador específico (partners, products, etc.)
recibe una instancia de esta clase.
"""

from __future__ import annotations

import logging
import xmlrpc.client
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


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

    # ─── Conexión ──────────────────────────────────────────

    def connect(self) -> None:
        """Autentica contra Odoo. Lanza ConnectionError si falla."""
        common = xmlrpc.client.ServerProxy(f"{self.config.url}/xmlrpc/2/common")
        self.uid = common.authenticate(
            self.config.db, self.config.username, self.config.password, {}
        )
        if not self.uid:
            raise ConnectionError("Credenciales incorrectas o Odoo inaccesible")

        self._models = xmlrpc.client.ServerProxy(
            f"{self.config.url}/xmlrpc/2/object"
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
        key = (country_id, value.strip().lower())
        if not self._states:
            self._load_states()
        return self._states.get(key)

    def _load_states(self) -> None:
        log.debug("Cargando catálogo res.country.state")
        recs = self.search_read(
            "res.country.state", [], ["id", "name", "code", "country_id"]
        )
        for r in recs:
            cid = r["country_id"][0]
            self._states[(cid, r["name"].lower())] = r["id"]
            self._states[(cid, r["code"].lower())] = r["id"]

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
