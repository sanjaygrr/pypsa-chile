# Cómo contribuir

Gracias por querer aportar. Las tareas abiertas están en los issues con las etiquetas
`good first issue` (1–3 horas) y `help wanted` (más grandes).

## Preparar el entorno

```bash
git clone https://github.com/<tu-usuario>/pypsa-chile.git
cd pypsa-chile
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install pytest
pytest
```

## Reglas

- **Sin red en los tests.** Los tests usan fixtures pequeñas, nunca descargan datos del CEN.
- **No versionar datos raw del CEN.** Todo lo que está en `data/raw/` y `data/processed/` queda fuera del repo.
- **Un issue, un PR.** Si el cambio es grande, abre primero un issue y conversémoslo.
- **Cambios mínimos.** Un bug fix no necesita refactorizar el módulo entero.
- **Tests para cada bug.** Si arreglas algo, agrega un test que falle antes y pase después.

## Pull requests

1. Crea una rama desde `main` con un nombre claro (`fix/cache-manifest`, `docs/readme-data`).
2. Corre `pytest` y confirma que pasa.
3. Abre el PR describiendo qué cambió, por qué y cómo lo probaste.
4. Si usas IA para escribir código, revisa y entiende lo que envías: el mismo estándar de calidad aplica.

Respondo los PR lo antes posible; si pasan días sin respuesta, escribe un comentario en el issue.
