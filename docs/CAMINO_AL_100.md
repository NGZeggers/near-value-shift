# Camino al 100: auditoría contra los criterios de NEAR Hackathon 2026

Fecha: 2026-11-06. Commit auditado: `68bbfd6` (local, 6 commits por delante de `origin/main`).
Puntuación actual: **71 / 100**. Cierre de desarrollo y envío: **2026-11-14 23:59 UTC** (17:59 Guadalajara).

## Estado de implementación — 2026-11-06

La puntuación de este documento es una estimación de auditoría, no una rúbrica oficial ni una garantía de 100 puntos. Los apartados originales se conservan abajo como plan de partida.

| Punto | Estado actual | Evidencia o paso pendiente |
|---|---|---|
| 1 | Pendiente de confirmación para publicar | Cambios preparados localmente; `git push origin main` publica también los seis commits anteriores. Después comprobar jobs build/deploy, `id="verdict"` y fecha del pie en Pages. |
| 2 | Guion actualizado; video y post pendientes del humano | `docs/DEMO.md` incluye los cuatro comandos, veredicto, argumento, fuente/consulta y evidencia en contra. Falta URL real del post para README. |
| 3 | Pendiente de cuenta real del equipo | No se inventa ni se crea una cuenta mainnet en nombre del humano. |
| 4 | Pendiente de datos, consentimiento y revisión humana | Handoff en `docs/DEMO.md`: contrato, UUID persistente, sin `website`, revisión del payload completo, sin duplicar envíos. No se envió ninguna solicitud. |
| 5 | Implementado | README declara primer commit `117c268`, fecha 2026-11-02 y ausencia de baseline previo. Historial completo consultado. |
| 6 | Implementado | Tres frases iniciales y enlace “Try it in two minutes” a reproducción. |
| 7 | Implementado | Los cuatro documentos enlazados comienzan con “Summary (English)”; distinguen hallazgos históricos del estado integrado. |
| 8 | Implementado | `--locked` en generador, Makefile y demo; resumen Granger compartido con p-valores Holm; test de navegador contrasta seis KPIs totales con el JSON. |
| 9 | Implementado | Condiciones compartidas por tesis/dashboard: intervalo debe incluir 1.0; ratio e intervalo actuales, 46 días comparables, 49 días muestreados y 4,892 bloques en ventanas parciales. Faltan extractos de días completos y reconciliación de rutas/precios; no se inventa cuántos días nuevos bastarían. |
| 10 | Alternativa mínima implementada | README y sección Gaps de la tesis declaran el pull Explorer no implementado, falta de JWT y sustitución por DefiLlama/Dune. Configurar el JWT no habilita un conector inexistente. |
| 11 | README de auditoría implementado; topics pendientes de aprobación | `audit/README.md` explica en tres líneas la evidencia histórica fuera del build. GitHub consultado: repositorio público, sin topics; lista propuesta en `docs/DEMO.md`. |

Precisiones al contrastar con código y [reglas oficiales](https://nearhackathon.com/HACKATHON.md) el 6 de noviembre:

- Q-001 admite trabajo desde el anuncio del **19 de octubre**; el 1 de noviembre inicia la fase formal. Todos los commits actuales comienzan el 2 de noviembre.
- El dashboard contiene **un KPI principal y cinco secundarios**. La antigua condición `#kpis .kpi == 5` no era un fallo de renderizado; ahora el test comprueba además el total y su correspondencia con la especificación.
- Q-012 exige video para demo solo local; con demo alojada admite capturas. Este plan mantiene el video de dos minutos como entregable pendiente.
- Q-011 aclara que las integraciones sugeridas no son obligatorias. Documentar el gap Explorer es la alternativa mínima de este plan; no equivale a implementar el pull.

La página ahora separa la fecha UTC de generación del dashboard de la fecha del último snapshot. La fecha de datos no se actualiza artificialmente al desplegar. Publicación, grabación/post, cuenta y aplicación siguen abiertos; no se acredita un “100/100”.

Verificación de la implementación local:

- `uv sync --locked --all-extras`: correcto.
- Dos `make build` completos, incluido notebook ejecutado: correctos. El render final añade la fecha de generación al pie.
- `make test`: **98 pruebas aprobadas** (incluye coherencia entre tesis/dashboard, inferencia Granger restringida a modelos válidos y estados de reconciliación ausente/consistente).
- `uv run --with playwright python tests/browser_dashboard.py`: **32 controles aprobados** en Chromium, incluidos HTTP/file, seis KPIs totales, condiciones visibles del veredicto, fecha del render, filtros, temas, tabla/fuente, tooltip, móvil/tablet, notebook y entradas hostiles/degeneradas. Instalación previa: `uv run --with playwright python -m playwright install chromium`.
- Comparación contra el commit anterior: solo cambian los tres artefactos esperados (`THESIS.md`, `site/data.json`, hash de tesis en `data/derived/onchain_index.json`); los demás datos analíticos coinciden. `make check-generated` se ejecuta contra el nuevo commit local que incorpora estos artefactos.
- `git diff --check` y `node --check near_thesis/web/app.js`: correctos.
- Estado público consultado: repo público, topics vacíos; últimas ejecuciones CI sobre `4843bcb`; Pages todavía contiene el snapshot del 3 de noviembre y carece de `id="verdict"`. El despliegue nuevo no está verificado hasta aprobar el push.

NEAR no publica rúbrica ni pesos. Esta puntuación usa lo que sí publica:

- [HACKATHON.md](https://nearhackathon.com/HACKATHON.md): criba con Claude Code y Codex (reproducibilidad, verificación de features, informe, puntuación preliminar; "screening, not deciding"), README con pasos "do X, see Y" sin marketing, demo que el jurado pueda abrir, repo público con LICENSE, post en X con video.
- [Prompt oficial del track thesis](https://github.com/nearai/near-hackathon-prompt-examples/blob/main/tracks/02-thesis.md): "the score depends on evidence someone else can reproduce"; cinco entregables (SQL BigQuery filtrado por `block_date`, pull de Intents Explorer API, un comando que reconstruye todo, dashboard con consulta y una frase por gráfico, THESIS.md con claim, evidencia a favor, en contra y qué cambiaría la opinión).

## Tabla de puntuación

| # | Criterio | Hoy | Máx. | Qué falta |
|---|---|---|---|---|
| A | Requisitos obligatorios de envío | 10 | 25 | Video, post en X, cuenta mainnet, envío por API |
| B | Reproducibilidad (criba IA) | 24 | 25 | Una línea inconsistente en THESIS.md |
| C | Entregables del track | 17 | 20 | Intents Explorer API (documentar mejor el gap) |
| D | Calidad de la evidencia | 12 | 15 | Veredicto "no resuelto" sin camino claro para el lector |
| E | Demo accesible | 5 | 10 | Pages sirve la versión del 3 de noviembre |
| F | Claridad para jueces | 3 | 5 | README denso, docs en español, ruido en `audit/` |
| | **Total** | **71** | **100** | |

Verificado hoy en un clon limpio: `uv sync --locked --all-extras` + `make build` en 1 min 56 s, `make test` 95 tests, `make check-generated` idéntico. CI en verde.

## Qué hacer, en orden de puntos recuperados

### 1. Push a `main` para que Pages sirva el dashboard nuevo (+5, criterio E)

- La página pública (https://ngzeggers.github.io/near-value-shift/) se construyó el 2026-11-03. No tiene veredicto, argumento de cinco pasos, índice lateral ni bloque de evidencia en contra.
- Acción: `git push origin main`. CI reconstruye y redespliega solo (job `deploy`).
- Comprobar después: la página pública contiene `id="verdict"` y el pie dice la fecha de hoy.
- Requiere confirmación humana (regla del proyecto).

### 2. Video del demo y post en X (+10, criterio A)

- Regla Q-012: capturas solas no bastan; el jurado necesita video para verificar el demo.
- Guion de dos minutos ya escrito en `docs/DEMO.md`. Grabar: terminal con los cuatro comandos, dashboard público con veredicto y argumento, un gráfico con "Source and query", el bloque de evidencia en contra.
- El post debe decir que se construyó en NEAR HACKATHON, etiquetar `@NEARProtocol` y `#NEARHackathon`, adjuntar el video y enlazar repo y dashboard. Borrador en `docs/DEMO.md`. Lo publica el humano.
- Al tener la URL del post, añadirla al README en la sección Submission.

### 3. Cuenta NEAR mainnet para el pago (+3, criterio A)

- Campo `nearAddress` del envío: 2 a 64 caracteres, minúsculas, formato válido. Debe existir en mainnet.
- La crea el humano; nunca se inventa.

### 4. Envío por la API (+2, criterio A)

- `POST https://nearhackathon.com/api/applications`. Campos: `requestId` (UUID generado una vez), `projectName`, `leadName`, `email`, `size`, `tracks: ["thesis"]`, `nearAddress`, `projectUrl`, `demoUrl` (URL del post en X), `idea` (20 a 2000 caracteres), `consent: true`.
- **Nunca llenar `website`**: cualquier valor rechaza el envío. Cuerpo máximo 12000 bytes. Un repo solo se envía una vez y no se edita.
- Releer HACKATHON.md ese día. Mostrar el payload completo y confirmar antes de enviar.

### 5. Declaración de ventana en el README (+1, criterio F)

- Reglas Q-001 y Q-003: solo se juzga trabajo entre 2026-11-01 y 2026-11-14; se pide separar el trabajo previo.
- Primer commit: 2026-11-02 10:10 (hora de Guadalajara). No hay baseline, pero el README no lo dice.
- Acción: una línea en "Disclosure and license": "All commits date from 2026-11-02 onward; there is no pre-hackathon baseline." Opcional: tag `hackathon-submission` al enviar.

### 6. Resumen plano al inicio del README (+1, criterio F)

- El screener busca en tres líneas: qué es, qué problema resuelve, cómo probarlo. Hoy está repartido en párrafos técnicos y una tabla L0 a L4.
- Acción: bajo el título, tres frases cortas y un enlace "Try it in two minutes" que apunte a la sección de reproducción. Sin adjetivos de marketing.

### 7. Docs en español enlazados desde el README (+1, criterio F)

- `docs/AUDITORIA_FUNCIONAL_SEGURIDAD_2026-11-03.md`, `docs/SECURITY_FIXES_2026-11-04.md`, `docs/REVALIDACION_L2_2026-11-05.md` y `docs/VALIDACION_HACKATHON.md` están en español. El jurado humano puede no leerlos.
- Acción mínima: un párrafo "Summary (English)" al inicio de cada uno. Acción completa: traducirlos.

### 8. Inconsistencias que un verificador de features detecta (+1, criterio B)

- `THESIS.md` línea final: `uv sync --all-extras` sin `--locked`; el README y CI usan `--locked`. Corregir en `near_thesis/thesis.py` y regenerar.
- `tests/browser_dashboard.py` espera 5 KPIs (`#kpis .kpi == 5`) y el dashboard ahora tiene 6. Actualizar el test (no está en `make test`, pero un juez puede ejecutarlo).
- `THESIS.md` llama "inconclusivo" al resultado Granger; el dashboard reporta el resultado preciso (txns → price Holm p = 0.005; price → gas y volumen significativos). Alinear THESIS.md con `narrative.py`.

### 9. Veredicto más legible para el lector no técnico (+3, criterio D)

- El veredicto es honesto ("shift descriptivo apoyado, validación on-chain independiente no resuelta"), pero el lector no ve qué haría falta para pasar de "no resuelto" a "confirmado".
- Acción: en "What changes the verdict" añadir el criterio numérico exacto (intervalo del ratio muestra/DefiLlama debe incluir 1.0) y la cantidad de datos faltante (días completos vs. ventanas fijas). Ya está computado; solo falta exponerlo.

### 10. Intents Explorer API (+3, criterio C)

- El prompt del track lo pide con JWT en `.env`. No hay testnet y el equipo no tiene JWT; el pipeline falla con mensaje claro.
- Acción mínima: en THESIS.md "Gaps" y en el README, decir explícitamente que este entregable no se implementó y por qué, y que el cross-check usa DefiLlama como sustituto. El prompt acepta gaps documentados.
- Acción completa (solo si hay JWT): implementar el pull y usarlo como segunda referencia del cross-check.

### 11. Ruido para el screener (+1, criterio F)

- `audit/` pesa 17 MB (evidencia de auditoría). Añadir `audit/README.md` de tres líneas explicando qué es y que no forma parte del build, o moverlo a una rama `audit-evidence` y enlazarla.
- Añadir topics al repo: `near`, `near-protocol`, `hackathon`, `investment-thesis`, `onchain-analytics`.

## Qué puede hacer Claude sin tocar nada público

Puntos 5, 6, 7 (resúmenes en inglés), 8, 9, 10 (documentación) y 11. Quedan como commits locales.

## Qué requiere confirmación humana

Punto 1 (push), 2 (grabar y publicar), 3 (cuenta mainnet), 4 (envío). Regla del proyecto: confirmación explícita antes de publicar, firmar o enviar.

## Resultado esperado

| Estado | Puntos |
|---|---|
| Hoy | 71 |
| Tras push y puntos 5 a 11 | ~84 |
| Tras video, post, cuenta y envío | 100 |
