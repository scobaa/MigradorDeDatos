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

// --- DATOS INICIALES MOCK ---
const DEFAULT_CLIENTS: DBClient[] = [
  {
    id: "1",
    name: "Distribuidora del Norte",
    odoo_url: "https://dist-norte.odoo.com",
    odoo_db: "dist-norte-db",
    odoo_user: "admin@distnorte.com",
    odoo_password: "admin",
    created_at: "2026-05-10",
    last_used_at: "2026-05-24",
  },
  {
    id: "2",
    name: "Ferretería Industrial Martínez",
    odoo_url: "https://martinez-industrial.odoo.com",
    odoo_db: "martinez_prod",
    odoo_user: "migrador@martinez.es",
    odoo_password: "admin",
    created_at: "2026-05-18",
    last_used_at: "2026-05-20",
  },
  {
    id: "3",
    name: "Textiles del Este S.A.",
    odoo_url: "https://textiles-este.odoo.com",
    odoo_db: "textiles_prod_db",
    odoo_user: "consultor@este.com",
    odoo_password: "admin",
    created_at: "2026-05-22",
    last_used_at: "Nunca",
  },
];

const DEFAULT_TEMPLATES: DBTemplate[] = [
  {
    id: "1",
    name: "Access Clientes Estándar",
    source_type: "Access",
    mapping_count: 9,
    created_at: "2026-05-12",
  },
  {
    id: "2",
    name: "Plantilla Proveedores Sage50",
    source_type: "Excel",
    mapping_count: 7,
    created_at: "2026-05-19",
  },
  {
    id: "3",
    name: "Mapeo CSV Clientes Genérico",
    source_type: "CSV",
    mapping_count: 8,
    created_at: "2026-05-24",
  },
];

// Inicializa el almacenamiento local si está vacío
const initLocalStorage = () => {
  if (typeof window === "undefined") return;
  if (!localStorage.getItem("odoo_migrator_clients")) {
    localStorage.setItem("odoo_migrator_clients", JSON.stringify(DEFAULT_CLIENTS));
  }
  if (!localStorage.getItem("odoo_migrator_templates")) {
    localStorage.setItem("odoo_migrator_templates", JSON.stringify(DEFAULT_TEMPLATES));
  }
};

initLocalStorage();

export const db = {
  // CRUD de Clientes
  async getClients(): Promise<DBClient[]> {
    if (isTauri()) {
      // NOTA: Cuando se active SQLite en Rust, se podrá consumir así:
      // const Database = (await import("@tauri-apps/plugin-sql")).default;
      // const sqliteDb = await Database.load("sqlite:odoo_migrator.db");
      // return await sqliteDb.select<DBClient[]>("SELECT * FROM clients ORDER BY created_at DESC");
    }
    const data = localStorage.getItem("odoo_migrator_clients");
    return data ? JSON.parse(data) : [];
  },

  async addClient(client: Omit<DBClient, "id" | "created_at" | "last_used_at">): Promise<DBClient> {
    const newClient: DBClient = {
      ...client,
      id: Date.now().toString(),
      created_at: new Date().toISOString().split("T")[0],
      last_used_at: "Nunca",
    };

    if (isTauri()) {
      // Para SQLite nativo:
      // const Database = (await import("@tauri-apps/plugin-sql")).default;
      // const sqliteDb = await Database.load("sqlite:odoo_migrator.db");
      // await sqliteDb.execute(
      //   "INSERT INTO clients (id, name, odoo_url, odoo_db, odoo_user, odoo_password, created_at, last_used_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
      //   [newClient.id, newClient.name, newClient.odoo_url, newClient.odoo_db, newClient.odoo_user, newClient.odoo_password, newClient.created_at, newClient.last_used_at]
      // );
    }

    const clients = await this.getClients();
    clients.push(newClient);
    localStorage.setItem("odoo_migrator_clients", JSON.stringify(clients));
    return newClient;
  },

  async deleteClient(id: string): Promise<void> {
    if (isTauri()) {
      // Para SQLite nativo:
      // const Database = (await import("@tauri-apps/plugin-sql")).default;
      // const sqliteDb = await Database.load("sqlite:odoo_migrator.db");
      // await sqliteDb.execute("DELETE FROM clients WHERE id = $1", [id]);
    }

    const clients = await this.getClients();
    const filtered = clients.filter((c) => c.id !== id);
    localStorage.setItem("odoo_migrator_clients", JSON.stringify(filtered));
  },

  async updateClientLastUsed(id: string): Promise<void> {
    if (isTauri()) {
      // Para SQLite nativo:
      // const Database = (await import("@tauri-apps/plugin-sql")).default;
      // const sqliteDb = await Database.load("sqlite:odoo_migrator.db");
      // await sqliteDb.execute("UPDATE clients SET last_used_at = $1 WHERE id = $2", [new Date().toISOString().split("T")[0], id]);
    }

    const clients = await this.getClients();
    const updated = clients.map((c) =>
      c.id === id ? { ...c, last_used_at: new Date().toISOString().split("T")[0] } : c
    );
    localStorage.setItem("odoo_migrator_clients", JSON.stringify(updated));
  },

  // CRUD de Plantillas
  async getTemplates(): Promise<DBTemplate[]> {
    if (isTauri()) {
      // Para SQLite nativo:
      // const Database = (await import("@tauri-apps/plugin-sql")).default;
      // const sqliteDb = await Database.load("sqlite:odoo_migrator.db");
      // return await sqliteDb.select<DBTemplate[]>("SELECT * FROM templates ORDER BY created_at DESC");
    }
    const data = localStorage.getItem("odoo_migrator_templates");
    return data ? JSON.parse(data) : [];
  },

  async addTemplate(template: Omit<DBTemplate, "id" | "created_at">): Promise<DBTemplate> {
    const newTemplate: DBTemplate = {
      ...template,
      id: Date.now().toString(),
      created_at: new Date().toISOString().split("T")[0],
    };

    if (isTauri()) {
      // Para SQLite nativo:
      // const Database = (await import("@tauri-apps/plugin-sql")).default;
      // const sqliteDb = await Database.load("sqlite:odoo_migrator.db");
      // await sqliteDb.execute(
      //   "INSERT INTO templates (id, name, source_type, mapping_count, created_at) VALUES ($1, $2, $3, $4, $5)",
      //   [newTemplate.id, newTemplate.name, newTemplate.source_type, newTemplate.mapping_count, newTemplate.created_at]
      // );
    }

    const templates = await this.getTemplates();
    templates.push(newTemplate);
    localStorage.setItem("odoo_migrator_templates", JSON.stringify(templates));
    return newTemplate;
  },

  async deleteTemplate(id: string): Promise<void> {
    if (isTauri()) {
      // Para SQLite nativo:
      // const Database = (await import("@tauri-apps/plugin-sql")).default;
      // const sqliteDb = await Database.load("sqlite:odoo_migrator.db");
      // await sqliteDb.execute("DELETE FROM templates WHERE id = $1", [id]);
    }

    const templates = await this.getTemplates();
    const filtered = templates.filter((t) => t.id !== id);
    localStorage.setItem("odoo_migrator_templates", JSON.stringify(filtered));
  },
};
