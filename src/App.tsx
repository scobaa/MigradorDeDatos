import { useState } from "react";
import Login from "./pages/Login";
import ClientList from "./pages/ClientList";
import MigrationWizard from "./pages/MigrationWizard";
import Templates from "./pages/Templates";
import { Database, Layers, LogOut, KeyRound, Menu, X, HardDrive } from "lucide-react";

type ActivePage = "clients" | "templates" | { type: "migrate"; clientId: string };

export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [activePage, setActivePage] = useState<ActivePage>("clients");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Lock panel / Logout
  const handleLogout = () => {
    setIsLoggedIn(false);
    setActivePage("clients");
  };

  if (!isLoggedIn) {
    return <Login onLogin={() => setIsLoggedIn(true)} />;
  }

  const renderContent = () => {
    if (activePage === "clients") {
      return (
        <ClientList
          onSelectClient={(id) => setActivePage({ type: "migrate", clientId: id })}
        />
      );
    }
    if (activePage === "templates") {
      return <Templates />;
    }
    if (typeof activePage === "object" && activePage.type === "migrate") {
      return (
        <MigrationWizard
          clientId={activePage.clientId}
          onBack={() => setActivePage("clients")}
        />
      );
    }
    return null;
  };

  return (
    <div className="min-h-screen bg-[#09090b] text-foreground flex relative">
      
      {/* Mobile Menu Toggle */}
      <div className="absolute top-4 right-4 md:hidden z-40">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="p-2 bg-secondary/80 border border-border rounded-xl text-white hover:bg-secondary transition"
        >
          {sidebarOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {/* Sidebar Navigation */}
      <aside
        className={`w-[260px] shrink-0 border-r border-border bg-[#0e0e11] flex flex-col justify-between p-5 h-screen sticky top-0 z-30 transition-all duration-300 md:translate-x-0 ${
          sidebarOpen ? "translate-x-0 fixed" : "-translate-x-full absolute md:relative"
        }`}
      >
        <div className="space-y-8">
          {/* Logo / Brand */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-primary to-cyan-400 flex items-center justify-center shadow-md shadow-primary/20">
              <KeyRound className="w-5 h-5 text-white" />
            </div>
            <div>
              <span className="font-extrabold text-sm tracking-tight text-white block">
                Migrador Odoo
              </span>
              <span className="text-[9px] text-primary font-semibold uppercase tracking-wider block">
                Herramienta Consultoría
              </span>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="space-y-1.5">
            <button
              onClick={() => {
                setActivePage("clients");
                setSidebarOpen(false);
              }}
              className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold tracking-wide transition-all ${
                activePage === "clients" || (typeof activePage === "object" && activePage.type === "migrate")
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted-foreground hover:text-white hover:bg-secondary/40 border border-transparent"
              }`}
            >
              <Database className="w-4 h-4" />
              Perfiles Clientes
            </button>

            <button
              onClick={() => {
                setActivePage("templates");
                setSidebarOpen(false);
              }}
              className={`w-full flex items-center gap-3 px-3.5 py-2.5 rounded-xl text-xs font-semibold tracking-wide transition-all ${
                activePage === "templates"
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted-foreground hover:text-white hover:bg-secondary/40 border border-transparent"
              }`}
            >
              <Layers className="w-4 h-4" />
              Plantillas Mapeo
            </button>
          </nav>
        </div>

        {/* Sidebar Footer info */}
        <div className="space-y-4 pt-4 border-t border-border">
          {/* Encryption status */}
          <div className="flex items-center gap-2 px-1 text-[10px] text-muted-foreground leading-snug">
            <HardDrive className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>SQLite Local Cifrado Activo</span>
          </div>

          {/* Lock Panel / Logout button */}
          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center gap-2 bg-secondary/50 hover:bg-red-500/10 hover:text-red-400 hover:border-red-500/20 border border-border px-3.5 py-2.5 rounded-xl text-xs font-semibold transition duration-150"
          >
            <LogOut className="w-3.5 h-3.5" />
            Bloquear Panel
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 min-w-0 p-6 md:p-8 max-w-7xl mx-auto overflow-y-auto">
        <div className="animate-fade-in">
          {renderContent()}
        </div>
      </main>
    </div>
  );
}
