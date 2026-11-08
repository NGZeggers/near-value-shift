# Balance frente a la auditoría: qué cumplió esta ronda y qué no

Fecha: 2026-11-08. Base: `8ed6826`. Nota del auditor de producto antes de esta ronda: **96/100** (séptima revisión). Documentos relacionados: respuesta pasada a pasada en [`AUDIT_RESPONSE_2026-11-06.md`](AUDIT_RESPONSE_2026-11-06.md); qué falta y qué datos lo cierran en [`PENDIENTES_AL_100.md`](PENDIENTES_AL_100.md).

## Lo que pedía la auditoría para subir de 96

1. Reconciliar el volumen global de Intents frente a la referencia.
2. Validar QAA a escala mensual y con evidencia externa.
3. Completar la atribución económica de las recompras.

Las tres son validaciones de evidencia, no fallos de código. El auditor advirtió que la nota no sube por correcciones puntuales sino por evidencia que cierre estos frentes.

## Qué se midió en esta ronda (declarado antes de leer bloques)

### Muestra sistemática del día 2025-11-14

| Medida | Valor |
| --- | --- |
| Diseño | cada 40.º bloque de 00:00 a 24:00 UTC, desplazamiento aleatorio de semilla declarada |
| Bloques leídos | 3,489 de 3,496 (2.49 % de los 139,853 del día); 7 no disponibles, contados como cero |
| Bloques con volumen Intents | 1,552 |
| Estimación del día | 46.9 M USD, error estándar de diseño 13.5 M (28.7 % relativo) |
| Referencia DefiLlama | 152.3 M USD |
| Ratio | 0.31; intervalo de diseño 0.13–0.48; bootstrap percentil 0.15–0.49 |
| Mismo día con dos ventanas fijas / 24 ventanas horarias | 0.36 / 0.33 |
| Concentración | el 1 % de los bloques muestreados concentra el 90 % del volumen |

Lectura: los tres diseños coinciden y ambos intervalos excluyen la paridad. Para ese día, los intervalos aportan evidencia contra una explicación puramente muestral, condicionada al diseño y al estimador de error; quedan abiertas diferencias de definición (qué cuenta la referencia, uno o dos lados, *confidential intents*) o de reconstrucción y precios. Un día no establece el total global.

### Búsqueda del swap de financiación de las recompras a 200 bloques

| Medida | Valor |
| --- | --- |
| Recibos buscados | 29 (los de la muestra de 45 sin swap en el rango original) |
| Bloques leídos | 4,099; 5 no disponibles |
| Swap encontrado | 12, los doce comprando wrap.near, a 4–141 bloques del retiro |
| Intercambio observado en total | 28 de 45 recibos muestreados |

Para los 17 restantes no se observó un swap en el rango leído; su existencia y ubicación temporal quedan sin determinar. Retiro desde Intents observado en los 45; intercambio en 28; origen del activo vendido sin trazar.

## Qué cumplió respecto a la auditoría

- **Separar error de muestreo de brecha definicional con cobertura y error justificados.** Cumplido para un día: la muestra sistemática lo hace con un diseño declarado y un error de diseño publicado. Es evidencia nueva y reproducible de que la diferencia con DefiLlama no viene de observar pocas horas.
- **Documentar qué cuenta la referencia.** Cumplido en lo público: DefiLlama suma el dataset de Dune que mantiene NEAR, que incluye *confidential intents* sin logs públicos; toda referencia pública comparte ese origen.
- **Ampliar la trazabilidad de recompras.** Cumplido parcialmente: de 22 a 28 intercambios observados de 45, con regla declarada antes de leer.
- **Medir el sesgo de muestreo de QAA.** Cumplido dentro del día (seis días): inclusión 9.9 %, cuota por nombre 25.8 % frente a 16.0 %, ponderación que subcorrige; lectura acotada como hipótesis, no como cota.
- **No ajustar nada para que pase.** Cumplido: el estimador declarado sigue en 0.253 y el chequeo sigue fallando; los factores son sensibilidades.

## Qué no cumplió y por qué

- **Reconciliar el volumen global.** Un día no es el total, y el hallazgo apunta a que el problema está en la definición de la referencia (`volume_amount_usd`, uno/dos lados, cuota confidencial del periodo), que solo NEAR o Dune pueden publicar. Los días completos de BigQuery eliminarían el error de muestreo en los 49 días comparados; la parte definicional seguiría abierta.
- **Validar QAA a escala mensual y con evidencia externa.** No se tocó: requiere meses completos de actividad (BigQuery) y etiquetas externas humano/bot que no existen.
- **Completar la atribución de recompras.** 28 de 45 es una muestra; los 3,081 recibos y el origen de fondos requieren consultas de logs en BigQuery.

## Por qué se detuvo aquí

La API pública de bloques (FastNear neardata, ~0.2 bloques/s) quedó agotada para estos frentes: la muestra sistemática tomó 4 h 27 min y la búsqueda profunda 4 h. La única fuente gratuita con datos completos es el dataset público de NEAR en BigQuery, que exige un proyecto de Google Cloud creado con la cuenta del equipo; en el entorno de trabajo no había `.env`, `gcloud` ni credenciales. Los pasos están en [`PENDIENTES_AL_100.md`](PENDIENTES_AL_100.md).

## Expectativa razonable sobre la nota

Con lo medido en esta ronda cabe esperar que el auditor mantenga el 96 y reconozca la muestra sistemática como avance en el frente de volumen, sin dar por cerrado ninguno de los tres. Subir exige BigQuery.

## Verificación de cada commit de la ronda

`make build` completo, 127 pruebas aprobadas, 47 de 47 comprobaciones de navegador, `make check-generated` coincidente. Commits: `177ab32` (declaración de diseños), `f610fce` (muestra sistemática), `8ed6826` (búsqueda profunda).
