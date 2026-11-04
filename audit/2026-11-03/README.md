# Evidencias de auditoría NEAR — 2026-11-03

Commit analizado: `4843bcb7b3e876bdfc330820358240b44d4f4311`, rama `near_hackaton` de `NGZeggers/hackathons`.

El [informe](../../docs/AUDITORIA_FUNCIONAL_SEGURIDAD_2026-11-03.md) contiene el dictamen, prioridades, reproducciones, impacto, recomendaciones y límites. Este paquete añade únicamente documentación y pruebas independientes; no cambia el código de la solución, sus dependencias, los workflows ni el repositorio `NGZeggers/near-value-shift`.

## Resultados originales

- Suite existente: 25 pasan.
- Suite existente más 24 controles independientes: 37 pasan y 12 fallan. Los fallos reproducen problemas pendientes, no correcciones.
- Navegador Chromium: 27 controles pasan y 1 falla con una serie sintética de ceros.
- Integridad: 91 controles pasan. Dos builds completos; comparación analítica correcta con Git y entre builds.
- Dependencias: 155 versiones contrastadas, sin avisos conocidos reportados en la consulta original.

`summary.json`, los JUnit y logs registran la ejecución original. `coverage.json` mide la ejecución pytest ampliada, no el build ni el navegador. Los logs y metadatos conservan las rutas locales originales. Las fechas son 3 de noviembre en México y 4 de noviembre en UTC.

## Reproducción

Ejecutar desde la raíz del repositorio con Python 3.12 y uv:

```sh
uv sync --locked --all-extras
uv run pytest -q tests
uv run pytest -q tests audit/2026-11-03/audit_checks.py
```

En el commit auditado la segunda ejecución debe devolver código distinto de cero: se esperan 12 fallos y 37 casos correctos. `audit_checks.py` está fuera de `tests/` para conservar el comportamiento del target existente. Ninguna prueba de este archivo firma transacciones ni ejecuta consultas BigQuery: los caminos sensibles usan dobles y datos sintéticos.

```sh
make build
uv run python -m near_thesis.check_generated --baseline-dir audit/2026-11-03/baseline-after-build
python3 audit/2026-11-03/verify_evidence.py
make -n onchain SEND=0
```

El baseline contiene los artefactos analíticos de la primera reconstrucción completa; no es una nueva fuente de datos. El comparador permite únicamente la tolerancia numérica declarada en el código. `make build` ejecuta Jupyter y necesita permitir puertos loopback.

Para repetir la guardia offline de sockets Python, usar una ruta absoluta en `PYTHONPATH`, `UV_OFFLINE=true` y `AUDIT_NETWORK_LOG` apuntando a un archivo nuevo fuera del paquete; ejecutar `make build`. El módulo `offline-guard/sitecustomize.py` permite loopback/Unix y rechaza conexiones externas Python. Es un control del proceso Python, no un firewall de sistema. La ejecución original no produjo un log de intentos externos.

La cobertura requiere instalar `coverage` y `pytest-cov` en un entorno de auditoría separado; las dependencias del proyecto se conservan como están. Añadir `--cov=near_thesis --cov-branch` a la ejecución de pytest permite repetir la medición.

Para el navegador, instalar Playwright y Chromium en un entorno separado. Con el proyecto ya reconstruido y su intérprete Playwright:

```sh
python audit/2026-11-03/audit_browser.py
```

El script inicia un servidor efímero en `127.0.0.1`, abre archivos locales y consulta el demo público mediante GET. Guarda resultados/capturas en un directorio temporal nuevo y lo imprime. `NEAR_AUDIT_ROOT` permite usar otra copia reconstruida; `NEAR_AUDIT_OUTPUT` permite elegir el destino de los resultados. El script imprime controles fallidos en JSON; su código de salida no representa un gate de todos los controles. La disponibilidad y los datos del demo pueden cambiar después de esta auditoría.

## Contenido y alcance

`sources/` conserva las reglas oficiales y el prompt de ejemplo consultados. `live-block-checks.json` registra cuatro bloques contrastados con FastNear. `raw-hashes.json` identifica los 65 snapshots. `secret-scan.json`, `bandit.json` y `dependencies.json` documentan los controles de seguridad, sin constituir una garantía universal. `public-actions.json` y `public-repository.json` son respuestas públicas de GitHub.

`evidence-sha256.json` cubre el contenido versionado de esta carpeta salvo el propio manifiesto y los caches Python. Los scripts de pruebas son reproducciones ejecutables; otras comprobaciones realizadas mediante comandos ad hoc conservan resultados y logs, sin prometer un runner integral de toda la auditoría. El checksum comprueba integridad respecto al manifiesto, no una firma externa de autenticidad.
