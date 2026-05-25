import React, { useState } from "react";
import { KeyRound, ArrowRight, ShieldCheck, Lock } from "lucide-react";

interface LoginProps {
  onLogin: () => void;
}

export default function Login({ onLogin }: LoginProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) {
      setError("Por favor, introduce la contraseña maestra.");
      return;
    }
    
    setIsLoading(true);
    setError("");

    // Simulate decrypting vault
    setTimeout(() => {
      if (password === "admin" || password.length >= 4) {
        onLogin();
      } else {
        setError("Contraseña maestra incorrecta. Inténtalo de nuevo.");
        setIsLoading(false);
      }
    }, 800);
  };

  return (
    <div className="relative min-h-screen w-full flex items-center justify-center bg-background overflow-hidden px-4">
      {/* Background Orbs */}
      <div className="absolute top-1/4 left-1/4 -translate-x-1/2 -translate-y-1/2 w-[350px] h-[350px] bg-primary/25 rounded-full blur-[80px] animate-pulse" />
      <div className="absolute bottom-1/4 right-1/4 translate-x-1/2 translate-y-1/2 w-[300px] h-[300px] bg-cyan-500/10 rounded-full blur-[90px] animate-pulse" />

      {/* Main Container */}
      <div className="w-full max-w-md glass-panel p-8 rounded-2xl shadow-2xl relative z-10 border border-white/5">
        
        {/* Brand / Logo */}
        <div className="flex flex-col items-center text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-primary to-cyan-400 flex items-center justify-center shadow-lg shadow-primary/25 mb-4">
            <KeyRound className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight font-sans">
            Migrador <span className="gradient-text">Odoo</span>
          </h1>
          <p className="text-muted-foreground text-sm mt-2">
            Base de datos local cifrada
          </p>
        </div>

        {/* Info Box */}
        <div className="bg-primary/5 border border-primary/10 rounded-xl p-4 mb-6 flex gap-3 text-xs text-muted-foreground leading-relaxed">
          <Lock className="w-5 h-5 text-primary shrink-0 mt-0.5" />
          <span>
            Las credenciales de tus clientes y el historial de migración están cifrados de forma segura en local. Necesitas tu contraseña para desbloquear el llavero.
          </span>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label className="text-xs font-semibold text-muted-foreground tracking-wider uppercase">
              Contraseña Maestra
            </label>
            <div className="relative">
              <input
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                className="w-full bg-secondary/50 border border-border focus:border-primary/50 focus:ring-1 focus:ring-primary/30 rounded-xl px-4 py-3 text-white placeholder-muted-foreground transition duration-200 outline-none pr-10"
              />
              <ShieldCheck className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground/50" />
            </div>
            {error && (
              <p className="text-red-400 text-xs mt-1 animate-pulse">{error}</p>
            )}
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full flex items-center justify-center gap-2 gradient-button text-white font-semibold py-3 px-4 rounded-xl shadow-lg hover:shadow-primary/20 transition-all duration-300 disabled:opacity-50 text-sm mt-2"
          >
            {isLoading ? (
              <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                Desbloquear Panel
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        {/* Footer */}
        <div className="text-center mt-8 text-[11px] text-muted-foreground/60">
          Uso exclusivo de consultoría interna v0.1.0
        </div>
      </div>
    </div>
  );
}
