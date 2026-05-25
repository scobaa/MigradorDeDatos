import { useState, useEffect } from "react";
import { db, DBClient } from "../lib/db";

export function useClients() {
  const [clients, setClients] = useState<DBClient[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchClients = async () => {
    setLoading(true);
    try {
      const data = await db.getClients();
      setClients(data);
      setError(null);
    } catch (err: any) {
      setError(err?.toString() || "Error al leer clientes de base de datos.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchClients();
  }, []);

  const addClient = async (
    client: Omit<DBClient, "id" | "created_at" | "last_used_at">
  ): Promise<DBClient> => {
    try {
      const newClient = await db.addClient(client);
      setClients((prev) => [...prev, newClient]);
      return newClient;
    } catch (err: any) {
      setError(err?.toString() || "Error al añadir el cliente.");
      throw err;
    }
  };

  const deleteClient = async (id: string): Promise<void> => {
    try {
      await db.deleteClient(id);
      setClients((prev) => prev.filter((c) => c.id !== id));
    } catch (err: any) {
      setError(err?.toString() || "Error al eliminar el cliente.");
      throw err;
    }
  };

  const updateClientLastUsed = async (id: string): Promise<void> => {
    try {
      await db.updateClientLastUsed(id);
      // Recargar clientes para reflejar la última fecha de uso modificada
      const data = await db.getClients();
      setClients(data);
    } catch (err: any) {
      setError(err?.toString() || "Error al actualizar la última fecha de uso.");
    }
  };

  return {
    clients,
    loading,
    error,
    addClient,
    deleteClient,
    updateClientLastUsed,
    refreshClients: fetchClients,
  };
}
