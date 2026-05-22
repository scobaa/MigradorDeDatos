"""
Punto de entrada del motor Python.

Tauri invoca este script con un comando + argumentos JSON via stdin.
La respuesta se devuelve por stdout en formato JSON estructurado.

Comandos disponibles:
    test_connection       — prueba credenciales Odoo
    analyze_source        — lee fichero y detecta tablas/columnas
    suggest_mapping       — usa IA para sugerir mapeo de columnas (Fase 2)
    preview_migration     — transforma N primeras filas sin escribir
    run_migration         — ejecuta la migración real
    list_partners         — lista partners existentes en Odoo (para verificar)

Convención de respuesta: JSON por stdout. Los logs y el progreso van por stderr
(el progreso como líneas {"event": "progress", ...}).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

# Forzar UTF-8 en stdout/stderr: la respuesta JSON y los logs deben ser UTF-8
# independientemente de la codepage de la consola de Windows (que por defecto no
# es UTF-8). Tauri lee estos flujos como UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - streams ya fijados
        pass

# Configurar logging a stderr para no contaminar stdout (que es la respuesta JSON)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("migrator")


def respond(status: str, data: Any = None, error: str | None = None) -> None:
    """Imprime respuesta JSON estructurada y termina."""
    payload = {"status": status}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str))
    sys.stdout.flush()


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        request = json.loads(raw_input)
        command = request.get("command")
        args = request.get("args", {})

        log.info("Comando recibido: %s", command)

        if command == "test_connection":
            handle_test_connection(args)
        elif command == "analyze_source":
            handle_analyze_source(args)
        elif command == "suggest_mapping":
            handle_suggest_mapping(args)
        elif command == "preview_migration":
            handle_preview_migration(args)
        elif command == "run_migration":
            handle_run_migration(args)
        else:
            respond("error", error=f"Comando desconocido: {command}")

    except json.JSONDecodeError as e:
        respond("error", error=f"JSON inválido en stdin: {e}")
    except Exception as e:
        log.exception("Error no controlado")
        respond("error", error=str(e))


# ─── Handlers de comandos ─────────────────────────────────────

def handle_test_connection(args: dict) -> None:
    from migrator.odoo_client import OdooClient, OdooConfig

    config = OdooConfig(
        url=args["url"],
        db=args["db"],
        username=args["username"],
        password=args["password"],
    )
    client = OdooClient(config)
    ok, message = client.test_connection()
    respond("ok" if ok else "error", data={"connected": ok, "message": message})


def _open_connector(path: str):
    """Devuelve un connector de lectura según la extensión del fichero."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".accdb", ".mdb"):
        from connectors.access import AccessConnector

        return AccessConnector(path)
    raise ValueError(
        f"Tipo de fichero no soportado todavía: {ext or '(sin extensión)'}. "
        "Por ahora solo Access (.accdb/.mdb)."
    )


def handle_analyze_source(args: dict) -> None:
    """
    Lee el fichero fuente y devuelve metadatos.

    args: {path, table?}
      - sin `table`: devuelve la lista de tablas disponibles.
      - con `table`: devuelve {columns, row_count, sample_rows}.
    """
    path = args["path"]
    table = args.get("table")

    with _open_connector(path) as conn:
        if not table:
            respond("ok", data={"tables": conn.list_tables()})
            return
        respond("ok", data=conn.analyze(table))


def handle_suggest_mapping(args: dict) -> None:
    """
    Llama a Claude para detectar el ERP y sugerir mapeo de columnas.

    args: {columns: [...], model?: "res.partner", api_key?: "sk-ant-..."}
    La api_key también se puede pasar como variable de entorno ANTHROPIC_API_KEY.
    """
    from migrator.ai_mapper import suggest_mapping

    columns = args["columns"]
    model = args.get("model", "res.partner")
    api_key = args.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")

    result = suggest_mapping(columns=columns, target_model=model, api_key=api_key)
    respond("ok", data=result)


def handle_preview_migration(args: dict) -> None:
    """
    Transforma las primeras N filas según el mapeo, sin escribir en Odoo.

    args: {path, table, mapping, options?, limit?}
    Devuelve {rows: [{ok, data|error}], count}.
    """
    from transformers.partners import transform_partner

    path = args["path"]
    table = args["table"]
    mapping = args["mapping"]
    options = args.get("options", {})
    limit = int(args.get("limit", 10))

    transform_kwargs = {
        "default_country": options.get("default_country", "ES"),
        "customer_rank": options.get("customer_rank", 1),
        "supplier_rank": options.get("supplier_rank", 0),
        "infer_company": options.get("infer_company", True),
    }

    results = []
    with _open_connector(path) as conn:
        for row in conn.iter_rows(table, limit=limit):
            try:
                vals = transform_partner(row, mapping, **transform_kwargs)
                results.append({"ok": True, "data": vals})
            except Exception as e:  # noqa: BLE001 - reportar fila a fila
                results.append({"ok": False, "error": str(e), "source": row})

    respond("ok", data={"rows": results, "count": len(results)})


def handle_run_migration(args: dict) -> None:
    """
    Ejecuta la migración real (o dry-run). Reporta progreso por stderr.

    args: {odoo: {url, db, username, password}, path, table, mapping,
           options?, dry_run?}
    """
    from migrator.odoo_client import OdooClient, OdooConfig
    from migrator.partners import MigrationOptions, PartnerMigrator

    odoo_args = args["odoo"]
    path = args["path"]
    table = args["table"]
    mapping = args["mapping"]
    dry_run = bool(args.get("dry_run", False))
    opts = args.get("options", {})

    options = MigrationOptions(
        default_country=opts.get("default_country", "ES"),
        customer_rank=opts.get("customer_rank", 1),
        supplier_rank=opts.get("supplier_rank", 0),
        infer_company=opts.get("infer_company", True),
        update_existing=opts.get("update_existing", True),
        ref_prefix=opts.get("ref_prefix", ""),
    )

    limit: int | None = int(args["limit"]) if args.get("limit") else None

    odoo = OdooClient(
        OdooConfig(
            url=odoo_args["url"],
            db=odoo_args["db"],
            username=odoo_args["username"],
            password=odoo_args["password"],
        )
    )
    odoo.connect()

    migrator = PartnerMigrator(odoo, mapping, options)
    with _open_connector(path) as conn:
        total = limit if limit else conn.count_rows(table)
        stats = migrator.run(
            conn.iter_rows(table, limit=limit), total=total, dry_run=dry_run
        )

    respond("ok", data={"dry_run": dry_run, "stats": stats.as_dict()})


if __name__ == "__main__":
    main()
