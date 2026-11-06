# Correcciones de seguridad y calidad — 2026-11-04

## Summary (English)

This report records corrections to audit findings A1–A10: explicit network/account signing controls, successful-receipt-only logs, exact asset identities, enforced BigQuery budgets, strict send modes, whole-item parser rejection, clear failure for the unsupported Explorer pull, robust chart domains, validated retries and restricted CI permissions. Tests and evidence are described below. The work was originally performed on a temporary review branch and has since been integrated into `NGZeggers/near-value-shift`; the branch and deployment statements below describe the historical review, not today's canonical repository. [Receipt revalidation](REVALIDACION_L2_2026-11-05.md) subsequently restored L2 analytics. Volume reconciliation remains unresolved; no transaction, demo post or hackathon application was sent by this review.

Aplicadas únicamente a la copia de trabajo de `NGZeggers/hackathons`, rama `near_hackaton`, sobre `99aaceb`. No se modificó ni desplegó `NGZeggers/near-value-shift`. La auditoría y sus evidencias del 3 de noviembre se conservan sin cambios.

## Comportamiento corregido

| Hallazgo | Corrección | Regresión |
|---|---|---|
| A1: publicación ignora red/cuenta | CLI propaga ambas opciones hasta el publicador, con precedencia sobre el entorno. Red inválida se rechaza; envío y verificación son mutuamente excluyentes. Antes de firmar se muestra destino, cuenta y depósito, sin clave. | Dobles de firma para ambas redes, overrides opuestos al entorno, credenciales ausentes y exclusión de modos. Ninguna transacción real. |
| A2: logs de receipts fallidos | Extractor y SQL L2 admiten solo éxitos explícitos. CSV nuevo conserva `execution_status`; caché con esquema 2 conserva estados/procedencia. Cachés antiguas se vuelven a obtener, nunca se consideran verificadas por defecto. | Éxito por valor/receipt, fallos, estado ausente/desconocido y envolturas ambiguas. |
| A2: extracto histórico sin estado | L2 devuelve `computed=false`, invalida salidas numéricas antiguas y explica la causa en dashboard, tesis y notebook. Nueva ruta `verify-events` comprueba todos los logs contra bloques, es reanudable por caché y reemplaza el CSV solo al completar todas las comprobaciones. | Verificación offline con cachés nuevas, rechazo de cachés antiguas, eliminación de eventos fallidos y conservación del extracto cuando falta un bloque. |
| A3: identidad inferida del nombre | Se eliminan regex/substrings de valoración y decimales. Solo identificadores exactos del registro, preservando mayúsculas/minúsculas de IDs multi-token. | Tokens con nombres engañosos, identificadores con distinto case y activos desconocidos permanecen sin precio. |
| A4: presupuesto BigQuery | Una estimación por consulta; techo server-side menor entre límite por consulta y presupuesto restante. La contabilidad usa bytes procesados/facturados reales. Metadatos inválidos detienen la invocación. `--force` no elimina el límite acumulado. | Servicio simulado que hace cumplir el techo: drift de estimación, bytes facturados superiores a procesados, fuerza y presupuestos inválidos. |
| A5: `SEND=0` firma | Solo `SEND=1` habilita `--send`; vacío/0 son secos; valores ambiguos se rechazan. | Expansión `make -n` para vacío, 0, 1, false, yes, 2 y `1 0`. |
| A6: parser malformado | Valida data, account, intent, diff, token y cantidades enteras en rango. Rechaza cada item completo, cuenta rechazos y no publica métricas parciales si hubo alguno. | Strings/listas/enteros como diff, payloads inválidos, booleanos y cantidades fraccionarias; producción queda no calculada. |
| A7: Explorer aparenta éxito | La solicitud explícita de una integración no implementada falla, con o sin JWT. El fetch general la omite e informa que es opcional y no soportada. | Solicitud explícita con credenciales ficticias y sin credenciales. |
| A8: eje de ceros divide por cero | Dominios constantes se amplían; datos no finitos o sin positivos para log muestran ausencia de datos; dominio invertido se rechaza. | Chromium: ceros lineales, constante negativa, ceros log y controles normales. |
| A9: reintentos inválidos | Argumentos de reintentos y timeout se validan antes de hacer HTTP; se elimina el assert de producción. | Reintentos cero/negativos/bool/fraccionarios; 403 sin reintento y 429 con recuperación. |
| A10: CI/rama/permisos | Push valida `near_hackaton`; lectura global únicamente. Pages/OIDC solo en deploy manual, condicionado a este repo/rama y `deploy_pages=true`. Acciones fijadas por SHA y instalación con `--locked`. | YAML inspeccionado: triggers, permisos, gate manual y SHA de 40 caracteres. No se ejecutó un despliegue. |

README, links de fuente del dashboard, borrador de demo e índice local identifican la rama de `hackathons`. El demo upstream se declara referencia histórica; no se afirma que contenga estos cambios. El borrador de demo sigue sin constituir una publicación en X.

## Verificación realizada

- **91 pruebas pytest pasan**; incluye las 25 pruebas previas con fixtures actualizados al esquema explícito, reproducciones promovidas de la auditoría y nuevas regresiones.
- **28 controles Chromium pasan**: HTTP/file, gráficos actuales, 6 KPIs, filtros/temas/persistencia, tablas/fuentes/tooltips, anchos 375/768 px, notebook, texto hostil y casos de ejes degenerados. El runner actual retorna error si falla un control y no consulta el demo upstream.
- **Dos builds completos pasan**, con notebook ejecutado. La segunda ejecución usa `UV_OFFLINE=true` y la guardia histórica de sockets Python, permitiendo únicamente loopback/Unix; no se registran conexiones externas intentadas. No es un firewall de sistema.
- Comparación entre ambas reconstrucciones: texto y hashes exactos; números dentro de `rtol=1e-9`, `atol=1e-11`. Los artefactos cuyo único cambio era ruido numérico dentro de esa tolerancia conservan los bytes previos para evitar diferencias sin contenido analítico.
- Bandit reporta **5 observaciones bajas** relacionadas con subprocess/git; ninguna media/alta. Las llamadas Git usan listas y no shell. Este resultado no garantiza ausencia de vulnerabilidades.
- **63 archivos de evidencia histórica verifican sus SHA-256**. `data/raw`, `data/blocks`, `audit/2026-11-03`, `pyproject.toml` y `uv.lock` no tienen cambios respecto a HEAD.
- No se firmaron transacciones, ejecutaron consultas Google facturables, enviaron inscripciones ni modificó la visibilidad de repositorios.

Las reproducciones históricas se mantienen como registro del commit auditado. Sus dos dobles de BigQuery no hacen cumplir los nuevos techos server-side: uno simula cargos por encima del techo y el otro cuenta como ejecutada una consulta que un servidor conforme rechazaría. Las regresiones actuales prueban explícitamente el rechazo del servidor y la ausencia de outputs para la consulta denegada, sin editar la evidencia histórica.

## Consecuencia sobre los datos y límites restantes

El CSV histórico de 7,280 eventos no contiene estados. **No se han revalidado sus 1,189 bloques con red en esta corrección.** Las cifras L2 anteriores quedan retiradas de los outputs actuales y siguen disponibles únicamente como evidencia histórica. El resultado actual contiene 18 gráficos, 6 KPIs y un estado L2 no calculado; no se sustituye una validación pendiente por ceros ni por estados inventados.

Para recuperar L2:

```sh
uv run near-thesis verify-events
make build
make test
```

La verificación consulta FastNear bajo sus límites de ritmo, puede tardar considerablemente y conserva cachés para continuar tras una interrupción. `uv run near-thesis verify-events --offline` funciona cuando todos los bloques necesarios ya están en caché de esquema 2. La comprobación se basa en fuentes públicas; no es una prueba criptográfica independiente.

El SQL BigQuery corregido no se ejecutó contra Google. Su esquema debe contrastarse mediante dry-run antes de una consulta facturable. Explorer sigue sin implementación; ya no se presenta como una extracción exitosa. La publicación del repo canónico, el post X, datos del equipo/cuenta de premio, consentimiento y entrega oficial siguen siendo decisiones/evidencias externas; esta corrección no los ejecuta.

## Repetir las comprobaciones

Desde la raíz del repositorio:

```sh
uv sync --locked --all-extras
make test
make build
python3 audit/2026-11-03/verify_evidence.py
```

Para Chromium, utilizar un entorno de auditoría con Playwright y su navegador instalados:

```sh
python tests/browser_dashboard.py
```

Los controles escriben resultados en un directorio temporal nuevo. `NEAR_AUDIT_OUTPUT` permite elegirlo. Los resultados de esta ejecución están en [audit/2026-11-04-fixes](../audit/2026-11-04-fixes/).

Los cambios y los artefactos regenerados están pendientes de commit. Por ello el comparador contra HEAD todavía identifica las diferencias deliberadas con el snapshot anterior. Se verificó el determinismo contra el baseline de la primera reconstrucción corregida con `near_thesis.check_generated --baseline-dir`; tras commitear código y artefactos juntos, `make check-generated` usará ese nuevo baseline Git.
