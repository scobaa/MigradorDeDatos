import React, { useState } from "react";
import { LogIn, UserPlus, KeyRound, Mail, AlertCircle, Database } from "lucide-react";

interface LoginProps {
  onLogin: (token: string) => void;
}

export default function Login({ onLogin }: LoginProps) {
  const [isRegistering, setIsRegistering] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError("Rellena todos los campos.");
      return;
    }
    setError(null);
    setLoading(true);

    try {
      const command = isRegistering ? "auth_register" : "auth_login";
      const apiBase = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000' : '';
      
      const res = await fetch(`${apiBase}/api`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, args: { email, password } }),
      });
      
      if (!res.ok) throw new Error("Error conectando con el servidor");
      const parsed = await res.json();
      
      if (parsed.status === "error") {
        throw new Error(parsed.error);
      }
      
      onLogin(parsed.data.token);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] flex items-center justify-center p-4">
      <div className="absolute inset-0 z-0">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/20 rounded-full blur-[120px] opacity-50 animate-pulse" />
        <div className="absolute bottom-1/4 right-1/4 w-[30rem] h-[30rem] bg-cyan-500/10 rounded-full blur-[150px] opacity-50" />
      </div>

      <div className="relative z-10 w-full max-w-md">
        <div className="text-center mb-10 space-y-3">
          <div className="w-20 h-20 bg-primary/10 rounded-3xl mx-auto flex items-center justify-center border border-primary/20 shadow-[0_0_40px_rgba(var(--primary-rgb),0.3)]">
            <Database className="w-10 h-10 text-primary" />
          </div>
          <h1 className="text-4xl font-black text-transparent bg-clip-text bg-gradient-to-br from-white to-white/60">
            MigradorDeDatos
          </h1>
          <p className="text-muted-foreground text-sm font-medium">
            Accede a tu panel para gestionar tus clientes de Odoo
          </p>
        </div>

        <div className="bg-secondary/40 backdrop-blur-xl border border-border p-8 rounded-3xl shadow-2xl">
          <h2 className="text-2xl font-bold text-white mb-6">
            {isRegistering ? "Crear una cuenta" : "Iniciar Sesión"}
          </h2>

          {error && (
            <div className="mb-6 bg-red-500/10 border border-red-500/20 text-red-400 p-3 rounded-xl flex items-center gap-3 text-sm">
              <AlertCircle className="w-5 h-5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider pl-1">
                Correo Electrónico
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                  <Mail className="w-5 h-5 text-muted-foreground" />
                </div>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ejemplo@empresa.com"
                  className="w-full bg-black/40 border border-border rounded-xl py-3 pl-11 pr-4 text-white focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all placeholder:text-muted-foreground/40"
                  required
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider pl-1">
                Contraseña
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                  <KeyRound className="w-5 h-5 text-muted-foreground" />
                </div>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full bg-black/40 border border-border rounded-xl py-3 pl-11 pr-4 text-white focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all placeholder:text-muted-foreground/40"
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full gradient-button text-white font-bold py-3.5 px-4 rounded-xl shadow-lg hover:shadow-primary/20 transition-all duration-300 mt-4 flex items-center justify-center gap-2 group disabled:opacity-70"
            >
              {loading ? (
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : isRegistering ? (
                <>
                  <UserPlus className="w-5 h-5 group-hover:scale-110 transition-transform" />
                  Registrarse
                </>
              ) : (
                <>
                  <LogIn className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                  Entrar al Panel
                </>
              )}
            </button>
          </form>

          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={() => {
                setIsRegistering(!isRegistering);
                setError(null);
              }}
              className="text-xs text-muted-foreground hover:text-white transition-colors"
            >
              {isRegistering
                ? "¿Ya tienes cuenta? Inicia sesión aquí"
                : "¿No tienes cuenta? Regístrate ahora"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
