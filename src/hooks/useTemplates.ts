import { useState, useEffect } from "react";
import { db, DBTemplate } from "../lib/db";

export function useTemplates() {
  const [templates, setTemplates] = useState<DBTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTemplates = async () => {
    setLoading(true);
    try {
      const data = await db.getTemplates();
      setTemplates(data);
      setError(null);
    } catch (err: any) {
      setError(err?.toString() || "Error al cargar las plantillas de base de datos.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  const addTemplate = async (
    template: Omit<DBTemplate, "id" | "created_at">
  ): Promise<DBTemplate> => {
    try {
      const newTemplate = await db.addTemplate(template);
      setTemplates((prev) => [...prev, newTemplate]);
      return newTemplate;
    } catch (err: any) {
      setError(err?.toString() || "Error al añadir la plantilla.");
      throw err;
    }
  };

  const deleteTemplate = async (id: string): Promise<void> => {
    try {
      await db.deleteTemplate(id);
      setTemplates((prev) => prev.filter((t) => t.id !== id));
    } catch (err: any) {
      setError(err?.toString() || "Error al eliminar la plantilla.");
      throw err;
    }
  };

  return {
    templates,
    loading,
    error,
    addTemplate,
    deleteTemplate,
    refreshTemplates: fetchTemplates,
  };
}
