# Revisión adversaria del diseño

Un agente revisor independiente recibió el encargo de **atacar** el diseño de JevESMO:
buscar formas en que pudiera recomendar algo inseguro, ocultar incertidumbre o
sobrevender su evaluación. Encontró 16 problemas. Esta tabla recoge cada uno y qué
se hizo con él.

| # | Gravedad | Problema | Estado | Qué se cambió |
|---|---|---|---|---|
| 1 | Crítica | Las reglas admitían opciones inválidas (mama: T-DM1 adyuvante sin enfermedad residual, sacituzumab en 1ª línea, "endocrino add-on" mal definido) | ✅ Corregido | Nuevo campo `enfermedad_residual`; sacituzumab exige `lineas_previas ≥ 1`; la opción pasa a "mantenimiento anti-HER2 + endocrino tras inducción". Validador que exige que una opción de 2ª línea o posterior compruebe líneas previas. |
| 2 | Crítica | Seguridad probabilística que fallaba **abierta**: sin respuesta de Jev, no se bloqueaba nada | ✅ Corregido | Tipos `duro` / `jev` / `revision`. La FEVI < 50% bloquea anti-HER2 de forma determinista. Una regla `jev` sin respuesta bloquea; cerca del umbral, exige revisión. |
| 3 | Crítica | `ajuste_dosis` se preguntaba pero no tenía efecto | ✅ Corregido | Si Jev indica ajuste o no responde, se exige revisión (`funcion_organica`). |
| 4 | Crítica | La UI podía mostrar un resultado de un caso anterior tras editar el formulario o fallar la API | ✅ Corregido | El resultado se guarda con una huella (hash) de los datos, se borra antes de cada cálculo y se oculta si el formulario cambia. |
| 5 | Alta | Los datos ausentes cambiaban la elegibilidad en silencio (`lineas_previas` vacío = 1ª línea; FEVI opcional) | ✅ Corregido | Comprobación contrafactual `datos_criticos_ausentes`. FEVI obligatoria si HER2+. |
| 6 | Alta | El modo simulado producía "recomendaciones", y la app degradaba en silencio si faltaba el SDK | ✅ Corregido | El modo simulado siempre añade `modo_simulado` (revisión obligatoria) y la UI lo advierte. Con clave pero sin SDK, la app da error. |
| 7 | Alta | El umbral de confianza de 0,6 no está calibrado | ⚠️ Parcial | Se añade el motivo `opciones_equilibradas` (margen < 0,15) y se documenta que el umbral no está calibrado. La calibración por tumor requiere datos clínicos etiquetados. |
| 8 | Alta | El texto libre puede influir en Jev pero no activa reglas de seguridad; riesgo de inyección | ⚠️ Parcial | El texto se envía delimitado como datos, no instrucciones. La capa 4.5 pregunta `manipulacion_ficha` (noul) cuando hay texto libre: p ≥ 0,5 → revisión obligatoria. En la batería congelada detecta 28/30 fichas manipuladas en 3 pasadas (10/10, 9/10, 9/10) con 0/30 FP en honestas; la de palabras repetidas (M06) es inestable alrededor del umbral (p=0,54, 0,48, 0,49) (pre-registro en `docs/experimentos/`). Pendiente: extracción estructurada de hechos de seguridad y ampliar la batería a más tumores. |
| 9 | Alta | Las 116 preguntas de las capas 1-2 no las usa ninguna regla, aunque la documentación decía que sí | ✅ Corregido (transparencia) | La documentación y la UI dicen la verdad: son contexto para la capa 3 ("solo contexto"). |
| 10 | Alta | La métrica de seguridad de las viñetas daba por buena cualquier revisión, incluso por baja confianza | ✅ Corregido | Nueva métrica `acierto_seguridad_robusta`: exige un motivo de seguridad o de datos. |
| 11 | Alta | La concordancia "exacta" de MSK era en realidad por clase, y la cobertura se excluía | ✅ Corregido | Renombrada a "misma clase terapéutica". Se añaden la cobertura y la concordancia compatible ITT. |
| 12 | Alta | Sesgo de espectro en MSK (muestra enriquecida) y fuga temporal de biomarcadores | ⚠️ Limitación documentada | Advertencia en la UI y en el README. Sin ponderación por prevalencia ni fechado de biomarcadores. |
| 13 | Media | La "calibración" de METABRIC está mal nombrada | ✅ Corregido | Renombrada a "concordancia histórica por nivel de confianza". |
| 14 | Media | No se validaban los rangos numéricos | ✅ Corregido | Un valor fuera de rango devuelve `necesita_datos`. |
| 15 | Media | `ne`/`nin` eran verdaderos con el dato ausente | ✅ Corregido | Lógica trivalente. Se reescribieron 76 usos a `not(eq/in)` y se comprobó que el conjunto de candidatas no cambia salvo en las correcciones de mama. |
| 16 | Media | La UI atribuía toda revisión a "baja confianza" | ✅ Corregido | Se muestra la lista `motivos_revision`, además de una tabla de comprobaciones de seguridad. |

## Efecto medido (Jev real)

- Viñetas: 404/404; opción preferida 96,5%; seguridad robusta 100% (re-evaluadas con la capa 4.5 activa).
- **El 52% de los casos de tratamiento acertados quedan marcados para revisión** (48% antes de la capa 4.5). Los
  motivos principales son datos opcionales ausentes que podrían cambiar la opción. El
  sistema es ahora más conservador: prefiere escalar a un oncólogo antes que suponer.
- MSK-CHORD: cobertura 94%, compatible 81% (77% ITT). Los casos de mama HER2+ piden
  la FEVI antes de recomendar anti-HER2.
- Capa 4.5 (auditoría Jev→Jev, posterior a esta revisión): en MSK-CHORD pareado
  el acierto agregado no cambia y la revisión sube de 18,7% a 26,7% (McNemar
  p=0,00012), marcando 14/42 discordancias reales frente a 11/42 sin auditoría. Alerta de manipulación:
  28/30 detectadas en 3 pasadas, 0/30 FP en el conjunto congelado.
- `tests/test_engine.py`: 73 pruebas de regresión: bloqueo duro por FEVI, fallo
  cerrado, datos fuera de rango, lógica trivalente, modo simulado, auditoría
  (desacuerdo, manipulación, sin respuesta, desactivada), backend alternativo y
  que la opción preferida de todas las viñetas sigue siendo candidata.

## Lo que sigue pendiente

- Validación de los árboles y las viñetas por oncólogos de cada área.
- Calibración del umbral de confianza con casos clínicos etiquetados.
- Extracción estructurada de datos de seguridad desde el texto libre.
- Anonimización de datos de salud y consentimiento antes de enviar datos a una API externa.
- Análisis de supervivencia ajustados y control de la fuga temporal en MSK-CHORD.
