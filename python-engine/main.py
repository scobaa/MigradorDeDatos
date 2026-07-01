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
        elif command == "get_odoo_fields":
            handle_get_odoo_fields(args)
        elif command == "auth_register":
            handle_auth_register(args)
        elif command == "auth_login":
            handle_auth_login(args)
        elif command == "auth_logout":
            handle_auth_logout(args)
        elif command == "db_get_clients":
            handle_db_get_clients(args)
        elif command == "db_add_client":
            handle_db_add_client(args)
        elif command == "db_delete_client":
            handle_db_delete_client(args)
        elif command == "db_update_client_last_used":
            handle_db_update_client_last_used(args)
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
    """Devuelve un conector de lectura según la extensión del fichero."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".accdb", ".mdb"):
        from connectors.access import AccessConnector
        return AccessConnector(path)
    elif ext in (".xlsx", ".xls"):
        from connectors.excel import ExcelConnector
        return ExcelConnector(path)
    elif ext == ".csv":
        from connectors.csv import CsvConnector
        return CsvConnector(path)
    raise ValueError(
        f"Tipo de fichero no soportado todavía: {ext or '(sin extensión)'}. "
        "Por ahora solo Access (.accdb/.mdb), Excel (.xlsx/.xls) y CSV (.csv)."
    )


def _find_lines_table(conn: Any, header_table: str) -> str | None:
    tables = conn.list_tables()
    ht_lower = header_table.lower()
    
    is_csv = hasattr(conn, "path") and conn.path.lower().endswith(".csv")
    if is_csv:
        import os
        dir_path = os.path.dirname(conn.path)
        files = os.listdir(dir_path)
        if "f_fac" in ht_lower:
            for f in files:
                if "f_lfa" in f.lower() and f.lower().endswith(".csv"):
                    return os.path.join(dir_path, f)
        elif "f_frt" in ht_lower:
            for f in files:
                if "f_lfr" in f.lower() and f.lower().endswith(".csv"):
                    return os.path.join(dir_path, f)
        elif "f_ped" in ht_lower:
            for f in files:
                if "f_lpe" in f.lower() and f.lower().endswith(".csv"):
                    return os.path.join(dir_path, f)
        for f in files:
            fl = f.lower()
            if "line" in fl or "lfa" in fl or "lfr" in fl or "lpe" in fl:
                if f.lower().endswith(".csv"):
                    return os.path.join(dir_path, f)
        return None

    if "f_fac" in ht_lower:
        for t in tables:
            if "f_lfa" in t.lower():
                return t
    if "f_frt" in ht_lower:
        for t in tables:
            if "f_lfr" in t.lower():
                return t
    if "f_ped" in ht_lower:
        for t in tables:
            if "f_lpe" in t.lower():
                return t
                
    if any(k in ht_lower for k in ("invoice", "fac", "venta", "sale")):
        for t in tables:
            tl = t.lower()
            if any(k in tl for k in ("line", "lfa")):
                if "frt" not in tl and "lfr" not in tl:
                    return t
    if any(k in ht_lower for k in ("bill", "frt", "compra", "recibida", "purchase")):
        for t in tables:
            tl = t.lower()
            if any(k in tl for k in ("line", "lfr")):
                return t
    if any(k in ht_lower for k in ("order", "ped", "quote", "presupuesto")):
        for t in tables:
            tl = t.lower()
            if any(k in tl for k in ("line", "lpe")):
                return t
                
    return None


def _detect_link_col(columns: list[str], table: str) -> str | None:
    link_col = None
    ht_lower = table.lower()
    if "f_fac" in ht_lower:
        patterns = ("codlfa", "codfac", "numfac", "factura", "id")
    elif "f_frt" in ht_lower:
        patterns = ("codlfr", "codfrt", "numfrt", "factura", "id")
    elif "f_ped" in ht_lower:
        patterns = ("codlpe", "codped", "numped", "pedido", "id")
    else:
        patterns = ("codlfa", "codlfr", "codlpe", "codfac", "codfrt", "codped", "numfac", "numfrt", "numped", "factura", "pedido", "id")
        
    for pat in patterns:
        for col in columns:
            if col.lower() == pat:
                link_col = col
                break
        if link_col:
            break
            
    if not link_col:
        for col in columns:
            cl = col.lower()
            if any(k in cl for k in ("cod", "num", "fac", "frt", "id")):
                link_col = col
                break
                
    if not link_col:
        log.warning("No se pudo detectar la columna de enlace en la tabla de líneas")
    else:
        log.info("Columna de enlace detectada en líneas: '%s'", link_col)
    return link_col


def _add_row_to_grouped(row: dict[str, Any], link_col: str, grouped_lines: dict[str, list[dict[str, Any]]]) -> None:
    link_val = row.get(link_col)
    if link_val is not None:
        key = str(link_val).strip()
        if key.endswith(".0"):
            key = key[:-2]
        grouped_lines.setdefault(key, []).append(row)


def _preload_invoice_lines(conn: Any, table: str, mapping: dict[str, str]) -> dict[str, list[dict[str, Any]]] | None:
    name_col = None
    for src_col, odoo_field in mapping.items():
        if odoo_field == "name":
            name_col = src_col
            break
            
    if not name_col:
        log.warning("No se mapeó ninguna columna a 'name' (número de factura). No se pueden agrupar líneas.")
        return None

    lines_table = _find_lines_table(conn, table)
    if not lines_table:
        log.warning("No se encontró tabla de líneas correspondiente para '%s'", table)
        return None

    log.info("Cargando y agrupando líneas desde: %s", lines_table)
    grouped_lines: dict[str, list[dict[str, Any]]] = {}
    
    try:
        if os.path.isfile(lines_table):
            # Es un archivo CSV
            with _open_connector(lines_table) as lines_conn:
                sample_cols = lines_conn.get_columns("CSV")
                link_col = _detect_link_col(sample_cols, table)
                if not link_col:
                    return None
                for row in lines_conn.iter_rows("CSV"):
                    _add_row_to_grouped(row, link_col, grouped_lines)
        else:
            # Es una tabla en Excel/Access
            sample_cols = conn.get_columns(lines_table)
            link_col = _detect_link_col(sample_cols, table)
            if not link_col:
                return None
            for row in conn.iter_rows(lines_table):
                _add_row_to_grouped(row, link_col, grouped_lines)
                
        log.info("Cargadas líneas agrupadas para %d facturas", len(grouped_lines))
        return grouped_lines
    except Exception as e:
        log.exception("Error cargando líneas de factura: %s", e)
        return None


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

    args: {path, table, mapping, options?, limit?, model?}
    Devuelve {rows: [{ok, data|error}], count}.
    """
    path = args["path"]
    table = args["table"]
    mapping = args["mapping"]
    options = args.get("options", {})
    limit = int(args.get("limit", 10))
    model = args.get("model", "res.partner")

    results = []
    with _open_connector(path) as conn:
        if model == "account.move.entry":
            name_col = None
            for src_col, odoo_field in mapping.items():
                if odoo_field in ("name", "__external_id"):
                    name_col = src_col
                    break
            if not name_col:
                raise ValueError("Se debe mapear una columna a 'name' o '__external_id' para agrupar los apuntes en asientos.")
            
            all_rows = list(conn.iter_rows(table))
            grouped = {}
            for row in all_rows:
                col_val = None
                col_clean = name_col.strip().lower()
                for k, v in row.items():
                    if str(k).strip().lower() == col_clean:
                        col_val = v
                        break
                key = str(col_val if col_val is not None else "").strip()
                if key.endswith(".0"):
                    key = key[:-2]
                if key:
                    grouped.setdefault(key, []).append(row)
            
            preview_rows = []
            for key, lines in list(grouped.items())[:limit]:
                header = dict(lines[0])
                header["_lines"] = lines
                preview_rows.append(header)
                
            for row in preview_rows:
                try:
                    from transformers.journal import transform_journal_entry
                    vals = transform_journal_entry(row, mapping)
                    results.append({"ok": True, "data": vals})
                except Exception as e:  # noqa: BLE001 - reportar fila a fila
                    results.append({"ok": False, "error": str(e), "source": row})
        else:
            # Pre-cargar líneas si es factura o pedido
            grouped_lines = None
            is_flat = False
            preview_rows_iter = None
            if model.startswith("account.move") or model == "sale.order" or model == "purchase.order":
                grouped_lines = _preload_invoice_lines(conn, table, mapping)
                if not grouped_lines:
                    name_col = None
                    for src_col, odoo_field in mapping.items():
                        if odoo_field in ("name", "__external_id"):
                            name_col = src_col
                            break
                    if name_col:
                        is_flat = True
                        log.info("Formato plano: agrupando %s por %s", model, name_col)
                        all_rows = list(conn.iter_rows(table))
                        grouped = {}
                        current_key = None
                        for row in all_rows:
                            col_val = None
                            col_clean = name_col.strip().lower()
                            for k, v in row.items():
                                if str(k).strip().lower() == col_clean:
                                    col_val = v
                                    break
                            key = str(col_val if col_val is not None else "").strip()
                            if key.endswith(".0"):
                                key = key[:-2]
                                
                            if key:
                                current_key = key
                                
                            if current_key:
                                grouped.setdefault(current_key, []).append(row)
                        
                        preview_rows = []
                        for key, lines in list(grouped.items())[:limit]:
                            header = dict(lines[0])
                            header["_lines"] = lines
                            preview_rows.append(header)
                        preview_rows_iter = preview_rows

            if preview_rows_iter is None:
                preview_rows_iter = conn.iter_rows(table, limit=limit)

            for row in preview_rows_iter:
                try:
                    if model.startswith("res.partner"):
                        from transformers.partners import transform_partner
                        transform_kwargs = {
                            "default_country": options.get("default_country", "ES"),
                            "customer_rank": options.get("customer_rank", 1),
                            "supplier_rank": options.get("supplier_rank", 0),
                            "infer_company": options.get("infer_company", True),
                        }
                        vals = transform_partner(row, mapping, **transform_kwargs)
                    elif model == "product.template":
                        from transformers.products import transform_product
                        vals = transform_product(row, mapping)
                    elif model.startswith("account.move"):
                        from transformers.invoices import transform_invoice
                        row_with_lines = dict(row)
                        if not is_flat:
                            name_col = None
                            for src_col, odoo_field in mapping.items():
                                if odoo_field == "name":
                                    name_col = src_col
                                    break
                            if name_col and grouped_lines:
                                header_id = str(row.get(name_col, "")).strip()
                                if header_id.endswith(".0"):
                                    header_id = header_id[:-2]
                                row_with_lines["_lines"] = grouped_lines.get(header_id, [])
                            else:
                                row_with_lines["_lines"] = []

                        move_type = "out_invoice" if model == "account.move" else "in_invoice"
                        vals = transform_invoice(row_with_lines, mapping, move_type=move_type, format_name=options.get("format_name", True))
                    elif model == "sale.order":
                        from transformers.sales import transform_sales_order
                        row_with_lines = dict(row)
                        if not is_flat:
                            name_col = None
                            for src_col, odoo_field in mapping.items():
                                if odoo_field == "name":
                                    name_col = src_col
                                    break
                            if name_col and grouped_lines:
                                header_id = str(row.get(name_col, "")).strip()
                                if header_id.endswith(".0"):
                                    header_id = header_id[:-2]
                                row_with_lines["_lines"] = grouped_lines.get(header_id, [])
                            else:
                                row_with_lines["_lines"] = []

                        vals = transform_sales_order(row_with_lines, mapping, format_name=options.get("format_name", True))
                    elif model == "purchase.order":
                        from transformers.purchases import transform_purchase_order
                        row_with_lines = dict(row)
                        if not is_flat:
                            name_col = None
                            for src_col, odoo_field in mapping.items():
                                if odoo_field == "name":
                                    name_col = src_col
                                    break
                            if name_col and grouped_lines:
                                header_id = str(row.get(name_col, "")).strip()
                                if header_id.endswith(".0"):
                                    header_id = header_id[:-2]
                                row_with_lines["_lines"] = grouped_lines.get(header_id, [])
                            else:
                                row_with_lines["_lines"] = []

                        vals = transform_purchase_order(row_with_lines, mapping, format_name=options.get("format_name", True))
                    else:
                        raise ValueError(f"Modelo no soportado para vista previa: {model}")
                    results.append({"ok": True, "data": vals})
                except Exception as e:  # noqa: BLE001 - reportar fila a fila
                    results.append({"ok": False, "error": str(e), "source": row})

    respond("ok", data={"rows": results, "count": len(results)})


def handle_run_migration(args: dict) -> None:
    """
    Ejecuta la migración real (o dry-run). Reporta progreso por stderr.

    args: {odoo: {url, db, username, password}, path, table, mapping,
           options?, dry_run?, model?}
    """
    from migrator.odoo_client import OdooClient, OdooConfig

    odoo_args = args["odoo"]
    path = args["path"]
    table = args["table"]
    mapping = args["mapping"]
    dry_run = bool(args.get("dry_run", False))
    opts = args.get("options", {})
    model = args.get("model", "res.partner")

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

    if model.startswith("res.partner"):
        from migrator.partners import MigrationOptions as PartnerOptions, PartnerMigrator
        partner_opts = PartnerOptions(
            default_country=opts.get("default_country", "ES"),
            customer_rank=int(opts.get("customer_rank", 1)),
            supplier_rank=int(opts.get("supplier_rank", 0)),
            infer_company=opts.get("infer_company", True),
            update_existing=opts.get("update_existing", True),
            ref_prefix=opts.get("ref_prefix", ""),
            external_id_prefix=opts.get("external_id_prefix", "cli_"),
            external_id_column=opts.get("external_id_column"),
            batch_size=int(opts.get("batch_size", 100)),
        )
        migrator = PartnerMigrator(odoo, mapping, partner_opts)
    elif model == "product.template":
        from migrator.products import MigrationOptions as ProductOptions, ProductMigrator
        
        # Intentar pre-cargar nombres de familias desde la base de datos/archivo
        families = {}
        try:
            with _open_connector(path) as conn:
                tables_list = conn.list_tables()
                fam_table = None
                for t in tables_list:
                    if t.lower() in ("f_fam", "familias", "familia", "families", "category", "categories"):
                        fam_table = t
                        break
                
                if fam_table:
                    log.info("Cargando nombres de familias desde la tabla: %s", fam_table)
                    for row in conn.iter_rows(fam_table):
                        code = None
                        name = None
                        for k, v in row.items():
                            kl = k.lower()
                            if kl in ("codfam", "codigo", "code", "id", "cod"):
                                code = str(v).strip()
                            elif kl in ("desfam", "descripcion", "name", "nombre", "description", "des"):
                                name = str(v).strip()
                        
                        if code and name:
                            if code.endswith(".0"):
                                code = code[:-2]
                            families[code] = name
                    log.info("Cargadas %d familias desde el origen para traducción de IDs", len(families))
        except Exception as e:
            log.warning("No se pudieron pre-cargar las familias desde el origen: %s", e)

        product_opts = ProductOptions(
            update_existing=opts.get("update_existing", True),
            external_id_prefix=opts.get("external_id_prefix", "art_"),
            external_id_column=opts.get("external_id_column"),
            batch_size=int(opts.get("batch_size", 100)),
        )
        migrator = ProductMigrator(odoo, mapping, product_opts, families=families)
    elif model == "account.move.entry":
        from migrator.journal import MigrationOptions as JournalOptions, JournalEntryMigrator
        journal_opts = JournalOptions(
            update_existing=opts.get("update_existing", True),
            external_id_prefix=opts.get("external_id_prefix", "asi_"),
            batch_size=int(opts.get("batch_size", 50)),
            post_entries=opts.get("post_entries", True),
        )
        migrator = JournalEntryMigrator(odoo, mapping, journal_opts)
    elif model.startswith("account.move"):
        from migrator.invoices import MigrationOptions as InvoiceOptions, InvoiceMigrator
        invoice_opts = InvoiceOptions(
            update_existing=opts.get("update_existing", True),
            external_id_prefix=opts.get("external_id_prefix", "inv_"),
            batch_size=int(opts.get("batch_size", 50)),
                        format_name=opts.get("format_name", True),
        )
        move_type = "out_invoice" if model == "account.move" else "in_invoice"
        migrator = InvoiceMigrator(odoo, mapping, invoice_opts, move_type=move_type)
    elif model == "sale.order":
        from migrator.sales import MigrationOptions as SalesOptions, SalesOrderMigrator
        sales_opts = SalesOptions(
            update_existing=opts.get("update_existing", True),
            external_id_prefix=opts.get("external_id_prefix", None),  # None → el migrador usará "so_" por defecto; "" → sin prefijo
            batch_size=int(opts.get("batch_size", 50)),
            confirm_orders=opts.get("confirm_orders", True),
            force_invoiced=opts.get("force_invoiced", False),
            format_name=opts.get("format_name", True),
        )
        migrator = SalesOrderMigrator(odoo, mapping, sales_opts)
    elif model == "purchase.order":
        from migrator.purchases import MigrationOptions as PurchaseOptions, PurchaseOrderMigrator
        purchase_opts = PurchaseOptions(
            update_existing=opts.get("update_existing", True),
            external_id_prefix=opts.get("external_id_prefix", None),
            batch_size=int(opts.get("batch_size", 50)),
            confirm_orders=opts.get("confirm_orders", True),
            force_invoiced=opts.get("force_invoiced", False),
            format_name=opts.get("format_name", True),
        )
        migrator = PurchaseOrderMigrator(odoo, mapping, purchase_opts)
    elif model == "stock.quant":
        from migrator.inventory import MigrationOptions as InventoryOptions, InventoryMigrator
        inv_opts = InventoryOptions(
            update_existing=opts.get("update_existing", True),
            apply_inventory=opts.get("apply_inventory", True),
            batch_size=int(opts.get("batch_size", 100)),
        )
        migrator = InventoryMigrator(odoo, mapping, inv_opts)
    else:
        raise ValueError(f"Modelo no soportado para migración: {model}")

    with _open_connector(path) as conn:
        if model == "account.move.entry":
            name_col = None
            for src_col, odoo_field in mapping.items():
                if odoo_field in ("name", "__external_id"):
                    name_col = src_col
                    break
            if not name_col:
                raise ValueError("Se debe mapear una columna a 'name' o '__external_id' para agrupar los apuntes en asientos.")
            
            all_rows = list(conn.iter_rows(table))
            grouped = {}
            for row in all_rows:
                col_val = None
                col_clean = name_col.strip().lower()
                for k, v in row.items():
                    if str(k).strip().lower() == col_clean:
                        col_val = v
                        break
                key = str(col_val if col_val is not None else "").strip()
                if key.endswith(".0"):
                    key = key[:-2]
                if key:
                    grouped.setdefault(key, []).append(row)
            
            grouped_headers = []
            for key, lines in grouped.items():
                header = dict(lines[0])
                header["_lines"] = lines
                grouped_headers.append(header)
            
            total = len(grouped_headers)
            rows_iter = grouped_headers[:limit] if limit else grouped_headers
            rows_to_migrate = rows_iter
        else:
            total = limit if limit else conn.count_rows(table)
            
            # Pre-cargar líneas si es factura o pedido
            grouped_lines = None
            is_flat = False
            if model.startswith("account.move") or model == "sale.order" or model == "purchase.order":
                grouped_lines = _preload_invoice_lines(conn, table, mapping)
                if not grouped_lines:
                    name_col = None
                    for src_col, odoo_field in mapping.items():
                        if odoo_field in ("name", "__external_id"):
                            name_col = src_col
                            break
                    if name_col:
                        is_flat = True
                        log.info("Formato plano: agrupando %s por %s", model, name_col)
                        all_rows = list(conn.iter_rows(table))
                        grouped = {}
                        current_key = None
                        for row in all_rows:
                            col_val = None
                            col_clean = name_col.strip().lower()
                            for k, v in row.items():
                                if str(k).strip().lower() == col_clean:
                                    col_val = v
                                    break
                            key = str(col_val if col_val is not None else "").strip()
                            if key.endswith(".0"):
                                key = key[:-2]
                                
                            if key:
                                current_key = key
                                
                            if current_key:
                                grouped.setdefault(current_key, []).append(row)
                        
                        grouped_headers = []
                        for key, lines in grouped.items():
                            header = dict(lines[0])
                            header["_lines"] = lines
                            grouped_headers.append(header)
                        
                        total = len(grouped_headers)
                        rows_iter = grouped_headers[:limit] if limit else grouped_headers
                        rows_to_migrate = rows_iter

            if not is_flat:
                rows_iter = conn.iter_rows(table, limit=limit)
                if model.startswith("account.move") or model == "sale.order" or model == "purchase.order":
                    name_col = None
                    for src_col, odoo_field in mapping.items():
                        if odoo_field == "name":
                            name_col = src_col
                            break
                    
                    def inject_lines_iter():
                        for row in rows_iter:
                            row_with_lines = dict(row)
                            if name_col and grouped_lines:
                                col_val = None
                                col_clean = name_col.strip().lower()
                                for k, v in row.items():
                                    if str(k).strip().lower() == col_clean:
                                        col_val = v
                                        break
                                header_id = str(col_val if col_val is not None else "").strip()
                                if header_id.endswith(".0"):
                                    header_id = header_id[:-2]
                                row_with_lines["_lines"] = grouped_lines.get(header_id, [])
                            else:
                                row_with_lines["_lines"] = []
                            yield row_with_lines
                    
                    rows_to_migrate = inject_lines_iter()
                else:
                    rows_to_migrate = rows_iter

        stats = migrator.run(
            rows_to_migrate, total=total, dry_run=dry_run
        )

    respond("ok", data={"dry_run": dry_run, "stats": stats.as_dict()})



def handle_get_odoo_fields(args: dict) -> None:
    from migrator.odoo_client import OdooClient, OdooConfig

    odoo_args = args["odoo"]
    model = args.get("model", "res.partner")

    odoo = OdooClient(
        OdooConfig(
            url=odoo_args["url"],
            db=odoo_args["db"],
            username=odoo_args["username"],
            password=odoo_args["password"],
        )
    )
    odoo.connect()

    # Obtener metadatos de los campos usando fields_get
    fields_info = odoo.execute(model, "fields_get", [], ["string", "type", "readonly"])

    result_fields = []
    for fname, info in fields_info.items():
        # Descartar campos que sean readonly (no almacenables directamente)
        if info.get("readonly", False):
            continue

        result_fields.append({
            "name": fname,
            "label": f"{info.get('string', fname)} ({fname})",
            "required": info.get("required", False),
            "type": info.get("type", "char"),
        })

    # Ordenar por nombre del campo para comodidad
    result_fields.sort(key=lambda x: x["name"])
    respond("ok", data={"fields": result_fields})


# ─── Handlers Base de Datos / Auth ────────────────────────────

def handle_auth_register(args: dict) -> None:
    import db_manager
    try:
        token = db_manager.register_user(args["email"], args["password"])
        respond("ok", data={"token": token})
    except Exception as e:
        respond("error", error=str(e))

def handle_auth_login(args: dict) -> None:
    import db_manager
    try:
        token = db_manager.login_user(args["email"], args["password"])
        respond("ok", data={"token": token})
    except Exception as e:
        respond("error", error=str(e))

def handle_auth_logout(args: dict) -> None:
    import db_manager
    try:
        success = db_manager.logout_user(args.get("token"))
        respond("ok", data={"success": success})
    except Exception as e:
        respond("error", error=str(e))

def handle_db_get_clients(args: dict) -> None:
    import db_manager
    try:
        clients = db_manager.get_clients(args.get("token"))
        respond("ok", data={"clients": clients})
    except Exception as e:
        respond("error", error=str(e))

def handle_db_add_client(args: dict) -> None:
    import db_manager
    try:
        client = db_manager.add_client(args.get("token"), args.get("client", {}))
        respond("ok", data={"client": client})
    except Exception as e:
        respond("error", error=str(e))

def handle_db_delete_client(args: dict) -> None:
    import db_manager
    try:
        success = db_manager.delete_client(args.get("token"), args.get("client_id"))
        respond("ok", data={"success": success})
    except Exception as e:
        respond("error", error=str(e))

def handle_db_update_client_last_used(args: dict) -> None:
    import db_manager
    try:
        success = db_manager.update_client_last_used(args.get("token"), args.get("client_id"))
        respond("ok", data={"success": success})
    except Exception as e:
        respond("error", error=str(e))


if __name__ == "__main__":
    main()
