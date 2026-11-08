# Correcciones de la segunda fase — 2026-11-07

Base: `a9ad733c9a32c362483a5ce7dae5154296cdb433`, incorporada por fast-forward desde `origin/near_hackaton`. Implementación y pruebas en `NGZeggers/hackathons`, sin escrituras al upstream `near-value-shift`. No se hizo commit, push, despliegue ni publicación externa. `megi-revision/` se conserva fuera del alcance.

## Resultado

**203 pruebas aprobadas**, incluidas las 53 reproducciones originales de la segunda fase y 23 comprobaciones adicionales de recuperación, serialización, configuración y paginación. Los 13 casos antes fallidos ahora pasan con el comportamiento robusto esperado. La suite anterior de 127 casos sigue aprobada.

El build completo offline se ejecutó en el worktree de corrección y se repitió en el checkout final, incluyendo notebook e índice local. La comparación con una instantánea de los artefactos corregidos aprobó con las tolerancias existentes (`rtol=1e-9`, `atol=1e-11`; textos y hashes exactos). Los guardias Python no registraron conexiones externas. Las salidas que solo diferían por precisión de máquina se conservaron con sus bytes anteriores para reducir ruido en el diff.

Los artefactos modificados intencionalmente incluyen JSON estándar con `null`, diagnósticos Johansen inconclusos cuando faltan prerrequisitos, texto de reconciliación más prudente, notebook tolerante a campos de resultados ausentes y hash del índice actualizado. `make check-generated` contra el HEAD anterior identifica estos cambios hasta que se commiteen; la comprobación de reproducibilidad realizada usa la instantánea corregida, no afirma que coincidan con `a9ad733`.

## Cambios por hallazgo

| Hallazgo | Corrección y comprobación |
|---|---|
| P2-01, pérdida de extractos | Validación de argumentos antes de escribir; archivos temporales y umbral de usabilidad por ventana antes de reemplazar los CSV. Interrupción, caché vacía y muestra insuficiente conservan extractos/manifiesto anteriores. La extracción nativa nueva invalida la atestación que describía bytes anteriores. Intradía/sistemático tampoco publican extractos vacíos. Pruebas negativas y una extracción simulada válida que sí publica. |
| P2-02, duplicados | L2 rechaza identidades ambiguas por fecha/receipt/contenido del log antes de calcular volumen. Se rechaza en vez de deduplicar silenciosamente porque el esquema histórico no lleva índice de log. |
| P2-03, eventos truncados | Un `EVENT_JSON` declarado inválido cuenta como rechazo; L2 queda no calculado e invalida sus salidas antiguas. El parser de bajo nivel conserva compatibilidad para texto ajeno a eventos. También se rechazan CSV vacíos o sin columnas requeridas. |
| P2-04, QAA obsoleto | Si faltan insumos se eliminan series/salidas antiguas; el consumidor causal respeta `computed=false` o estado ilegible. Se conserva el modelo congelado, que no debe refitearse ni borrarse por ausencia temporal de datos. |
| P2-05, atestación incompatible | En la ruta muestreada, si existe `event_verification.json`, su hash de salida debe coincidir con el CSV antes de consumirlo. No se presenta como prueba criptográfica. |
| P2-06, período del publicador | Se escoge el último mes realmente cerrado según el corte diario y QAA del mismo mes. Si no existe mes completo se rechaza; QAA ausente queda `null`. No se firmaron transacciones. |
| P2-07, estimadores no identificados | Quiebres constantes devuelven diagnóstico; Johansen no ejecuta el estimador si no se establecen prerrequisitos I(1) y devuelve inconcluso ante singularidad. La prueba de rango completo ahora establece explícitamente sus prerrequisitos simulados. |
| P2-08, JSON no estándar | Serializador compartido convierte valores no finitos a `null` y usa `allow_nan=False`; los puntos de gráficos excluyen infinitos. El ensamblador HTML rechaza JSON no estándar antes de reemplazar la página anterior. |
| P2-09, fuente desconocida | `fetch` rechaza selecciones vacías o desconocidas antes de ejecutar pasos. |
| P2-10, escape HTML | Se escapan `<`, `>` y `&` en JSON embebido. Los marcadores del template se sustituyen antes de insertar los datos para impedir que un título con `/*APP*/` altere el ensamblado. El navegador usa ahora el generador real para sus fixtures, evitando que cambios en el escape hagan inoperantes las pruebas antiguas. |
| P2-11, accesibilidad | Colores de texto/badges/deltas con más contraste; pasos narrativos sin opacidad que lave el texto; progreso decorativo oculto a lectores. Export del notebook con prompts opacos, sintaxis legible, cabeceras de índice y alternativas de imágenes. |
| Revisión remota: CI | Push en `main` y `near_hackaton`; Pages queda restringido al repositorio canónico y su `main`. En `hackathons` estos cambios ejecutarán validación al subir, sin desplegar el upstream. |
| Revisión remota: NearBlocks | Errores en el cuerpo JSON consumen el presupuesto de ocho intentos por página. Cursores repetidos se rechazan. Pruebas de error persistente, recuperación y paginación sin avance, sin red ni esperas reales. |
| Revisión remota: inferencias excesivas | No observar un swap se describe como no observado, con ubicación sin determinar. Los intervalos aportan evidencia condicionada al diseño, sin excluir categóricamente todo error de muestreo. La guía de entrega distingue edición directa de solicitud humana de cambios. |

## Evidencia de validación

Resultados completos y hashes en [audit/2026-11-07-fixes](../audit/2026-11-07-fixes/README.md).

- Pytest: **203/203**, Python 3.12.3; una advertencia esperada por el evento corrupto que se rechaza. Cobertura: **67.56% de sentencias, 53.75% de ramas**, solo pytest.
- Reproducciones históricas sin editar: **53/53**; se conserva intacta la carpeta del 6/11 y se promueven sus casos a `tests/test_phase2_regressions.py`.
- Dashboard: **47/47 controles** de interacción, HTTP/archivo local, temas, geometría y datos adversarios; **4/4** casos adicionales de endurecimiento.
- Axe-core 4.14.0: cero infracciones automáticas en dashboard claro 1440/375, oscuro 1440 y notebook. Los SVG con evaluación incompleta requieren revisión manual; esto no certifica conformidad universal.
- Procedencia: **15,758 comprobaciones aprobadas**, 1,189 bloques cacheados; 7,227 eventos exitosos y 53 fallidos excluidos. No se volvieron a adquirir bloques por red. Los snapshots raw, de bloques y el plan prospectivo permanecen idénticos a HEAD.
- pip-audit fresco: **155 dependencias, sin avisos conocidos**. Bandit: siete resultados bajos, ninguno medio/alto. No se actualizaron dependencias; los paquetes de instrumentación se mantuvieron fuera del lock del proyecto.

## Límites que siguen abiertos

La reconciliación global con DefiLlama sigue fallando y no se ajustó el estimador para hacerla pasar. QAA no adquiere validación humana/bot o cobertura mensual completa por estos fixes; la atribución económica de recompras sigue limitada a las trazas disponibles. La evaluación prospectiva requiere datos futuros. Las fechas declaradas en documentos de la ronda remota no se reinterpretaron: el entorno registra 7/11 y algunos documentos dicen 8/11; para certificar cronología se necesitan registros externos de ejecución.

No se ejecutaron BigQuery facturable, firmas/pagos reales, envíos al hackathon ni publicación en X. Las pruebas automatizadas no acreditan ausencia de todos los defectos ni cubren todos los navegadores/versiones de Python. El notebook conserva dependencias CDN de mejora visual, bloqueadas en el ensayo; sus tablas y gráficos exportados se evaluaron localmente.
