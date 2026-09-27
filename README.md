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

## Arquitectura

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
   (sus respuestas alimentan las reglas como `jev.<key>`)
   ▼
Opciones permitidas por ESMO (reglas deterministas)               ← spec.opciones[].cuando
   ▼
Capa 3 Jev: eleccion entre las opciones validas + beneficio esperado
   ▼
Capa 4 Jev: seguridad / contraindicaciones (bloquean opciones)    ← spec.seguridad (+ reglas comunes)
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
  jev_client.py            # Cliente Jev: real (typesafe-sdk) o mock si no hay API key
  evaluation/              # Evaluacion: viñetas por tumor + cohorte METABRIC (mama)
scripts/                   # validate_specs.py, run_vignettes.py, run_evaluation.py
data/eval/                 # Resultados de evaluacion por tumor
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

La pestaña **📊 Evaluacion** muestra (y permite relanzar) dos pruebas:

1. **Casos de referencia ESMO** (campo `vinetas` de cada spec): 404 viñetas en
   43 tumores, con la respuesta esperada segun la guia vigente e incluyendo casos
   de seguridad (datos faltantes, contraindicaciones). Muestra el acierto global,
   por especialidad y por tumor, y la **dificultad real** (casos donde Jev tuvo
   que elegir entre 2 o mas opciones validas).
2. **METABRIC** (cBioPortal `brca_metabric`, Curtis 2012 / Pereira 2016), solo
   mama: cohorte real. Compara con el tratamiento recibido y calcula el AUC, la
   calibracion y el valor pronostico (Kaplan-Meier).

```powershell
.\.venv\Scripts\python.exe scripts\run_evaluation.py            # todo
.\.venv\Scripts\python.exe scripts\run_evaluation.py --no-metabric
```

Ultimos resultados (Jev real): viñetas **404/404**, opcion preferida 96,5%, 132
casos con eleccion real entre 2 o mas opciones: 100%. METABRIC luminal precoz:
AUC 0,92, sensibilidad 93%.

**Limitaciones**: las viñetas las ha redactado IA a partir de las guias y
**deben validarse por oncologos**. Los arboles se iteraron con esas mismas
viñetas, asi que el 100% sobreestima el rendimiento en casos reales. Los arboles
simplifican las guias: las situaciones no modeladas terminan en "fuera del arbol"
con revision obligatoria. METABRIC es practica de 1977-2005 y ECOG se asume 0.

## Siguientes pasos

- Validacion clinica de cada spec y viñeta por especialistas de cada area.
- Cohortes reales de otros tumores (p.ej. MSK-CHORD en cBioPortal).
- Persistencia/auditoria de cada decision (paciente, version del arbol,
  preguntas y respuestas, aprobacion humana).
