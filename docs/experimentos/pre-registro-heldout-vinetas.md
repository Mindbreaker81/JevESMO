# Pre-registro: conjunto de viñetas held-out

Fecha: 2026-10-03. Objetivo: una estimacion honesta del acierto. Metodo tomado
del banco de pruebas de Jev, donde cada evaluacion nueva se pre-registra y el
conjunto de referencia se congela por commit antes de ejecutar.

## Problema que resuelve

Las 404 viñetas de `src/jevesmo/tumors/*.json` se usaron para iterar los
arboles, asi que el 100% actual sobreestima el acierto real (limitacion
declarada en el README). Hace falta un conjunto de viñetas que nunca haya
servido para ajustar specs.

## Reglas del conjunto held-out

1. Los archivos viven en `src/jevesmo/heldout/<tumor>.json` con el formato
   `{"tumor": "<id>", "vinetas": [<vineta>, ...]}` (mismo esquema `Vineta`
   que `spec.vinetas`).

2. **Quien redacta las viñetas held-out no es quien itera los arboles.**
   Se redactan a ciegas de los fallos conocidos, a partir de las guias ESMO
   vigentes, y se validan con `python scripts/validate_specs.py --heldout`.

3. **El conjunto se congela por commit antes de la primera ejecucion.** El
   hash del archivo queda registrado en cada run (`heldout_sha256` en
   `data/eval/_heldout_<tumor>.json`), junto al commit, el modelo resuelto,
   el SDK y el host. Si el conjunto cambia, el run siguiente lo deja constar.

4. **Ningun resultado held-out se usa para ajustar specs** hasta despues de
   su ejecucion completa y registrada. Corregir un arbol a partir de un fallo
   held-out convierte esa viñeta en una de desarrollo: se mueve al spec
   (`vinetas`) y se redacta una sustituta held-out nueva a ciegas.

5. Ejecucion: `python scripts/run_vignettes.py --heldout` (o
   `scripts/run_evaluation.py --heldout`). Los fallos de API no cuentan como
   aciertos ni como fallos: se reintentan con `--retry-errors` y se reportan
   aparte en `errores`.

## Criterio de lectura (fijado antes de ejecutar)

- Se reporta por tumor: `aciertos/n`, `acierto_tratamiento`,
  `acierto_seguridad`, `acierto_multiopcion`, `errores`, IC95 de Wilson del
  acierto global (`scripts/compare_eval_runs.py` lo calcula al comparar runs,
  o bien se lee directamente de la metrica).
- `brier_confianza`/`ece_confianza` calibran la confianza reportada frente al
  acierto, con mas sentido aqui que en las viñetas de desarrollo (casi todo
  acierto).
- No se publica un numero unico como "el acierto del sistema": el held-out es
  una muestra por tumor, no una prevalencia real.
- El resultado no valida clinicamente las viñetas: la validacion por
  oncologos requiere su propio flujo (segunda anotacion + adjudicacion).

## Estado

Conjunto aun vacio (`src/jevesmo/heldout/` solo con `.gitkeep`): las viñetas
las aporta un redactor distinto del mantenedor de los arboles, por
especialidad, empezando por mama y CPNM (los tumores con cohorte real para
contrastar).
