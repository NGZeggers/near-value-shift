# Revisión de cambios remotos — a9ad733

Consulta realizada el 2026-11-07, según fecha del entorno. Base comparativa: `e8e2d84`. Remoto revisado: `a9ad733c9a32c362483a5ce7dae5154296cdb433`, 20 commits adicionales y 77 archivos modificados. Se usó un worktree separado; no se integraron los cambios en la rama local ni se hizo push.

## Resultados y pendientes

1. **Alta: siguen abiertos los fallos de integridad de la segunda fase.** Se ejecutó `python -m pytest -q tests audit/2026-11-06-phase2/phase2_checks.py` con Python 3.12 y las dependencias bloqueadas existentes: **167 aprobadas y 13 fallidas**, 180 casos totales. La suite propia suma 127 aprobadas; los 53 controles de auditoría aportan 40 aprobadas y los mismos 13 fallos. Persisten truncado de extractos sin caché/argumentos inválidos, volumen duplicado y consumo de QAA obsoleto, además de los otros escenarios documentados. Evidencia: `audit/2026-11-07-remote-review/pytest.txt`. No equivale a 13 vulnerabilidades distintas.
2. **Media: CI dejó de escuchar la rama de trabajo.** `.github/workflows/build.yml:4` cambia `near_hackaton` por `main`. En `hackathons`, los pushes a `near_hackaton` no activan este workflow. Sigue disponible la ejecución manual y por PR. La configuración puede ser deliberada para el upstream `main`, pero requiere adaptar el filtro al repositorio de trabajo si se desea mantener allí el gate automático. La condición de Pages también perdió la restricción al nombre del repositorio; revisar intención antes de futuros pushes a `main`.
3. **Media: reintentos potencialmente ilimitados en código nuevo.** `near_thesis/fetch.py:126-148`, `_nearblocks_paged`: el cuerpo con `message` sin filas vuelve al `while True` y reinicia el contador de ocho intentos. Reproducción con `fetch_json` simulado devolviendo `{'message':'rate limited'}`, sin red ni esperas reales: nueve respuestas consecutivas no terminan el proceso; se detuvo la simulación antes de la décima mediante un `BaseException` de control. Un cursor repetido tampoco tiene guard de avance visible. Aplicar un presupuesto global de reintentos/tiempo por página y detectar cursores repetidos.
4. **Media: afirmaciones de causalidad más fuertes que los datos.** `docs/BALANCE_AUDITORIA_2026-11-08.md:39` afirma que el swap de los 17 casos restantes es anterior al rango examinado. No encontrarlo en ese rango no demuestra existencia ni ubicación anterior: debe quedar como “no observado en el rango; origen sin determinar”. También conviene expresar que la muestra sistemática aporta evidencia contra una explicación puramente muestral, condicionada al diseño y al estimador de error, en lugar de excluir categóricamente toda posibilidad de error de muestreo.
5. **Trazabilidad temporal pendiente.** Hay documentos fechados 2026-11-08 pese a que el entorno marca 2026-11-07; el commit merge está fechado 2026-11-07T22:28:59-06:00. Verificar zona horaria y fechas reales de ejecución antes de tratarlas como evidencia prospectiva. No se presupone alteración deliberada.

## Aportes nuevos

Se agregaron módulos `reconcile`, `bridge` y `narrative`, muestras intradía y sistemática, trazas de retiros/intercambios, plan OOS persistido, sensibilidad QAA y rediseño del dashboard. Los documentos reconocen que volumen global, validación mensual/externa de QAA y atribución económica completa siguen abiertos. Son avances de evidencia y presentación; no cierran automáticamente la revisión de seguridad/calidad ni justifican por sí mismos una nota 96/100, que esta revisión no asigna.

## Estado de repositorios

`git ls-remote` confirmó en la consulta:

- `NGZeggers/hackathons`, `near_hackaton`: `a9ad733c9a32c362483a5ce7dae5154296cdb433`.
- `NGZeggers/near-value-shift`, `HEAD` y `main`: **el mismo commit `a9ad733`**.

El original sí ha avanzado respecto al `4843bcb` comprobado anteriormente; esta revisión hizo únicamente consultas de lectura y no causó ese cambio. Los documentos históricos del 3, 4 y 5 de noviembre también recibieron resúmenes nuevos en este rango; las evidencias de `audit/2026-11-03` y de la segunda fase no se modificaron en el diff revisado.

No se repitió aquí el build completo, el navegador ni la adquisición de miles de bloques. Las cifras publicadas por los commits nuevos se distinguen de las pruebas ejecutadas en esta revisión. La rama local principal permanece en `e8e2d84`; `megi-revision/` sigue fuera del alcance.
