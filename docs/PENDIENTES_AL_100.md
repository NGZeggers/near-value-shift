# Pendientes para el 100: qué falta, qué datos lo cierran y quién lo hace

**Actualización 2026-11-08:** BigQuery se configuró y se ejecutó (coste 0 USD, proyecto sandbox). Resultados en `docs/AUDIT_RESPONSE_2026-11-06.md` (undécima pasada): la referencia de volumen cuenta los dos lados de cada swap; la cuota QAA no es una cuota poblacional; el intercambio de las recompras está observado en el 60 % de los 3,197 retiros. Lo que sigue abajo describe el plan tal como se declaró antes de ejecutarlo.

Estado al 2026-11-07, base `177ab32`, nota del auditor de producto **96/100**. Los tres frentes abiertos son de evidencia, no de código: el auditor ya verificó que el pipeline reconstruye, que las pruebas pasan (127) y que los artefactos regenerados coinciden. Subir más exige datos que la API pública de bloques (FastNear neardata, ~0.2 bloques/s) no puede dar en el tiempo disponible.

## La base de datos que sí existe: BigQuery público de NEAR

El hackatón no ofrece ninguna base de datos (su `HACKATHON.md` solo lista RPC públicos, créditos de NEAR AI y el JWT opcional de 1Click). NEAR sí publica una:

- **Dataset:** `bigquery-public-data.crypto_near_mainnet_us` (tablas `blocks`, `chunks`, `transactions`, `receipt_details`, `receipt_actions`, `execution_outcomes` con logs, `account_changes`). Fuente: NEAR Lake Indexer → Databricks → copia pública en BigQuery (repo `near/near-public-lakehouse`).
- **Coste:** NEAR paga el almacenamiento; Google regala 1 TiB de procesamiento al mes en el sandbox, sin tarjeta.
- **Frescura comprobada el 2026-11-08:** `blocks`, `transactions` y `execution_outcomes` llegan hasta el mismo día (última fecha 2026-11-08). La fecha "19 de febrero" visible en la consola es metadato de la tabla, no el último dato. `make bq` sigue deteniéndose si la última fecha supera `BQ_MAX_STALENESS_DAYS`.
- **El repo ya está listo:** consultas en `sql/`, runner `make bq` con puerta de coste por consulta (`BQ_MAX_GB_PER_QUERY`) y por ejecución (`BQ_MAX_GB_PER_RUN`), resultados cacheados y comprometidos en `data/bigquery/` para que el jurado nunca necesite credenciales. Guía: `docs/SETUP_BIGQUERY.md`.

### Estado de la adquisición (2026-11-08)

Proyecto creado y autenticado. Costes medidos con dry-run antes de ejecutar (1 TiB gratis al mes; topes del runner `maximum_bytes_billed` 200 GB por consulta y 400 GB por invocación):

| Consulta | Cobertura | Escaneo |
| --- | --- | --- |
| L1 por cuenta (primer intento) | 15 meses 2024-11..2026-01; resultado de 46 M filas, agregado en el servidor a `l1_full_month_summary.csv` | 148 GB + 4 GB |
| `l1_full_month_summary_2.sql` | 9 meses 2026-02..2026-10, agregado por mes y clase de nombre | 20 GB |
| `l2_full_days_valued.sql` | 32 días de muestra hasta 2026-02-12, bloques completos, valorados en SQL con la misma regla | 186 GB |
| `l2_full_days_valued_2.sql` | 17 días de muestra restantes (2026-02-27..2026-10-25) | 34 GB |
| `l3_buyback_withdrawals.sql` | 198 días con recibos de recompra (2026-04-23..2026-11-06), logs `native_withdraw`/`token_diff`/`mt_*` | 293 GB (pendiente de autorización) |

Total si se ejecuta todo: unos 690 GB, dentro del tramo gratuito. Lección: agregar dentro de BigQuery; un resultado por cuenta o por log tiene decenas de millones de filas y no se puede descargar ni comprometer. Los extractos se guardan en `data/bigquery/l2_full_days_valued*.csv` y `l1_full_month_summary*.csv` con nombres distintos de los que activan el modo BigQuery del pipeline: el estimador declarado (muestra de bloques) y el QAA comprometido siguen siendo la base; los datos completos entran como validación (`reconcile.complete_days`, `qaa.monthly_validation_from_full`).

## Pasos humanos (unos 5 minutos)

1. Entrar en https://console.cloud.google.com/bigquery con una cuenta de Google, aceptar términos, **Create project** (por ejemplo `near-thesis`), anotar el **ID** del proyecto.
2. En la terminal (o con el prefijo `!` en la sesión de Claude Code):
   ```bash
   brew install --cask google-cloud-sdk
   gcloud init
   gcloud auth application-default login
   ```
3. Escribir en `.env`: `GOOGLE_CLOUD_PROJECT=<id-del-proyecto>` (y opcionalmente `BQ_MAX_GB_PER_QUERY=120`).
4. Comprobar frescura antes de gastar cuota: `bq query --use_legacy_sql=false --dry_run < sql/q0_freshness.sql` y después la consulta real. Si la última fecha es de hace meses, el dataset está parado y hay que declararlo así en THESIS.md en lugar de usarlo.

## Frente 1: reconciliar el volumen global de Intents

- **Qué falta (auditor):** el estimador declarado da 0.253 de la referencia DefiLlama con intervalo condicional 0.178–0.327 y el chequeo sigue fallando; cobertura completa, incertidumbre de muestreo justificada, definición comparable de la referencia y una fuente de origen independiente.
- **Qué ya está:** unidad económica declarada; descomposición por componentes (valoración, rutas, cobertura temporal); factor intradía medido en tres días y validado en otros tres; definición de la referencia documentada (`reconcile.REFERENCE_DEFINITION`: DefiLlama suma el dataset de Dune que mantiene NEAR, incluye *confidential intents*, no hay referencia pública de origen independiente); muestra sistemática de un día en adquisición (ver abajo).
- **Qué lo cierra con BigQuery:** `sql/l2_intents_events.sql` (ya escrito; filtra `execution_outcomes` de `intents.near` con estado explícito de éxito por `block_date`) para **los 49 días comparados completos**, no muestras. Con eso `reconcile` calcula el ratio diario real frente a DefiLlama sin error de muestreo; lo que quede es definicional (uno/dos lados, *confidential intents*) o de reconstrucción/precios. Escaneo estimado: comprobar con dry-run; filtrar siempre por `block_date` y limitar a los días con referencia.
- **Lo que ni BigQuery cierra:** la convención a uno o dos lados de `volume_amount_usd` y la cuota de *confidential intents* del periodo. Solo NEAR o Dune pueden publicarlo; se declara.

## Frente 2: validar QAA a escala mensual y con evidencia externa

- **Qué falta (auditor):** la cuota QAA se mide en dos ventanas de 50 bloques al día; el sesgo de inclusión está medido dentro del día (seis días) pero no a nivel de mes; faltan etiquetas externas humano/bot y refits con datos completos.
- **Qué ya está:** medición de inclusión dentro del día (`qaa.inclusion_from_intraday`), refits de sensibilidad (`make qaa-refits`), alcance conductual de los grupos, modelo congelado separado del clustering retrospectivo.
- **Qué lo cierra con BigQuery:** `sql/l1_account_month_features.sql` y `sql/l1_account_month_actions.sql` (ya escritos) dan **todas las cuentas firmantes por mes** con las mismas features. Entonces: (a) cuota QAA mensual sobre la población completa frente a la muestreada, es decir, el sesgo mensual medido; (b) refit del clustering con datos completos como sensibilidad separada del baseline; (c) extrapolación poblacional sin el reescalado por DAU de NearBlocks. Presupuesto: estas consultas son las más caras; dry-run obligatorio y limitar a los meses necesarios (por ejemplo seis meses recientes) si el TiB no alcanza.
- **Lo que ni BigQuery cierra:** etiquetas verificadas de humanos y bots. No existen; los grupos siguen siendo conductuales y así deben nombrarse.

## Frente 3: completar la atribución económica de las recompras

- **Qué falta (auditor):** de 3,081 recibos entrantes antes del corte, la traza cubre 45 (retiro observado en todos, intercambio observado en 22); contraprestación y origen de fondos sin trazar.
- **Qué ya está:** estados estrictos, libro reconciliado al corte, traza declarada y ampliada a 40 bloques; ampliación a 200 bloques en adquisición (ver abajo).
- **Qué lo cierra con BigQuery:** consulta sobre `execution_outcomes` de `intents.near` filtrando logs `native_withdraw` con `receiver_id = buybacks.multisignature.near` (todos los retiros, no una muestra) y, para cada cuenta Intents origen, sus `token_diff` anteriores (el intercambio) y sus `mt_mint`/depósitos (origen de fondos). Nueva SQL por escribir, filtrada por `block_date` en los días de los recibos. Con eso la atribución pasa de inferida a observada para la parte que los logs cubran, y lo no cubierto se cuantifica.
- **Lo que ni BigQuery cierra:** la intención (que el retiro sea "recompra" en sentido económico) sigue siendo una interpretación; se mantiene la separación entre retiro observado y recompra inferida.

## Completado con la API pública (declarado antes de leer, 2026-11-07; resultados 2026-11-08)

- **Muestra sistemática del día 2025-11-14:** 3,489 de 3,496 alturas (cada 40.º, ~2.5 % del día; 7 alturas sin bloque). Ratio 0.31 frente a la referencia, intervalo de diseño 0.13–0.48, bootstrap 0.15–0.49; los otros dos diseños del mismo día dan 0.36 y 0.33. **Revisado tras la reserva del auditor:** el diagnóstico de cobertura sobre las 24 ventanas horarias del mismo día (regla declarada antes de calcularlo) no respalda el estimador de error (razón 3.8 entre la dispersión real entre fases y el error estimado; cobertura 27.5 %; autocorrelación débil pero por encima del umbral en el retardo 4, divisor de 40), así que el veredicto de muestreo es no concluyente y la brecha de ese día no se atribuye. La simulación con poblaciones sintéticas del tamaño real cubre al 85 % en volumen concentrado o dependiente y al 0 % con un patrón periódico en el paso. El 1 % de los bloques concentra el 90 % del volumen muestreado. Un día no establece el total global.
- **Diseño declarado para una adquisición futura (`SYSTEMATIC_REPLICATED_DESIGN`, no ejecutado):** cuatro arranques aleatorios independientes con paso 160, interpenetrantes, mismo presupuesto de bloques; la varianza se estima de la dispersión entre réplicas sin supuestos sobre la secuencia. Tardaría unas 5 horas de API pública.
- **Búsqueda del swap de financiación a 200 bloques:** 12 de 29 encontrados (a 4–141 bloques del retiro); intercambio observado en 28 de 45 recibos muestreados. En los 17 restantes no se observó el swap en el rango leído; su ubicación temporal queda sin determinar. Origen de fondos sin trazar.

Con esto la API pública está agotada para los tres frentes: lo que sigue requiere BigQuery.

## Lo que no se cierra con datos

- **Evaluación prospectiva:** plan congelado en `data/prospective/oos_freeze.json`; primeras puntuaciones el 2027-04-18 (h=4) y el 2027-06-13 (h=12). Antes de esas fechas no hay resultado posible por diseño.
- **Chequeo del volumen:** no se amplía la tolerancia ni se corrige el estimador declarado para que pase; el factor intradía y la cuota confidencial son sensibilidades.

## Orden sugerido

1. Configurar BigQuery y verificar frescura (humano, 5 min).
2. `make bq` para L2 (volumen) en los 49 días con referencia → `make build` → reconciliación global.
3. L1 mensual (QAA) en los meses que quepan en el TiB → sesgo mensual y refit completo como sensibilidad.
4. SQL nueva de recompras (todos los retiros y sus swaps/depósitos).
5. Nueva pasada del auditor con `docs/AUDIT_RESPONSE_2026-11-06.md` actualizado. Nada se publica ni se envía sin confirmación humana.
