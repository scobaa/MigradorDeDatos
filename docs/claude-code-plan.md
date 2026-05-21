# Plan de trabajo con Claude Code

Este documento es la guía paso a paso para arrancar el proyecto con Claude Code. Cada bloque es un prompt que puedes pegar tal cual.

## Prerequisitos antes de empezar

Instalar Claude Code:
```bash
npm install -g @anthropic-ai/claude-code
```

Luego en la raíz del proyecto:
```bash
claude
```

Claude Code leerá automáticamente `CLAUDE.md` y entenderá el contexto.

---

## Sesión 1: Scaffolding Tauri + React (1-2 horas)

### Prompt 1.1
```
Lee CLAUDE.md y README.md. Necesito que inicialices el proyecto Tauri + React + TypeScript en la raíz del repo, manteniendo la estructura de carpetas ya existente (src/, src-tauri/, python-engine/). Usa Vite como bundler y Tailwind + shadcn/ui. Instala las dependencias y verifica que `npm run tauri dev` arranca una ventana en blanco.
```

### Prompt 1.2
```
Configura shadcn/ui con un tema neutro. Instala los componentes que vamos a necesitar: button, input, dialog, select, table, toast, progress, card, form, label, badge, tabs. Crea un layout base con sidebar izquierdo (220px) y área principal, como el mockup que tenemos en mente.
```

### Prompt 1.3
```
Crea las 4 rutas principales con React Router:
- /login — pantalla de login local con clave maestra
- /clients — lista de clientes guardados (vista por defecto tras login)
- /clients/:id/migrate — wizard de migración
- /templates — gestión de plantillas de mapeo

Mock data por ahora, sin conectar a SQLite todavía.
```

---

## Sesión 2: Base de datos local SQLite cifrada

### Prompt 2.1
```
Necesitamos guardar perfiles de cliente (URL Odoo, db, usuario, password) en SQLite local cifrado. Usa el plugin oficial de Tauri `tauri-plugin-sql` y cifra el password con la API de keyring del sistema (`tauri-plugin-stronghold` o equivalente). El esquema debe tener:

- clients (id, name, odoo_url, odoo_db, odoo_user, odoo_password_encrypted, created_at, last_used_at)
- templates (id, name, source_type, mapping_json, created_at)
- migrations (id, client_id, type, source_file, status, started_at, finished_at, log_path)

Crea las migraciones y un hook `useClients()` que las cargue.
```

---

## Sesión 3: Comunicación Tauri ↔ Python

### Prompt 3.1
```
Necesito que el frontend pueda invocar el motor Python que está en python-engine/main.py.

En src-tauri/src/commands.rs crea un comando Tauri `run_python` que:
1. Reciba { command: string, args: object }
2. Lance el script python-engine/main.py como subproceso
3. Le pase el JSON por stdin
4. Lea stdout (JSON estructurado) y stderr (logs en vivo)
5. Devuelva el JSON parseado al frontend

Para desarrollo Python lo invocamos directamente (`python python-engine/main.py`). Para producción ya empaquetaremos con PyOxidizer. Documenta eso en docs/development.md.

Crea también un wrapper TypeScript en src/lib/python.ts que tipice los comandos disponibles.
```

### Prompt 3.2
```
Conecta el botón "Probar conexión" del formulario de nuevo cliente al comando Python `test_connection`. Muestra un toast verde si OK y rojo con el mensaje de error si falla.
```

---

## Sesión 4: Migración de res.partner (núcleo de la fase 1)

### Prompt 4.1
```
Lee docs/odoo-models.md sección res.partner. En python-engine implementa:

1. `connectors/excel.py` y `connectors/csv.py` — leen el fichero y devuelven un DataFrame de pandas más metadatos (columnas, num filas, 10 filas de muestra)
2. `transformers/partners.py` — recibe un dict de fila y un mapeo de columnas, devuelve un dict listo para `res.partner.create()`. Aplica las limpiezas descritas en CLAUDE.md (NIF, teléfono, email, empresa vs persona)
3. `migrator/partners.py` — orquesta el proceso: lee fichero → transforma → busca duplicado → crea o actualiza. Reporta progreso por stderr en formato `{"progress": N, "total": M, "current_row": ...}`

Implementa los handlers de main.py: `analyze_source`, `preview_migration`, `run_migration` para tipo "partners".
Añade tests unitarios en python-engine/tests/test_partners_transformer.py.
```

### Prompt 4.2
```
Construye el wizard de migración paso a paso en src/pages/MigrationWizard.tsx:

Paso 1 — Tipo: solo "Clientes" disponible (los demás grises con tooltip "próximamente")
Paso 2 — Fuente: dropzone para arrastrar Excel/CSV, llama a `analyze_source` y muestra columnas detectadas
Paso 3 — Mapeo: tabla editable origen → destino. Cada fila tiene un Select con los campos de res.partner. Por ahora sin IA, solo manual.
Paso 4 — Vista previa: invoca `preview_migration` y muestra una tabla con las 10 primeras filas ya transformadas
Paso 5 — Ejecutar: barra de progreso conectada al stream de stderr del proceso Python. Permite cancelar.
Paso 6 — Resumen: stats (creados/actualizados/omitidos/errores) + botón para descargar log JSON.

Usa un componente Stepper de shadcn o monta uno simple con tabs deshabilitados.
```

---

## Sesión 5: Integración con la API de Claude para mapeo automático

### Prompt 5.1
```
En python-engine/migrator/ai_mapper.py crea una función `suggest_mapping(source_columns, target_model)` que:

1. Reciba la lista de columnas detectadas + el modelo destino ("res.partner")
2. Llame a la API de Claude (modelo claude-sonnet-4-5) con un system prompt que explica el modelo Odoo y los campos esperados
3. Devuelva un dict {columna_origen: {odoo_field: str, confidence: float, reasoning: str}}
4. NUNCA envíe valores de las celdas, solo nombres de columna

La API key se lee de una variable de entorno ANTHROPIC_API_KEY (que en producción guardamos en el keyring del sistema operativo).

Conecta un botón "Sugerir mapeo con IA" en el Paso 3 del wizard que rellene automáticamente los selects con la sugerencia, mostrando un badge de confianza (verde >85%, ámbar 60-85%, rojo <60%).
```

---

## Sesión 6: Empaquetado y distribución

### Prompt 6.1
```
Empaqueta el motor Python con PyOxidizer o pyinstaller en un binario único que se incluya como recurso en el bundle Tauri (sección `bundle.resources` en tauri.conf.json). Modifica src-tauri/src/commands.rs para invocar el binario empaquetado en producción y el `python main.py` directo en dev.

Configura el workflow de GitHub Actions para compilar releases Windows (.exe) y Mac (.dmg) automáticamente al hacer tag v*.
```

---

## Notas para Claude Code

- Cada prompt está pensado para una sesión coherente. No los mezcles.
- Si algo no encaja con CLAUDE.md, pregunta antes de inventar.
- Mantén CLAUDE.md y docs/odoo-models.md actualizados con cada cambio relevante.
- Antes de ejecutar `npm install` o `pip install` de paquetes nuevos, comprueba que estén en requirements.txt o package.json.
