# Modelos Odoo — referencia para el migrador

Esta es la referencia rápida de los modelos Odoo que tocamos, los campos clave y las trampas conocidas. **Mantener actualizada cuando se añadan modelos.**

---

## res.partner — Clientes y proveedores

### Campos mínimos para crear
| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `name` | Char | Sí | Razón social o nombre |
| `is_company` | Bool | No | True empresa, False persona |
| `vat` | Char | No | NIF/CIF con prefijo país (`ES12345678A`) |
| `email` | Char | No | Validar formato |
| `phone` | Char | No | Limpiar extensiones |
| `mobile` | Char | No | |
| `street` | Char | No | Dirección |
| `city` | Char | No | |
| `zip` | Char | No | Código postal |
| `country_id` | Many2one → `res.country` | No | Usar ID, no nombre |
| `state_id` | Many2one → `res.country.state` | No | Depende de country_id |
| `customer_rank` | Int | No | 1 si es cliente |
| `supplier_rank` | Int | No | 1 si es proveedor |
| `ref` | Char | No | Referencia externa (útil para idempotencia) |

### Deduplicación
Orden de prioridad:
1. `vat` igual (normalizado)
2. `name` exacto + `is_company` coincide
3. `ref` igual

---

## product.template / product.product — Productos

### Notas críticas
- `product.template` es la plantilla (modelo), `product.product` son las variantes
- Al crear un `product.template` se crea automáticamente un `product.product` por defecto
- Para migrar lo más simple es crear `product.template` directamente

### Campos mínimos
| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `name` | Char | Sí | |
| `default_code` | Char | No | SKU / referencia interna |
| `type` | Selection | Sí | `consu` (consumible), `service`, `product` (almacenable) |
| `list_price` | Float | No | PVP |
| `standard_price` | Float | No | Coste |
| `uom_id` | Many2one | Sí | Unidad de medida, por defecto `Units` (id=1) |
| `uom_po_id` | Many2one | Sí | Unidad compra |
| `categ_id` | Many2one | Sí | Categoría producto |
| `taxes_id` | Many2many | No | Impuestos venta `[(6, 0, [ids])]` |
| `supplier_taxes_id` | Many2many | No | Impuestos compra |
| `barcode` | Char | No | EAN/UPC, único |

---

## account.move — Facturas y asientos contables

### Campos críticos
| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `move_type` | Selection | Sí | Ver tabla abajo |
| `partner_id` | Many2one | Si factura | El cliente/proveedor |
| `invoice_date` | Date | Si factura | Fecha de la factura original |
| `invoice_date_due` | Date | No | Vencimiento |
| `journal_id` | Many2one | Sí | Diario contable |
| `currency_id` | Many2one | No | Por defecto del diario |
| `ref` | Char | No | Referencia externa (núm. factura original) |
| `invoice_line_ids` | One2many | Sí factura | Líneas de factura |
| `line_ids` | One2many | Sí asiento | Líneas contables (debe/haber) |
| `date` | Date | Sí asiento | Fecha contable (¡se resetea al confirmar!) |

### Valores de `move_type`
| Valor | Significado |
|---|---|
| `out_invoice` | Factura de cliente |
| `out_refund` | Nota de crédito cliente (abono) |
| `in_invoice` | Factura de proveedor |
| `in_refund` | Nota de crédito proveedor |
| `entry` | Asiento contable manual (sin factura) |

### Trampas conocidas (importantes)

1. **`invoice_line_ids` vs `line_ids` no son lo mismo**
   - `invoice_line_ids`: líneas visibles de la factura (productos, cantidades)
   - `line_ids`: líneas contables completas (incluye contrapartidas y IVA)
   - Para facturas: usar `invoice_line_ids`, Odoo genera `line_ids` al confirmar
   - Para asientos manuales: usar `line_ids` directamente

2. **El estado `posted` bloquea modificaciones**
   - Una vez confirmada, no se puede editar
   - Para corregir hay que llamar `button_draft` → modificar → `action_post`

3. **Descuadres debe/haber**
   - Odoo no valida hasta `action_post`
   - En migración masiva, siempre comprobar suma debe == suma haber ANTES de enviar

4. **Fecha de asiento histórico**
   - Al llamar `action_post`, Odoo puede resetear `date` al día actual
   - Solución: hacer `write({'date': fecha_original})` DESPUÉS de `action_post` si hace falta

### Flujo correcto para crear una factura

```python
# 1. Crear en borrador
invoice_id = odoo.create('account.move', {
    'move_type': 'out_invoice',
    'partner_id': partner_id,
    'invoice_date': '2024-01-15',
    'ref': 'FAC-001',
    'journal_id': journal_ventas_id,
    'invoice_line_ids': [(0, 0, {
        'name': 'Descripción',
        'quantity': 1.0,
        'price_unit': 100.0,
        'account_id': cuenta_700_id,
        'tax_ids': [(6, 0, [iva_21_id])],
    })],
})

# 2. Confirmar
odoo.execute('account.move', 'action_post', [invoice_id])

# 3. Para histórico, registrar pago si ya está pagada
# (ver account.payment)
```

### account.move.line — Líneas contables

Campos clave:
- `account_id` (Many2one → `account.account`) — la cuenta contable
- `name` — descripción
- `debit` / `credit` — debe / haber (en asientos manuales)
- `quantity`, `price_unit` — en líneas de factura
- `tax_ids` — impuestos aplicados
- `analytic_distribution` — distribución analítica (en Odoo 17+)

---

## account.payment — Pagos

Para registrar el pago de una factura existente:

```python
payment_id = odoo.create('account.payment', {
    'payment_type': 'inbound',    # 'outbound' para pagos salientes
    'partner_type': 'customer',   # 'supplier' para pagos a proveedor
    'partner_id': partner_id,
    'amount': 121.0,
    'date': '2024-01-20',
    'journal_id': banco_id,
})
odoo.execute('account.payment', 'action_post', [payment_id])
```

Después hay que conciliar la línea contable del pago con la de la factura.

---

## res.country, res.country.state, account.account, account.tax

Estos son **catálogos pre-existentes**. Nunca crearlos: buscar por código/nombre y obtener el ID.

```python
# País por código ISO
country_id = odoo.search('res.country', [('code', '=', 'ES')])

# Cuenta contable por código
account_id = odoo.search('account.account', [('code', '=', '700')])

# Impuesto por nombre
tax_id = odoo.search('account.tax', [
    ('name', '=', 'IVA 21%'),
    ('type_tax_use', '=', 'sale'),
])
```

**Recomendación:** cachear todos estos lookups al inicio de cada migración para no spammear la API.
