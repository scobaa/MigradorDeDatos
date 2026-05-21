# Migrador Odoo

App de escritorio para migrar datos legacy (Access, Excel, SQL Server) a instancias Odoo de clientes finales. Uso interno del equipo de consultoría.

## Quick start

### Requisitos
- Node.js 20+
- Rust 1.75+ (instalar con `rustup`)
- Python 3.11+
- Tauri CLI: `cargo install tauri-cli`

### Desarrollo
```bash
# Instalar dependencias frontend
npm install

# Instalar dependencias Python
cd python-engine
pip install -r requirements.txt
cd ..

# Arrancar app en modo dev
npm run tauri dev
```

### Build
```bash
# Compilar para Windows (.exe)
npm run tauri build -- --target x86_64-pc-windows-msvc

# Compilar para Mac (.dmg)
npm run tauri build -- --target universal-apple-darwin
```

## Documentación
- `CLAUDE.md` — contexto del proyecto para Claude Code
- `docs/architecture.md` — diagrama y decisiones técnicas
- `docs/odoo-models.md` — referencia de modelos Odoo que migramos
- `docs/development.md` — guía para añadir nuevos conectores o tipos de datos
