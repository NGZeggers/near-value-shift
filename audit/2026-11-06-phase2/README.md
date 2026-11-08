# Evidencias — segunda fase, 2026-11-06

Base `743e24374d41c8ca604414896ffd8066d9c70441`. Informe: [segunda revisión](../../docs/SEGUNDA_REVISION_2026-11-06.md).

Los archivos son resultados de ejecución, no un gate verde. `combined.txt/xml` conserva **13 fallos / 132 aprobados**. Las reproducciones adicionales están fuera de `tests/` para no alterar la suite original ni el CI durante esta fase de diagnóstico.

Desde la raíz del repositorio, con sus dependencias bloqueadas y pytest-cov instalado en un entorno de auditoría:

```bash
python -m pytest -q tests audit/2026-11-06-phase2/phase2_checks.py --cov=near_thesis --cov-branch
```

En la base auditada se esperan 13 fallos. Las pruebas usan temporales y monkeypatch para evitar truncar los extractos reales. `offline-data-loss.json` documenta la reproducción independiente sobre copias temporales.

Para navegador se requieren Playwright/Chromium y axe-core 4.14.0 instalados fuera del proyecto. El script guarda resultados en `/tmp/near-phase2-browser`; acepta `PHASE2_ROOT`, `PHASE2_OUT` y `PHASE2_AXE` (ruta a `axe.min.js`) como variables de entorno. Las adaptaciones de rutas del script archivado no cambian los escenarios ejecutados. Los resultados incluidos corresponden a su ejecución inicial en el worktree aislado. Bloquea peticiones externas y reporta resultados; no usa el código de salida como gate.

```bash
PHASE2_AXE=/ruta/axe.min.js python audit/2026-11-06-phase2/phase2_browser.py
```

`dependencies.json`: pip-audit fresco. `bandit.json`: análisis estático. `github-status.json`: datos sanitizados de API autenticada, sin credenciales. `full-provenance/`: reconciliación completa contra caché; `live-witnesses.json`: cuatro verificaciones GET recientes. `HACKATHON-20261106.md`: captura de reglas oficiales, consultar cambios antes de entregar. `coverage.json` conserva rutas de la ejecución aislada.

Los manifiestos históricos se verificaron sin modificarlos. `evidence-sha256.json` cubre todos los archivos de esta carpeta excepto el propio manifiesto. Los resultados no certifican ausencia de defectos, secretos ni vulnerabilidades desconocidas.
