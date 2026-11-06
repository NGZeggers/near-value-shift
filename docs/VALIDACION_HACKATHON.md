# Validación del proyecto para NEAR Hackathon 2026

## Summary (English)

This dated review documents the initial thesis audit and subsequent corrections: observed net revenue, repaired QAA features/cache identity, a separate past-only predictive model, explicit statistical prerequisites and multiplicity control, corrected Intents aggregation and broader generated-artifact checks. The sample/reference cross-check still fails and is evidence against independent confirmation; QAA remains a behavioral proxy and no robust return signal is claimed. Historical test counts and deployment observations below apply to their named commits. Later [security fixes](SECURITY_FIXES_2026-11-04.md) and [receipt revalidation](REVALIDACION_L2_2026-11-05.md) are integrated into the canonical repository. A public X demo post and the team's reviewed final application remain outstanding.

Revisión: 2026-11-02, zona America/Mexico_City. Commit revisado: `e361fee1537bb13a7c611c3f20aef32754219300`.

## Estado después de las correcciones autorizadas

Los hallazgos originales se conservan abajo como registro de la revisión del commit inicial. El código, los datos derivados y la tesis se han corregido; las limitaciones que requieren datos externos se declaran en el resultado en vez de presentarse como validaciones superadas.

| Hallazgo | Resolución |
|---|---|
| Captura de ingresos desactualizada | Snapshots reproducibles `dailyRevenue` y `dailyHoldersRevenue`; valoración calibrada a captura observada, con distinción entre receipts, recompras clasificadas, dividendos y quema. |
| Self-calls de QAA | Se recuperan las 6,620 filas; actividad normalizada por ventanas; HDBSCAN recalculado. |
| Información futura | Modelo predictivo separado y congelado, entrenado hasta 2025-04-30; datos posteriores disponibles desde el mes siguiente. Primera publicación 2025-06-01. Prueba de invariancia al cambiar meses futuros. |
| Volumen de Intents | Agregación por participante-intent, días cero y usuarios observados; sensibilidad de roles; precios cargados una vez. La reconciliación sigue fallando: ratio 0.253, intervalo condicional [0.178, 0.327], sobre 46 días comparables. La tesis lo cuenta como evidencia contraria, sin atribuir la causa a las colas ni prometer una cota inferior. |
| Econometría | ADF en la muestra exacta, estabilidad y residuos antes de inferir; p-valores Holm; rango Johansen explícito y casos no concluyentes. IC con intervalos individuales y familiares Bonferroni: ninguna asociación supera el criterio familiar actual. |
| Hash de QAA | Conserva magnitud, esquema, claves y versión metodológica; artefactos regenerados. |
| BigQuery | Q0 primero, rechazo de datos obsoletos, límite de bytes server-side y presupuesto por invocación. Ruta probada con dobles; consulta real opcional no ejecutada. |
| Outputs obsoletos | Tablas, modelos, dashboard, notebook y tesis regenerados. CI compara todos los artefactos relevantes, con tolerancia únicamente de precisión numérica; texto y hashes exactos. |

Validación local final: **25 pruebas aprobadas**, reconstrucción completa con notebook ejecutado y segunda reconstrucción sin diferencias analíticas frente a la primera (texto/hashes exactos y solo tolerancia de precisión numérica). Se verificaron en Safari la carga del dashboard, el tema oscuro, el filtro de fechas y la tabla/fuente de ingresos. El índice on-chain sigue siendo opcional y no se presenta como publicado; su verificador ahora compara todos los campos.

Pendientes de la entrega oficial: publicación del post de demo en X y datos del equipo/cuenta de premio/consentimiento. El repositorio ya es público; GitHub Pages se publica mediante el workflow y su resultado debe comprobarse por job, no solo por el estado global. Enlace de demo en README.md.

## Dictamen de la auditoría original (antes de corregir)

El proyecto corresponde al track `thesis` y tiene una implementación sustancial de L0–L4, pruebas y un pipeline reproducible. **Todavía no lo considero listo para enviar:** hay una premisa económica desactualizada, errores reproducibles en QAA, problemas en la validación de Intents y limitaciones en la inferencia estadística. Además, el repositorio sigue privado y el despliegue de Pages falló.

Esta revisión documenta resultados; no modifica modelos, datos ni conclusiones generadas.

## Reglas oficiales verificadas

No había una copia de las reglas en `docs/`. Consulté [HACKATHON.md oficial](https://nearhackathon.com/HACKATHON.md), la [web del evento](https://nearhackathon.com/) y el [ejemplo oficial del track Investment Thesis](https://github.com/nearai/near-hackathon-prompt-examples/blob/main/tracks/02-thesis.md).

| Requisito o condición | Estado observado |
|---|---|
| Track `thesis`: tesis sobre NEAR respaldada por datos y resultados reproducibles | Encaja: tesis, fuentes on-chain, dashboard y modelos implementados. La solidez de varias conclusiones requiere las correcciones indicadas abajo. |
| Repositorio público antes del cierre y durante la evaluación | Pendiente: GitHub devuelve `visibility=PRIVATE`. Estar privado durante el desarrollo está permitido. |
| README con pasos y resultados esperados | Cumple en estructura: instalación, reconstrucción, servidor, pruebas y notebook. |
| Demo pública en X que mencione el evento, `@NEARProtocol` y `#NEARHackathon` | Solo hay un borrador en `docs/DEMO.md`; no encontré evidencia local de una publicación. No se ha verificado la cuenta del equipo en X. |
| Demo alojada | Opcional. Pages falló. Si se presenta solo una demo local, la regla Q-012 exige video; capturas solas no bastan. |
| Código desarrollado dentro de la ventana permitida | Los commits visibles comienzan el 2 de noviembre. La regla permite trabajo desde el anuncio del 19 de octubre de 2026; los timestamps de Git por sí solos no prueban originalidad. |
| Licencia y declaración de reutilización/IA | MIT presente; README declara librerías, uso de Claude Code y ausencia de proyecto anterior. |
| Cuenta NEAR mainnet para el premio, datos del equipo, consentimiento y formulario final | No verificados en esta revisión. |
| Cierre | 14 de noviembre de 2026, 23:59 UTC; 17:59 en Ciudad de México. |

Las reglas Q-011 y la sección Tracks aclaran que las integraciones y los prompts son orientativos. **BigQuery, JWT de Explorer y publicación del índice on-chain no son requisitos generales obligatorios.** El uso de FastNear/DefiLlama es una elección válida si se documentan sus límites. La aprobación del plan solicitada por el prompt de ejemplo es parte de ese flujo sugerido; no la traté como requisito de elegibilidad.

## Comprobaciones realizadas

| Comprobación | Resultado |
|---|---|
| Pruebas existentes: `.venv/bin/python -m pytest -q` | **12 passed**, 3.77 s. |
| Sintaxis de JavaScript: `node --check near_thesis/web/app.js` | Correcta. |
| Dashboard | 19 especificaciones; todas tienen fuente, consulta y frase explicativa; JSON sin valores no finitos. |
| Integridad de `data/raw/` | 63 snapshots; todos coinciden con los prefijos SHA-256 publicados en `docs/REPRODUCIBILITY.md`. El informe solo publica 16 caracteres del hash y no incluye los CSV de bloques ni el modelo QAA. |
| Credenciales versionadas | No hay `.env` versionado ni nombres `.env`, `.pem`, `.key` o `*credentials*.json` en el historial consultado. No aparecieron los patrones de credenciales examinados en archivos actuales. Esto no equivale a una auditoría exhaustiva de todos los secretos históricos. |
| CI del commit revisado | El job `build` pasó instalación, reconstrucción, pruebas y comparación exacta de `THESIS.md`. El job `deploy` falló con HTTP 404 al crear el despliegue; el log pide habilitar Pages. `continue-on-error` permite que la ejecución global aparezca verde. |
| Generador de tesis frente a outputs versionados | `thesis.build()` produce exactamente el `THESIS.md` actual. Esto verifica consistencia con esos outputs, no sustituye reconstruir todos los modelos. |
| Reconstrucción local aislada | Se ejecutaron todas las etapas en una copia temporal de los archivos versionados, reutilizando el entorno instalado. Features, L1–L4, charts, tesis y site terminaron; Jupyter requirió reintento fuera del sandbox porque el kernel abre puertos locales. El notebook terminó y produjo `site/walkthrough.html`. `THESIS.md` resultó idéntico byte por byte. Se reutilizó la asignación HDBSCAN versionada, como establece el build; no se probó `QAA_REFIT=1`. |
| Inspección visual/interacción en navegador | No realizada: la herramienta no dispone de navegadores conectados. No se certifican tooltips, filtros ni presentación móvil. |

Evidencia de CI: [ejecución 41563304453](https://github.com/NGZeggers/near-value-shift/actions/runs/41563304453). La reconstrucción en GitHub duró aproximadamente 12 minutos. Se consultó por separado el resultado de cada job. SHA-256 de la tesis reconstruida y versionada: `5db611cd1aaac6ab07b1822e8b8ade2ee1b05c9a8ec325de4560180d2a3cb7e8`.

## Hallazgos que deben resolverse antes de presentar

### 1. Alta: la valoración parte de una descripción desactualizada de captura de ingresos

Referencias: `near_thesis/signal.py:111`, `near_thesis/thesis.py:122`, `near_thesis/thesis.py:222` y `THESIS.md`.

El generador afirma que no existe revenue sharing y trata como futura la conexión entre Intents y el token. Sin embargo, NEAR describe un fee switch activo y recompras financiadas con ingresos desde febrero de 2026. Véanse [Evolving NEAR Tokenomics, 24 de febrero](https://www.near.org/blog/evolving-near-tokenomics) y [The State of NEAR Q2 2026, 8 de julio](https://www.near.org/blog/the-state-of-near-q-2-2026).

Esto no demuestra retornos para holders ni garantiza futuras recompras: la primera fuente explica la discrecionalidad de gobernanza. Sí obliga a distinguir fees brutos, revenue neto retenido, recompras, staking/locking, quema y emisiones. El [dashboard oficial de ingresos](https://revenue.near.org/) identifica esas categorías y wallets; no importé sus números dinámicos al pipeline.

**Acción:** añadir evidencia reproducible de ingresos netos/recompras e incorporar el cambio de régimen económico. Mantener escenarios explícitos para el futuro, pero recalibrarlos contra mecanismos existentes y eliminar la afirmación absoluta de ausencia de captura. Esto no obliga a convertir la tesis en una recomendación alcista.

### 2. Alta: QAA ignora todas las llamadas a la propia cuenta

Referencia: `near_thesis/qaa.py:59`.

La agregación compara el receptor con `r.name[1]`. En esta agregación, `r.name` es el nombre de la columna, no el signer del grupo. Resultado comprobado sobre el snapshot:

```text
filas de tx_sampled.csv:                    198565
filas con signer == receiver:                 6620
sum(qaa.load_sampled().self_txns):                 0
```

`self_share` alimenta el clustering. Sus resultados, porcentajes humanos y QAA deben recalcularse después de corregirlo; no se puede asumir que los valores actuales permanezcan iguales. Las filas de la muestra representan acciones, por lo que este conteo no debe presentarse como número de hashes de transacciones distintos.

**Acción:** calcular `signer == receiver` antes del groupby, agregar ese indicador, probar un grupo con self-calls y otro sin ellas y regenerar el modelo.

### 3. Alta: QAA introduce información futura en los tests de señales

Referencias: `near_thesis/signal.py:25`, `near_thesis/econ.py:31`, `near_thesis/qaa.py:97`.

El QAA mensual se indexa al primer día del mes y se propaga hacia adelante, aunque usa actividad posterior de ese mismo mes. Se comprobó que la semana terminada el **3 de noviembre de 2024** ya recibe QAA de noviembre, pese a que el muestreo empieza el **4 de noviembre**. Además, scaler y clustering se ajustan usando todos los meses.

Esto es adecuado como descripción retrospectiva si se etiqueta así, pero contamina la interpretación predictiva del IC y Granger de QAA. Dividir el IC en dos mitades no constituye una evaluación walk-forward con modelos entrenados solo con pasado.

**Acción:** usar fechas de disponibilidad después del cierre de mes y entrenar/predecir por ventanas temporales; separar análisis descriptivo de señales fuera de muestra.

### 4. Alta: la discrepancia con DefiLlama no está explicada ni validada como se afirma

Referencias: `near_thesis/intents.py:175`, `near_thesis/intents.py:199`, `near_thesis/thesis.py:176`, `docs/SAMPLING.md:25`.

El ratio agregado guardado es **0.2608**, IC 95% **[0.1807, 0.3436]**. Por trimestre, el ratio va aproximadamente de **0.068 a 0.440**. Esto no demuestra por sí mismo estabilidad ni permite atribuir toda la diferencia a operaciones grandes ausentes. Extrapolar ventanas fijas y aplicar bootstrap sobre días tampoco convierte el resultado en una cota inferior garantizada.

Hay además un mecanismo concreto de subestimación: el volumen conserva el mayor outflow por cuenta dentro de cada receipt. En un receipt con dos usuarios que pagan 10 y 20 USDC, y contrapartida no cotizada, el código devuelve **20 USD** y `priced_batch_share=1`, aunque los outflows de usuarios suman **30 USD**. Por tanto, tener una pata cotizada en cada batch no equivale a valorar todo su volumen. La muestra sin filtrar tiene 302 receipts con más de dos cuentas: la estructura multiparticipante requiere validación.

Los días sin `token_diff` no entran en `daily_metrics`: el manifiesto tiene 49 días y la serie L2, 39. Deben distinguirse ceros observados, días sin actividad y datos ausentes al estimar medias.

**Acción:** validar reconstrucción por operaciones/intents en batches multiparticipante, cobertura monetaria y ceros; ampliar o aleatorizar ventanas; probar consistencia con días completos. Hasta entonces presentar el cross-check como discrepancia pendiente y evitar afirmar que la causa está demostrada. BigQuery no arregla automáticamente errores del parser o del estimador.

La propia tesis establece desacuerdo fuera del intervalo como criterio para cambiar de opinión; la reconciliación de esa condición debe aparecer explícitamente en el dictamen final.

### 5. Alta: los supuestos y resultados econométricos necesitan una interpretación más precisa

Referencias: `near_thesis/econ.py:93`, `near_thesis/econ.py:125`, `near_thesis/thesis.py:139`.

El ADF aplicado a la misma serie diferenciada de Intents que recibe el VAR da **p=0.2538**: no permite rechazar raíz unitaria al 5%. Esto no prueba no estacionariedad, pero significa que el supuesto requerido no está acreditado y el pipeline lo ignora. La [documentación de statsmodels](https://www.statsmodels.org/stable/vector_ar.html) exige estacionariedad para el VAR estable utilizado.

En Johansen, `cointegrated_5pct=False` mezcla rango 0 con rango 2. Los valores guardados para `tx_volume_usd` y `qaa` rechazan tanto rango 0 como rango 1; `select_coint_rank(..., det_order=0, k_ar_diff=2)` devuelve **2** para ambos. Esos casos, y las series que ADF considera estacionarias en niveles, necesitan revisar integración, especificación y estabilidad numérica; no deben agruparse bajo una afirmación general de ausencia de cointegración.

**Acción:** guardar rango y diagnósticos explícitos, alinear muestras, comprobar integración y residuos, y etiquetar como no concluyentes los tests cuyos supuestos no se acrediten. Granger mide precedencia predictiva condicionada al modelo, no causalidad económica.

### 6. Media: el hash de QAA pierde la magnitud de las variables

Referencia: `near_thesis/qaa.py:158`.

La normalización para redondear descarta el exponente de cada entrada. Prueba ejecutada:

```python
x = pd.DataFrame([[1., 2.]])
qaa._input_hash(x) == qaa._input_hash(x * 10)  # True
```

Si se mantienen las claves de filas, ciertos cambios reales pueden reutilizar asignaciones antiguas. El hecho de que el hash sea SHA-256 no corrige esta pérdida previa de información.

**Acción:** serializar valores redondeados conservando magnitud, claves, columnas y versión del método; invalidar y regenerar el artefacto después de corregirlo.

### 7. Media: la comprobación de frescura de BigQuery ocurre después de L1/L2

Referencia: `near_thesis/bq.py:52`.

El runner ordena alfabéticamente: ejecuta `l1_account_month_actions`, `l1_account_month_features` y `l2_intents_events` antes de `q0_freshness`. No inspecciona el resultado de Q0 para detener o acotar consultas. Esto contradice la documentación y la afirmación generada de que se comprueba frescura antes de L1/L2. El límite por consulta mediante dry-run sí está implementado.

**Acción:** ejecutar Q0 primero, validar la fecha realmente disponible y registrar el corte utilizado. Un límite de 120 GB por consulta no constituye un presupuesto acumulado mensual.

### 8. Media: algunos outputs versionados no corresponden al snapshot actual

La reconstrucción desde los mismos archivos raw cambió `data/derived/peers.csv` y `data/derived/models/peer_valuation.json`. Por ejemplo, el market cap de NEAR versionado es **5,081,673,866 USD**, mientras que el snapshot actual produce **5,068,386,772 USD**; también cambian los de los otros peers y sus ratios. No son diferencias de redondeo de coma flotante.

`THESIS.md` permanece igual porque la presentación redondea los valores afectados. Por eso el check actual de CI no detecta todos los outputs obsoletos. Las otras diferencias fueron `qaa_status.json`, por el indicador de reutilización del modelo, y `site/data.json`, por timestamp y valores regenerados.

**Acción:** regenerar y versionar los outputs tras actualizar snapshots; ampliar la comparación de CI a artefactos analíticos relevantes y separar metadatos variables de resultados numéricos.

## Diferencias frente al plan y documentación pendiente

- L0, L1, L2, L3, L4, dashboard, notebook, tests y workflow existen. El camino real de L1/L2 usa bloques muestreados; no hay CSV de BigQuery. Su funcionamiento online y su esquema SQL no se verificaron contra Google.
- El plan propone estabilidad temporal, validación contra anchors y sensibilidad de clusters; no encontré esas salidas. Silhouette mide separación geométrica, no precisión de la etiqueta humano/bot. QAA es un proxy exploratorio; tampoco se demuestra que su sesgo sea siempre conservador.
- El índice on-chain tiene publisher y verificador, pero solo hay evidencia de dry-run. README habla de publicación como si ya existiera; falta una transacción identificable. Es un stretch, no un bloqueo reglamentario.
- `docs/PLAN_v2.md` conserva el estado «GitHub repo + push» pendiente, aunque el remoto y CI ya existen; también habla de 45 snapshots frente a 63 actuales.
- `docs/METRICS.md` atribuye QAA y HHI a BigQuery pese a utilizar bloques. `THESIS.md` describe solo umbrales absolutos de solvers, pero `identify_solvers` también aplica la regla relativa y la aplica en ambos modos.
- Se ejecutan **24** tests IC, aunque el texto dice 20. La advertencia sobre multiplicidad existe; no se implementa un ajuste formal ni un walk-forward completo.
- Los comentarios de `data/bigquery/README.md` asignan consumidores a Q0–Q3 que no aparecen conectados en el código revisado.
- El coste principal observado al reconstruir L2 está en `near_thesis/intents.py:313`: se reconstruye la tabla completa de precios dentro de un bucle por pata negativa. Una llamada medida tardó 0.344 s; la muestra sin filtrar tiene 1,848 patas negativas, aproximadamente 10.6 minutos de trabajo repetido a ese ritmo. Conviene cargarla una sola vez; el tiempo real varía por equipo.

## Orden recomendado de cierre

1. Corregir la descripción de captura de ingresos y respaldarla con datos reproducibles.
2. Corregir QAA y su hash; recalcular y revisar si cambia la tesis.
3. Eliminar look-ahead y ajustar la interpretación de los resultados econométricos.
4. Reconciliar el volumen de Intents y rebajar afirmaciones no demostradas.
5. Actualizar documentación; repetir pruebas, reconstrucción y comparación de artefactos.
6. Preparar demo, verificar cuenta de premio, publicar el repositorio y completar la entrega oficial antes del cierre.

No se publicó contenido, no se cambió la visibilidad del repositorio, no se firmaron transacciones y no se envió la inscripción durante esta revisión.
