import { useTemplates } from "../hooks/useTemplates";
import { Layers, Trash2, Calendar, CheckCircle } from "lucide-react";

export default function Templates() {
  const { templates, loading, deleteTemplate } = useTemplates();

  const handleDelete = async (id: string) => {
    if (confirm("¿Estás seguro de que deseas eliminar esta plantilla de mapeo?")) {
      try {
        await deleteTemplate(id);
      } catch (err) {
        console.error("Error al eliminar la plantilla:", err);
      }
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-extrabold tracking-tight">Plantillas de Mapeo</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Guarda las asociaciones de columnas para reutilizarlas en bases de datos con la misma estructura.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-8 h-8 border-4 border-primary/30 border-t-primary rounded-full animate-spin" />
        </div>
      ) : templates.length === 0 ? (
        <div className="text-center py-12 border border-dashed border-border rounded-xl space-y-3 bg-secondary/15">
          <Layers className="w-10 h-10 text-muted-foreground mx-auto" />
          <h4 className="font-bold text-white text-sm">No hay plantillas de mapeo guardadas</h4>
          <p className="text-muted-foreground text-xs max-w-xs mx-auto">
            Las plantillas se crean automáticamente al finalizar con éxito el paso de mapeo en el asistente de migración.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {templates.map((t) => (
            <div
              key={t.id}
              className="bg-card border border-border/80 rounded-xl p-5 hover:border-primary/40 transition duration-150 flex flex-col justify-between"
            >
              <div>
                <div className="flex justify-between items-start">
                  <span className="bg-primary/10 text-primary border border-primary/25 text-[10px] font-semibold tracking-wider uppercase px-2 py-0.5 rounded">
                    {t.source_type}
                  </span>
                  <button
                    onClick={() => handleDelete(t.id)}
                    className="p-1.5 text-muted-foreground hover:text-red-400 hover:bg-red-500/10 rounded-lg transition duration-150"
                    title="Eliminar plantilla"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>

                <h3 className="font-bold text-white text-base mt-3 group-hover:text-primary transition duration-150">
                  {t.name}
                </h3>

                <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-3">
                  <Layers className="w-3.5 h-3.5" />
                  <span>{t.mapping_count} campos mapeados</span>
                </div>
              </div>

              <div className="flex items-center justify-between border-t border-border mt-5 pt-3.5 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Calendar className="w-3.5 h-3.5" />
                  {t.created_at}
                </span>
                <span className="flex items-center gap-1 text-emerald-400 font-medium">
                  <CheckCircle className="w-3 h-3" /> Activo
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
