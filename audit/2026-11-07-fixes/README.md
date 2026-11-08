# Evidencias de correcciones y pruebas robustas

Base `a9ad733`; fuentes corregidas identificadas en `source-sha256.json`. Informe: [correcciones](../../docs/FIXES_SEGUNDA_FASE_2026-11-07.md). Esta carpeta añade evidencia nueva; no reemplaza las ejecuciones históricas fallidas.

Reproducción desde la raíz, con dependencias del proyecto instaladas:

```bash
uv sync --locked --all-extras
make build
make test
uv run pytest -q audit/2026-11-06-phase2/phase2_checks.py
```

Resultados esperados: 203 pruebas en la suite y 53 en las reproducciones históricas. Para instrumentación se usó un entorno de auditoría separado con pytest-cov, Playwright/Chromium y axe-core 4.14.0; no se modificó el lock del proyecto.

```bash
python tests/browser_dashboard.py
PHASE2_AXE=/ruta/axe.min.js PHASE2_OUT=/tmp/near-fixes-browser python audit/2026-11-07-fixes/browser_hardening.py
```

El primer comando de navegador es un gate; el segundo reporta JSON y debe comprobarse que todos los casos `checks.json` sean verdaderos. El segundo también conserva la evaluación axe y sus reglas incompletas. Ambos necesitan los paquetes de instrumentación. Los resultados archivados corresponden al checkout final salvo los primeros builds y el ensayo explícito de 53 casos en el worktree aislado, cuyas rutas se conservan en los logs.

`reproducibility.txt` registra la comparación contra la instantánea corregida de la primera regeneración. Una vez commiteados los resultados intencionales, `make check-generated` debe compararlos con ese nuevo HEAD. Antes del commit, HEAD sigue conteniendo las salidas anteriores y ese gate reportará diferencias esperadas.

`input-integrity.json` compara snapshots de entrada y evidencia histórica con HEAD. `generated-sha256.json` identifica las salidas entregadas. `provenance-summary.json` resume una nueva reconciliación offline de la caché. `evidence-sha256.json` cubre todos los archivos de esta carpeta excepto su propio contenido. No incluye secretos ni credenciales.
