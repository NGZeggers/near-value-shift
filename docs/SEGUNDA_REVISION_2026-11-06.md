# Segunda revisión funcional, de seguridad y de requisitos — 2026-11-06

Base auditada: `743e24374d41c8ca604414896ffd8066d9c70441`, rama `near_hackaton` de `NGZeggers/hackathons`. Ejecución aislada en un worktree; no se aplicaron fixes. Esta revisión no cambia `NGZeggers/near-value-shift`, datos productivos ni evidencia histórica. Evidencias y reproducciones: [audit/2026-11-06-phase2](../audit/2026-11-06-phase2/README.md).

## Dictamen

El flujo principal funciona y la propuesta conserva encaje con la pista de tesis basada en evidencia. La segunda fase encuentra problemas de integridad y robustez que impiden dar por cerrada la revisión. La suite existente pasa, pero las pruebas independientes reproducen pérdida de extractos, duplicación de volumen y uso de QAA obsoleto, entre otros casos. Los fallos sintéticos no demuestran manipulación de la muestra actual ni explotación remota.

El repositorio está **privado**, confirmado mediante API autenticada sin registrar credenciales. Eso permite trabajar durante el desarrollo, pero debe resolverse antes de la entrega pública. El CI del commit auditado terminó correctamente: [run 42177658588](https://github.com/NGZeggers/hackathons/actions/runs/42177658588); build aprobado, despliegue omitido conforme a su condición manual.

## Requisitos de competencia

Fuentes: [reglas oficiales](https://nearhackathon.com/HACKATHON.md), [sitio oficial](https://nearhackathon.com/), [convocatoria referenciada](https://condor-nest.lat/o/near-hackathon-2026?cn_entry=9b183bc4-ed9d-4e59-905f-b8db21fbd119). Se conserva una copia de las reglas consultadas en esta fecha; la convocatoria contextual no sustituye las reglas oficiales.

| Requisito o condición | Resultado de revisión |
|---|---|
| Pista de tesis: hipótesis, evidencia y análisis reproducible | Implementados; persisten hallazgos de calidad y validación externa desfavorable. |
| Código público al cierre | Pendiente: repositorio privado. No se cambió visibilidad. |
| Reproducibilidad | Build completo offline aprobado con insumos existentes. Extracción offline sin caché falla de forma destructiva: P2-01. |
| Demo funcional | Dashboard local probado. Una demo local es admisible según Q012 con video; no se acreditó video final. La demo del upstream es histórica. |
| Publicación pública en X, mención @NEARProtocol y #NEARHackathon | No se acreditó enlace final. No se publicó nada. |
| Licencia | MIT admitida y presente; conservar atribuciones y declaraciones de fuentes/uso de herramientas. |
| Integraciones sugeridas | Q011 las presenta como orientación, no todas como requisitos obligatorios. No se exige incorporar cada integración. |
| Registro, equipo, consentimiento, contacto y NEAR para pago | Requieren comprobación humana en la entrega; no se enviaron formularios ni transacciones. |
| Una propuesta por proyecto | No se realizó segunda inscripción. |
| Correcciones después de enviar | Las reglas actuales permiten solicitar revisión humana en `/request-changes`; no editar/reinscribir directamente. La redacción de `docs/DEMO.md` debe actualizarse para reflejar esta vía. |
| Cierre | 14 de noviembre de 2026, 23:59 UTC; 17:59 en Ciudad de México. Confirmar reglas vigentes al entregar. |

La reconciliación externa con DefiLlama sigue sin superar el criterio propio: razón 0.2525357503, IC [0.1777911233, 0.3274618358], 46 días comunes, `cross_check_passed=false`. Debe mostrarse como limitación, no como validación aprobada.

## Resultados ejecutados

- Suite original: **92/92** aprobadas.
- Suite combinada: **145 casos; 132 aprobados y 13 fallidos**. Los 53 casos nuevos incluyen 30 controles numéricos independientes aprobados (volumen, usuarios, solvers, HHI e invariancia de escala). Los 13 fallos son expectativas de comportamiento robusto conservadas deliberadamente, no tests adaptados al defecto.
- Cobertura pytest: **56.87% de sentencias y 46.27% de ramas**; medida combinada 54.53%. No incluye cobertura del notebook, build ni navegador y no equivale a cobertura completa de requisitos.
- Build offline completo y verificación `near_thesis.check_generated`: aprobados contra la base auditada. El guard no registró intentos de red. Se trabajó con dependencias y fuentes disponibles en caché.
- Navegador: **28 controles existentes aprobados**. Cuatro casos adversarios adicionales: dos aprobados y dos fallidos. El cierre directo de `script` no ejecutó inyección; Unicode se mostró correctamente.
- Accesibilidad con axe-core 4.14.0: contraste insuficiente en dashboard claro/oscuro y notebook; resultados detallados en JSON. Hay 235 nodos SVG que requieren revisión manual, no una certificación de conformidad.
- Dependencias: **155 examinadas, sin vulnerabilidades conocidas reportadas por pip-audit** a esta fecha. Bandit: cinco hallazgos de severidad baja, ninguno medio/alto. Esto no prueba ausencia de vulnerabilidades.
- Reconciliación de procedencia: **15,758 comprobaciones aprobadas**, 1,189 bloques, 7,227 logs aceptados y 53 fallidos excluidos. Cuatro consultas públicas nuevas verificaron 15 logs, incluidos dos fallidos; todas coincidieron con la caché. Es reconciliación de fuente pública, no prueba criptográfica de ejecución.
- Integridad histórica: 63 archivos del manifiesto del 3/11 y 16 del 5/11 sin discrepancias. La carpeta del 4/11 no tiene ese mismo manifiesto y no se inventó uno retrospectivo.
- Escaneo de patrones de secretos en 18 commits alcanzables: cero coincidencias de los patrones seleccionados; ver alcance y límite por tamaño en JSON. No se revisaron credenciales locales ni archivos ajenos sin seguimiento.

## Hallazgos y prioridades

Las severidades expresan impacto sobre esta solución analítica, no una puntuación CVSS. Primero resolver P2-01, P2-02 y P2-04; después integridad de publicación y robustez. No se identificó una ruta pública de entrada controlada por un atacante para los escenarios locales descritos.

| ID | Prioridad | Reproducción, impacto y recomendación |
|---|---|---|
| P2-01 | Alta | `blocks.run(offline=True)` sin caché abre los CSV en modo escritura y deja solo cabeceras; `workers=0` también trunca antes de fallar. En copias reales se perdieron 7,227 eventos y 198,565 acciones, con originales intactos. Validar argumentos/caché antes de escribir y reemplazar archivos atómicamente solo tras validar resultados. Tests `test_offline_without_cache_preserves_existing_extracts`, `test_invalid_worker_count_cannot_truncate_extracts`. |
| P2-02 | Alta | Duplicar el mismo log duplica volumen de 1 a 2 USD sin duplicar usuarios/batches. `intents` no rechaza ni deduplica por identidad de procedencia. La muestra actual no presentó duplicación. Definir clave bloque/receipt/log/evento, rechazar conflictos y garantizar idempotencia. Test `test_duplicate_logs_cannot_double_volume`. |
| P2-03 | Media | Un evento válido seguido de un `EVENT_JSON` truncado produce métricas parciales con `computed=true`; `parse_event` devuelve `None` y el consumidor omite el error. Distinguir texto ajeno de un evento declarado inválido, contar rechazos y bloquear publicación incompleta. Test `test_truncated_event_must_not_produce_partial_metrics`. |
| P2-04 | Alta | QAA sin insumos informa indisponibilidad pero deja archivos causales anteriores; `available_series` los sigue sirviendo a consumidores econométricos/predictivos. La muestra actual dispone de insumos válidos. Invalidar salidas antiguas y exigir estado/procedencia vigente en consumidores. Test `test_qaa_unavailable_cannot_feed_old_predictive_features`. |
| P2-05 | Media | L2 puede afirmar `execution_status_verified` pese a un hash incompatible en `event_verification.json`, basándose en la columna de estado. La prueba existente de CI sí detecta ese desajuste en los datos versionados: mitigación real, sin sustituir validación en runtime. Comprobar atestación y hash al consumirla, diferenciando rutas BQ/extractor. Test `test_success_column_cannot_override_mismatched_attestation`. |
| P2-06 | Media | El publicador supone que el último mes siempre está incompleto y toma QAA por última fila. Dos casos: excluye marzo completo o mezcla índice de febrero con QAA de marzo. La fecha actual no reprodujo desalineación. Seleccionar mes por cierre real y QAA por ese mismo período; probar firma simulada. Test `test_publisher_uses_actual_latest_complete_month`, dos parámetros. |
| P2-07 | Media | Series constantes hacen fallar detección de quiebres y Johansen con excepciones, aun cuando faltan prerrequisitos. Devolver resultado inconcluso con diagnóstico y evitar ejecutar estimadores inválidos. Dos tests `test_constant_series_*`. Los insumos actuales completan el build. |
| P2-08 | Media | `peer_valuation.json` versionado contiene `NaN`, inválido en JSON estándar; `_pts` conserva infinito y una especificación sintética con `Infinity` deja el dashboard vacío. Validar finitud, serializar ausencias como `null` y usar `allow_nan=False`. Dos tests pytest y un caso de navegador. El dashboard actual sí funciona. |
| P2-09 | Baja | `fetch.run(['typo-source'])` termina con éxito sin hacer trabajo. Rechazar fuentes desconocidas antes de ejecutar. Test `test_unknown_fetch_source_cannot_claim_success`. |
| P2-10 | Baja | El escape de JSON embebido solo reemplaza `</`. Un título sintético `<!--<script>` altera el estado del parser HTML y deja cero gráficos. No hubo JavaScript inyectado: no es XSS confirmado. Escapar `<` como `\u003c` o cargar JSON mediante un mecanismo seguro y validado. Caso navegador `comment_script`. |
| P2-11 | Media, calidad | Contraste del dashboard claro 3.4:1 en cuatro nodos; oscuro 3.62:1 en dos deltas, por debajo de 4.5:1 para texto pequeño. Notebook con 25 incidencias de contraste. Mejorar colores y revisar semántica; sugerencias de landmark/regiones no se presentan como infracciones WCAG independientes. La accesibilidad es calidad adicional, no requisito obligatorio atribuido al hackathon. |

Ubicaciones principales: `near_thesis/blocks.py` (validación y escritura de extractos), `intents.py` (parseo, agrupación, deduplicación y atestación), `qaa.py` (estado y disponibilidad), `onchain.py` (selección de período), `econ.py` (prerrequisitos estadísticos), `charts.py` y `site.py` (serialización/HTML), `fetch.py` (selección de fuentes). Los nombres de tests y trazas completas permiten ubicar las líneas exactas en el commit base.

## Límites y siguiente paso

No se ejercieron pagos, firmas/transacciones reales, BigQuery con facturación ni inscripción/publicación final. Python probado: 3.12.3; no se certifican otras versiones anunciadas. El notebook intenta cargar dos recursos CDN de MathJax/RequireJS, bloqueados durante el ensayo; sus tablas e imágenes permanecen accesibles offline. El dashboard sí es autocontenido. El build reportó tres imágenes sin texto alternativo en notebook.

La siguiente fase debe implementar las correcciones priorizadas y repetir estas mismas reproducciones, preservando los fallos esperados como pruebas de regresión una vez corregido el comportamiento. No se realizó commit ni push de esta segunda fase: esta petición autorizó revisión y pruebas.
