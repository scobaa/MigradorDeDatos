# Migrador Odoo — Contexto del proyecto

## ¿Qué es esto?

App de escritorio (Windows + Mac) que usan los consultores de la empresa para migrar datos desde sistemas legacy (Microsoft Access, Excel/CSV, SQL Server, MySQL, otros ERPs) hacia instancias de Odoo de clientes finales.

Los datos migrados van por capas:
1. Clientes (`res.partner`) — FASE ACTUAL
2. Productos (`product.template`, `product.product`)
3. Stock inicial (`stock.quant`)
4. Facturas y asientos contables (`account.move`) — lo más complejo
5. Listas de precios, impuestos, cuentas contables

## Stack técnico

- **Tauri** (Rust) como contenedor de la app de escritorio
- **React + TypeScript** para el frontend
- **shadcn/ui + Tailwind** para componentes UI
- **Python 3.11+** como motor de migración (corre como sidecar)
- **SQLite cifrado** para perfiles de cliente, plantillas y logs locales
- **API XML-RPC de Odoo** para escribir en las instancias destino
- **API de Claude (Anthropic)** para mapeo automático de columnas

## Estructura del repo

```
odoo-migrator/
├── CLAUDE.md                  ← este fichero
├── src-tauri/                 ← Rust + Tauri (orquestador)
│   ├── src/
│   │   ├── main.rs            ← entry point
│   │   └── commands.rs        ← invoca el motor Python
│   └── tauri.conf.json
├── src/                       ← Frontend React
│   ├── pages/
│   │   ├── Login.tsx
│   │   ├── ClientList.tsx
│   │   ├── MigrationWizard.tsx
│   │   └── Templates.tsx
│   ├── components/            ← componentes UI reutilizables
│   ├── hooks/                 ← React hooks
│   └── lib/                   ← utilidades (cliente Tauri, etc.)
├── python-engine/             ← Motor de migración en Python
│   ├── main.py                ← CLI que invoca Tauri
│   ├── connectors/            ← lectura de orígenes
│   │   ├── access.py
│   │   ├── excel.py
│   │   ├── csv.py
│   │   └── sql.py
│   ├── transformers/          ← limpieza y validación
│   │   ├── partners.py
│   │   ├── products.py
│   │   └── invoices.py
│   ├── migrator/              ← escritura en Odoo
│   │   ├── odoo_client.py
│   │   └── ai_mapper.py       ← integración con Claude para mapeo
│   └── requirements.txt
└── docs/                      ← documentación interna
```

## Convenciones de código

### Python
- PEP 8, líneas máximo 100 caracteres
- Type hints obligatorios en funciones públicas
- Logging con `logging` (no print)
- Manejo de errores explícito: nunca dejar excepciones sin capturar al llamar a Odoo
- Tests con pytest en `python-engine/tests/`

### TypeScript / React
- Componentes funcionales con hooks (no class components)
- Props tipadas con interfaces
- shadcn/ui para componentes; nunca CSS suelto, solo Tailwind
- Estado global con Zustand (no Redux, no Context para todo)

### Comunicación Tauri ↔ Python
- El frontend invoca comandos Tauri (Rust)
- Rust lanza el motor Python como subproceso y recoge stdout/stderr
- Python devuelve JSON estructurado: `{"status": "ok|error", "data": ..., "logs": [...]}`

## Reglas de negocio importantes

### Odoo
- Siempre usar XML-RPC vía `xmlrpc.client` (estándar Python)
- Antes de crear, comprobar con `check_access_rights` si la operación está permitida
- Para campos One2many: usar `(0, 0, vals)` para crear, `(6, 0, [ids])` para reemplazar
- Para `account.move`: crear en estado `draft`, luego `action_post`
- `account.move`: el campo `date` se resetea al confirmar, hay que forzarlo después si es histórico

### Identificación de duplicados (res.partner)
Prioridad para considerar que un partner ya existe:
1. Mismo `vat` (NIF/CIF normalizado)
2. Mismo `name` exacto + `is_company` coincidente
3. Mismo `ref` (referencia externa)

### Limpieza de datos comunes
- NIFs: quitar espacios, guiones y puntos, mayúsculas, prefijo país (ES si español)
- Teléfonos: quitar extensiones, normalizar
- Emails: minúsculas, validar formato regex
- Empresa vs persona: heurística por CIF (empieza por letra) o keywords (S.L., S.A., etc.)

## Seguridad y privacidad

- **Los datos del cliente NUNCA salen del portátil del consultor**
- Credenciales de Odoo en SQLite cifrado con clave maestra del usuario
- Los ficheros del cliente (Access, Excel) se leen en local, no se suben a ningún lado
- Solo las **plantillas de mapeo** (metadatos sobre nombres de columna) pueden sincronizarse
  entre consultores, nunca los datos en sí
- La API de Claude se llama solo con **nombres de columna**, jamás con valores reales

## Flujo del usuario (UX)

1. Abre la app → login local con clave maestra
2. Lista de clientes guardados (cada uno con URL Odoo, BD, credenciales cifradas)
3. Selecciona un cliente o crea uno nuevo → prueba la conexión a Odoo
4. Wizard de migración:
   - Paso 1: Seleccionar tipo (clientes / productos / facturas / etc.)
   - Paso 2: Seleccionar fuente (subir Excel, conectar SQL, abrir Access)
   - Paso 3: Mapeo automático con IA + revisión manual
   - Paso 4: Vista previa de los primeros 10 registros transformados
   - Paso 5: Ejecutar en dry-run (sin escribir)
   - Paso 6: Ejecutar real con barra de progreso y log en vivo
   - Paso 7: Resumen con creados / actualizados / omitidos / errores
5. Historial de migraciones por cliente, descargable como JSON / CSV

## Fases del desarrollo

- [x] **Fase 0:** Scaffolding inicial + decisión de stack
- [ ] **Fase 1:** Migración de `res.partner` con UI completa (2 semanas)
- [ ] **Fase 2:** IA para mapeo + soporte Access y SQL (2 semanas)
- [ ] **Fase 3:** Migración de productos y stock (3 semanas)
- [ ] **Fase 4:** Migración de facturas y asientos contables (3-4 semanas)
- [ ] **Fase 5:** Sincronización de plantillas entre consultores (opcional)

## Cómo trabajar con Claude Code en este repo

1. Lee siempre este CLAUDE.md primero
2. Antes de crear código nuevo, busca si ya existe algo similar (`grep -r`)
3. Para nuevas pantallas React, usa los componentes de `src/components/ui/`
   (shadcn/ui ya instalado)
4. Para nuevos conectores de datos, sigue el patrón de `python-engine/connectors/excel.py`
5. Para tests: cada función pública del motor Python debe tener al menos un test
6. **No hardcodear credenciales nunca**, leer siempre de SQLite cifrado
