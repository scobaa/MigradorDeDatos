export interface PythonResponse<T = any> {
  status: "ok" | "error";
  data?: T;
  error?: string;
}

export interface ProgressPayload {
  event: "progress";
  progress: number;
  total: number;
  current_row?: number;
  [key: string]: any;
}

// Determina si la aplicación se está ejecutando dentro del contenedor de Tauri
const isTauri = () => {
  return typeof window !== "undefined" && (window as any).__TAURI_INTERNALS__ !== undefined;
};

/**
 * Llama al motor de Python a través del backend Rust de Tauri.
 * 
 * @param command Nombre del comando a ejecutar (ej: 'test_connection')
 * @param args Argumentos que se pasarán serializados como JSON
 */
// Cuando la app se sirve desde un servidor remoto (nginx), el motor Python
// está accesible en /api (relativo). En desarrollo local sigue siendo localhost.
const getPythonApiUrl = () => {
  const hostname = window.location.hostname;
  const isLocal = hostname === 'localhost' || hostname === '127.0.0.1';
  return isLocal ? 'http://127.0.0.1:8000/api' : '/api';
};

export async function callPython<T = any>(
  command: string,
  args: any = {}
): Promise<PythonResponse<T>> {
  if (!isTauri()) {
    const apiUrl = getPythonApiUrl();
    console.log(`Intentando conectar con el motor Python en ${apiUrl} para '${command}'...`);
    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ command, args }),
      });
      if (response.ok) {
        return await response.json();
      }
    } catch (e) {
      console.warn(
        `No se pudo contactar con el motor Python (${apiUrl}).\n` +
        `En modo local, ejecuta: python python-engine/server.py\n` +
        `Usando datos de simulación por defecto.`
      );
    }

    // Simulación para poder probar el flujo visual en el navegador
    if (command === "test_connection") {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      return {
        status: "ok",
        data: {
          connected: true,
          message: "Conexión simulada con Odoo exitosa (Entorno Navegador)",
        } as any,
      };
    }

    if (command === "analyze_source") {
      await new Promise((resolve) => setTimeout(resolve, 600));
      const path: string = args.path || "archivo.xlsx";
      const table: string | undefined = args.table;
      const ext = path.split(".").pop()?.toLowerCase();

      if (!table) {
        // Devuelve las tablas/hojas disponibles
        let tables = ["CSV"];
        if (ext === "xlsx" || ext === "xls") {
          tables = ["Clientes", "Proveedores", "Productos"];
        } else if (ext === "accdb" || ext === "mdb") {
          tables = ["Clientes_Legacy", "Contactos", "Productos_Legacy"];
        }
        return {
          status: "ok",
          data: { tables } as any,
        };
      } else {
        // Devuelve el análisis de la tabla/hoja seleccionada
        const columns = ext === "csv" 
          ? ["ID", "Razón Social", "CIF_NIF", "Email_Contacto", "Teléfono", "Calle", "CP", "Población"]
          : ["Código", "Nombre Comercial", "CIF/NIF", "Email", "Teléfono 1", "Móvil", "Dirección", "C.Postal", "Ciudad"];
          
        return {
          status: "ok",
          data: {
            table,
            columns,
            row_count: ext === "csv" ? 85 : 152,
            sample_rows: [
              { id: "1", name: "CONSTRUCCIONES S.A.", vat: "ESB12345678", email: "info@construcciones.com", phone: "912345678", mobile: "600112233", street: "Gran Vía 45", zip: "28013", city: "Madrid" },
              { id: "2", name: "José Martínez Gómez", vat: "ES12345678X", email: "jose@martinez.es", phone: "931112233", mobile: "611223344", street: "Diagonal 123", zip: "08018", city: "Barcelona" },
              { id: "3", name: "TALLERES RAMOS S.L.", vat: "ESA87654321", email: "contacto@talleresramos.es", phone: "963445566", mobile: "622334455", street: "Av. Colón 12", zip: "46004", city: "Valencia" }
            ]
          } as any,
        };
      }
    }

    if (command === "get_odoo_fields") {
      await new Promise((resolve) => setTimeout(resolve, 500));
      return {
        status: "ok",
        data: {
          fields: [
            { name: "ref", label: "Referencia Externa (ref)", required: false, type: "char" },
            { name: "name", label: "Nombre/Razón Social (name)", required: true, type: "char" },
            { name: "vat", label: "NIF/CIF (vat)", required: false, type: "char" },
            { name: "email", label: "Correo Electrónico (email)", required: false, type: "char" },
            { name: "phone", label: "Teléfono Fijo (phone)", required: false, type: "char" },
            { name: "mobile", label: "Teléfono Móvil (mobile)", required: false, type: "char" },
            { name: "street", label: "Calle (street)", required: false, type: "char" },
            { name: "zip", label: "Código Postal (zip)", required: false, type: "char" },
            { name: "city", label: "Ciudad (city)", required: false, type: "char" },
            { name: "website", label: "Sitio Web (website)", required: false, type: "char" },
            { name: "comment", label: "Notas (comment)", required: false, type: "text" },
            { name: "property_payment_term_id", label: "Plazo de Pago (property_payment_term_id)", required: false, type: "many2one" },
          ]
        } as any
      };
    }

    return {
      status: "error",
      error: `El motor Python no está disponible (${getPythonApiUrl()}). Para ejecutar migraciones reales, asegúrate de que el servidor Python esté en ejecución.`,
    };
  }

  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<PythonResponse<T>>("run_python", { command, args });
  } catch (err: any) {
    console.error("Tauri Python Invoke Error:", err);
    return {
      status: "error",
      error: err?.toString() || "Error al comunicarse con Python.",
    };
  }
}

/**
 * Escucha la salida de logs y progreso del motor de Python (stderr).
 * Parsea automáticamente eventos estructurados como la barra de progreso.
 * 
 * @param onLog Callback para logs estándar de texto
 * @param onProgress Callback para eventos de progreso en tiempo real
 * @returns Desconstructor/unlisten function
 */
export async function listenToPythonEvents(
  onLog: (line: string) => void,
  onProgress?: (progress: ProgressPayload) => void
) {
  if (!isTauri()) {
    console.warn("listenToPythonEvents llamado en navegador web. Retornando mock unlisten.");
    return () => {};
  }

  try {
    const { listen } = await import("@tauri-apps/api/event");
    return await listen<string>("python-log", (event) => {
      const line = event.payload;
      const trimmed = line.trim();

      if (onProgress && (trimmed.startsWith("{") && trimmed.endsWith("}"))) {
        try {
          const parsed = JSON.parse(trimmed);
          if (parsed && parsed.event === "progress") {
            onProgress(parsed);
            return; // Interceptado: no lo enviamos como log de texto común
          }
        } catch {
          // No es JSON válido, ignorar y tratar como log normal
        }
      }
      
      onLog(line);
    });
  } catch (err) {
    console.error("Error al suscribirse a eventos de Tauri:", err);
    return () => {};
  }
}
