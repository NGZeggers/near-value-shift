# Revalidación de receipts y recuperación de L2 — 2026-11-05

Rama: `near_hackaton`, `NGZeggers/hackathons`. Base: `e8d69e1ca617e677872a1a391afde7f549dce042`.

## Resultado

Se comprobaron **los 1,189 bloques con eventos del extracto original** contra FastNear. Cada log original se contrastó por altura, timestamp, receipt ID, caller y contenido. El CSV se reemplazó atómicamente después de completar la comprobación, sin atribuir éxito a estados ausentes.

| Medida | Resultado |
|---|---:|
| Bloques originales contrastados | 1,189 |
| Receipts originales | 2,170 |
| Receipts exitosos conservados | 2,117 |
| Receipts fallidos excluidos | 53 |
| Logs originales | 7,280 |
| Logs aceptados | 7,227 |
| Logs de receipts fallidos excluidos | 53 |
| Logs con `SUCCESS_VALUE` | 7,211 |
| Logs con `SUCCESS_RECEIPT_ID` | 16 |
| Bloques que conservan eventos aceptados | 1,159 |

Los 53 logs excluidos corresponden a **53 receipts fallidos**, todos de tipo DIP-4 `transfer`; ninguno es `token_diff`. Se conservan completos con su fuente en las evidencias, en lugar de desaparecer del registro de auditoría. Treinta bloques del extracto anterior quedan sin logs aceptados; siguen formando parte de la comprobación de los 1,189 bloques originales.

El control independiente efectuó **15,758 comprobaciones de campos y coherencia**, todas correctas. Además de comprobar cada log original, verificó que los eventos aceptados coinciden exactamente con todos los logs exitosos emitidos por `intents.near` presentes en esos bloques cacheados: no hay logs exitosos adicionales omitidos ni registros aceptados ausentes de la respuesta externa.

Esto reconcilia el extracto con una fuente pública. **No se presenta como una prueba criptográfica independiente de ejecución.**

## Impacto analítico

L2 vuelve a producir métricas con `computed=true` y `execution_status_verified=true`: 49 días muestreados, 39 días con `token_diff`, nueve cuentas clasificadas como solvers y veinte gráficos en el dashboard. La ventana analítica permanece hasta 2026-11-01; no se actualizaron precios ni series de terceros durante esta tarea.

Las cinco salidas numéricas L2 —diaria, mensual, trimestral, solvers y sensibilidad— coinciden con las archivadas en la auditoría del 3 de noviembre, dentro de la tolerancia numérica declarada. Los logs retirados no eran `token_diff` y su exclusión no altera esas estimaciones. Sí cambia el total de eventos admitidos y queda acreditado explícitamente el estado de los receipts.

La discrepancia con DefiLlama **sigue sin resolverse**: ratio 0.2525357503, intervalo condicional [0.1777911233, 0.3274618358], sobre 46 días comparables. La paridad queda fuera del intervalo, por lo que `cross_check_passed=false`. Recuperar L2 y verificar receipts no valida el estimador de volumen total, su extrapolación ni una señal de inversión.

`failed_events_excluded=0` en el status del modelo describe los fallos filtrados durante esa ejecución del modelo: recibió un CSV ya depurado. Los **53 fallos eliminados previamente** se registran en `data/blocks/event_verification.json` y en las evidencias de esta revalidación.

## Funcionamiento y seguridad

- **92 pruebas pytest pasan**, incluida una regresión que comprueba el SHA-256 del extracto contra su informe, sus recuentos y la ausencia de estados fallidos.
- **28 controles Chromium pasan** sobre el build local: carga HTTP/file, gráficos y KPIs, filtros/temas, tablas/fuentes/tooltips, móvil/tablet, notebook y casos de texto hostil/ejes degenerados.
- **Dos reconstrucciones completas pasan**, con notebook ejecutado. La segunda usa `UV_OFFLINE=true` y la guardia de sockets Python: no registró intentos externos; Jupyter utiliza loopback.
- Las dos reconstrucciones coinciden: texto y hashes exactos, números con `rtol=1e-9`, `atol=1e-11`. Se conservan los bytes previos de artefactos cuyo único cambio es ruido numérico dentro de esa tolerancia.
- La descarga es reanudable mediante cachés de esquema 2. Se utilizaron dos lectores con limitador compartido; en la fase final se aplicó un techo conservador de 0.30 peticiones/s, reducido automáticamente ante respuestas 429. Las reanudaciones no descartaron progreso ni produjeron métricas parciales.
- Los archivos fuente raw de precios/series, el extracto de transacciones L1 y las evidencias históricas permanecen sin cambios. No se modificó `NGZeggers/near-value-shift`, no se firmaron transacciones ni se publicaron sitios o inscripciones.

## Alcance y límites

La comprobación cubre los 1,189 bloques representados en el CSV original de eventos. **No vuelve a descargar los 4,892 bloques de toda la muestra**, no verifica de nuevo los bloques sin eventos en ese extracto, no amplía ventanas y no acredita cobertura del mercado completo. La imputación de días cero y el marco de muestreo conservan sus limitaciones documentadas.

Se conservan las hipótesis de precios, stablecoins a par, roles heurísticos y expansión por ventanas. BigQuery y Explorer no se ejecutaron. El demo upstream no se redeployó; para inspeccionar el resultado actual se debe abrir el build local.

## Evidencias y reproducción

- [Informe de verificación del extracto](../data/blocks/event_verification.json): recuentos y hashes de entrada/salida.
- [Resumen independiente](../audit/2026-11-05-revalidation/revalidation-summary.json).
- [Manifest de bloques y fuentes](../audit/2026-11-05-revalidation/block-cache-manifest.json).
- [Logs de receipts fallidos excluidos](../audit/2026-11-05-revalidation/excluded-failed-events.json).
- [Comparación analítica histórica](../audit/2026-11-05-revalidation/analytical-comparison.json).
- [Pruebas, builds y navegador](../audit/2026-11-05-revalidation/).

SHA-256 de entrada: `e0224a184993806b25c8574ef05f0f3a44e34d7b6e7406497637341f0c858af7`.

El CSV conserva terminadores CRLF de `csv.writer`; son parte de los bytes atestados y no se normalizan después de calcular el hash. Para comprobar whitespace en este cambio: `git -c core.whitespace=cr-at-eol diff --check`.

SHA-256 del CSV revalidado: `c9aeb3830f15e2e597b431d67a7314c82be01dd0a4e89f851b06baa7614bb111`.

Desde la raíz:

```sh
uv run pytest -q tests
make build
python3 audit/2026-11-03/verify_evidence.py
```

El runner de navegador es `tests/browser_dashboard.py` y necesita un entorno con Playwright/Chromium. El validador independiente se ejecuta sin red y requiere las cachés de los 1,189 bloques originales más una copia del CSV original:

```sh
git show e8d69e1:data/blocks/intents_events_sampled.csv > /tmp/near-original-events.csv
uv run python audit/2026-11-05-revalidation/validate_revalidation.py /tmp/near-original-events.csv --output /tmp/near-revalidation-check
```

Las cachés se mantienen fuera del versionado; el manifest permite comprobar su integridad. Si faltan, repetir la adquisición en una copia aislada del commit base mediante `near-thesis verify-events`, respetando los límites del servicio. La adquisición puede tardar considerablemente. Ejecutar ese comando sobre un extracto ya depurado verifica ese nuevo input, por lo que su hash de entrada y su recuento de fallos no reproducen el informe histórico original.

Los cambios de datos, outputs y documentación quedan locales, pendientes de commit/push. El comparador contra HEAD identifica las diferencias deliberadas respecto al estado anterior con L2 deshabilitado; la repetición se contrastó contra el baseline de la primera reconstrucción revalidada.
