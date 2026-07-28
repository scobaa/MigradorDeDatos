import React, { useState, useEffect, useRef } from "react";
import {
  ArrowRight, CheckCircle2, AlertCircle, Loader2,
  Play, RotateCcw, ChevronRight, Wifi, WifiOff,
  Package, Users, BarChart3, Database, Layers,
  FileText, ShoppingCart, ShoppingBag, BookOpen
} from "lucide-react";
import { callPython } from "../lib/python";
import { useClients } from "../hooks/useClients";
import { DBClient } from "../lib/db";

// ─── Tipos ──────────────────────────────────────────────────────────────────

interface OdooCredentials {
  url: string;
  db: string;
  username: string;
  password: string;
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
    id: "all",
    label: "Migrar Todo",
    sublabel: "Todos los modelos en orden",
    icon: Layers,
    color: "from-pink-500 to-rose-600",
  },
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
  {
    id: "account.account",
    label: "Plan Contable",
    sublabel: "Cuentas contables",
    icon: Database,
    color: "from-orange-500 to-amber-600",
  },
  {
    id: "res.partner.supplier",
    label: "Proveedores",
    sublabel: "Contactos tipo proveedor",
    icon: Users,
    color: "from-indigo-500 to-blue-600",
  },
  {
    id: "account.move",
    label: "Facturas de Clientes",
    sublabel: "Facturas emitidas",
    icon: FileText,
    color: "from-blue-500 to-indigo-600",
  },
  {
    id: "account.move.supplier",
    label: "Facturas de Proveedores",
    sublabel: "Facturas recibidas",
    icon: FileText,
    color: "from-rose-500 to-red-600",
  },
  {
    id: "sale.order",
    label: "Pedidos de Venta",
    sublabel: "Pedidos a clientes",
    icon: ShoppingBag,
    color: "from-green-500 to-emerald-600",
  },
  {
    id: "purchase.order",
    label: "Pedidos de Compra",
    sublabel: "Pedidos a proveedores",
    icon: ShoppingCart,
    color: "from-amber-500 to-orange-600",
  },
  {
    id: "account.move.entry",
    label: "Asientos Contables",
    sublabel: "Apuntes manuales y diarios",
    icon: BookOpen,
    color: "from-slate-500 to-gray-600",
  },
];

const MODEL_LABELS: Record<string, string> = {
  "account.account": "Plan Contable",
  "res.partner": "Contactos",
  "product.template": "Productos",
  "stock.quant": "Inventario",
  "res.partner.supplier": "Proveedores",
  "account.move": "Facturas de Clientes",
  "account.move.supplier": "Facturas de Proveedores",
  "sale.order": "Pedidos de Venta",
  "purchase.order": "Pedidos de Compra",
  "account.move.entry": "Asientos Contables",
};

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
  clients,
}: {
  label: string;
  value: OdooCredentials;
  onChange: (v: OdooCredentials) => void;
  testStatus: "idle" | "ok" | "error";
  onTest: () => void;
  testing: boolean;
  clients: DBClient[];
}) {
  const inputClass =
    "w-full bg-secondary/50 border border-border rounded-xl px-3 py-2.5 text-xs text-white placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 transition";

  const handleClientSelect = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const clientId = e.target.value;
    if (!clientId) {
      // Manual
      return;
    }
    const client = clients.find(c => c.id === clientId);
    if (client) {
      onChange({
        url: client.odoo_url,
        db: client.odoo_db,
        username: client.odoo_user,
        password: client.odoo_password || "",
      });
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-2">
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

      {clients.length > 0 && (
        <select
          onChange={handleClientSelect}
          className="w-full bg-secondary/50 border border-border rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-primary/50 cursor-pointer appearance-none"
          defaultValue=""
        >
          <option value="" disabled>Seleccionar cliente guardado...</option>
          {clients.map(c => (
            <option key={c.id} value={c.id}>{c.name} ({c.odoo_db})</option>
          ))}
          <option value="">Introducir manualmente</option>
        </select>
      )}

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
  const { clients } = useClients();

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
  const [sendEmail, setSendEmail] = useState(false);
  const [notificationEmail, setNotificationEmail] = useState("");

  // Progreso y resultado
  const [running, setRunning] = useState(false);
  const [progressNum, setProgressNum] = useState(0);
  const [progressLabel, setProgressLabel] = useState("");
  const [logs, setLogs] = useState<string[]>([]);
  const [stats, setStats] = useState<MigrationStats | null>(null);
  const [migrationError, setMigrationError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [perModelStats, setPerModelStats] = useState<Record<string, MigrationStats & { total: number; status: string }> | null>(null);


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

  const logsEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll logs
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const runMigration = async () => {
    if (running) return;
    setRunning(true);
    setMigrationError(null);
    setStats(null);
    setPerModelStats({});
    setProgressNum(0);
    setProgressLabel("");
    setLogs([]);
    setStep(3);

    const apiBase = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
      ? "http://127.0.0.1:8000" : "";

    // ── 1. Lanzar la migración en segundo plano ────────────────────────────
    let jobId: string;
    try {
      const startRes = await fetch(`${apiBase}/api/start_job`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          command: "run_odoo_migration",
          session_token: (await import("../lib/auth")).getSessionToken() ?? undefined,
          args: {
            odoo_source: srcCreds,
            odoo_dest: dstCreds,
            model: selectedModel,
            dry_run: dryRun,
            options: {
              update_existing: updateExisting,
              send_email: sendEmail,
              notification_email: notificationEmail || undefined,
            },
          },
        }),
      });
      const startData = await startRes.json();
      if (!startRes.ok || startData.status !== "ok" || !startData.job_id) {
        setMigrationError(startData.error || "No se pudo lanzar la migración en segundo plano.");
        setRunning(false);
        return;
      }
      jobId = startData.job_id;
    } catch (e: any) {
      setMigrationError(`Error de conexión al arrancar la migración: ${e.message}`);
      setRunning(false);
      return;
    }

    // ── 2. Polling del estado del job ──────────────────────────────────────
    let logOffset = 0;

    const intervalId = setInterval(async () => {
      try {
        const res = await fetch(`${apiBase}/api/job/${jobId}?log_offset=${logOffset}`);
        if (!res.ok) return;
        const data = await res.json();

        // Actualizar offset de logs
        if (data.next_log_offset !== undefined) logOffset = data.next_log_offset;

        // Procesar logs nuevos
        const displayLogs: string[] = [];
        for (const line of (data.logs ?? []) as string[]) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
            try {
              const parsed = JSON.parse(trimmed);
              if (parsed?.action === "warning" && parsed.message) {
                displayLogs.push(`⚠️ AVISO: ${parsed.message}`);
              }
              // Los eventos de progreso los maneja el campo `progress` del job
              continue;
            } catch { /* no es JSON, mostrar como texto */ }
          }
          // Filtrar el token __FINAL_RESPONSE__ de los logs visibles
          if (trimmed.includes("__FINAL_RESPONSE__:")) continue;
          displayLogs.push(line);
        }
        if (displayLogs.length > 0) setLogs(prev => [...prev, ...displayLogs]);

        // Actualizar barra de progreso desde el campo progress del job
        const prog = data.progress ?? {};
        if (prog.total > 0 && data.status === "running") {
          setProgressNum(Math.min(Math.round((prog.done / prog.total) * 100), 99));
          if (prog.model) setProgressLabel(MODEL_LABELS[prog.model] ?? prog.model);
        }

        // ── Trabajo terminado ──────────────────────────────────────────────
        if (data.status === "done") {
          clearInterval(intervalId);
          setProgressNum(100);
          setProgressLabel("");
          const result = data.result ?? {};
          setStats(result.stats ?? null);
          setTotal(result.total ?? 0);
          if (result.per_model) setPerModelStats(result.per_model);
          setRunning(false);
          return;
        }

        if (data.status === "error") {
          clearInterval(intervalId);
          setMigrationError(data.error || "El proceso finalizó con error.");
          setRunning(false);
          return;
        }

      } catch { /* ignorar errores de red transitorios */ }
    }, 1000);
  };

  // ─── UI Helpers ────────────────────────────────────────────────────────────

  const canProceedStep1 = srcTestStatus === "ok" && dstTestStatus === "ok";
  const model = MODELS.find((m) => m.id === selectedModel) ?? MODELS[0];

  const progressPercent = stats ? 100 : progressNum;

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
                clients={clients}
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
                clients={clients}
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

            <div className="pt-2 border-t border-border space-y-2">
              <label className="flex items-center gap-3 cursor-pointer">
                <div
                  onClick={() => setSendEmail(!sendEmail)}
                  className={`w-10 h-5 rounded-full transition-colors ${
                    sendEmail ? "bg-primary" : "bg-secondary border border-border"
                  } relative`}
                >
                  <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                    sendEmail ? "translate-x-5" : "translate-x-0.5"
                  }`} />
                </div>
                <div>
                  <p className="text-xs font-semibold text-white">Enviar correo de notificación al finalizar</p>
                  <p className="text-[10px] text-muted-foreground">Envía un resumen completo y logs por correo al terminar.</p>
                </div>
              </label>
              {sendEmail && (
                <div className="pl-13 pt-1 flex items-center gap-3">
                  <span className="text-[10px] text-muted-foreground">Destino:</span>
                  <input
                    type="email"
                    value={notificationEmail}
                    onChange={(e) => setNotificationEmail(e.target.value)}
                    placeholder="ejemplo@empresa.com"
                    className="bg-secondary/50 border border-border rounded-lg px-2.5 py-1 text-xs text-white placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 font-mono w-64"
                  />
                </div>
              )}
            </div>
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
                    {selectedModel === "all" ? "Todos los modelos" : model.label} · {srcCreds.url} → {dstCreds.url}
                  </p>
                </div>
              </div>
              {!running && (
                <button
                  onClick={() => { setStep(2); setStats(null); setProgressNum(0); }}
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
                  className="h-full bg-gradient-to-r from-primary to-cyan-400 rounded-full transition-all duration-500"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <div className="flex items-center justify-between mt-1">
                {running && progressLabel ? (
                  <p className="text-[10px] text-primary/80 font-medium">Migrando: {progressLabel}...</p>
                ) : <span />}
                <p className="text-[10px] text-muted-foreground">
                  {stats ? stats.created + stats.updated + stats.skipped : `${progressPercent}%`}
                  {stats && total > 0 && ` / ${total}`} {stats ? "registros procesados" : "completado"}
                </p>
              </div>
            </div>

            {/* Consola de logs */}
            {logs.length > 0 && (
              <div className="bg-black/90 text-green-400 font-mono text-[11px] p-4 rounded-xl h-64 overflow-y-auto space-y-1 border border-border shadow-inner">
                {logs.map((log, i) => (
                  <div key={i} className={log.includes("⚠️") || log.toLowerCase().includes("warning") ? "text-yellow-400" : log.toLowerCase().includes("error") ? "text-red-400" : ""}>
                    {log}
                  </div>
                ))}
                <div ref={logsEndRef} />
              </div>
            )}

            {/* Contadores */}
            {stats && (
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: "Creados", value: stats.created, color: "text-emerald-400" },
                  { label: "Actualizados", value: stats.updated, color: "text-blue-400" },
                  { label: "Errores", value: stats.error_count, color: "text-red-400" },
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

          {/* Tabla de desglose por modelo (modo Migrar Todo) */}
          {perModelStats && (
            <div className="bg-secondary/20 border border-border rounded-2xl p-5 space-y-3">
              <h3 className="text-xs font-bold text-white flex items-center gap-2">
                <Layers className="w-4 h-4 text-primary" />
                Desglose por modelo
              </h3>
              <div className="space-y-2">
                {Object.entries(perModelStats).map(([modelKey, ms]) => (
                  <div key={modelKey} className="grid grid-cols-5 gap-2 items-center bg-secondary/30 rounded-xl px-3 py-2 border border-border">
                    <div className="col-span-2">
                      <p className="text-xs font-semibold text-white">{MODEL_LABELS[modelKey] ?? modelKey}</p>
                      <p className="text-[10px] text-muted-foreground">{modelKey}</p>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-bold text-emerald-400">{ms.created}</p>
                      <p className="text-[9px] text-muted-foreground">Creados</p>
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-bold text-blue-400">{ms.updated}</p>
                      <p className="text-[9px] text-muted-foreground">Actualizados</p>
                    </div>
                    <div className="text-center">
                      <p className={`text-sm font-bold ${ms.error_count > 0 ? "text-red-400" : "text-muted-foreground"}`}>{ms.error_count}</p>
                      <p className="text-[9px] text-muted-foreground">Errores</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
