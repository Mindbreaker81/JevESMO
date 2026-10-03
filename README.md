# JevESMO

App de apoyo a la decision clinica oncologica: a partir de la ficha clinica de
un paciente oncologico (**43 tumores de 11 especialidades** cubiertas por las
guias ESMO), recorre el arbol de decision de las guias **ESMO** y usa **Jev** (System One Model de [TypeSafe AI](https://typesafe.ai))
para las decisiones que requieren juicio clinico, devolviendo una
recomendacion **explicable** (que se pregunto, que respondio, con que
confianza) y **nunca autonoma**: si falta informacion o la confianza es baja,
la app pregunta o exige revision de un oncologo.

> ⚠️ Prototipo de investigacion. No es un dispositivo medico certificado ni
> sustituye el criterio clinico. Toda recomendacion requiere validacion por
> un oncologo.

**Vídeo de 20 s:** [docs/media/JevESMO_20s.mp4](docs/media/JevESMO_20s.mp4)

## Arquitectura

> Explicacion detallada del flujo de decision y de como se usa Jev:
> [docs/FLUJO_DECISION.md](docs/FLUJO_DECISION.md)

Motor generico + un **spec JSON por tumor** (`src/jevesmo/tumors/<id>.json`).
El motor (`src/jevesmo/engine/`) es identico para todos los tumores:

```
Ficha del paciente (formulario generado desde el spec)
   │
   ├─ Faltan datos imprescindibles (requerido / requerido_si) → la app PREGUNTA y no calcula
   ▼
Derivados deterministas (subtipo, grupo de riesgo...)            ← spec.derivados
   ▼
Capas 1-2 Jev: juicio clinico en zonas grises (Choice/Score/Noul) ← spec.preguntas
   (sus respuestas son contexto para la capa 3; hoy no activan reglas)
   ▼
Opciones permitidas por ESMO (reglas deterministas)               ← spec.opciones[].cuando
   ▼
Capa 3 Jev: eleccion entre las opciones validas + beneficio esperado
   ▼
Capa 4 Jev: seguridad / contraindicaciones (bloquean opciones)    ← spec.seguridad (+ reglas comunes)
   ▼
Capa 4.5 Jev: auditoria (2ª lectura; activa por defecto, JEVESMO_AUDITORIA=0 la desactiva)
   · solo puede ANADIR revisiones: desacuerdo del revisor o posible
     manipulacion del texto libre — nunca cambia la recomendacion
   ▼
Gate de confianza (< 60%, sin opcion segura, o ECOG 3-4 no candidato → revision obligatoria)
   ▼
Resultado + explicabilidad completa (preguntas, respuestas, probabilidades)
```

El conocimiento "duro" (que permite ESMO) vive en los specs, versionados y
auditables; Jev solo emite juicios acotados sobre el caso concreto dentro de las
opciones validas.

### Tumores cubiertos

| Especialidad | Tumores (id) |
|---|---|
| Mama | mama |
| Toracico | cpnm_precoz, cpnm_metastasico, cpm, mesotelioma, timo |
| Digestivo | esofago, gastrico, pancreas, biliar, hcc, colon_localizado, recto, ccr_metastasico, anal, gist, tne_gep |
| Genitourinario | prostata, vejiga, rinon, testiculo, pene |
| Ginecologico | ovario, endometrio, cervix, vulva |
| Cabeza y cuello / Endocrino | cyc_escamoso, nasofaringe, tiroides |
| Piel | melanoma, carcinoma_escamoso_cutaneo, carcinoma_basocelular, merkel |
| Sarcomas | sarcoma_partes_blandas, sarcoma_oseo |
| Neurooncologia | glioma |
| Origen desconocido | cod |
| Hematologia | dlbcl, folicular, hodgkin, llc, mieloma, manto |

### Anadir o modificar un tumor

1. Crea/edita `src/jevesmo/tumors/<id>.json` (esquema en `engine/spec.py`,
   lenguaje de condiciones en `engine/conditions.py`; `mama.json` es la referencia).
2. `python scripts\validate_specs.py <id>`
3. `python scripts\run_vignettes.py <id>` (contra Jev real).

## Estructura del proyecto

```
app.py                     # App visual (Streamlit): formulario dinamico + resultados + evaluacion
src/jevesmo/
  engine/spec.py           # Esquema de los specs + campos comunes + validador
  engine/conditions.py     # Lenguaje de condiciones (eq, in, gte, missing, any/all/not, jev.*)
  engine/pipeline.py       # Motor generico: run(tumor_id, datos, client)
  tumors/*.json            # 43 arboles ESMO (opciones, preguntas Jev, seguridad, viñetas)
  heldout/*.json           # Viñetas held-out (no usadas para iterar; congeladas por commit)
  adversarial/*.json       # Bateria de fichas manipuladas/honestas (alerta de manipulacion)
  jev_client.py            # Cliente Jev (typesafe-sdk, mock si no hay key) + make_client()
  llm_client.py            # Backend LLM alternativo opt-in via system-one-adapter
  evaluation/              # Evaluacion: viñetas + METABRIC + MSK-CHORD + held-out +
                           # adversarial + stats (McNemar/Wilson/Brier/ECE) + comparador
scripts/                   # validate_specs, run_vignettes, run_evaluation, run_adversarial,
                           # compare_eval_runs
data/eval/                 # Resultados de evaluacion por tumor
docs/experimentos/         # Pre-registros: held-out y manipulacion (congelados por commit)
```

## Como conseguir la clave de la API de Jev

1. Entra en <https://console.typesafe.ai/> y crea una cuenta (o inicia sesion).
2. Ve al dashboard de claves: <https://console.typesafe.ai/keys>.
3. Genera una API key nueva.
4. Copia `.env.example` a `.env` y pega la clave:
   ```
   TYPESAFE_API_KEY=sk-...
   JEV_MODEL=jev-latest
   ```
5. Instala el SDK oficial (ya incluido en `pyproject.toml`):
   ```powershell
   pip install typesafe-sdk
   ```

Sin clave configurada, la app funciona igualmente en **modo mock**: genera
respuestas simuladas deterministas para poder probar todo el flujo, y las
marca explicitamente en la UI y en la traza (`"simulado": true`) para que
nunca se confundan con una respuesta real de Jev.

### Backend LLM alternativo (opcional, no validado)

Con `pip install -e ".[llm]"` (`system-one-adapter` + SDK del proveedor) se
puede evaluar con un LLM generico en vez de Jev — util como baseline
comparativo o para un
despliegue que no pueda enviar datos a la API externa. Es **opt-in
explicito**: nunca se selecciona como fallback silencioso, y todo caso
evaluado con el lleva el motivo permanente `backend_alternativo` (revision
humana obligatoria).

```
JEVESMO_BACKEND=llm
JEVESMO_LLM_PROVIDER=openai      # openai|anthropic|gemini
JEVESMO_LLM_MODEL=llama3.2:1b
JEVESMO_LLM_BASE_URL=http://localhost:11434/v1   # OpenAI-compatible (Ollama, vLLM...)
JEVESMO_LLM_ANSWER_MODE=probabilities            # probabilities|discrete
```

Para comparar backend alternativo vs Jev sobre las mismas viñetas:
`run_vignettes.py` en cada configuracion y `compare_eval_runs.py` (McNemar
pareado). Aviso del banco: un decisor no-Jev **no** hereda la deteccion de
manipulacion de Jev — la capa 4.5 corre igualmente, pero su calidad hay que
medirla con la bateria adversarial propia (`run_adversarial.py`).

## Instalacion y ejecucion

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -e .
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abre <http://localhost:8501>. Panel izquierdo: datos del paciente y del
tumor. Panel derecho: recomendacion, alternativas, avisos por datos
faltantes y la traza de explicabilidad capa a capa.

## Uso programatico (sin UI)

```python
from jevesmo.engine.pipeline import run

resultado = run("mama", {
    "edad": 45, "estadio": "IV", "tipo_histologico": "ductal_invasivo",
    "ecog": "1", "premenopausica": True, "her2": "negativo",
    "re": "positivo", "rp": "positivo", "ki67_porcentaje": 22.0,
    "lineas_previas": 1, "esr1_mutado": True,
})
```

Si `resultado["status"] == "necesita_datos"`, `resultado["preguntas"]`
contiene las preguntas que hay que responder antes de continuar.

## Evaluacion

La pestaña **📊 Evaluacion** muestra (y permite relanzar) tres pruebas:

1. **Casos de referencia ESMO** (campo `vinetas` de cada spec): 404 viñetas en
   43 tumores, con la respuesta esperada segun la guia vigente e incluyendo casos
   de seguridad (datos faltantes, contraindicaciones). Muestra el acierto global,
   por especialidad y por tumor, y la **dificultad real** (casos donde Jev tuvo
   que elegir entre 2 o mas opciones validas).
2. **Bateria adversarial** (`src/jevesmo/adversarial/`): fichas cuyo texto libre
   intenta sesgar la decision (ordenes al evaluador, datos inventados,
   aprobaciones falsas) mezcladas con notas largas y honestas. Mide la alerta
   de manipulacion de la capa 4.5.
3. **METABRIC** (cBioPortal `brca_metabric`, Curtis 2012 / Pereira 2016), solo
   mama: cohorte real. Compara con el tratamiento recibido y calcula el AUC, la
   concordancia por nivel de confianza (no es una calibracion clinica) y el valor pronostico (Kaplan-Meier).
4. **MSK-CHORD** (cBioPortal `msk_chord_2024`, Jee et al., *Nature* 2024):
   cohorte real de Memorial Sloan Kettering (~25.000 pacientes, 2014-2022) con
   linea temporal de tratamientos, ECOG y genomica MSK-IMPACT. Se reconstruye la
   1ª linea de pacientes metastasicos de novo de **CPNM, colorrectal, pancreas y
   mama** (60 por tumor), se construye el caso (edad, ECOG, histologia, EGFR/ALK/
   ROS1/BRAF/MET/RET/NTRK/KRAS G12C/HER2, RAS/BRAF/MSI y lateralidad, BRCA, HR/HER2)
   y se compara la recomendacion con el tratamiento recibido (*misma clase terapeutica* y
   *compatible*: mismo escalon ESMO) y con la supervivencia global.

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation.py            # todo
.\.venv\Scripts\python.exe scripts\run_evaluation.py --no-metabric
.\.venv\Scripts\python.exe scripts\run_evaluation.py --solo-msk    # solo MSK-CHORD
.\.venv\Scripts\python.exe scripts\run_evaluation.py --retry-errors # repite solo las filas con error de API
.\.venv\Scripts\python.exe scripts\run_evaluation.py --heldout     # vinetas held-out
.\.venv\Scripts\python.exe scripts\run_adversarial.py            # bateria de manipulacion
```

Solo los fallos de transporte o de API (timeouts, conexion, rate limit, 5xx)
no cuentan como aciertos ni como fallos: se reportan aparte en `errores` y se
repiten con `--retry-errors`, que conserva las filas sanas del run guardado.
Cualquier otra excepcion (spec roto, bug del pipeline) **si cuenta como
fallo** (`fallos_pipeline`). `--retry-errors` aborta si el run guardado no
coincide con la configuracion actual (auditoria, backend, modelo, specs). Cada
run guarda un manifiesto: alias y versiones resueltas de Jev, si la capa 4.5
estaba activa, commit, SDK, host (hash) y hash SHA-256 de cada spec. Las
curvas de supervivencia con n<5 se suprimen (licencia de MSK-CHORD).

**Viñetas held-out** (`src/jevesmo/heldout/<tumor>.json`): un conjunto nuevo
que no se usa para iterar los arboles, congelado por commit antes de la
primera ejecucion. Es la estimacion honesta del acierto (las viñetas del spec
sirvieron para iterar). Protocolo y criterio de lectura:
[docs/experimentos/pre-registro-heldout-vinetas.md](docs/experimentos/pre-registro-heldout-vinetas.md).

**Comparar dos runs** (cascada, backend alternativo, dos versiones de un
spec): McNemar pareado + IC95 de Wilson sobre las filas por caso:

```powershell
.\.venv\Scripts\python.exe scripts\compare_eval_runs.py data\eval\mama.json data\eval\_heldout_mama.json --metric acierto
```

Ultimos resultados (Jev real, tras la revision adversaria;
todas las viñetas re-evaluadas con la capa 4.5 activa, ver `auditoria` en el
manifiesto de cada fichero): viñetas **404/404** (la auditoria marca ademas
34 con `desacuerdo_revisor`),
opcion preferida 96,5%, 130 casos con eleccion real entre 2 o mas opciones: 100%,
seguridad robusta (escala por un motivo de seguridad/datos, no solo baja confianza)
100%. **El 52% de los casos de tratamiento acertados se marcan igualmente para
revision** (sobre todo por datos opcionales ausentes que podrian cambiar la opcion):
es el precio de fallar en modo seguro. METABRIC luminal precoz: AUC 0,92,
sensibilidad 93%.

MSK-CHORD (n=240, 226 evaluables, cobertura 94%):

| Tumor | Evaluables | Misma clase terapeutica | Compatible |
|---|---|---|---|
| CPNM metastasico | 60/60 | 72% | 72% |
| CCR metastasico | 57/60 | 16% | 88% |
| Pancreas metastasico | 60/60 | 45% | 97% |
| Mama metastasica | 49/60 | 59% | 67% |
| **Global** | 226/240 | 48% | 81% (ITT 77%) |

En mama, los 11 casos HER2+ piden ahora la FEVI (no consta en MSK-CHORD) antes de
recomendar anti-HER2. La muestra esta **enriquecida** (CPNM alterna con/sin driver)
y el global no refleja la prevalencia real.

En CPNM con driver accionable en 1ª linea, Jev recomienda terapia dirigida en el
100% de los casos (SG a 24 m: 65% con dirigida vs 57% sin ella). En CCR, MSK suele
empezar FOLFOX sin biologico (se cuenta como compatible). En pancreas, Jev prefiere
gemcitabina + nab-paclitaxel y MSK FOLFIRINOX (equivalentes en ESMO). Las
discordancias en CPNM sin driver son sobre todo quimio sola (practica anterior a
2018) frente a quimio-inmunoterapia.

**Capa 4.5 (auditoria) medida**: con el conjunto adversarial congelado,
Jev detecta **28/30 fichas manipuladas (3 pasadas: 10/10, 9/10, 9/10) con 0/30 falsos positivos** en honestas; la ficha M06 (palabras repetidas) es inestable, con p=0,54, 0,48 y 0,49 frente al umbral 0,5
(criterio pre-registrado: >=7/10 y <=1/10). En MSK-CHORD pareado (240 casos
con/sin auditoria, re-ejecutado con el manifiesto corregido) el acierto
agregado es identico (183/239 compatibles en ambos; Jev no es determinista:
en 2 casos de pancreas la primera eleccion cambio entre ejecuciones) y las
marcas suben de 18,7% a 26,7% (McNemar p=0,00012, 225 pares), capturando
14/42 discordancias reales con la practica MSK frente a 11/42 sin auditoria.
Las tablas 2x2 pareadas (solo contadores, sin datos de paciente) estan en
`data/eval/_msk_chord_pareado.json` (`scripts/export_msk_pareado.py`) para verificar el McNemar. La comparativa Jev vs
`llama3.2:1b` local via backend alternativo: **22/22 vs 13/22** en mama
(McNemar p=0,0039).

**Limitaciones**: las viñetas las ha redactado IA a partir de las guias y
**deben validarse por oncologos**. Los arboles se iteraron con esas mismas
viñetas, asi que el 100% sobreestima el rendimiento en casos reales (el
conjunto held-out esta pendiente de un redactor externo). El conjunto
adversarial lo redacto el mismo agente que implemento la alerta: casos y
criterio estan congelados por commit, pero la validacion clinica sigue
pendiente. Los arboles
simplifican las guias: las situaciones no modeladas terminan en "fuera del arbol"
con revision obligatoria. METABRIC es practica de 1977-2005 y ECOG se asume 0. En MSK-CHORD **concordar
con la practica no equivale a acertar**; hay datos imputados (PD-L1 solo
positivo/negativo, edad aproximada, RE/RP = estado HR global, localizacion del
pancreas y resecabilidad del CCR cuando no constan), y la comparacion de
supervivencia es observacional. Licencia CC BY-NC-ND 4.0: el repositorio solo
contiene metricas agregadas; los datos por paciente se descargan en local
(`data/msk_chord/`, ignorado por git).

Ver [docs/REVISION_ADVERSARIA.md](docs/REVISION_ADVERSARIA.md) para los problemas de
diseño encontrados, lo corregido y lo que sigue siendo una limitacion.

## Siguientes pasos

- **Viñetas held-out**: pendiente un redactor distinto del iterador de los
  arboles (maquinaria, pre-registro y congelado por commit listos).
- **Validacion clinica** de cada spec y viñeta por especialistas de cada area,
  con doble anotacion y adjudicacion.
- Cohortes reales de otros tumores (p.ej. MSK-CHORD en cBioPortal).
- Persistencia/auditoria de cada decision — parcialmente hecho: cada run y
  cada caso registran alias + version resuelta de Jev, commit, host, SDK y
  hash SHA-256 del spec; falta persistir la decision clinica completa con la
  aprobacion humana.
- Ampliar la bateria adversarial a mas tumores si la señal se mantiene.
