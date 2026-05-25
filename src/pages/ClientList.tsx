import { useState } from "react";
import { Plus, Database, Globe, Play, Trash2, CheckCircle2, XCircle, AlertCircle, RefreshCw } from "lucide-react";
import { callPython } from "../lib/python";
import { useClients } from "../hooks/useClients";

interface ClientListProps {
  onSelectClient: (clientId: string) => void;
}

export default function ClientList({ onSelectClient }: ClientListProps) {
  const { clients, loading, addClient, deleteClient } = useClients();
  const [connectionStatuses, setConnectionStatuses] = useState<Record<string, "idle" | "connected" | "error">>({});

  const [showAddModal, setShowAddModal] = useState(false);
  const [newClient, setNewClient] = useState({
    name: "",
    odoo_url: "",
    odoo_db: "",
    odoo_user: "",
    odoo_password: "",
  });
  
  const [testingConnection, setTestingConnection] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const handleAddClient = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newClient.name || !newClient.odoo_url || !newClient.odoo_db || !newClient.odoo_user || !newClient.odoo_password) {
      alert("Por favor, rellena todos los campos.");
      return;
    }

    setIsSaving(true);
    try {
      await addClient({
        name: newClient.name,
        odoo_url: newClient.odoo_url,
        odoo_db: newClient.odoo_db,
        odoo_user: newClient.odoo_user,
        odoo_password: newClient.odoo_password,
      });
      setNewClient({
        name: "",
        odoo_url: "",
        odoo_db: "",
        odoo_user: "",
        odoo_password: "",
      });
      setShowAddModal(false);
    } catch (err) {
      console.error("Error al guardar cliente:", err);
    } finally {
      setIsSaving(false);
    }
  };

  const handleTestConnection = async (id: string) => {
    const client = clients.find((c) => c.id === id);
    if (!client) return;

    setTestingConnection(id);
    
    const response = await callPython("test_connection", {
      url: client.odoo_url,
      db: client.odoo_db,
      username: client.odoo_user,
      password: client.odoo_password || "admin",
    });

    setConnectionStatuses((prev) => ({
      ...prev,
      [id]: response.status === "ok" && response.data?.connected ? "connected" : "error",
    }));
    
    setTestingConnection(null);
  };

  const handleDeleteClient = async (id: string) => {
    if (confirm("¿Estás seguro de que deseas eliminar este cliente del llavero local?")) {
      try {
        await deleteClient(id);
      } catch (err) {
        console.error("Error al eliminar cliente:", err);
      }
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight">Perfiles de Clientes</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Gestiona los servidores y bases de datos Odoo de destino.
          </p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 gradient-button text-white font-semibold py-2.5 px-4 rounded-xl shadow-lg transition-all duration-300 text-sm"
        >
          <Plus className="w-4 h-4" />
          Añadir Cliente
        </button>
      </div>

      {/* Grid of Clients */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-8 h-8 border-4 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      ) : clients.length === 0 ? (
        <div className="text-center py-12 border border-dashed border-border rounded-xl space-y-3 bg-secondary/15">
          <Database className="w-10 h-10 text-muted-foreground mx-auto" />
          <h4 className="font-bold text-white text-sm">No hay perfiles registrados</h4>
          <p className="text-muted-foreground text-xs max-w-xs mx-auto">
            Registra tu primer cliente Odoo destino para comenzar con el wizard de migración.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
          {clients.map((client) => {
            const status = connectionStatuses[client.id] || "idle";
            return (
              <div
                key={client.id}
                className="bg-card hover:bg-card/80 border border-border/80 rounded-xl p-5 transition duration-200 relative group flex flex-col justify-between"
              >
                {/* Top Bar inside card */}
                <div className="flex justify-between items-start gap-4">
                  <div>
                    <h3 className="font-bold text-lg text-white group-hover:text-primary transition duration-150">
                      {client.name}
                    </h3>
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-1.5">
                      <Globe className="w-3.5 h-3.5" />
                      <span className="truncate max-w-[250px]">{client.odoo_url}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-1">
                      <Database className="w-3.5 h-3.5" />
                      <span>BD: {client.odoo_db} | User: {client.odoo_user}</span>
                    </div>
                  </div>

                  {/* Status Badge */}
                  <div className="flex items-center gap-1">
                    {status === "connected" && (
                      <span className="bg-emerald-500/10 text-emerald-400 text-[11px] font-medium px-2 py-0.5 rounded-full border border-emerald-500/20 flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3" /> Conectado
                      </span>
                    )}
                    {status === "error" && (
                      <span className="bg-red-500/10 text-red-400 text-[11px] font-medium px-2 py-0.5 rounded-full border border-red-500/20 flex items-center gap-1">
                        <XCircle className="w-3 h-3" /> Error Conexión
                      </span>
                    )}
                    {status === "idle" && (
                      <span className="bg-muted text-muted-foreground text-[11px] font-medium px-2 py-0.5 rounded-full border border-border flex items-center gap-1">
                        <AlertCircle className="w-3 h-3" /> Sin verificar
                      </span>
                    )}
                  </div>
                </div>

                {/* Bottom Actions inside card */}
                <div className="flex items-center justify-between border-t border-border mt-5 pt-4">
                  <span className="text-[11px] text-muted-foreground">
                    Último uso: {client.last_used_at}
                  </span>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleTestConnection(client.id)}
                      disabled={testingConnection === client.id}
                      className="p-2 text-muted-foreground hover:text-white bg-secondary/50 hover:bg-secondary border border-border rounded-lg transition duration-150 text-xs flex items-center gap-1"
                      title="Probar conexión"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${testingConnection === client.id ? "animate-spin" : ""}`} />
                      {testingConnection === client.id ? "Verificando..." : "Probar"}
                    </button>
                    
                    <button
                      onClick={() => handleDeleteClient(client.id)}
                      className="p-2 text-red-400 hover:text-red-300 bg-red-500/5 hover:bg-red-500/10 border border-red-500/10 rounded-lg transition duration-150"
                      title="Eliminar"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>

                    <button
                      onClick={() => onSelectClient(client.id)}
                      className="flex items-center gap-1.5 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 hover:border-primary/40 font-semibold py-1.5 px-3.5 rounded-lg transition duration-150 text-xs"
                    >
                      <Play className="w-3 h-3 fill-current" />
                      Migrar
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal Dialog */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-card border border-border max-w-lg w-full rounded-2xl shadow-2xl overflow-hidden p-6 space-y-4">
            <div>
              <h2 className="text-xl font-bold text-white">Registrar Servidor Odoo</h2>
              <p className="text-muted-foreground text-xs mt-1">
                La contraseña se almacenará de manera cifrada en la base de datos local.
              </p>
            </div>

            <form onSubmit={handleAddClient} className="space-y-3.5">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-muted-foreground">Nombre del cliente</label>
                <input
                  type="text"
                  required
                  placeholder="Ej. Distribuidora del Norte"
                  value={newClient.name}
                  onChange={(e) => setNewClient({ ...newClient, name: e.target.value })}
                  className="w-full bg-secondary/50 border border-border focus:border-primary/50 focus:ring-1 focus:ring-primary/20 rounded-lg px-3 py-2 text-sm outline-none text-white transition"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-muted-foreground">URL de Odoo (XML-RPC)</label>
                <input
                  type="url"
                  required
                  placeholder="Ej. https://mi-cliente.odoo.com"
                  value={newClient.odoo_url}
                  onChange={(e) => setNewClient({ ...newClient, odoo_url: e.target.value })}
                  className="w-full bg-secondary/50 border border-border focus:border-primary/50 focus:ring-1 focus:ring-primary/20 rounded-lg px-3 py-2 text-sm outline-none text-white transition"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground">Nombre de la BD</label>
                  <input
                    type="text"
                    required
                    placeholder="Ej. prod-db"
                    value={newClient.odoo_db}
                    onChange={(e) => setNewClient({ ...newClient, odoo_db: e.target.value })}
                    className="w-full bg-secondary/50 border border-border focus:border-primary/50 focus:ring-1 focus:ring-primary/20 rounded-lg px-3 py-2 text-sm outline-none text-white transition"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground">Usuario (Email)</label>
                  <input
                    type="text"
                    required
                    placeholder="Ej. admin@cliente.com"
                    value={newClient.odoo_user}
                    onChange={(e) => setNewClient({ ...newClient, odoo_user: e.target.value })}
                    className="w-full bg-secondary/50 border border-border focus:border-primary/50 focus:ring-1 focus:ring-primary/20 rounded-lg px-3 py-2 text-sm outline-none text-white transition"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-muted-foreground">Contraseña o API Key</label>
                <input
                  type="password"
                  required
                  placeholder="••••••••"
                  value={newClient.odoo_password}
                  onChange={(e) => setNewClient({ ...newClient, odoo_password: e.target.value })}
                  className="w-full bg-secondary/50 border border-border focus:border-primary/50 focus:ring-1 focus:ring-primary/20 rounded-lg px-3 py-2 text-sm outline-none text-white transition"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-border mt-4">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 border border-border text-muted-foreground hover:text-white rounded-lg transition text-xs font-semibold"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="gradient-button text-white font-semibold py-2 px-4 rounded-lg shadow-lg hover:shadow-primary/20 transition-all text-xs"
                >
                  {isSaving ? "Guardando..." : "Guardar Cliente"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
