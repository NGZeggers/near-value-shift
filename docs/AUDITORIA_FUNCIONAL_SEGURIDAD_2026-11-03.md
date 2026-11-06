# Auditoría de cumplimiento, funcionamiento y seguridad — NEAR Hackathon 2026

## Summary (English)

This is the historical audit of commit `4843bcb`, not the current project's security verdict. The pipeline and hosted dashboard were reproducible, but the audit found high-priority signing-network and failed-receipt issues, plus pricing, parser, budget and robustness defects. Those findings were subsequently addressed in [fix verification](SECURITY_FIXES_2026-11-04.md), and the historical receipt extract was [revalidated](REVALIDACION_L2_2026-11-05.md); both changes are now integrated into the canonical `NGZeggers/near-value-shift` repository. The failed volume cross-check and exploratory behavioral/statistical limits remain. A real X demo post, team details and official submission still require the team. The original dated findings below are preserved for traceability.

Fecha: 2026-11-03. Rama: `near_hackaton`. Commit: `4843bcb7b3e876bdfc330820358240b44d4f4311`.

## Dictamen

El proyecto **encaja en Investment Thesis (`thesis`) y su flujo principal es funcional y reproducible**. La tesis incluye evidencia a favor, en contra, limitaciones y condiciones para cambiar el veredicto. Una conclusión de inversión condicional o negativa no incumple el track: se juzga la evidencia.

**No lo doy por cerrado para entrega ni aprobado en seguridad.** Hay dos hallazgos de prioridad alta: selección de red ignorada en publicación on-chain y aceptación de logs de receipts fallidos. Hay problemas adicionales de integridad de valoración, robustez, límites de gasto y opciones de firma. No se demuestra explotación ni contaminación del snapshot actual mediante estas reproducciones sintéticas.

El repo solicitado, `https://github.com/NGZeggers/hackathons`, devuelve **404 sin autenticación** tanto en web como en API. Eso impide acreditar su acceso público; no permite distinguir por sí solo entre privado e inexistente para terceros. Existe otro repo público, `NGZeggers/near-value-shift`, que contiene el mismo commit, tiene un workflow exitoso y sirve el demo enlazado. El JSON del demo coincide con el reconstruido localmente. Puede resolver el requisito de publicación si ese es el repositorio que el equipo decide entregar. Falta evidencia del post real de X y de la entrega oficial.

## Fuentes y requisitos

Se consultó la [ficha de Condor Nest](https://condor-nest.lat/o/near-hackathon-2026), las [reglas oficiales vivas](https://nearhackathon.com/HACKATHON.md), la [web oficial](https://nearhackathon.com/) y el [prompt de Investment Thesis](https://github.com/nearai/near-hackathon-prompt-examples/blob/main/tracks/02-thesis.md). La ficha sin el parámetro de seguimiento fue accesible; las reglas Markdown se descargaron directamente porque el lector web no aceptó su tipo de contenido. Se conservaron copias de reglas y prompt en las evidencias.

Las reglas prevalecen sobre el resumen de Condor Nest y sobre el prompt de ejemplo. Q-011 aclara que las integraciones sugeridas son orientativas. Q-001 admite trabajo desde el anuncio del 19 de octubre; la fase formal empieza el 1 de noviembre. Los commits revisados de este proyecto comienzan el 2 de noviembre de 2026. Esto acredita las fechas del historial, no una prueba independiente de autoría o ausencia de código previo.

| Parámetro | Resultado | Evidencia / pendiente |
|---|---|---|
| Track `thesis`: análisis, dashboard y modelos repetibles | Cumple técnicamente | Pipeline L0–L4, tesis generada, 20 gráficos, notebook ejecutado y reconstrucción verificada. |
| Uso concreto de NEAR | Cumple | Bloques FastNear, receipt logs de `intents.near`, métricas NearBlocks y series de liquidación. |
| Evidencia y límites explícitos | Cumple con reservas analíticas | Declara reconciliación fallida, QAA exploratorio y ausencia de señal robusta; los nuevos fallos de extracción/valoración requieren corrección. |
| BigQuery, JWT Explorer o contrato propio obligatorio | No exigido | Q-011; no confundir el prompt de ejemplo con una lista obligatoria. Explorer no está implementado. |
| Reproducción desde README | Verificada | Instalación bloqueada por `uv.lock`, build completo, notebook y comparación de artefactos. Jupyter necesita puertos locales. |
| Repositorio público | Condicional | `hackathons`: 404 anónimo. `near-value-shift`: público y mismo commit. Seleccionar explícitamente el URL final. |
| Licencia y declaración de herramientas | Presente | MIT; README declara librerías, Claude Code y Codex. No se investigó originalidad contra todos los proyectos externos. |
| Demo accesible | Verificado | https://ngzeggers.github.io/near-value-shift/ responde 200; datos iguales a los reconstruidos. Mantener disponible durante el periodo exigido. |
| Post público de X con demo, @NEARProtocol y #NEARHackathon | No acreditado | `docs/DEMO.md` es un borrador, no un post publicado. Si solo hubiera demo local, Q-012 exige video. |
| Datos del equipo, cuenta mainnet de premio y consentimiento | No acreditado | No se inventaron ni solicitaron para esta auditoría. |
| Una entrega por proyecto/repositorio | No acreditado | No se consultó ni envió una solicitud con datos personales; confirmar estado antes de presentar. |
| Fecha límite | Pendiente de entrega | 14 de noviembre de 2026, 23:59 UTC; 17:59 en America/Mexico_City. Revisar de nuevo las reglas vivas antes de enviar. |

La auditoría no garantiza elegibilidad final ni puntuación: el jurado humano decide según Q-017.

## Pruebas ejecutadas

Se trabajó en un worktree separado: `/home/ttech-main/hackathons-review/near-audit-20261103`. El checkout original conserva su código, datos y archivos ajenos. El empaquetado posterior añade este informe y `audit/2026-11-03/`; no modifica la implementación.

| Validación | Resultado |
|---|---|
| `uv sync --locked --all-extras`, Python 3.12.3 | Correcta; dependencias del lock instaladas. |
| Suite original | **25/25 pasan**, 4.31 s. |
| Suite original + 24 casos independientes de auditoría | **37 pasan, 12 fallan**, 49 casos, 4.55 s con cobertura. Los fallos se detallan abajo; varios son variantes de un mismo problema. |
| Cobertura de esa ejecución pytest | 49.31% de sentencias, 38.13% de ramas; indicador combinado 46.98%. El build y las pruebas de navegador se ejecutaron aparte y no están incluidos en ese porcentaje. |
| Build completo con notebook | **Dos reconstrucciones completas correctas**. Un intento previo falló por el bloqueo de sockets del sandbox; al permitir puertos locales funcionó. |
| Segunda reconstrucción con guardia de red | `UV_OFFLINE=true` y guardia de sockets Python que solo permite loopback/Unix; **sin intentos externos registrados**. No es una captura de red a nivel de sistema. |
| Comparación con Git y entre builds | Correcta: texto/hashes exactos y números con `rtol=1e-9`, `atol=1e-11`. Diferencias binarias de flotantes no se presentan como igualdad byte a byte. |
| Integridad y coherencia | **91/91 controles pasan**: fechas, signos, QAA, disponibilidad temporal, concentración, unicidad, hashes de 65 snapshots, índice local y horizontes sin retornos posteriores al corte. |
| Chromium | **27/28 controles pasan**; el fallo corresponde a una serie sintética de ceros. Flujo normal sin excepciones JS. |
| Publicación web | JSON público igual al local, 20 gráficos, notebook accesible. |
| Contraste externo de bloques | **4/4 bloques** devuelven los logs y timestamps versionados: alturas 134214723, 174722328, 200219611 y 221554876; 29 logs en total. Ninguno contiene receipts Intents fallidos. No extrapolar a toda la muestra. |
| `pip-audit`, versiones exactas | **155 dependencias sin vulnerabilidades conocidas reportadas** por la base consultada. No acredita ausencia de vulnerabilidades desconocidas. |
| Bandit | 6 observaciones, todas bajas: subprocess/git y assert. Revisión manual no demuestra inyección de shell; se usan listas de argumentos sin `shell=True`. |
| Secretos por patrones | Sin coincidencias en 158 archivos versionados y 880 blobs alcanzables en las refs locales. Patrones: claves privadas PEM, claves privadas NEAR, tokens GitHub y access keys AWS. No cubre todo formato de credencial ni todos los mnemónicos. |
| Transacciones reales, BigQuery facturable, inscripción y publicación social | No ejecutados. Los controles respectivos se probaron con dobles o modo seco. |

Los controles de navegador incluyen HTTP local y `file://`, 6 KPIs, 5 filtros, 3 temas, persistencia, tablas, fuentes, tooltips, anchos 375/768 px, notebook, demo público y texto hostil. El caso `</script><script>…` no ejecutó código: el generador escapa cierres y el renderer usa `textContent`.

## Hallazgos reproducibles

### A1 — Alta: publicar ignora la red solicitada en CLI

Ubicación: `near_thesis/cli.py:47`, `near_thesis/onchain.py:58`.

`--network` y `--account` se pasan a `verify`, pero la ruta de publicación solo llama `onchain.run(dry_run=not a.send)`. `publish()` toma red/cuenta del entorno. Con `NEAR_NETWORK=mainnet`, indicar `onchain --network testnet` sigue seleccionando mainnet. Si además se indica `--send` y hay credenciales/fondos válidos, puede firmarse en la red del entorno contra la intención expresada en CLI.

Prueba: `test_cli_testnet_selection_must_override_mainnet_environment` sustituye completamente `onchain.run`; observa `mainnet` en vez de `testnet`. **No firma ni hace RPC**.

Corrección: propagar cuenta/red explícitas hasta `publish`, validar conflictos y mostrar destino/cuenta/depósito antes de la ruta de envío. Probar ambos sentidos y precedencia sin transacciones reales.

### A2 — Alta para integridad analítica: logs de receipts fallidos cuentan como eventos

Ubicación: `near_thesis/blocks.py:189`; también revisar el filtro de estado en `sql/l2_intents_events.sql`.

El extractor filtra receiver y prefijo del log, pero nunca consulta `execution_outcome.outcome.status`. Un receipt sintético con `Failure` y `token_diff` se conserva como un evento de liquidación. Un log emitido antes de un fallo no prueba una transferencia finalizada. El CSV guardado descarta el estado, lo que impide resolver esta cuestión desde el extracto reducido.

Prueba: `test_failed_receipt_must_not_be_counted_as_settlement` falla porque devuelve el log. Los cuatro bloques reales contrastados no tenían este problema; no se afirma que ya afecte a los 4,892 bloques versionados.

Corrección: exigir estado exitoso, conservar estado/procedencia y revisar la muestra completa o regenerarla desde fuentes que permitan acreditarlo. Recalcular L2 y la tesis si cambia el resultado.

### A3 — Media: tokens desconocidos heredan valoración por substrings

Ubicación: `near_thesis/intents.py:92`.

Fuera del registro, `STABLE_RE.search(t)` valora como stablecoin por nombre y `if k in t` reconoce majors por coincidencia parcial. Los identificadores `nep141:fake-usdc.attacker.near`, `nep141:fake-btc.attacker.near` y `nep141:fake-wrap.near.attacker` reciben precios en las pruebas. Esto permite contaminar estadísticas si un activo ajeno con ese nombre llega al input.

Tres pruebas `test_unknown_token_name_cannot_impersonate_priced_asset` fallan. En los datos actuales hay 94 identificadores observados y 20 ausentes del registro; **los 20 permanecen sin precio**. No se encontró explotación de este mecanismo en el snapshot actual. La valoración de stablecoins a par sigue siendo una hipótesis económica distinta.

Corrección: registro/allowlist por identificador exacto y decimales comprobados; desconocidos sin precio. Separar la política histórica de activos retirados de heurísticas abiertas.

### A4 — Media: el presupuesto acumulado BigQuery no constituye un techo efectivo

Ubicación: `near_thesis/bq.py:35` y `near_thesis/bq.py:69`.

`run()` suma el primer dry-run. `run_query()` vuelve a estimar, ejecuta y guarda bytes procesados, pero esos valores no vuelven al acumulador. `maximum_bytes_billed` solo aplica el techo por consulta, sin acotarlo al presupuesto restante de la invocación.

Dos reproducciones con dobles fallan: (1) presupuesto 150 GB, primeras estimaciones 1 GB y consultas posteriores de 100 GB; se permiten ambas con techos de 120 GB cada una; (2) presupuesto 3 GB, estimaciones 0.5 GB y ejecución simulada 2 GB por consulta; se permiten cuatro. **No se ejecutaron consultas Google ni se incurrió en cargos**.

Corrección: acotar el techo server-side a lo restante, usar una estimación por decisión y contabilizar bytes facturados/procesados retornados por el job antes de la siguiente consulta. Mantener el rechazo de datos obsoletos, que sí pasó su prueba.

### A5 — Media: `SEND=0` también activa firma en Makefile

Ubicación: `Makefile:51`.

GNU Make considera verdadero cualquier texto no vacío en `$(if $(SEND),--send,)`. La comprobación estática `make -n onchain SEND=0` produce `uv run near-thesis onchain --send`. Solo se utilizó `-n`; no se envió nada.

Corrección: admitir `--send` exclusivamente con `SEND=1`, rechazar valores ambiguos y probar la expansión del target para vacío/0/1.

### A6 — Media: un `diff` malformado interrumpe el parser

Ubicación: `near_thesis/intents.py:125`.

Se ejecuta `.items()` antes del bloque que captura errores. Un string, lista o entero no vacío como `diff` causa `AttributeError`. Las tres variantes de `test_malformed_diff_is_rejected_without_crashing` fallan. Es una interrupción del pipeline local al consumir datos malformados; el dashboard estático no expone este parser como servicio remoto.

Corrección: validar esquema y tipos antes de iterar, registrar filas rechazadas y no publicar un resultado parcial como completo.

### A7 — Media/baja, integración opcional: Explorer no implementado puede terminar con éxito

Ubicación: `near_thesis/fetch.py:122` y `near_thesis/fetch.py:141`.

Con un JWT ficticio, `fetch.run(['intents'])` imprime `NotImplementedError` pero lo captura sin añadir un fallo y retorna normalmente. La integración no existe aunque la opción se acepta. El README actual declara que el build no usa JWT, por lo que no invalida la reproducción principal ni es un requisito reglamentario incumplido.

Corrección: implementar la ruta o marcarla inequívocamente como no soportada con salida distinta de cero cuando se solicite.

### A8 — Baja: serie de ceros genera geometría SVG inválida

Ubicación: `near_thesis/web/app.js:42`.

Para dos puntos cero, sin dominio explícito y eje lineal, `hi == lo == 0`; el cálculo divide por cero. Chromium detecta cuatro atributos con `NaN`. Los veinte gráficos actuales y todos los filtros normales no producen geometría inválida.

Corrección: ensanchar dominios degenerados y tratar series vacías/no positivas según el tipo de eje.

### A9 — Baja: número de reintentos inválido produce AssertionError

Ubicación: `near_thesis/http.py:41`.

`fetch_json(..., retries=0)` llega a `assert last is not None`, en lugar de validar argumentos. No se observó en las llamadas normales. Corrección: validar reintentos positivos con un error explícito y evitar usar assert para validar configuración.

### A10 — Entrega/operación: CI no se ejecuta automáticamente al hacer push a la rama auditada

Ubicación: `.github/workflows/build.yml:4` y condición del job deploy.

`push.branches` solo incluye `main`; deploy exige `refs/heads/main`. El remoto solicitado tiene `bluiders.io` y `near_hackaton`, sin `main`. Hay triggers de PR y manual, por lo que no se afirma que sea imposible ejecutar validación. La publicación existente corresponde al otro repo público y su workflow exitoso para el mismo commit: [run 41583178623](https://github.com/NGZeggers/near-value-shift/actions/runs/41583178623).

Corrección: definir el repo/rama canónicos de entrega y alinear README, links, índice y CI. Si se usa el repo público existente, este hallazgo no invalida su despliegue actual. Reducir permisos de Pages/OIDC al job que despliega y fijar acciones por SHA son mejoras de endurecimiento; no se demostró una explotación del workflow.

## Límites científicos que siguen abiertos

- La reconciliación Intents/DefiLlama es 0.253, intervalo condicional [0.178, 0.327], 46 días comparables: no acredita paridad. La tesis lo declara correctamente como evidencia contraria. No se resolvió su causa en esta auditoría.
- QAA describe comportamiento, no identidades humanas. El muestreo fijo y las probabilidades de inclusión desiguales limitan extrapolación. El modelo predictivo separado evita el uso directo del clustering retrospectivo, pero eso no convierte el análisis en una estrategia de inversión validada.
- La sensibilidad QAA es amplia; no hay anchors humanos verificados. Las inferencias econométricas no concluyentes se presentan como tales.
- La suite pytest ampliada cubre solo parte del código; build y navegador aportan comprobaciones independientes. No se certifica ausencia de errores en caminos no probados.
- No se ejecutó el SQL contra el esquema real de BigQuery ni se probó Explorer autenticado. Tampoco se publicaron/verificaron datos on-chain reales: el índice local es determinista, no evidencia de una transacción.
- El análisis de vulnerabilidades consulta una base de avisos conocidos; la búsqueda de secretos es por patrones; Chromium fue el único motor de navegador probado ahora. El notebook advierte que tres imágenes carecen de texto alternativo.

## Evidencias y reproducción

Directorio versionado: [audit/2026-11-03](../audit/2026-11-03/). Contiene reglas/prompt, logs, JUnit, cobertura, Bandit, dependencias, hashes, controles de integridad, navegador, capturas y contraste externo de bloques. Los logs conservan las rutas y el commit de la ejecución original. El manifiesto `evidence-sha256.json` permite comprobar los archivos empaquetados. Las instrucciones portables están en su [README](../audit/2026-11-03/README.md).

Desde la raíz del repositorio, con el entorno de dependencias instalado:

```sh
# Suite existente
uv run pytest -q tests

# Casos independientes: se esperan 12 fallos en el commit auditado
uv run pytest -q tests audit/2026-11-03/audit_checks.py

# Después de make build: comparar con el snapshot de la auditoría
uv run python -m near_thesis.check_generated --baseline-dir audit/2026-11-03/baseline-after-build

# Verificar la integridad de los archivos de evidencia
python3 audit/2026-11-03/verify_evidence.py

# Expansión sin ejecutar el publicador
make -n onchain SEND=0
```

Orden recomendado: corregir selección de red y activación de firma; filtrar receipts fallidos y endurecer valoración/parser; regenerar y comparar artefactos si cambian los datos; corregir presupuesto BigQuery; resolver repo canónico y evidencias de entrega. Los problemas opcionales no deben presentarse como razones reglamentarias de descalificación.

La ejecución inicial de la auditoría **no modificó la implementación**, no hizo commits/push, no cambió visibilidad, no publicó contenido, no firmó transacciones y no envió inscripción. El usuario autorizó después commitear y subir exclusivamente el informe y las evidencias a `NGZeggers/hackathons`, rama `near_hackaton`. Este empaquetado no modifica `NGZeggers/near-value-shift`. Se conserva `megi-revision/` sin tocar.
