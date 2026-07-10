import { useState, useEffect } from "react";
import {
  ArrowRight, CheckCircle2, AlertCircle, Loader2,
  Play, RotateCcw, ChevronRight, Wifi, WifiOff,
  Package, Users, BarChart3,
} from "lucide-react";
import { callPython } from "../lib/python";

// ─── Tipos ──────────────────────────────────────────────────────────────────

interface OdooCredentials {
  url: string;
  db: string;
  username: string;
  password: string;
}

interface ProgressEvent {
  done: number;
  total: number;
  action: "created" | "updated" | "skipped" | "error";
  name?: string;
  message?: string;
}

interface MigrationStats {
  created: number;
  updated: number;
  skipped: number;
  error_count: number;
  errors: Array<{ row: number; error: string }>;
}

const MODELS = [
  {
    id: "res.partner",
    label: "Contactos",
    sublabel: "Clientes y proveedores",
    icon: Users,
    color: "from-violet-500 to-purple-600",
  },
  {
    id: "product.template",
    label: "Productos",
    sublabel: "Catálogo de artículos",
    icon: Package,
    color: "from-blue-500 to-cyan-600",
  },
  {
    id: "stock.quant",
    label: "Inventario",
    sublabel: "Stock físico por ubicación",
    icon: BarChart3,
    color: "from-emerald-500 to-teal-600",
  },
];

const emptyCredentials = (): OdooCredentials => ({
  url: "", db: "", username: "", password: "",
});

const loadCredentials = (key: string): OdooCredentials => {
  try {
    const saved = localStorage.getItem(key);
    if (saved) return JSON.parse(saved);
  } catch (e) {
    console.error(`Error al cargar ${key} desde localStorage:`, e);
  }
  return emptyCredentials();
};

// ─── Subcomponente: formulario de credenciales ───────────────────────────────

function CredentialsForm({
  label,
  value,
  onChange,
  testStatus,
  onTest,
  testing,
}: {
  label: string;
  value: OdooCredentials;
  onChange: (v: OdooCredentials) => void;
  testStatus: "idle" | "ok" | "error";
  onTest: () => void;
  testing: boolean;
}) {
  const inputClass =
    "w-full bg-secondary/50 border border-border rounded-xl px-3 py-2.5 text-xs text-white placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 transition";

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-white">{label}</h3>
        <button
          onClick={onTest}
          disabled={testing || !value.url || !value.db || !value.username || !value.password}
          className="flex items-center gap-1.5 text-[11px] font-semibold px-3 py-1.5 rounded-lg border transition
            disabled:opacity-40 disabled:cursor-not-allowed
            border-border hover:border-muted-foreground/30 bg-secondary/30 hover:bg-secondary/60 text-muted-foreground hover:text-white"
        >
          {testing ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : testStatus === "ok" ? (
            <Wifi className="w-3 h-3 text-emerald-400" />
          ) : testStatus === "error" ? (
            <WifiOff className="w-3 h-3 text-red-400" />
          ) : (
            <Wifi className="w-3 h-3" />
          )}
          {testStatus === "ok" ? "Conectado" : testStatus === "error" ? "Error" : "Probar"}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-2">
        <input
          className={inputClass}
          placeholder="URL (ej. https://miodoo.com)"
          value={value.url}
          onChange={(e) => onChange({ ...value, url: e.target.value })}
        />
        <div className="grid grid-cols-2 gap-2">
          <input
            className={inputClass}
            placeholder="Base de datos"
            value={value.db}
            onChange={(e) => onChange({ ...value, db: e.target.value })}
          />
          <input
            className={inputClass}
            placeholder="Usuario"
            value={value.username}
            onChange={(e) => onChange({ ...value, username: e.target.value })}
          />
        </div>
        <input
          className={inputClass}
          type="password"
          placeholder="Contraseña / API Key"
          value={value.password}
          onChange={(e) => onChange({ ...value, password: e.target.value })}
        />
      </div>

      {testStatus === "ok" && (
        <p className="text-[11px] text-emerald-400 flex items-center gap-1">
          <CheckCircle2 className="w-3 h-3" /> Conexión establecida correctamente
        </p>
      )}
      {testStatus === "error" && (
        <p className="text-[11px] text-red-400 flex items-center gap-1">
          <AlertCircle className="w-3 h-3" /> No se pudo conectar. Revisa los datos.
        </p>
      )}
    </div>
  );
}

// ─── Página principal ────────────────────────────────────────────────────────

export default function OdooMigration() {
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // Credenciales
  const [srcCreds, setSrcCreds] = useState<OdooCredentials>(() => loadCredentials("odoo_mig_src_creds"));
  const [dstCreds, setDstCreds] = useState<OdooCredentials>(() => loadCredentials("odoo_mig_dst_creds"));
  
  useEffect(() => {
    localStorage.setItem("odoo_mig_src_creds", JSON.stringify(srcCreds));
  }, [srcCreds]);

  useEffect(() => {
    localStorage.setItem("odoo_mig_dst_creds", JSON.stringify(dstCreds));
  }, [dstCreds]);
  const [srcTestStatus, setSrcTestStatus] = useState<"idle" | "ok" | "error">("idle");
  const [dstTestStatus, setDstTestStatus] = useState<"idle" | "ok" | "error">("idle");
  const [srcTesting, setSrcTesting] = useState(false);
  const [dstTesting, setDstTesting] = useState(false);

  // Configuración de migración
  const [selectedModel, setSelectedModel] = useState("res.partner");
  const [updateExisting, setUpdateExisting] = useState(true);
  const [dryRun, setDryRun] = useState(false);

  // Progreso y resultado
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<ProgressEvent[]>([]);
  const [stats, setStats] = useState<MigrationStats | null>(null);
  const [migrationError, setMigrationError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);


  // ─── Test de conexión ──────────────────────────────────────────────────────

  const testConnection = async (
    creds: OdooCredentials,
    setStatus: (s: "idle" | "ok" | "error") => void,
    setLoading: (v: boolean) => void
  ) => {
    setLoading(true);
    setStatus("idle");
    try {
      const res = await callPython("test_connection", {
        url: creds.url, db: creds.db,
        username: creds.username, password: creds.password,
      });
      setStatus(res.status === "ok" && res.data?.connected ? "ok" : "error");
    } catch {
      setStatus("error");
    } finally {
      setLoading(false);
    }
  };

  // ─── Migración ─────────────────────────────────────────────────────────────

  const runMigration = async () => {
    setRunning(true);
    setProgress([]);
    setStats(null);
    setMigrationError(null);
    setStep(3);

    try {
      const res = await callPython("run_odoo_migration", {
        odoo_source: srcCreds,
        odoo_dest: dstCreds,
        model: selectedModel,
        dry_run: dryRun,
        options: { update_existing: updateExisting },
      });

      if (res.status === "ok") {
        setStats(res.data.stats);
        setTotal(res.data.total);
      } else {
        setMigrationError(res.error || "Error desconocido");
      }
    } catch (e: any) {
      setMigrationError(String(e));
    } finally {
      setRunning(false);
    }
  };

  // ─── UI Helpers ────────────────────────────────────────────────────────────

  const canProceedStep1 = srcTestStatus === "ok" && dstTestStatus === "ok";
  const model = MODELS.find((m) => m.id === selectedModel)!;

  const createdCount = progress.filter((p) => p.action === "created").length;
  const updatedCount = progress.filter((p) => p.action === "updated").length;
  const errorCount = progress.filter((p) => p.action === "error").length;

  const progressPercent =
    stats
      ? 100
      : total > 0
      ? Math.round((progress.length / total) * 100)
      : 0;

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-extrabold text-white tracking-tight flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-primary to-cyan-400 flex items-center justify-center shadow-lg shadow-primary/20">
            <ArrowRight className="w-5 h-5 text-white" />
          </div>
          Migración Odoo → Odoo
        </h1>
        <p className="text-xs text-muted-foreground mt-2">
          Copia registros de una instancia Odoo a otra directamente por API, sin archivos intermedios.
        </p>
      </div>

      {/* Stepper */}
      <div className="flex items-center gap-3 text-xs font-semibold">
        {["Conexiones", "Configurar", "Ejecutar"].map((label, i) => {
          const n = i + 1;
          const active = step === n;
          const done = step > n;
          return (
            <div key={n} className="flex items-center gap-2">
              <div
                className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold border transition ${
                  done
                    ? "bg-primary border-primary text-white"
                    : active
                    ? "bg-primary/10 border-primary text-primary"
                    : "bg-secondary/30 border-border text-muted-foreground"
                }`}
              >
                {done ? <CheckCircle2 className="w-3.5 h-3.5" /> : n}
              </div>
              <span className={active ? "text-white" : "text-muted-foreground"}>{label}</span>
              {i < 2 && <ChevronRight className="w-3 h-3 text-muted-foreground" />}
            </div>
          );
        })}
      </div>

      {/* STEP 1: Conexiones */}
      {step === 1 && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-secondary/20 border border-border rounded-2xl p-5">
              <CredentialsForm
                label="🔵 Odoo Origen (fuente de datos)"
                value={srcCreds}
                onChange={setSrcCreds}
                testStatus={srcTestStatus}
                onTest={() => testConnection(srcCreds, setSrcTestStatus, setSrcTesting)}
                testing={srcTesting}
              />
            </div>
            <div className="bg-secondary/20 border border-border rounded-2xl p-5">
              <CredentialsForm
                label="🟢 Odoo Destino (donde se copiarán)"
                value={dstCreds}
                onChange={setDstCreds}
                testStatus={dstTestStatus}
                onTest={() => testConnection(dstCreds, setDstTestStatus, setDstTesting)}
                testing={dstTesting}
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => setStep(2)}
              disabled={!canProceedStep1}
              className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white font-semibold py-2.5 px-5 rounded-xl transition text-xs disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-primary/20"
            >
              Siguiente
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: Configuración */}
      {step === 2 && (
        <div className="space-y-5">
          <div>
            <h2 className="text-sm font-bold text-white mb-3">¿Qué datos quieres migrar?</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {MODELS.map((m) => {
                const Icon = m.icon;
                return (
                  <button
                    key={m.id}
                    onClick={() => setSelectedModel(m.id)}
                    className={`p-4 rounded-xl border text-left transition ${
                      selectedModel === m.id
                        ? "border-primary bg-primary/5 shadow shadow-primary/10"
                        : "border-border bg-secondary/20 hover:border-muted-foreground/30"
                    }`}
                  >
                    <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${m.color} flex items-center justify-center mb-2`}>
                      <Icon className="w-4 h-4 text-white" />
                    </div>
                    <p className="text-xs font-bold text-white">{m.label}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">{m.sublabel}</p>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="bg-secondary/20 border border-border rounded-2xl p-5 space-y-4">
            <h2 className="text-sm font-bold text-white">Opciones</h2>
            <label className="flex items-center gap-3 cursor-pointer">
              <div
                onClick={() => setUpdateExisting(!updateExisting)}
                className={`w-10 h-5 rounded-full transition-colors ${
                  updateExisting ? "bg-primary" : "bg-secondary border border-border"
                } relative`}
              >
                <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  updateExisting ? "translate-x-5" : "translate-x-0.5"
                }`} />
              </div>
              <div>
                <p className="text-xs font-semibold text-white">Actualizar registros existentes</p>
                <p className="text-[10px] text-muted-foreground">Si está desactivado, solo crea registros nuevos.</p>
              </div>
            </label>

            <label className="flex items-center gap-3 cursor-pointer">
              <div
                onClick={() => setDryRun(!dryRun)}
                className={`w-10 h-5 rounded-full transition-colors ${
                  dryRun ? "bg-amber-500" : "bg-secondary border border-border"
                } relative`}
              >
                <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  dryRun ? "translate-x-5" : "translate-x-0.5"
                }`} />
              </div>
              <div>
                <p className="text-xs font-semibold text-white">Modo simulación (Dry Run)</p>
                <p className="text-[10px] text-muted-foreground">No escribe nada. Muestra cuántos registros se crearían.</p>
              </div>
            </label>
          </div>

          <div className="flex justify-between">
            <button
              onClick={() => setStep(1)}
              className="flex items-center gap-2 text-muted-foreground hover:text-white border border-border hover:border-muted-foreground/30 bg-secondary/20 font-semibold py-2.5 px-4 rounded-xl transition text-xs"
            >
              ← Atrás
            </button>
            <button
              onClick={runMigration}
              className="flex items-center gap-2 bg-primary hover:bg-primary/90 text-white font-semibold py-2.5 px-5 rounded-xl transition text-xs shadow-lg shadow-primary/20"
            >
              <Play className="w-3.5 h-3.5" />
              {dryRun ? "Simular migración" : "Iniciar migración"}
            </button>
          </div>
        </div>
      )}

      {/* STEP 3: Ejecución y resultados */}
      {step === 3 && (
        <div className="space-y-5">
          {/* Estado general */}
          <div className="bg-secondary/20 border border-border rounded-2xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {running ? (
                  <Loader2 className="w-5 h-5 text-primary animate-spin" />
                ) : stats ? (
                  <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                ) : (
                  <AlertCircle className="w-5 h-5 text-red-400" />
                )}
                <div>
                  <p className="text-sm font-bold text-white">
                    {running
                      ? "Migrando..."
                      : stats
                      ? dryRun
                        ? "Simulación completada"
                        : "Migración completada"
                      : "Error en la migración"}
                  </p>
                  <p className="text-[11px] text-muted-foreground">
                    {model.label} · {srcCreds.url} → {dstCreds.url}
                  </p>
                </div>
              </div>
              {!running && (
                <button
                  onClick={() => { setStep(2); setStats(null); setProgress([]); }}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-white border border-border hover:border-muted-foreground/30 bg-secondary/20 px-3 py-1.5 rounded-lg transition"
                >
                  <RotateCcw className="w-3 h-3" />
                  Nueva migración
                </button>
              )}
            </div>

            {/* Barra de progreso */}
            <div className="space-y-1.5">
              <div className="h-2 bg-secondary rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-primary to-cyan-400 rounded-full transition-all duration-300"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <p className="text-[10px] text-muted-foreground text-right">
                {stats ? stats.created + stats.updated + stats.skipped : progress.length}
                {total > 0 && ` / ${total}`} registros procesados
              </p>
            </div>

            {/* Contadores */}
            {(stats || progress.length > 0) && (
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "Creados", value: stats?.created ?? createdCount, color: "text-emerald-400" },
                  { label: "Actualizados", value: stats?.updated ?? updatedCount, color: "text-blue-400" },
                  { label: "Errores", value: stats?.error_count ?? errorCount, color: "text-red-400" },
                ].map((c) => (
                  <div key={c.label} className="bg-secondary/30 rounded-xl p-3 text-center border border-border">
                    <p className={`text-xl font-bold ${c.color}`}>{c.value}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">{c.label}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Errores detallados */}
          {stats && stats.errors.length > 0 && (
            <div className="bg-red-500/5 border border-red-500/20 rounded-2xl p-5 space-y-3">
              <h3 className="text-xs font-bold text-red-400 flex items-center gap-2">
                <AlertCircle className="w-4 h-4" />
                {stats.errors.length} error(es) durante la migración
              </h3>
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {stats.errors.map((err, i) => (
                  <div key={i} className="text-[10px] bg-secondary/30 rounded-lg px-3 py-2 border border-border">
                    <span className="text-muted-foreground">Fila {err.row}:</span>{" "}
                    <span className="text-red-300">{err.error}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {migrationError && (
            <div className="bg-red-500/5 border border-red-500/20 rounded-2xl p-5">
              <p className="text-xs text-red-400 font-semibold flex items-center gap-2">
                <AlertCircle className="w-4 h-4" /> {migrationError}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
