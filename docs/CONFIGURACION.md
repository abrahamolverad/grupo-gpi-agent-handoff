# Configuración de tarifas

Guarde un archivo `policy.local.json` en la carpeta del repositorio. El programa exige todos estos campos:

| Campo | Significado | Formato |
| --- | --- | --- |
| `annual_rate` | Tasa anual aplicada al monto afianzado | Fracción decimal entre 0 y 1 |
| `min_prima` | Prima mínima por fianza | Monto en MXN |
| `derechos_rate` | Tasa de derechos sobre la prima | Fracción decimal entre 0 y 1 |
| `gastos_tramite` | Gasto fijo por fianza | Monto en MXN |
| `iva_rate` | Tasa de impuesto sobre el subtotal | Fracción decimal entre 0 y 1 |
| `minimum_billable_months` | Mínimo de meses facturables | Entero de 1 a 120 |

La fórmula por fianza es:

```text
meses_cobrados = max(vigencia_meses redondeada hacia arriba, minimum_billable_months)
prima_calculada = monto x annual_rate x meses_cobrados / 12
prima = max(prima_calculada, min_prima)
derechos = prima x derechos_rate
subtotal = prima + derechos + gastos_tramite
impuesto = subtotal x iva_rate
total = subtotal + impuesto
```

Los importes monetarios se redondean a dos decimales con la regla de mitad hacia arriba. La prima calculada se redondea antes de aplicar el mínimo. Cada renglón se calcula por separado y el total general suma los totales de las fianzas.

El archivo de ejemplo usa números ficticios. Copie su estructura, sustituya todos los valores por la política aprobada y mantenga `policy.local.json` fuera de Git.
