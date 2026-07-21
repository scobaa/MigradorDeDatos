"""
Migrador de Asientos Contables (account.move con move_type='entry').
"""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

from migrator.odoo_client import OdooClient
from transformers.journal import transform_journal_entry

log = logging.getLogger(__name__)

ACCOUNT_MOVE_MODEL = "account.move"


@dataclass
class MigrationOptions:
    """Opciones de la migración de asientos contables."""
    update_existing: bool = True
    batch_size: int = 50
    external_id_prefix: str = "asi_"
    post_entries: bool = True


@dataclass
class MigrationStats:
    """Estadísticas acumuladas de la migración."""
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "error_count": len(self.errors),
            "errors": self.errors,
        }


def _emit_progress(event: dict[str, Any]) -> None:
    """Escribe un evento de progreso como línea JSON en stderr."""
    sys.stderr.write(json.dumps({"event": "progress", **event}, ensure_ascii=False))
    sys.stderr.write("\n")
    sys.stderr.flush()


def clean_xml_id(text: str) -> str:
    """Normaliza un texto para usarlo como XML ID válido en Odoo."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)


class JournalEntryMigrator:
    """Migra asientos contables hacia el modelo account.move de Odoo."""

    def __init__(
        self,
        odoo: OdooClient,
        mapping: dict[str, str],
        options: MigrationOptions | None = None,
    ) -> None:
        self.odoo = odoo
        self.mapping = mapping
        self.options = options or MigrationOptions()

        # Cachés locales para evitar peticiones repetidas
        self._account_cache: dict[str, int | None] = {}
        self._partner_cache: dict[str, int | None] = {}
        self._journal_cache: dict[str, int | None] = {}

    def _resolve_account(self, code: str | None) -> int | None:
        """Busca el ID de una cuenta contable en Odoo según su código."""
        if not code:
            return None

        clean_code = str(code).strip()
        if clean_code in self._account_cache:
            return self._account_cache[clean_code]

        try:
            # Buscar por código exacto
            ids = self.odoo.search("account.account", [("code", "=", clean_code)])
            if ids:
                self._account_cache[clean_code] = ids[0]
                return ids[0]
            
            # Reintentar quitando puntos si tuviera
            clean_code_no_dots = clean_code.replace(".", "")
            if clean_code_no_dots != clean_code:
                ids = self.odoo.search("account.account", [("code", "=", clean_code_no_dots)])
                if ids:
                    self._account_cache[clean_code] = ids[0]
                    return ids[0]

            # Fallback dinámico por prefijos si no se encuentra la cuenta exacta
            # Esto resuelve descuadres de dígitos (ej: origen 7/8 dígitos y Odoo 6 dígitos)
            # Buscamos desde el prefijo más específico (largo) al más general (corto, min 3 dígitos)
            for length in range(len(clean_code_no_dots) - 1, 2, -1):
                prefix = clean_code_no_dots[:length]
                ids = self.odoo.search("account.account", [("code", "=like", f"{prefix}%")])
                if ids:
                    found_id = ids[0]
                    try:
                        acc_info = self.odoo.read("account.account", [found_id], ["code"])
                        found_code = acc_info[0]["code"] if acc_info else prefix
                        log.info(
                            "Cuenta exacta '%s' no encontrada. Fallback automático a la cuenta padre '%s' (ID %s)",
                            clean_code, found_code, found_id
                        )
                    except Exception:
                        log.info(
                            "Cuenta exacta '%s' no encontrada. Fallback automático a cuenta con prefijo '%s' (ID %s)",
                            clean_code, prefix, found_id
                        )
                    self._account_cache[clean_code] = found_id
                    return found_id
        except Exception as e:
            log.warning("Error al resolver cuenta '%s': %s", clean_code, e)

        self._account_cache[clean_code] = None
        return None

    def _extract_partner_code_from_account(self, account_code: str) -> tuple[str, str] | None:
        """
        Deduce el código de cliente/proveedor a partir de la cuenta corriente contable.
        Ej:
          - 43000028 -> ('client', '28')
          - 43000105 -> ('client', '105')
          - 40000005 -> ('supplier', '5')
          - 41000012 -> ('supplier', '12')
        """
        code = account_code.replace(".", "").strip()
        # Clientes: cuentas que empiezan por 430 o 4300
        if code.startswith("430"):
            suffix = code[3:].lstrip("0")
            if suffix.isdigit():
                return "client", suffix
        # Proveedores/Acreedores: cuentas que empiezan por 400, 4000, 410, 4100
        if code.startswith("400") or code.startswith("410"):
            suffix = code[3:].lstrip("0")
            if suffix.isdigit():
                return "supplier", suffix
        return None

    def _resolve_partner(self, partner_code: str | None, is_supplier: bool = False) -> int | None:
        """Busca el ID de un partner en Odoo: ID externo → ref → nombre."""
        if not partner_code:
            return None

        key = str(partner_code).strip()
        cache_key = f"{key}_{is_supplier}"
        if cache_key in self._partner_cache:
            return self._partner_cache[cache_key]

        # Probar primero con el prefijo correspondiente (cli_ o pro_/prov_)
        prefixes = ["cli_"] if not is_supplier else ["pro_", "prov_"]
        for prefix in prefixes:
            result = self.odoo.resolve_many2one(
                key,
                "res.partner",
                xml_id_prefix=prefix,
                extra_fields=["ref"],
                cache=None,  # Usamos cache_key propio a continuación
            )
            if result:
                self._partner_cache[cache_key] = result
                return result

        self._partner_cache[cache_key] = None
        return None

    def _resolve_journal(self, name_or_code: str | None) -> int | None:
        """Busca el ID del diario contable: ID externo → code → nombre."""
        if not name_or_code:
            return None

        key = str(name_or_code).strip()
        if key in self._journal_cache:
            return self._journal_cache[key]

        result = self.odoo.resolve_many2one(
            key,
            "account.journal",
            extra_fields=["code"],
            cache=self._journal_cache,
        )
        return result

    def _process_row(self, row: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        """Transforma un asiento agrupado y resuelve todas sus cuentas y dependencias."""
        vals = transform_journal_entry(row, self.mapping)

        # 1. Resolver el diario (journal_id)
        journal_val = vals.pop("journal_id", None)
        journal_id = self._resolve_journal(journal_val)
        if journal_id:
            vals["journal_id"] = journal_id
        # Si no se especifica, Odoo intentará autodetectarlo, por lo que no es estrictamente obligatorio

        # 2. Resolver apuntes de asiento (line_ids)
        lines = vals.pop("_lines", [])
        line_ids = []

        total_debit = 0.0
        total_credit = 0.0

        for line in lines:
            account_code = line["_account_code"]
            account_id = self._resolve_account(account_code)
            if not account_id:
                raise ValueError(f"No se pudo encontrar ninguna cuenta contable en Odoo con código '{account_code}'.")

            # Intentar resolver partner
            partner_id = None
            partner_code = line["_partner_code"]
            if partner_code:
                # Buscar con heurística
                partner_id = self._resolve_partner(partner_code)
            else:
                # Intentar deducir partner desde la cuenta contable
                deduced = self._extract_partner_code_from_account(account_code)
                if deduced:
                    role, code_suffix = deduced
                    partner_id = self._resolve_partner(code_suffix, is_supplier=(role == "supplier"))

            debit_val = line["debit"]
            credit_val = line["credit"]
            total_debit += debit_val
            total_credit += credit_val

            line_vals = {
                "account_id": account_id,
                "name": line["name"],
                "debit": debit_val,
                "credit": credit_val,
            }
            if partner_id:
                line_vals["partner_id"] = partner_id

            line_ids.append((0, 0, line_vals))

        if not line_ids:
            raise ValueError("El asiento contable debe contener al menos un apunte válido con cuenta contable.")

        # Opcional: advertencia si no está balanceado
        if abs(total_debit - total_credit) > 0.01:
            log.warning(
                "Asiento '%s' desbalanceado: total Debe = %.2f, total Haber = %.2f (dif = %.2f)",
                vals.get("name"), total_debit, total_credit, total_debit - total_credit
            )

        vals["line_ids"] = line_ids
        return vals

    def run(
        self,
        rows: Iterable[dict[str, Any]],
        total: int = 0,
        dry_run: bool = False,
    ) -> MigrationStats:
        """Migra asientos contables ejecutando la inserción/actualización en Odoo."""
        stats = MigrationStats()
        log.info(
            "Iniciando migración de asientos contables (dry_run=%s, total=%s)",
            dry_run,
            total,
        )

        for idx, row in enumerate(rows):
            row_idx = idx + 1
            try:
                # 1. Transformar y resolver relaciones
                vals = self._process_row(row, dry_run)
                name = vals.get("name")
                if not name or name == "/":
                    raise ValueError("El número o nombre del asiento contable (campo 'name') es obligatorio.")

                # Generar XML ID único para el asiento
                xml_id = vals.pop("__external_id", None)
                if not xml_id:
                    clean_name = clean_xml_id(name)
                    xml_id = f"{self.options.external_id_prefix}{clean_name}"

                # 2. Comprobar si ya existe
                existing_id = self.odoo.get_xml_id_res_id(xml_id, ACCOUNT_MOVE_MODEL)

                if existing_id:
                    if not self.options.update_existing:
                        stats.skipped += 1
                        _emit_progress({
                            "done": row_idx,
                            "total": total,
                            "action": "skipped",
                            "name": name,
                        })
                        continue

                    # Actualización
                    if not dry_run:
                        # Mover a borrador si está publicado
                        move_data = self.odoo.read(ACCOUNT_MOVE_MODEL, [existing_id], ["state"])
                        if move_data and move_data[0]["state"] == "posted":
                            try:
                                self.odoo.execute(ACCOUNT_MOVE_MODEL, "button_draft", [existing_id])
                            except Exception as e:
                                log.warning("Fallo al cambiar estado a borrador para actualizar asiento: %s", e)

                        # Reemplazar líneas: (5, 0, 0) borra las existentes, luego agregamos las nuevas
                        vals["line_ids"] = [(5, 0, 0)] + vals["line_ids"]
                        
                        # Limpiar campos de Odoo
                        clean_vals = self.odoo.filter_vals(ACCOUNT_MOVE_MODEL, vals)
                        self.odoo.write(ACCOUNT_MOVE_MODEL, [existing_id], clean_vals)

                        # Volver a publicar si la opción está activa
                        if self.options.post_entries:
                            try:
                                self.odoo.execute(ACCOUNT_MOVE_MODEL, "action_post", [existing_id])
                            except Exception as e:
                                log.debug("Excepción silenciada en action_post: %s", e)

                    stats.updated += 1
                    _emit_progress({
                        "done": row_idx,
                        "total": total,
                        "action": "updated",
                        "name": name,
                    })

                else:
                    # Creación
                    if not dry_run:
                        clean_vals = self.odoo.filter_vals(ACCOUNT_MOVE_MODEL, vals)
                        new_id = self.odoo.create(ACCOUNT_MOVE_MODEL, clean_vals)
                        self.odoo.create_or_update_xml_id(xml_id, ACCOUNT_MOVE_MODEL, new_id)

                        # Publicar si está activa la opción
                        if self.options.post_entries:
                            try:
                                self.odoo.execute(ACCOUNT_MOVE_MODEL, "action_post", [new_id])
                            except Exception as e:
                                log.debug("Excepción silenciada en action_post: %s", e)

                    stats.created += 1
                    _emit_progress({
                        "done": row_idx,
                        "total": total,
                        "action": "created",
                        "name": name,
                    })

            except Exception as e:
                log.exception("Error procesando asiento contable en fila %s", row_idx)
                stats.errors.append({"row": row_idx, "error": str(e), "data": row})
                _emit_progress({
                    "done": row_idx,
                    "total": total,
                    "action": "error",
                    "message": str(e),
                })

        log.info("Migración de asientos finalizada: %s", stats.as_dict())
        return stats
