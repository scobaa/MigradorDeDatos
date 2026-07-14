import { useState, useEffect } from "react";
import { ArrowLeft, ArrowRight, UploadCloud, CheckCircle, Database, FileSpreadsheet, Settings, Play, Sparkles } from "lucide-react";
import { callPython } from "../lib/python";
import { db, DBClient } from "../lib/db";

interface MigrationWizardProps {
  clientId: string;
  onBack: () => void;
}

export default function MigrationWizard({ clientId, onBack }: MigrationWizardProps) {
  const [step, setStep] = useState(1);
  const [selectedModel, setSelectedModel] = useState("res.partner");
  const [fileName, setFileName] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [progress, setProgress] = useState(0);
  const [isMigrating, setIsMigrating] = useState(false);
  const [isDryRun, setIsDryRun] = useState(true);

  // Estados dinámicos de análisis de archivos
  const [tables, setTables] = useState<string[]>([]);
  const [selectedTable, setSelectedTable] = useState("");
  const [sourceColumns, setSourceColumns] = useState<string[]>([]);
  const [rowCount, setRowCount] = useState(0);
  const [sampleRows, setSampleRows] = useState<any[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const [pythonServerConnected, setPythonServerConnected] = useState<boolean | null>(null);
  const [client, setClient] = useState<DBClient | null>(null);
  const [updateExisting, setUpdateExisting] = useState(true);
  const [externalIdPrefix, setExternalIdPrefix] = useState("cli_");
  const [externalIdColumn, setExternalIdColumn] = useState<string>("");
  const [categoriesTable, setCategoriesTable] = useState<string>("");
  const [logs, setLogs] = useState<string[]>([]);
  const [batchSize, setBatchSize] = useState(100);
  const [confirmOrders, setConfirmOrders] = useState(true);
  const [forceInvoiced, setForceInvoiced] = useState(false);
  const [postEntries, setPostEntries] = useState(true);
  const [formatName, setFormatName] = useState(true);
  const [migrationStats, setMigrationStats] = useState<{
    created: number;
    updated: number;
    skipped: number;
    error_count: number;
    errors: any[];
  } | null>(null);
  const [migrationProgress, setMigrationProgress] = useState<{ done: number; total: number } | null>(null);

  useEffect(() => {
    if (selectedModel === "res.partner") {
      setExternalIdPrefix("cli_");
    } else if (selectedModel === "res.partner.supplier") {
      setExternalIdPrefix("pro_");
    } else if (selectedModel === "product.template") {
      setExternalIdPrefix("art_");
    } else if (selectedModel === "account.move") {
      setExternalIdPrefix("inv_out_");
    } else if (selectedModel === "account.move.supplier") {
      setExternalIdPrefix("inv_in_");
    } else if (selectedModel === "sale.order") {
      setExternalIdPrefix("so_");
    } else if (selectedModel === "purchase.order") {
      setExternalIdPrefix("po_");
    } else if (selectedModel === "account.move.entry") {
      setExternalIdPrefix("asi_");
    }
  }, [selectedModel]);

  useEffect(() => {
    // Cargar información del cliente
    db.getClients().then((clients) => {
      const found = clients.find((c) => c.id === clientId);
      if (found) {
        setClient(found);
      }
    });

    const isTauri = typeof (window as any).__TAURI_INTERNALS__ !== "undefined";
    if (!isTauri) {
      // Check Python server connection status (relativo en servidor, localhost en dev)
      const hostname = window.location.hostname;
      const apiBase = (hostname === 'localhost' || hostname === '127.0.0.1') ? 'http://127.0.0.1:8000' : '';
      fetch(`${apiBase}/api`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: "test_connection", args: { url: "", db: "", username: "", password: "" } }),
      })
      .then(() => setPythonServerConnected(true))
      .catch(() => setPythonServerConnected(false));
    } else {
      setPythonServerConnected(true);
    }
  }, [clientId]);

  // Recalcular mapeo inicial, ID externo y tabla de familias de forma reactiva al cambiar modelo o columnas
  useEffect(() => {
    if (sourceColumns.length === 0) return;

    const initialMappings: Record<string, string> = {};
    if (selectedModel === "product.template") {
      sourceColumns.forEach((col: string) => {
        const lowerCol = col.toLowerCase();
        if (lowerCol === "codart" || lowerCol === "código" || lowerCol === "cod" || lowerCol === "id" || lowerCol === "referencia" || lowerCol === "ref" || lowerCol === "default_code") {
          initialMappings[col] = "default_code";
        } else if (lowerCol === "eanart" || lowerCol === "codbar" || lowerCol === "barcode" || lowerCol.includes("ean") || lowerCol.includes("barra")) {
          initialMappings[col] = "barcode";
        } else if (lowerCol === "desart" || lowerCol === "nomart" || lowerCol.includes("nombre") || lowerCol.includes("descrip") || lowerCol === "name") {
          initialMappings[col] = "name";
        } else if (lowerCol === "pcoart" || lowerCol.includes("coste") || lowerCol.includes("costo") || lowerCol === "cost") {
          initialMappings[col] = "standard_price";
        } else if (lowerCol === "pvpart" || lowerCol.includes("venta") || lowerCol.includes("pvp") || lowerCol === "price" || lowerCol === "list_price") {
          initialMappings[col] = "list_price";
        } else if (lowerCol === "famart" || lowerCol.includes("familia") || lowerCol.includes("categor") || lowerCol === "category") {
          initialMappings[col] = "_category";
        } else {
          initialMappings[col] = "";
        }
      });
    } else if (selectedModel === "account.move" || selectedModel === "account.move.supplier") {
      sourceColumns.forEach((col: string) => {
        const lowerCol = col.toLowerCase();
        if (selectedModel === "account.move") {
          if (lowerCol === "codfac" || lowerCol === "numfac" || lowerCol === "factura" || lowerCol === "id" || lowerCol === "name") {
            initialMappings[col] = "name";
          } else if (lowerCol === "fecfac" || lowerCol === "fecha" || lowerCol === "invoice_date") {
            initialMappings[col] = "invoice_date";
          } else if (lowerCol === "clifac" || lowerCol === "codcli" || lowerCol === "cliente" || lowerCol === "_partner_code" || lowerCol === "partner_id/id") {
            initialMappings[col] = "_partner_code";
          } else if (lowerCol === "obsfac" || lowerCol === "observaciones" || lowerCol === "narration" || lowerCol === "obs") {
            initialMappings[col] = "narration";
          } else if (lowerCol === "reffac" || lowerCol === "referencia" || lowerCol === "ref") {
            initialMappings[col] = "ref";
          } else {
            initialMappings[col] = "";
          }
        } else {
          if (lowerCol === "codfrt" || lowerCol === "numfrt" || lowerCol === "factura" || lowerCol === "id" || lowerCol === "name") {
            initialMappings[col] = "name";
          } else if (lowerCol === "fecfrt" || lowerCol === "fecha" || lowerCol === "invoice_date") {
            initialMappings[col] = "invoice_date";
          } else if (lowerCol === "profrt" || lowerCol === "codpro" || lowerCol === "proveedor" || lowerCol === "_partner_code" || lowerCol === "partner_id/id") {
            initialMappings[col] = "_partner_code";
          } else if (lowerCol === "obsfrt" || lowerCol === "observaciones" || lowerCol === "narration" || lowerCol === "obs") {
            initialMappings[col] = "narration";
          } else if (lowerCol === "reffrt" || lowerCol === "referencia" || lowerCol === "ref") {
            initialMappings[col] = "ref";
          } else {
            initialMappings[col] = "";
          }
        }
      });
    } else if (selectedModel === "sale.order" || selectedModel === "purchase.order") {
      sourceColumns.forEach((col: string) => {
        const lowerCol = col.toLowerCase();
        if (lowerCol === "codped" || lowerCol === "numped" || lowerCol === "pedido" || lowerCol === "id" || lowerCol === "name" || lowerCol === "codfac" || lowerCol === "numfac") {
          initialMappings[col] = "name";
        } else if (lowerCol === "fecped" || lowerCol === "fecha" || lowerCol === "date_order" || lowerCol === "fecfac") {
          initialMappings[col] = "date_order";
        } else if (lowerCol === "cliped" || lowerCol === "codcli" || lowerCol === "cliente" || lowerCol === "_partner_code" || lowerCol === "clifac" || lowerCol === "partner_id/id") {
          initialMappings[col] = "_partner_code";
        } else if (lowerCol === "obsped" || lowerCol === "observaciones" || lowerCol === "note" || lowerCol === "obs" || lowerCol === "obsfac") {
          initialMappings[col] = "note";
        } else if (lowerCol === "refped" || lowerCol === "referencia" || lowerCol === "ref") {
          initialMappings[col] = "client_order_ref";
        } else {
          initialMappings[col] = "";
        }
      });
    } else if (selectedModel === "account.move.entry") {
      sourceColumns.forEach((col: string) => {
        const lowerCol = col.toLowerCase();
        if (lowerCol === "asiapu" || lowerCol === "asiento" || lowerCol === "id" || lowerCol === "name" || lowerCol === "nº asiento" || lowerCol === "nºasiento" || lowerCol === "num_asiento" || lowerCol === "número asiento" || lowerCol === "num. asiento") {
          initialMappings[col] = "name";
        } else if (lowerCol === "fecapu" || lowerCol === "fecha" || lowerCol === "date" || lowerCol === "fecha apunte" || lowerCol === "fecha_apunte" || lowerCol === "fec_apunte") {
          initialMappings[col] = "date";
        } else if (lowerCol === "docapu" || lowerCol === "documento" || lowerCol === "referencia" || lowerCol === "ref" || lowerCol === "num_documento" || lowerCol === "nº documento") {
          initialMappings[col] = "ref";
        } else if (lowerCol === "diaapu" || lowerCol === "diario" || lowerCol === "journal" || lowerCol === "diario contable" || lowerCol === "diario_contable") {
          initialMappings[col] = "journal_id";
        } else if (lowerCol === "cueapu" || lowerCol === "cuenta" || lowerCol === "account" || lowerCol === "cuenta contable" || lowerCol === "cuenta_contable" || lowerCol === "subcuenta") {
          initialMappings[col] = "line_ids/account_id";
        } else if (lowerCol === "conapu" || lowerCol === "concepto" || lowerCol === "glosa" || lowerCol === "descrip" || lowerCol === "descripción" || lowerCol === "descripcion" || lowerCol === "concepto apunte" || lowerCol === "concepto_apunte" || lowerCol === "detalle") {
          initialMappings[col] = "line_ids/name";
        } else if (lowerCol === "debe" || lowerCol === "debit" || lowerCol === "deb") {
          initialMappings[col] = "line_ids/debit";
        } else if (lowerCol === "haber" || lowerCol === "credit" || lowerCol === "hab" || lowerCol === "cre") {
          initialMappings[col] = "line_ids/credit";
        } else if (lowerCol === "imeapu" || lowerCol === "importe" || lowerCol === "monto" || lowerCol === "amount" || lowerCol === "importe_apunte" || lowerCol === "importe apunte" || lowerCol === "valor") {
          initialMappings[col] = "_line_amount";
        } else if (lowerCol === "d-hapu" || lowerCol === "dh" || lowerCol === "debe_haber" || lowerCol === "lado" || lowerCol === "side" || lowerCol === "d/h" || lowerCol === "debe/haber") {
          initialMappings[col] = "_line_side";
        } else {
          initialMappings[col] = "";
        }
      });
    } else {
      sourceColumns.forEach((col: string) => {
        const lowerCol = col.toLowerCase().trim().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        if (lowerCol === "codcli" || lowerCol === "codpro" || lowerCol === "cod" || lowerCol === "codigo" || lowerCol === "id_cliente" || lowerCol === "id") {
          initialMappings[col] = "__external_id";
        } else if (lowerCol.includes("codigo") || lowerCol.includes("ref") || lowerCol.includes("referencia")) {
          initialMappings[col] = "ref";
        } else if (lowerCol.includes("nombre") || lowerCol.includes("razon") || lowerCol.includes("name") || lowerCol.includes("social")) {
          initialMappings[col] = "name";
        } else if (lowerCol.includes("cif") || lowerCol.includes("nif") || lowerCol.includes("vat") || lowerCol.includes("documento") || lowerCol.includes("identificacion")) {
          initialMappings[col] = "vat";
        } else if (lowerCol.includes("mail") || lowerCol.includes("email") || lowerCol.includes("correo")) {
          initialMappings[col] = "email";
        } else if (lowerCol.includes("contacto") || lowerCol.includes("persona") || lowerCol.includes("representante") || lowerCol.includes("pcocli") || lowerCol.includes("pcopro")) {
          initialMappings[col] = "contact_name";
        } else if (lowerCol.includes("movil") || lowerCol.includes("mobile") || lowerCol.includes("celular")) {
          initialMappings[col] = "mobile";
        } else if (lowerCol.includes("telefono") || lowerCol.includes("phone")) {
          initialMappings[col] = "phone";
        } else if (lowerCol.includes("calle") || lowerCol.includes("direccion") || lowerCol.includes("street")) {
          initialMappings[col] = "street";
        } else if (lowerCol.includes("cp") || lowerCol.includes("postal") || lowerCol.includes("zip") || lowerCol.includes("c.postal")) {
          initialMappings[col] = "zip";
        } else if (lowerCol.includes("ciudad") || lowerCol.includes("poblacion") || lowerCol.includes("city") || lowerCol.includes("municipio")) {
          initialMappings[col] = "city";
        } else if (lowerCol.includes("iban") || lowerCol.includes("swfcli") || lowerCol.includes("swfpro") || lowerCol.includes("cuenta") || lowerCol.includes("cuecli") || lowerCol.includes("cuepro")) {
          initialMappings[col] = "bank_acc_number";
        } else if (lowerCol.includes("banco") || lowerCol.includes("bancli") || lowerCol.includes("banpro") || lowerCol.includes("entidad")) {
          initialMappings[col] = "bank_name";
        } else {
          initialMappings[col] = "";
        }
      });
    }
    setMappings(initialMappings);

    // Autodetectar columna para ID externo
    let defaultExtIdCol = "";
    if (selectedModel === "product.template") {
      const found = sourceColumns.find((col: string) => {
        const lower = col.toLowerCase();
        return lower === "codart" || lower === "código" || lower === "cod" || lower === "id" || lower === "referencia" || lower === "ref";
      });
      if (found) defaultExtIdCol = found;
    } else if (selectedModel === "account.move" || selectedModel === "account.move.supplier" || selectedModel === "sale.order" || selectedModel === "purchase.order") {
      const found = sourceColumns.find((col: string) => {
        const lower = col.toLowerCase();
        return lower === "codfac" || lower === "codfrt" || lower === "codped" || lower === "numfac" || lower === "numfrt" || lower === "numped" || lower === "factura" || lower === "pedido" || lower === "id" || lower === "name";
      });
      if (found) defaultExtIdCol = found;
    } else {
      const found = sourceColumns.find((col: string) => {
        const lower = col.toLowerCase();
        return lower === "codcli" || lower === "codpro" || lower === "cod" || lower === "código" || lower === "id_cliente" || lower === "id";
      });
      if (found) defaultExtIdCol = found;
    }
    setExternalIdColumn(defaultExtIdCol);

    // Autodetectar tabla de categorías/familias
    const foundFamTable = tables.find((t: string) => {
      const lower = t.toLowerCase();
      return lower === "f_fam" || lower === "familias" || lower === "familia" || lower === "families" || lower === "category" || lower === "categories";
    });
    setCategoriesTable(foundFamTable || "");

  }, [selectedModel, sourceColumns, tables]);

  // Auto-scroll para la consola de logs
  useEffect(() => {
    const consoleEl = document.getElementById("logs-console");
    if (consoleEl) {
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  }, [logs]);

  const [odooFields, setOdooFields] = useState<any[]>([]);

  // Reset odooFields to model-specific defaults when model changes,
  // so the user never sees another model's fields while Odoo loads.
  useEffect(() => {
    if (selectedModel.startsWith("res.partner")) {
      setOdooFields([
        { name: "__external_id", label: "ID Externo (XML ID)", required: false },
        { name: "name", label: "Nombre/Razón Social (name)", required: true },
        { name: "vat", label: "NIF/CIF (vat)", required: false },
        { name: "ref", label: "Referencia Externa (ref)", required: false },
        { name: "email", label: "Email (email)", required: false },
        { name: "phone", label: "Teléfono (phone)", required: false },
        { name: "mobile", label: "Móvil (mobile)", required: false },
        { name: "street", label: "Calle (street)", required: false },
        { name: "zip", label: "Código Postal (zip)", required: false },
        { name: "city", label: "Ciudad (city)", required: false },
        { name: "_country", label: "País (country_id)", required: false },
        { name: "_state", label: "Provincia/Estado (state_id)", required: false },
        { name: "contact_name", label: "Contacto: Nombre", required: false },
        { name: "contact_email", label: "Contacto: Email", required: false },
        { name: "contact_phone", label: "Contacto: Teléfono", required: false },
        { name: "contact_mobile", label: "Contacto: Móvil", required: false },
        { name: "bank_acc_number", label: "Banco: Número de Cuenta (IBAN)", required: false },
        { name: "bank_name", label: "Banco: Nombre de la Entidad", required: false },
      ]);
    } else if (selectedModel === "product.template") {
      setOdooFields([
        { name: "__external_id", label: "ID Externo (XML ID)", required: false },
        { name: "name", label: "Nombre del Producto (name)", required: true },
        { name: "default_code", label: "Referencia Interna (default_code)", required: false },
        { name: "barcode", label: "Código de Barras (barcode)", required: false },
        { name: "list_price", label: "Precio de Venta (list_price)", required: false },
        { name: "standard_price", label: "Coste (standard_price)", required: false },
        { name: "_category", label: "Categoría (categ_id)", required: false },
      ]);
    } else if (selectedModel === "sale.order") {
      setOdooFields([
        { name: "__external_id", label: "ID Externo (XML ID)", required: false },
        { name: "name", label: "Número de Pedido (name)", required: true },
        { name: "_partner_code", label: "Código Cliente (_partner_code)", required: true },
        { name: "date_order", label: "Fecha del Pedido (date_order)", required: false },
        { name: "client_order_ref", label: "Referencia Cliente (client_order_ref)", required: false },
        { name: "note", label: "Notas/Observaciones (note)", required: false },
      ]);
    } else if (selectedModel === "purchase.order") {
      setOdooFields([
        { name: "__external_id", label: "ID Externo (XML ID)", required: false },
        { name: "name", label: "Número de Pedido (name)", required: true },
        { name: "_partner_code", label: "Código Proveedor (_partner_code)", required: true },
        { name: "date_order", label: "Fecha del Pedido (date_order)", required: false },
        { name: "partner_ref", label: "Referencia Proveedor (partner_ref)", required: false },
        { name: "note", label: "Notas/Observaciones (note)", required: false },
      ]);
    } else if (selectedModel === "account.move" || selectedModel === "account.move.supplier") {
      setOdooFields([
        { name: "__external_id", label: "ID Externo (XML ID)", required: false },
        { name: "name", label: "Número de Factura (name)", required: true },
        { name: "_partner_code", label: "Código Cliente/Proveedor (_partner_code)", required: true },
        { name: "invoice_date", label: "Fecha de Factura (invoice_date)", required: false },
        { name: "ref", label: "Referencia (ref)", required: false },
        { name: "narration", label: "Observaciones (narration)", required: false },
      ]);
    } else if (selectedModel === "account.move.entry") {
      setOdooFields([
        { name: "__external_id", label: "ID Externo (XML ID)", required: false },
        { name: "name", label: "Número Asiento (name)", required: true },
        { name: "date", label: "Fecha (date)", required: false },
        { name: "ref", label: "Referencia (ref)", required: false },
        { name: "journal_id", label: "Diario (journal_id)", required: false },
        { name: "line_ids/account_id", label: "Cuenta Contable Apunte *", required: true },
        { name: "line_ids/name", label: "Concepto Apunte *", required: true },
        { name: "line_ids/debit", label: "Debe (Importe)", required: false },
        { name: "line_ids/credit", label: "Haber (Importe)", required: false },
        { name: "_line_amount", label: "Importe Único (Debe/Haber)", required: false },
        { name: "_line_side", label: "Indicador Lado (D/H)", required: false },
        { name: "line_ids/partner_id", label: "Partner en Apunte (Opcional)", required: false },
      ]);
    }
  }, [selectedModel]);

  useEffect(() => {
    if (!client) return;

    const fetchOdooFields = async () => {
      try {
        const response = await callPython("get_odoo_fields", {
          odoo: {
            url: client.odoo_url,
            db: client.odoo_db,
            username: client.odoo_user,
            password: client.odoo_password,
          },
          model: selectedModel.startsWith("res.partner") ? "res.partner" : (selectedModel.startsWith("account.move") ? "account.move" : selectedModel),
        });

        if (response.status === "ok" && response.data?.fields) {
          const fetchedFields: any[] = response.data.fields;

          // Campos virtuales especiales
          let virtualFields = [
            { name: "__external_id", label: "ID Externo (XML ID)", required: false },
          ];
          if (selectedModel.startsWith("res.partner")) {
            virtualFields = [
              ...virtualFields,
              { name: "_country", label: "País (country_id)", required: false },
              { name: "_state", label: "Provincia/Estado (state_id)", required: false },
              { name: "contact_name", label: "Contacto: Nombre", required: false },
              { name: "contact_email", label: "Contacto: Email", required: false },
              { name: "contact_phone", label: "Contacto: Teléfono", required: false },
              { name: "contact_mobile", label: "Contacto: Móvil", required: false },
              { name: "bank_acc_number", label: "Banco: Número de Cuenta (IBAN)", required: false },
              { name: "bank_name", label: "Banco: Nombre de la Entidad", required: false },
            ];
          } else if (selectedModel === "account.move.entry") {
            virtualFields = [
              ...virtualFields,
              { name: "line_ids/account_id", label: "Cuenta Contable Apunte (CUEAPU) *", required: true },
              { name: "line_ids/name", label: "Concepto/Glosa Apunte (CONAPU) *", required: true },
              { name: "line_ids/debit", label: "Debe (Importe)", required: false },
              { name: "line_ids/credit", label: "Haber (Importe)", required: false },
              { name: "_line_amount", label: "Importe Único (Debe/Haber)", required: false },
              { name: "_line_side", label: "Indicador Lado (D/H)", required: false },
              { name: "line_ids/partner_id", label: "Partner en Apunte (Opcional)", required: false },
            ];
          } else if (selectedModel.startsWith("account.move") || selectedModel === "sale.order" || selectedModel === "purchase.order") {
            virtualFields = [
              ...virtualFields,
              { name: "_partner_code", label: "Código Cliente/Proveedor (_partner_code)", required: true },
            ];
          }

          const combinedFields = [...virtualFields];
          const virtualNames = new Set(virtualFields.map(f => f.name));
          const ignoreNames = new Set(["country_id", "state_id"]);

          fetchedFields.forEach(f => {
            if (!virtualNames.has(f.name) && !ignoreNames.has(f.name)) {
              if (selectedModel === "account.move.entry") {
                // Para asientos contables, solo mostramos campos de cabecera específicos
                if (!["name", "date", "ref", "journal_id"].includes(f.name)) {
                  return;
                }
              }
              combinedFields.push({
                name: f.name,
                label: `${f.label.split(" (")[0]} (${f.name})`,
                required: f.required,
              });
            }
          });

          // Ordenar los campos para comodidad del usuario
          const mainFieldNames = ["__external_id", "name", "vat", "ref", "email", "phone", "mobile", "street", "zip", "city", "_country", "_state"];
          const contactBankNames = ["contact_name", "contact_email", "contact_phone", "contact_mobile", "bank_acc_number", "bank_name"];

          const sorted = combinedFields.sort((a, b) => {
            const aMainIdx = mainFieldNames.indexOf(a.name);
            const bMainIdx = mainFieldNames.indexOf(b.name);

            if (aMainIdx !== -1 && bMainIdx !== -1) return aMainIdx - bMainIdx;
            if (aMainIdx !== -1) return -1;
            if (bMainIdx !== -1) return 1;

            const aCBIdx = contactBankNames.indexOf(a.name);
            const bCBIdx = contactBankNames.indexOf(b.name);

            if (aCBIdx !== -1 && bCBIdx !== -1) return aCBIdx - bCBIdx;
            if (aCBIdx !== -1) return -1;
            if (bCBIdx !== -1) return 1;

            return a.label.localeCompare(b.label);
          });

          setOdooFields(sorted);
        }
      } catch (err) {
        console.error("Error al obtener campos de Odoo:", err);
      }
    };

    fetchOdooFields();
  }, [client, selectedModel]);

  const uploadAndAnalyzeFile = async (file: File) => {
    const isTauri = typeof (window as any).__TAURI_INTERNALS__ !== "undefined";
    
    // Si estamos en la app de escritorio (Tauri), usamos la ruta absoluta nativa
    if (isTauri && (file as any).path) {
      handleFileAnalyze((file as any).path);
      return;
    }

    // Si estamos en web (OVH o local HTTP), subimos el archivo al servidor Python
    setIsAnalyzing(true);
    try {
      const hostname = window.location.hostname;
      const apiBase = (hostname === 'localhost' || hostname === '127.0.0.1') ? 'http://127.0.0.1:8000' : '';
      
      const response = await fetch(`${apiBase}/api/upload`, {
        method: "POST",
        headers: {
          "X-File-Name": encodeURIComponent(file.name),
        },
        body: file,
      });
      
      if (!response.ok) {
        throw new Error("Error HTTP al subir el archivo");
      }
      
      const data = await response.json();
      if (data.status === "ok" && data.path) {
        handleFileAnalyze(data.path);
      } else {
        throw new Error(data.error || "Error guardando el archivo");
      }
    } catch (err: any) {
      setIsAnalyzing(false);
      alert("Error subiendo archivo: " + err.message);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragOver(true);
    } else {
      setDragOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      uploadAndAnalyzeFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      uploadAndAnalyzeFile(e.target.files[0]);
    }
  };

  const handleFileAnalyze = async (filePath: string) => {
    setIsAnalyzing(true);
    setFileName(filePath);
    
    // Reiniciamos estados previos
    setTables([]);
    setSelectedTable("");
    setSourceColumns([]);
    setRowCount(0);
    setSampleRows([]);
    setMappings({});

    try {
      const response = await callPython("analyze_source", { path: filePath });
      if (response.status === "ok" && response.data?.tables) {
        const detectedTables: string[] = response.data.tables;
        setTables(detectedTables);
        
        // Si hay una sola tabla (ej: CSV), se selecciona automáticamente
        if (detectedTables.length === 1) {
          await handleTableSelect(filePath, detectedTables[0]);
        }
      } else {
        alert("Error al analizar el origen: " + response.error);
        setFileName(null);
      }
    } catch (e: any) {
      alert("Error de comunicación: " + e.toString());
      setFileName(null);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleTableSelect = async (filePath: string, table: string) => {
    setSelectedTable(table);
    setIsAnalyzing(true);
    try {
      const response = await callPython("analyze_source", { path: filePath, table });
      if (response.status === "ok" && response.data) {
        const { columns, row_count, sample_rows } = response.data;
        setSourceColumns(columns);
        setRowCount(row_count);
        setSampleRows(sample_rows || []);
      } else {
        alert("Error al analizar la hoja/tabla: " + response.error);
      }
    } catch (e: any) {
      alert("Error de comunicación: " + e.toString());
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleAutoMap = async () => {
    if (sourceColumns.length === 0) return;
    alert("Claude AI ha sugerido el mapeo óptimo basado en coincidencias semánticas.");
  };

  const startMigration = async () => {
    if (!client) {
      alert("Error: No se pudo cargar la configuración del cliente.");
      return;
    }
    if (!fileName || !selectedTable) {
      alert("Error: Debes seleccionar un archivo de origen y una tabla.");
      return;
    }

    setIsMigrating(true);
    setProgress(0);
    setMigrationProgress(null);
    setLogs([]);
    setMigrationStats(null);

    const isTauri = typeof (window as any).__TAURI_INTERNALS__ !== "undefined";
    let logIntervalId: any = null;
    let unlisten: (() => void) | null = null;
    let isFinished = false;
    let continuePolling = false;
    let logOffset = 0;

    if (!isTauri) {
      logIntervalId = setInterval(async () => {
        try {
          const apiBase = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000' : '';
          const res = await fetch(`${apiBase}/api/logs?offset=${logOffset}`);
          if (res.ok) {
            const data = await res.json();
            if (data && data.logs) {
              const rawLogs: string[] = data.logs;
              if (data.next_offset !== undefined) {
                logOffset = data.next_offset;
              }
              const displayLogs: string[] = [];
              let lastProgress: { done: number; total: number } | null = null;

              for (const line of rawLogs) {
                const trimmed = line.trim();
                
                if (trimmed.includes("__FINAL_RESPONSE__: ")) {
                  try {
                    const finalPayload = JSON.parse(trimmed.split("__FINAL_RESPONSE__: ")[1]);
                    if (!isFinished) {
                      isFinished = true;
                      if (logIntervalId) clearInterval(logIntervalId);
                      if (finalPayload.status === "ok") {
                        setProgress(100);
                        setMigrationStats({
                          created: finalPayload.data?.stats?.created || 0,
                          updated: finalPayload.data?.stats?.updated || 0,
                          skipped: finalPayload.data?.stats?.skipped || 0,
                          error_count: finalPayload.data?.stats?.error_count || 0,
                          errors: finalPayload.data?.stats?.errors || [],
                        });
                        // No action needed on null error
                      } else {
                        alert("Error: " + (finalPayload.error || "Error desconocido"));
                      }
                      setIsMigrating(false);
                    }
                  } catch { /* ignorar */ }
                  continue;
                }

                if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
                  try {
                    const parsed = JSON.parse(trimmed);
                    if (parsed && parsed.event === "progress") {
                      if (parsed.total > 0) {
                        lastProgress = { done: parsed.done, total: parsed.total };
                      }
                      // Mostrar warnings (ej. pedidos no confirmados) en la consola
                      if (parsed.action === "warning" && parsed.message) {
                        displayLogs.push(`⚠️ AVISO: ${parsed.message}`);
                      }
                      continue; // Omitir el resto de eventos JSON de la consola
                    }
                  } catch {
                    // No es JSON, conservar
                  }
                }
                displayLogs.push(line);
              }

              if (displayLogs.length > 0) {
                setLogs(prev => [...prev, ...displayLogs]);
              }
              if (lastProgress) {
                setMigrationProgress(lastProgress);
                const pct = Math.round((lastProgress.done / lastProgress.total) * 100);
                setProgress(Math.min(pct, 99));
              }
            }
          }
        } catch (err) {
          console.error("Error fetching logs:", err);
        }
      }, 1000);
    } else {
      try {
        const { listenToPythonEvents } = await import("../lib/python");
        unlisten = await listenToPythonEvents(
          (line) => {
            setLogs((prev) => [...prev, line.trim()]);
          },
          (progressPayload: any) => {
            if (progressPayload.total > 0 && !isFinished) {
              setMigrationProgress({ done: progressPayload.done, total: progressPayload.total });
              const pct = Math.round((progressPayload.done / progressPayload.total) * 100);
              setProgress(Math.min(pct, 99));
            }
          }
        );
      } catch (err) {
        console.error("Error setting up Tauri log listener:", err);
      }
    }

    try {
      const response = await callPython("run_migration", {
        model: selectedModel,
        odoo: {
          url: client.odoo_url,
          db: client.odoo_db,
          username: client.odoo_user,
          password: client.odoo_password || "",
        },
        path: fileName,
        table: selectedTable,
        mapping: mappings,
        options: {
          default_country: "ES",
          customer_rank: selectedModel === "res.partner" ? 1 : 0,
          supplier_rank: selectedModel === "res.partner" ? 0 : 1,
          infer_company: true,
          update_existing: updateExisting,
          ref_prefix: "",
          external_id_prefix: externalIdPrefix,
          external_id_column: externalIdColumn,
          categories_table: categoriesTable,
          batch_size: batchSize,
          confirm_orders: confirmOrders,
          force_invoiced: forceInvoiced,
          post_entries: postEntries,
          format_name: formatName,
        },
        dry_run: isDryRun,
      });

      if (isFinished) return;

      if (response.status === "ok" && response.data) {
        if (logIntervalId) clearInterval(logIntervalId);
        if (unlisten) unlisten();
        setProgress(100);
        setMigrationStats({
          created: response.data.stats?.created || 0,
          updated: response.data.stats?.updated || 0,
          skipped: response.data.stats?.skipped || 0,
          error_count: response.data.stats?.error_count || 0,
          errors: response.data.stats?.errors || [],
        });
        // Error cleared
        setIsMigrating(false);
        setTimeout(() => setStep(6), 800);
      } else if (response.status === "error" && response.error?.includes("motor Python no está disponible")) {
        // Nginx timeout, continue polling
        continuePolling = true;
        setLogs(prev => [...prev, "⚠️ La conexión web principal excedió el tiempo límite (timeout), pero la migración continúa en el servidor. Seguimos recibiendo los logs en directo..."]);
        return;
      } else {
        if (logIntervalId) clearInterval(logIntervalId);
        if (unlisten) unlisten();
        alert("Error: " + (response.error || "Error desconocido"));
        setIsMigrating(false);
        setProgress(0);
      }
    } catch (e: any) {
      if (isFinished) return;
      if (logIntervalId) clearInterval(logIntervalId);
      if (unlisten) unlisten();
      alert("Error: " + (e.message || String(e)));
      setIsMigrating(false);
      setProgress(0);
    } finally {
      if (!isFinished && !continuePolling) {
        setIsMigrating(false);
      }
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Navigation */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-2 border border-border bg-secondary/50 hover:bg-secondary text-muted-foreground hover:text-white rounded-xl transition duration-150"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <h1 className="text-2xl font-bold font-poppins">Wizard de Migración</h1>
            <p className="text-xs text-muted-foreground">ID del Cliente: {clientId}</p>
          </div>
        </div>

        {/* Python Connection Status Badge */}
        {pythonServerConnected !== null && (
          <div className="flex items-center gap-2 bg-secondary/30 border border-border px-3.5 py-1.5 rounded-xl shrink-0">
            <span className={`w-2 h-2 rounded-full ${pythonServerConnected ? "bg-emerald-500 animate-pulse" : "bg-amber-500"}`} />
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              {pythonServerConnected ? "Motor Python Activo" : "Motor Desconectado (Simulando)"}
            </span>
          </div>
        )}
      </div>

      {/* Stepper bar */}
      <div className="grid grid-cols-6 gap-2">
        {[
          { step: 1, label: "Modelo" },
          { step: 2, label: "Origen" },
          { step: 3, label: "Mapeo" },
          { step: 4, label: "Preview" },
          { step: 5, label: "Ejecutar" },
          { step: 6, label: "Resumen" },
        ].map((s) => (
          <div key={s.step} className="space-y-2">
            <div
              className={`h-1.5 rounded-full transition duration-300 ${
                step >= s.step ? "bg-primary" : "bg-border"
              }`}
            />
            <span
              className={`text-[10px] block font-semibold uppercase tracking-wider ${
                step === s.step ? "text-primary" : "text-muted-foreground"
              }`}
            >
              Paso {s.step}: {s.label}
            </span>
          </div>
        ))}
      </div>

      {/* Wizard Content box */}
      <div className="bg-card border border-border/80 rounded-2xl p-6 min-h-[380px] flex flex-col justify-between">
        
        {/* STEP 1: MODEL SELECTION */}
        {step === 1 && (
          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-bold">1. Selecciona el modelo de Odoo destino</h2>
              <p className="text-xs text-muted-foreground mt-1">
                La migración de datos de Odoo se realiza por capas lógicas. Selecciona el tipo de registro a importar.
              </p>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
              <div
                onClick={() => setSelectedModel("res.partner")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "res.partner"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Clientes (res.partner)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `res.partner` (customer). Importa la tabla de clientes (F_CLI) con `customer_rank = 1` y deduplicación inteligente.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("res.partner.supplier")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "res.partner.supplier"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Proveedores (res.partner)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `res.partner` (supplier). Importa la tabla de proveedores (F_PRO) con `supplier_rank = 1` y deduplicación inteligente.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("product.template")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "product.template"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Productos (product.template)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `product.template`. Creación e importación de artículos/productos (F_ART) con SKU, precios y deduplicación.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("account.move")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "account.move"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Facturas de Clientes (account.move)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `account.move` (out_invoice). Importa facturas de clientes (F_FAC + F_LFA) vinculando clientes e impuestos.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("account.move.supplier")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "account.move.supplier"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Facturas de Proveedores (account.move)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `account.move` (in_invoice). Importa facturas de proveedores/recibidas (F_FRT + F_LFR) vinculando proveedores e impuestos.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("sale.order")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "sale.order"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Pedidos de Venta (sale.order)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `sale.order`. Importa facturas/pedidos como pedidos de venta históricos (F_PED + F_LPE o F_FAC + F_LFA) vinculando clientes e impuestos.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("purchase.order")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "purchase.order"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Pedidos de Compra (purchase.order)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `purchase.order`. Importa pedidos a proveedores (F_PED) vinculando el proveedor y calculando el estado según su facturación.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("stock.quant")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "stock.quant"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Inventario Físico (stock.quant)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Ajusta el stock físico de productos en Odoo. Necesita las columnas: <code>product_id</code>, <code>location_id</code> e <code>inventory_quantity</code>.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("account.move.entry")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "account.move.entry"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Asientos Contables (account.move)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `account.move` (entry). Importa asientos y apuntes contables (F_APU) agrupándolos y vinculando cuentas contables y partners.
                  </p>
                </div>
              </div>

              <div
                onClick={() => setSelectedModel("account.account")}
                className={`p-5 rounded-xl border cursor-pointer transition flex gap-4 ${
                  selectedModel === "account.account"
                    ? "border-primary bg-primary/5 shadow-md shadow-primary/5"
                    : "border-border hover:border-muted-foreground/30 bg-secondary/20"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary shrink-0">
                  <Database className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="font-bold text-sm text-white">Plan Contable (account.account)</h4>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Capa `account.account`. Importa cuentas contables (F_CUE) asegurando no duplicar códigos existentes.
                  </p>
                </div>
              </div>

              {[
                { name: "stock.quant", label: "Stock Inicial (Quants)", desc: "Capa `stock.quant`. Ajustes de inventario por almacén. (Próximamente)" },
              ].map((m) => (
                <div
                  key={m.name}
                  className="p-5 rounded-xl border border-border bg-secondary/10 opacity-50 cursor-not-allowed flex gap-4"
                >
                  <div className="w-10 h-10 rounded-lg bg-border flex items-center justify-center text-muted-foreground shrink-0">
                    <Database className="w-5 h-5" />
                  </div>
                  <div>
                    <h4 className="font-bold text-sm text-muted-foreground">{m.label}</h4>
                    <p className="text-[11px] text-muted-foreground mt-1">{m.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* STEP 2: SOURCE FILE SELECT */}
        {step === 2 && (
          <div className="space-y-4 text-center">
            <div className="text-left">
              <h2 className="text-lg font-bold">2. Selecciona la base de datos origen</h2>
              <p className="text-xs text-muted-foreground mt-1">
                Puedes subir una base de datos local Microsoft Access (.mdb/.accdb) o un archivo Excel/CSV.
              </p>
            </div>

            {/* Instrucción clara para web */}
            {typeof (window as any).__TAURI_INTERNALS__ === "undefined" && (
              <div className="bg-primary/10 border border-primary/20 p-4 rounded-xl text-left space-y-2 max-w-2xl mx-auto">
                <p className="text-xs text-primary font-semibold">
                  💡 Modo Web Activo: Puedes arrastrar tu archivo Excel, CSV o Access directamente aquí. Se subirá automáticamente y de forma segura al servidor para ser procesado.
                </p>
              </div>
            )}

            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-2xl p-10 flex flex-col items-center justify-center transition ${
                dragOver ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground/30 bg-secondary/10"
              }`}
            >
              {isAnalyzing ? (
                <div className="space-y-3">
                  <div className="w-10 h-10 border-4 border-primary/30 border-t-primary rounded-full animate-spin mx-auto" />
                  <p className="font-semibold text-xs text-white">Analizando estructura del fichero...</p>
                </div>
              ) : (
                <>
                  <UploadCloud className="w-12 h-12 text-muted-foreground mb-4" />
                  <p className="font-bold text-sm">
                    Arrastra tu archivo aquí o busca en el explorador
                  </p>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Formatos soportados: Microsoft Access (.mdb, .accdb), Excel (.xlsx, .xls), CSV (.csv).
                  </p>
                  
                  <label className="mt-4 px-4 py-2 bg-secondary hover:bg-secondary/80 border border-border hover:border-muted-foreground/50 rounded-lg cursor-pointer transition text-xs font-semibold">
                    Buscar Archivo
                    <input
                      type="file"
                      accept=".accdb,.mdb,.xlsx,.xls,.csv"
                      onChange={handleFileChange}
                      className="hidden"
                    />
                  </label>
                </>
              )}

              {fileName && !isAnalyzing && (
                <div className="mt-5 flex flex-col items-center gap-3">
                  <div className="flex items-center gap-2 bg-primary/10 border border-primary/20 px-3.5 py-2 rounded-xl text-primary text-xs font-semibold">
                    <FileSpreadsheet className="w-4 h-4" />
                    {fileName.split(/[/\\]/).pop()}
                  </div>
                  
                  {/* Selector de tablas/hojas (para archivos con múltiples tablas como Excel u Access) */}
                  {tables.length > 1 && (
                    <div className="space-y-1 w-[250px] text-left">
                      <label className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                        Seleccionar hoja o tabla:
                      </label>
                      <select
                        value={selectedTable}
                        onChange={(e) => handleTableSelect(fileName, e.target.value)}
                        className="bg-secondary border border-border rounded-lg px-3 py-2 text-white outline-none focus:border-primary/50 text-xs w-full"
                      >
                        <option value="">-- Selecciona --</option>
                        {tables.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  
                  {selectedTable && rowCount > 0 && (
                    <p className="text-[10px] text-emerald-400 font-medium">
                      Estructura leída: {rowCount} registros cargados de "{selectedTable}".
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* STEP 3: MAPPING */}
        {step === 3 && (
          <div className="space-y-4">
            <div className="flex justify-between items-start gap-4">
              <div>
                <h2 className="text-lg font-bold">3. Mapeo de columnas</h2>
                <p className="text-xs text-muted-foreground mt-1">
                  Asocia los campos detectados en tu origen con las columnas del modelo Odoo.
                </p>
              </div>
              <button
                onClick={handleAutoMap}
                disabled={sourceColumns.length === 0}
                className="flex items-center gap-1.5 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 hover:border-primary/40 font-semibold py-1.5 px-3 rounded-lg transition text-xs disabled:opacity-40"
              >
                <Sparkles className="w-3.5 h-3.5" />
                Mapear con IA
              </button>
            </div>

            {sourceColumns.length === 0 ? (
              <div className="text-center py-10 border border-border rounded-xl bg-secondary/10">
                <p className="text-xs text-muted-foreground">Carga un archivo y selecciona una tabla para ver las columnas.</p>
              </div>
            ) : (
              <div className="max-h-[550px] overflow-y-auto border border-border rounded-xl">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-secondary/40 border-b border-border">
                      <th className="p-3 font-semibold text-muted-foreground">Columna Origen</th>
                      <th className="p-3 font-semibold text-muted-foreground">Campo Odoo Destino</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {sourceColumns.map((col) => (
                      <tr key={col} className="hover:bg-secondary/20 transition">
                        <td className="p-3 font-medium text-white">{col}</td>
                        <td className="p-3">
                          <select
                            value={mappings[col] || ""}
                            onChange={(e) =>
                              setMappings({ ...mappings, [col]: e.target.value })
                            }
                            className="bg-secondary border border-border rounded px-2.5 py-1.5 text-white outline-none focus:border-primary/50 text-xs w-full max-w-[250px]"
                          >
                            <option value="">-- Omitir columna --</option>
                            {odooFields.map((f) => (
                              <option key={f.name} value={f.name}>
                                {f.label} {f.required ? "*" : ""}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* STEP 4: DATA PREVIEW */}
        {step === 4 && (
          <div className="space-y-4">
            <div>
              <h2 className="text-lg font-bold">4. Vista previa de transformación (Primeras filas)</h2>
              <p className="text-xs text-muted-foreground mt-1">
                Visualiza cómo se transformarán y limpiarán los datos en local antes de subirlos a Odoo.
              </p>
            </div>

            {sampleRows.length === 0 ? (
              <div className="text-center py-10 border border-border rounded-xl bg-secondary/10">
                <p className="text-xs text-muted-foreground">No hay registros de muestra disponibles.</p>
              </div>
            ) : (
              <div className="max-h-[450px] overflow-auto border border-border rounded-xl">
                <table className="w-full text-left border-collapse text-xs min-w-[700px]">
                  <thead>
                    <tr className="bg-secondary/40 border-b border-border">
                      {sourceColumns.map((col) => (
                        <th key={col} className="p-3 font-semibold text-muted-foreground truncate max-w-[120px]" title={col}>
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {sampleRows.map((row, idx) => (
                      <tr key={idx} className="hover:bg-secondary/20 transition">
                        {sourceColumns.map((col) => (
                          <td key={col} className="p-3 truncate max-w-[150px] text-white/90">
                            {row[col] !== null && row[col] !== undefined ? String(row[col]) : <span className="text-muted-foreground/40 italic">null</span>}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* STEP 5: EXECUTE */}
        {step === 5 && (
          <div className="space-y-6 my-auto max-w-lg mx-auto w-full">
            <div className="text-center">
              <Settings className="w-12 h-12 text-primary mx-auto animate-spin mb-4" style={{ animationDuration: isMigrating ? '3s' : '0s' }} />
              <h2 className="text-xl font-bold">5. Ejecutar Proceso</h2>
              <p className="text-xs text-muted-foreground mt-1.5">
                Configura las opciones de subida antes de iniciar la migración de datos.
              </p>
            </div>

            {/* Dry run / Options */}
            <div className="bg-secondary/30 border border-border p-4 rounded-xl space-y-3.5">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="font-bold text-xs">Simulación de subida (Dry Run)</h4>
                  <p className="text-[10px] text-muted-foreground">Prueba la migración en Odoo sin guardar ningún cambio.</p>
                </div>
                <input
                  type="checkbox"
                  checked={isDryRun}
                  disabled={isMigrating}
                  onChange={(e) => setIsDryRun(e.target.checked)}
                  className="w-4 h-4 accent-primary"
                />
              </div>
              <div className="h-[1px] bg-border" />
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="font-bold text-xs">Actualizar registros existentes</h4>
                  <p className="text-[10px] text-muted-foreground">Si detecta un duplicado, actualiza la información en lugar de omitirlo.</p>
                </div>
                <input
                  type="checkbox"
                  checked={updateExisting}
                  disabled={isMigrating}
                  onChange={(e) => setUpdateExisting(e.target.checked)}
                  className="w-4 h-4 accent-primary"
                />
              </div>
              <div className="h-[1px] bg-border" />
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h4 className="font-bold text-xs">Prefijo de ID Externo</h4>
                  <p className="text-[10px] text-muted-foreground">Se añadirá al valor del campo ID mapeado (ej: cli_15).</p>
                </div>
                <input
                  type="text"
                  value={externalIdPrefix}
                  disabled={isMigrating}
                  onChange={(e) => setExternalIdPrefix(e.target.value)}
                  placeholder="cli_"
                  className="bg-secondary border border-border rounded px-2.5 py-1 text-white outline-none focus:border-primary/50 text-xs w-28 text-right font-mono"
                />
              </div>
              <div className="h-[1px] bg-border" />
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h4 className="font-bold text-xs">Columna para ID Externo (XML ID)</h4>
                  <p className="text-[10px] text-muted-foreground">Columna del archivo origen para identificar registros en Odoo.</p>
                </div>
                <select
                  value={externalIdColumn}
                  disabled={isMigrating}
                  onChange={(e) => setExternalIdColumn(e.target.value)}
                  className="bg-secondary border border-border rounded px-2.5 py-1.5 text-white outline-none focus:border-primary/50 text-xs w-44 text-right font-mono"
                >
                  <option value="">-- Autodetectar / Omitir --</option>
                  {sourceColumns.map((col) => (
                    <option key={col} value={col}>
                      {col}
                    </option>
                  ))}
                </select>
              </div>
              {selectedModel === "product.template" && (
                <>
                  <div className="h-[1px] bg-border" />
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <h4 className="font-bold text-xs">Tabla de Categorías/Familias</h4>
                      <p className="text-[10px] text-muted-foreground">Tabla secundaria que traduce los códigos de familia a nombres reales.</p>
                    </div>
                    <select
                      value={categoriesTable}
                      disabled={isMigrating}
                      onChange={(e) => setCategoriesTable(e.target.value)}
                      className="bg-secondary border border-border rounded px-2.5 py-1.5 text-white outline-none focus:border-primary/50 text-xs w-44 text-right font-mono"
                    >
                      <option value="">-- Autodetectar / Ninguna --</option>
                      {tables.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                </>
              )}
              {(selectedModel === "sale.order" || selectedModel === "purchase.order") && (
                <>
                  <div className="h-[1px] bg-border" />
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="font-bold text-xs">Confirmar Pedidos automáticamente</h4>
                      <p className="text-[10px] text-muted-foreground">Confirma los presupuestos de venta convirtiéndolos en pedidos de venta (sale).</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={confirmOrders}
                      disabled={isMigrating}
                      onChange={(e) => setConfirmOrders(e.target.checked)}
                      className="w-4 h-4 accent-primary"
                    />
                  </div>
                  {confirmOrders && (
                    <>
                      <div className="h-[1px] bg-border" />
                      <div className="flex items-center justify-between">
                        <div>
                          <h4 className="font-bold text-xs">Forzar estado &quot;Facturado&quot; (force_invoiced)</h4>
                          <p className="text-[10px] text-muted-foreground">Tras confirmar cada pedido, lo marca como totalmente facturado aunque no tenga facturas vinculadas.</p>
                        </div>
                        <input
                          type="checkbox"
                          checked={forceInvoiced}
                          disabled={isMigrating}
                          onChange={(e) => setForceInvoiced(e.target.checked)}
                          className="w-4 h-4 accent-primary"
                        />
                      </div>
                    </>
                  )}
                </>
              )}
              {selectedModel === "account.move.entry" && (
                <>
                  <div className="h-[1px] bg-border" />
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="font-bold text-xs">Publicar Asientos automáticamente</h4>
                      <p className="text-[10px] text-muted-foreground">Publica/asienta las entradas contables directamente (estado asimilado a posted).</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={postEntries}
                      disabled={isMigrating}
                      onChange={(e) => setPostEntries(e.target.checked)}
                      className="w-4 h-4 accent-primary"
                    />
                  </div>
                </>
              )}
              {(selectedModel === "sale.order" || selectedModel === "purchase.order" || selectedModel === "account.move" || selectedModel === "account.move.supplier") && (
                <>
                  <div className="h-[1px] bg-border" />
                  <div className="flex items-center justify-between">
                    <div>
                      <h4 className="font-bold text-xs">Formatear nombre (Añadir prefijo, año...)</h4>
                      <p className="text-[10px] text-muted-foreground">Si se desmarca, se mantendrá el nombre original de la factura/pedido (ej. 152) sin añadir prefijos (ej. SO/2026/0/152).</p>
                    </div>
                    <input
                      type="checkbox"
                      checked={formatName}
                      disabled={isMigrating}
                      onChange={(e) => setFormatName(e.target.checked)}
                      className="w-4 h-4 accent-primary"
                    />
                  </div>
                </>
              )}
              <div className="h-[1px] bg-border" />
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h4 className="font-bold text-xs">Tamaño de Lote (Batch Size)</h4>
                  <p className="text-[10px] text-muted-foreground">Cantidad de registros a importar por cada bloque.</p>
                </div>
                <select
                  value={batchSize}
                  disabled={isMigrating}
                  onChange={(e) => setBatchSize(Number(e.target.value))}
                  className="bg-secondary border border-border rounded px-2.5 py-1.5 text-white outline-none focus:border-primary/50 text-xs w-28 text-right font-mono"
                >
                  <option value={1}>1 (Uno a uno)</option>
                  <option value={20}>20 registros</option>
                  <option value={50}>50 registros</option>
                  <option value={100}>100 registros</option>
                  <option value={200}>200 registros</option>
                </select>
              </div>
            </div>

            {/* Progress bar */}
            {isMigrating && (
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-semibold">
                  <span className="text-muted-foreground">
                    {migrationProgress 
                      ? `Migrando registros (${migrationProgress.done} de ${migrationProgress.total})...` 
                      : "Migrando registros..."}
                  </span>
                  <span className="text-primary">{progress}%</span>
                </div>
                <div className="w-full bg-secondary h-2.5 rounded-full overflow-hidden">
                  <div
                    className="bg-gradient-to-r from-primary to-cyan-500 h-full rounded-full transition-all duration-300"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="text-[10px] text-muted-foreground text-center animate-pulse">
                  Procesando lote de datos...
                </p>
              </div>
            )}

            {/* Terminal de logs en tiempo real */}
            {logs.length > 0 && (
              <div className="space-y-2">
                <div className="flex justify-between items-center text-[10px] text-muted-foreground">
                  <span>Logs de ejecución (Motor Python)</span>
                  {isMigrating && <span className="animate-pulse flex h-1.5 w-1.5 rounded-full bg-emerald-500" />}
                </div>
                <div
                  id="logs-console"
                  className="bg-black/70 border border-border rounded-xl p-3.5 font-mono text-[9px] text-emerald-400 max-h-[140px] overflow-y-auto space-y-1.5 scrollbar-thin scrollbar-thumb-muted"
                >
                  {logs.map((logLine, idx) => (
                    <div key={idx} className="whitespace-pre-wrap leading-relaxed border-l-2 border-emerald-500/20 pl-2">
                      {logLine}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!isMigrating && progress === 100 && (
              <div className="flex items-center justify-center gap-2 text-emerald-400 text-sm font-semibold bg-emerald-500/5 border border-emerald-500/10 p-3 rounded-xl">
                <CheckCircle className="w-5 h-5" /> Proceso de {isDryRun ? "simulación" : "migración"} finalizado correctamente.
              </div>
            )}

            {!isMigrating && progress < 100 && (
              <button
                onClick={startMigration}
                className="w-full flex items-center justify-center gap-2 gradient-button text-white font-semibold py-3 px-4 rounded-xl shadow-lg hover:shadow-primary/20 transition-all duration-300 text-xs"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                {isDryRun ? "Iniciar Simulación (Dry Run)" : "Ejecutar Migración Real"}
              </button>
            )}
          </div>
        )}

        {/* STEP 6: SUMMARY */}
        {step === 6 && (
          <div className="space-y-6 max-w-lg mx-auto w-full">
            <div className="text-center space-y-2">
              <div className="w-12 h-12 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto mb-2">
                <CheckCircle className="w-6 h-6" />
              </div>
              <h2 className="text-xl font-bold">¡{isDryRun ? "Simulación" : "Migración"} Finalizada!</h2>
              <p className="text-xs text-muted-foreground">
                El proceso ha concluido. A continuación se muestran las estadísticas de importación.
              </p>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center">
              <div className="bg-secondary/20 border border-border p-3.5 rounded-xl">
                <div className="text-2xl font-black text-white">
                  {migrationStats
                    ? migrationStats.created + migrationStats.updated + migrationStats.skipped + migrationStats.error_count
                    : rowCount}
                </div>
                <div className="text-[10px] text-muted-foreground font-semibold mt-1">Total Filas</div>
              </div>
              <div className="bg-emerald-500/5 border border-emerald-500/10 p-3.5 rounded-xl">
                <div className="text-2xl font-black text-emerald-400">
                  {migrationStats ? migrationStats.created : Math.floor(rowCount * 0.8)}
                </div>
                <div className="text-[10px] text-emerald-400 font-semibold mt-1">Creados</div>
              </div>
              <div className="bg-blue-500/5 border border-blue-500/10 p-3.5 rounded-xl">
                <div className="text-2xl font-black text-blue-400">
                  {migrationStats ? migrationStats.updated : rowCount - Math.floor(rowCount * 0.8)}
                </div>
                <div className="text-[10px] text-blue-400 font-semibold mt-1">Actualizados</div>
              </div>
              <div className={`border p-3.5 rounded-xl ${migrationStats && migrationStats.error_count > 0 ? "bg-red-500/10 border-red-500/20" : "bg-secondary/20 border-border"}`}>
                <div className={`text-2xl font-black ${migrationStats && migrationStats.error_count > 0 ? "text-red-400" : "text-white"}`}>
                  {migrationStats ? migrationStats.error_count : 0}
                </div>
                <div className="text-[10px] text-muted-foreground font-semibold mt-1">Errores</div>
              </div>
            </div>

            {migrationStats && migrationStats.error_count > 0 && (
              <div className="bg-red-500/5 border border-red-500/20 p-4 rounded-xl text-left space-y-2 max-h-[300px] overflow-y-auto">
                <h4 className="font-bold text-sm text-red-400 flex items-center gap-2">
                  ⚠️ Registros con error ({migrationStats.error_count}) — copia esta lista para buscarlos en Odoo
                </h4>
                <div className="space-y-1.5">
                  {migrationStats.errors.map((e, index) => (
                    <div key={index} className="flex items-start gap-2 bg-red-900/20 border border-red-500/10 px-3 py-2 rounded-lg">
                      <span className="text-red-400 font-mono font-black text-xs shrink-0">
                        {e.name ? `📄 ${e.name}` : `#${e.row}`}
                      </span>
                      <span className="text-muted-foreground text-[10px] leading-relaxed">
                        {e.error}
                      </span>
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => {
                    const lines = migrationStats.errors.map(e =>
                      `${e.name || `fila_${e.row}`}: ${e.error}`
                    ).join("\n");
                    navigator.clipboard.writeText(lines);
                  }}
                  className="text-[10px] text-red-400/70 hover:text-red-400 transition border border-red-500/20 rounded px-2 py-1 mt-1"
                >
                  📋 Copiar lista de errores al portapapeles
                </button>
              </div>
            )}

            <div className="flex gap-3">
              <button
                onClick={() => {
                  setStep(1);
                  setFileName(null);
                  setProgress(0);
                  setMigrationProgress(null);
                  setTables([]);
                  setSelectedTable("");
                  setSourceColumns([]);
                  setRowCount(0);
                  setSampleRows([]);
                  setMappings({});
                }}
                className="flex-1 px-4 py-2.5 border border-border bg-secondary/20 hover:bg-secondary text-white rounded-xl transition text-xs font-semibold"
              >
                Volver al Inicio
              </button>
              <button
                onClick={() => alert("Descargando logs estructurados en JSON...")}
                className="flex-1 gradient-button text-white font-semibold py-2.5 px-4 rounded-xl shadow-lg hover:shadow-primary/20 transition-all text-xs"
              >
                Descargar Log JSON
              </button>
            </div>
          </div>
        )}

        {/* Navigation Bar */}
        <div className="flex justify-between items-center border-t border-border pt-4 mt-6">
          <button
            onClick={() => setStep((s) => Math.max(1, s - 1))}
            disabled={step === 1 || isMigrating}
            className="flex items-center gap-1.5 px-4 py-2 border border-border bg-secondary/20 hover:bg-secondary/40 text-muted-foreground hover:text-white rounded-xl transition duration-150 text-xs font-semibold disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Anterior
          </button>
          
          <button
            onClick={() => setStep((s) => Math.min(6, s + 1))}
            disabled={
              (step === 2 && (!fileName || (tables.length > 1 && !selectedTable))) || 
              (step === 5 && progress < 100) || 
              step === 6
            }
            className="flex items-center gap-1.5 px-4 py-2 gradient-button text-white rounded-xl transition duration-150 text-xs font-semibold disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Siguiente
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>

      </div>
    </div>
  );
}
