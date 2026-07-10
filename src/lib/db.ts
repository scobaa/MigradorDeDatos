import { getSessionToken } from "./auth";

export interface DBClient {
  id: string;
  name: string;
  odoo_url: string;
  odoo_db: string;
  odoo_user: string;
  odoo_password?: string;
  created_at: string;
  last_used_at: string;
}

export interface DBTemplate {
  id: string;
  name: string;
  source_type: "Access" | "Excel" | "CSV" | "SQL Server";
  mapping_count: number;
  created_at: string;
}

const isTauri = () => {
  return typeof window !== "undefined" && (window as any).__TAURI_INTERNALS__ !== undefined;
};

// Función auxiliar para llamar al backend Python
async function callBackend(command: string, args: any = {}) {
  const token = getSessionToken();
  if (token) {
    args.token = token;
  }
  
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const jsonStr = await invoke<string>("execute_python_engine", {
      payload: JSON.stringify({ command, args }),
    });
    const parsed = JSON.parse(jsonStr);
    if (parsed.status === "error") throw new Error(parsed.error);
    return parsed.data;
  } else {
    const apiBase = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000' : '';
    const res = await fetch(`${apiBase}/api`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command, args }),
    });
    if (!res.ok) throw new Error("Error de conexión al motor Python");
    const parsed = await res.json();
    if (parsed.status === "error") throw new Error(parsed.error);
    return parsed.data;
  }
}

export const db = {
  // CRUD de Clientes usando la API
  async getClients(): Promise<DBClient[]> {
    try {
      const data = await callBackend("db_get_clients");
      return data.clients || [];
    } catch (e) {
      console.error("Error obteniendo clientes:", e);
      return [];
    }
  },

  async addClient(client: Omit<DBClient, "id" | "created_at" | "last_used_at">): Promise<DBClient> {
    const data = await callBackend("db_add_client", { client });
    return data.client;
  },

  async deleteClient(id: string): Promise<void> {
    await callBackend("db_delete_client", { client_id: id });
  },

  async updateClient(id: string, client: Omit<DBClient, "id" | "created_at" | "last_used_at">): Promise<DBClient> {
    const data = await callBackend("db_update_client", { client_id: id, client });
    return data.client;
  },

  async updateClientLastUsed(id: string): Promise<void> {
    try {
      await callBackend("db_update_client_last_used", { client_id: id });
    } catch (e) {
      console.error("No se pudo actualizar last_used_at", e);
    }
  },

  // CRUD de Plantillas (temporalmente en localstorage para no romper si se usaban)
  async getTemplates(): Promise<DBTemplate[]> {
    const data = localStorage.getItem("odoo_migrator_templates");
    return data ? JSON.parse(data) : [];
  },

  async addTemplate(template: Omit<DBTemplate, "id" | "created_at">): Promise<DBTemplate> {
    const newTemplate: DBTemplate = {
      ...template,
      id: Date.now().toString(),
      created_at: new Date().toISOString().split("T")[0],
    };
    const templates = await this.getTemplates();
    templates.push(newTemplate);
    localStorage.setItem("odoo_migrator_templates", JSON.stringify(templates));
    return newTemplate;
  },

  async deleteTemplate(id: string): Promise<void> {
    const templates = await this.getTemplates();
    const filtered = templates.filter((t) => t.id !== id);
    localStorage.setItem("odoo_migrator_templates", JSON.stringify(filtered));
  },
};
