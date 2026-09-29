"""App visual JevESMO (Streamlit).

Multi-tumor: cada tumor ESMO es un spec JSON (src/jevesmo/tumors) y el
formulario se genera dinamicamente a partir de el.

Panel izquierdo: descripción del paciente y del tumor.
Panel derecho: recomendación, ranking de alternativas y explicabilidad
(que se le pregunto a Jev en cada capa y que respondio, con su confianza).

Si faltan datos clínicos imprescindibles, la app pregunta antes de intentar
generar ninguna recomendación.

Ejecutar con:  streamlit run app.py
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from jevesmo.engine.pipeline import CONFIDENCE_THRESHOLD, run  # noqa: E402
from jevesmo.engine.spec import Campo, TumorSpec, load_all  # noqa: E402
from jevesmo.jev_client import JevClient  # noqa: E402

st.set_page_config(page_title="JevESMO — Guías ESMO + Jev", layout="wide")
UNK = "desconocido"


def inject_css() -> None:
    css = (ROOT / "assets" / "neobrutalist.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def e(value: object) -> str:
    return html.escape("" if value is None else str(value))


def nb(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


@st.cache_resource
def get_client() -> JevClient:
    return JevClient()


def specs_by_group() -> dict[str, list[TumorSpec]]:
    groups: dict[str, list[TumorSpec]] = {}
    for sp in sorted(load_all().values(), key=lambda x: (x.grupo, x.nombre)):
        groups.setdefault(sp.grupo, []).append(sp)
    return groups


def _key(spec: TumorSpec, c: Campo) -> str:
    return f"{spec.id}.{c.id}"


def _to_widget(c: Campo, v: object) -> object:
    """Valor de payload -> valor de widget (para cargar ejemplos)."""
    if v is None or v == "" or v == []:
        return None if c.tipo == "number" else ("" if c.tipo in ("text", "list") else UNK)
    if c.tipo == "bool":
        return "si" if v else "no"
    if c.tipo == "number":
        f = float(v)
        lo = c.min if c.min is not None else -1e9
        hi = c.max if c.max is not None else 1e9
        return min(max(f, lo), hi)
    if c.tipo == "list":
        return ", ".join(map(str, v)) if isinstance(v, list) else str(v)
    return str(v)


def _load_example(spec: TumorSpec, vid: str) -> None:
    v = next((x for x in spec.vinetas if x.id == vid), None)
    for c in spec.all_campos():
        st.session_state[_key(spec, c)] = _to_widget(c, (v.payload if v else {}).get(c.id))


def _widget(spec: TumorSpec, c: Campo, box) -> object:
    k = _key(spec, c)
    label = c.label + (f" ({c.unidad})" if c.unidad else "") + (" *" if c.requerido else "")
    if c.tipo == "choice":
        labels = {o.id: o.label for o in c.opciones}
        v = box.selectbox(label, [UNK] + list(labels), key=k, help=c.ayuda,
                          format_func=lambda x: "— desconocido —" if x == UNK else labels.get(x, {"si": "sí"}.get(x, x)))
        return None if v == UNK else v
    if c.tipo == "bool":
        v = box.selectbox(label, [UNK, "si", "no"], key=k, help=c.ayuda,
                          format_func=lambda x: "— desconocido / no testado —" if x == UNK else {"si": "sí"}.get(x, x))
        return {"si": True, "no": False}.get(v)
    if c.tipo == "number":
        return box.number_input(label, min_value=c.min, max_value=c.max, value=None, step=1.0, format="%g",
                                key=k, help=c.ayuda, placeholder="no disponible")
    if c.tipo == "list":
        v = box.text_input(label + " · separar por comas", key=k, help=c.ayuda)
        return [x.strip() for x in v.split(",") if x.strip()]
    if c.id == "descripcion_libre":
        return box.text_area(label, key=k, height=100, help=c.ayuda)
    return box.text_input(label, key=k, help=c.ayuda) or None


def render_form() -> tuple[TumorSpec, dict]:
    nb('<div class="nb-section">01 · Paciente y tumor</div>')
    groups = specs_by_group()
    c1, c2 = st.columns([1, 2])
    grupo = c1.selectbox("Especialidad", list(groups), key="sel_grupo",
                         index=list(groups).index("Mama") if "Mama" in groups else 0)
    opciones = groups[grupo]
    spec = c2.selectbox("Tumor", opciones, key=f"sel_tumor.{grupo}", format_func=lambda x: x.nombre)

    guias = " · ".join(f'<a href="{e(g.url)}" target="_blank">{e(g.titulo)} ({e(g.anio)})</a>' for g in spec.guias)
    nb(f'<div class="nb-card cyan"><div class="note">{e(spec.descripcion)}</div>'
       f'<div class="src">Guías · {guias}</div></div>')

    if spec.vinetas:
        c1, c2 = st.columns([3, 1])
        ej = c1.selectbox("Cargar caso de ejemplo", [""] + [v.id for v in spec.vinetas], key=f"ej.{spec.id}",
                          format_func=lambda x: "— caso en blanco —" if not x else
                          f"{x} · {next(v.titulo for v in spec.vinetas if v.id == x)}")
        c2.button("Cargar", key=f"load.{spec.id}", on_click=_load_example, args=(spec, ej), width="stretch")

    secciones: dict[str, list[Campo]] = {}
    for c in spec.all_campos():
        if c.id != "descripcion_libre":
            secciones.setdefault(c.seccion, []).append(c)
    raw: dict = {}
    for i, (sec, campos) in enumerate(secciones.items()):
        req = any(c.requerido for c in campos)
        with st.expander(sec + (" · obligatorios *" if req else ""), expanded=i < 2 or req):
            cols = st.columns(2)
            for j, c in enumerate(campos):
                raw[c.id] = _widget(spec, c, cols[j % 2])
    dl = spec.campo("descripcion_libre")
    raw["descripcion_libre"] = _widget(spec, dl, st)
    nb('<div class="note">* obligatorio. Deja en "desconocido" lo que no sepas: la app te preguntará lo imprescindible.</div>')
    return spec, raw


def _meter(conf: float | None) -> str:
    if conf is None:
        return '<div class="nb-meter low"><div class="lbl"><b>SIN DATO</b></div></div>'
    pct = max(0.0, min(conf, 1.0)) * 100
    low = " low" if conf < CONFIDENCE_THRESHOLD else ""
    thr = CONFIDENCE_THRESHOLD * 100
    return (
        f'<div class="nb-meter{low}"><span class="fill" style="width:{pct:.0f}%"></span>'
        f'<div class="nb-threshold" style="left:{thr:.0f}%" title="Umbral {thr:.0f}%"></div>'
        f'<div class="lbl"><b>CONFIANZA {pct:.0f}% · UMBRAL {thr:.0f}%</b></div></div>'
    )


def _prob_bars(probs: dict) -> str:
    rows = []
    for k, v in sorted(probs.items(), key=lambda kv: -float(kv[1] or 0)):
        p = float(v or 0) * 100
        rows.append(
            f'<div class="nb-bar"><span class="k" title="{e(k)}">{e(k)}</span>'
            f'<span class="track"><div class="fillb" style="width:{p:.0f}%"></div></span>'
            f'<span class="v">{p:.0f}%</span></div>'
        )
    return "".join(rows)


def _format_value(v: object) -> str:
    if isinstance(v, float):
        return f"{v:.2f}"
    return e(v)


def render_results(resultado: dict) -> None:
    nb('<div class="nb-section right">02 · Resultado</div>')

    if resultado["status"] == "necesita_datos":
        items = "".join(f"<li>{e(p)}</li>" for p in resultado["preguntas"])
        nb(
            '<div class="nb-card yellow"><h3>Necesito más datos</h3>'
            "<div>Faltan datos clínicos imprescindibles. No voy a recomendar nada hasta que me respondas:</div>"
            f"<ul>{items}</ul></div>"
        )
        return

    rec = resultado["recomendacion_principal"]
    conf = resultado["confianza"]

    nb(
        f'<span class="nb-tag yellow">{e(resultado.get("grupo"))} · {e(resultado.get("tumor_nombre"))}</span>'
        + "".join(f'<span class="nb-tag lilac">{e(k)} · {e(v)}</span>' for k, v in (resultado.get("derivados") or {}).items() if v)
        + f'<span class="nb-tag">Árbol · {e(resultado["esmo_tree_version"])}</span>'
    )

    if resultado["requiere_revision_humana"]:
        motivos = resultado.get("motivos_revision") or []
        items = "".join(
            f"<li>{e(m['texto'])}"
            + (f" ({(conf or 0):.0%} &lt; {CONFIDENCE_THRESHOLD:.0%})" if m["codigo"] == "confianza_baja" and conf is not None else "")
            + "</li>"
            for m in motivos
        )
        nb(
            '<div class="nb-card red"><h3>Revisión obligatoria por oncólogo</h3>'
            f"<div>Motivos:</div><ul>{items}</ul></div>"
        )

    if rec:
        nb(
            '<div class="nb-card green"><h3>Recomendación principal</h3>'
            f'<div class="big">{e(rec["label"])}</div>'
            f'<div class="note">{e(rec["esmo_note"])}</div>'
            + (_meter(conf) if conf is not None else '<div class="note">Sin confianza del modelo para esta opción (alternativa tras un bloqueo de seguridad).</div>')
            + "</div>"
        )
    else:
        nb('<div class="nb-card"><h3>Sin recomendación</h3>Ninguna opción candidata es segura.</div>')

    if resultado["avisos_datos_faltantes"]:
        items = "".join(f"<li>{e(a)}</li>" for a in resultado["avisos_datos_faltantes"])
        nb(f'<div class="nb-card yellow"><h3>Datos que mejorarían la decisión</h3><ul>{items}</ul></div>')

    nb('<div class="nb-section right">03 · Alternativas ESMO</div>')
    chosen_id = rec["id"] if rec else None
    for i, c in enumerate(resultado["candidatos"], start=1):
        cls = "blocked" if c["contraindicado"] else ("chosen" if c["id"] == chosen_id else "")
        extra = f'<div class="n">✕ {e(c["motivo_contraindicacion"])}</div>' if c["contraindicado"] else ""
        nb(
            f'<div class="nb-option {cls}"><div class="badge">{i}</div><div>'
            f'<div class="t">{e(c["label"])}</div><div class="n">{e(c["esmo_note"])}'
            f'{" · evidencia " + e(c["evidencia"]) if c.get("evidencia") else ""}</div>{extra}</div></div>'
        )

    seg = resultado.get("seguridad") or []
    if seg:
        rows = "".join(
            f'<tr class="{"ko" if s["bloquea"] else "ok"}"><td><b>{e(s["regla"])}</b></td><td>{e(s["tipo"])}</td>'
            f'<td>{e(s["motivo"])}</td><td>{e(s["resultado"])}</td></tr>'
            for s in seg
        )
        nb('<div class="nb-card"><h3>Comprobaciones de seguridad</h3><table class="nb-table"><thead><tr><th>Regla</th>'
           '<th>Tipo</th><th>Motivo</th><th>Resultado</th></tr></thead><tbody>' + rows + "</tbody></table>"
           '<div class="note">duro = bloqueo determinista · jev = contraindicación relativa valorada por Jev (falla cerrado) · '
           "revisión = exige valoración del especialista</div></div>")

    nb('<div class="nb-section right">04 · Explicabilidad</div>')
    for capa in resultado["explicabilidad"]:
        n = len(capa["preguntas"])
        with st.expander(f'{capa["capa"]} · {n} pregunta{"s" if n != 1 else ""}', expanded=False):
            if not n:
                nb('<div class="note">En esta capa no hizo falta preguntar nada a Jev para este caso.</div>')
                continue
            for key, q in capa["preguntas"].items():
                ans = capa["respuestas"].get(key, {})
                tags = f'<span class="nb-tag cyan">{e(q["tipo"])}</span>'
                uso = q.get("uso")
                if uso == "contexto":
                    tags += '<span class="nb-tag yellow" title="No activa ninguna regla: solo se pasa como contexto a la elección">solo contexto</span>'
                elif uso == "regla":
                    tags += '<span class="nb-tag green">usada en reglas</span>'
                if ans.get("confianza") is not None:
                    tags += f'<span class="nb-tag">conf {ans["confianza"]:.0%}</span>'
                if ans.get("simulado"):
                    tags += '<span class="nb-tag red">simulado</span>'
                bars = _prob_bars(ans["probabilidades"]) if ans.get("probabilidades") else ""
                nb(
                    f'<div class="nb-q"><div class="qt">{e(key)}</div>'
                    f"<div>{e(q['instrucciones'])}</div>"
                    f'<div class="ans">→ {_format_value(ans.get("valor"))}</div>{tags}{bars}</div>'
                )


def _pct(v: object) -> str:
    return "—" if v is None else f"{float(v):.0%}"


def _kpi(label: str, value: str, color: str = "", sub: str = "") -> str:
    return (
        f'<div class="nb-card {color} nb-kpi"><div class="kl">{e(label)}</div>'
        f'<div class="kv">{e(value)}</div><div class="note">{e(sub)}</div></div>'
    )


def _hbar(label: str, value: float | None, color: str = "cyan", suffix: str = "") -> str:
    p = 0 if value is None else max(0.0, min(float(value), 1.0)) * 100
    txt = "—" if value is None else f"{p:.0f}%{suffix}"
    return (
        f'<div class="nb-hbar"><span class="k">{e(label)}</span>'
        f'<span class="track"><span class="f {color}" style="width:{p:.0f}%"></span></span>'
        f'<span class="v">{e(txt)}</span></div>'
    )


def _kpi_row(items: list[str]) -> None:
    for col, html_ in zip(st.columns(len(items)), items):
        with col:
            nb(html_)


def _vignette_table(casos: list[dict]) -> None:
    rows_html = []
    for c in casos:
        cls = "ok" if c["acierto"] else "ko"
        conf = "" if c["confianza"] is None else f"{c['confianza']:.0%}"
        rows_html.append(
            f'<tr class="{cls}"><td><b>{e(c["id"])}</b></td><td>{e(c["titulo"])}<div class="src">{e(c["fuente"])}</div></td>'
            f'<td><code>{e(c["esperado"])}</code></td><td><code>{e(c["obtenido"])}</code></td>'
            f'<td>{e(c.get("n_candidatos", ""))}</td><td>{e(conf)}</td><td class="st">{"✔" if c["acierto"] else "✘"}</td></tr>'
        )
    nb(
        '<table class="nb-table"><thead><tr><th>ID</th><th>Caso</th><th>Esperado (ESMO)</th>'
        '<th>Obtenido</th><th>Opc.</th><th>Conf.</th><th></th></tr></thead><tbody>' + "".join(rows_html) + "</tbody></table>"
    )


def _color(v: float | None) -> str:
    return "" if v is None else ("green" if v >= .9 else "yellow" if v >= .75 else "red")


def render_evaluation(client: JevClient) -> None:
    from jevesmo.evaluation.runner import DEFAULT_STRATA, load_results, run_all

    specs = load_all()
    nb('<div class="nb-section">Evaluación</div>')
    nb(
        '<div class="nb-card"><b>Cómo se evalúa JevESMO.</b> Tres pruebas complementarias:'
        f"<ul><li><b>Casos de referencia ESMO</b> ({len(specs)} tumores): viñetas con la respuesta que marca la guía "
        "vigente de cada tumor. Mide si acierta el tratamiento y si se comporta con seguridad (pregunta cuando faltan "
        "datos, bloquea opciones peligrosas).</li>"
        "<li><b>METABRIC</b> (cBioPortal, Curtis et al. 2012 · Pereira et al. 2016): cohorte real de "
        "pacientes con cáncer de mama. Compara la recomendación con el tratamiento que realmente recibieron "
        "y con su evolución (supervivencia libre de recaída).</li>"
        "<li><b>MSK-CHORD</b> (cBioPortal, Jee et al. <i>Nature</i> 2024): cohorte real de Memorial Sloan Kettering "
        "(~25.000 pacientes, 2014-2022) con línea temporal de tratamientos, ECOG y perfil genómico MSK-IMPACT. "
        "Se usa para CPNM, colorrectal y páncreas metastásicos y mama metastásica: compara la 1ª línea que "
        "recomienda JevESMO con la que realmente recibió cada paciente y con su supervivencia global.</li></ul></div>"
    )

    with st.expander("▶ Ejecutar una nueva evaluación", expanded=False):
        sel = st.multiselect("Tumores (viñetas)", sorted(specs), default=sorted(specs),
                             format_func=lambda t: f"{specs[t].grupo} · {specs[t].nombre}")
        do_met = st.checkbox("Incluir cohorte METABRIC (mama, ~200 pacientes)", value=False)
        cm1, cm2 = st.columns([3, 1])
        do_msk = cm1.checkbox("Incluir cohorte MSK-CHORD (CPNM, CCR, páncreas y mama metastásicos)", value=False)
        msk_n = cm2.number_input("Pacientes por tumor", 10, 300, 60, step=10)
        c1, c2, c3, c4, c5 = st.columns(5)
        strata = {
            "HR+/HER2-": c1.number_input("HR+/HER2-", 0, 1000, DEFAULT_STRATA["HR+/HER2-"], step=10),
            "TNBC": c2.number_input("TNBC", 0, 300, DEFAULT_STRATA["TNBC"], step=10),
            "HER2+": c3.number_input("HER2+", 0, 100, DEFAULT_STRATA["HER2+"], step=10),
            "HR+/HER2+": c4.number_input("HR+/HER2+", 0, 100, DEFAULT_STRATA["HR+/HER2+"], step=10),
        }
        seed = c5.number_input("Semilla", 0, 9999, 42)
        if client.is_mock:
            nb('<div class="nb-card red">Modo simulado: los resultados no reflejarán el rendimiento real de Jev.</div>')
        if st.button("▶ Ejecutar evaluación", width="stretch", disabled=not (sel or do_met or do_msk)):
            bar = st.progress(0.0, text="Iniciando...")

            def prog(done: int, total: int, label: str) -> None:
                bar.progress(done / total, text=f"{label}: {done}/{total}")

            try:
                run_all(client=client, tumors=sel or [], metabric_too=do_met, msk_too=do_msk, msk_n=int(msk_n),
                        strata={k: int(v) for k, v in strata.items()}, seed=int(seed), progress=prog)
                st.rerun()
            except Exception as exc:
                nb(f'<div class="nb-card red"><h3>Error en la evaluación</h3><div class="note">{e(exc)}</div></div>')

    res = load_results()
    if not res["tumores"] and not res["metabric"] and not res.get("msk_chord"):
        nb('<div class="nb-empty">Aún no hay resultados.<br>Ejecuta una evaluación.</div>')
        return

    # ------------------------------------------------ Vinetas ESMO (todas las especialidades)
    tum = res["tumores"]
    if tum:
        g = res["global"]
        modelos = sorted({x["modelo"] for x in tum.values()})
        fechas = sorted(x["fecha"] for x in tum.values())
        mock = any(x["mock"] for x in tum.values())
        nb(
            f'<span class="nb-tag {"red" if mock else "green"}">Modelo · {e(", ".join(modelos))}</span>'
            f'<span class="nb-tag">Última ejecución · {e(fechas[-1][:16].replace("T", " "))} UTC</span>'
            f'<span class="nb-tag">Umbral de confianza · {_pct(CONFIDENCE_THRESHOLD)}</span>'
        )
        nb('<div class="nb-section right">A · Casos de referencia ESMO · todas las especialidades</div>')
        _kpi_row([
            _kpi("Acierto global", _pct(g["acierto_global"]), _color(g["acierto_global"]),
                 f"{g['aciertos']}/{g['n']} casos · {len(tum)} tumores"),
            _kpi("Tratamiento correcto", _pct(g["acierto_tratamiento"]), "cyan", "1ª opción dentro de lo aceptable"),
            _kpi("Opción preferida", _pct(g["acierto_preferida"]), "lilac", "la primera elección de ESMO"),
            _kpi("Seguridad", _pct(g["acierto_seguridad"]), "pink",
                 f"pregunta / escala · robusta {_pct(g.get('acierto_seguridad_robusta'))}"),
        ])
        if g.get("pct_tratamiento_con_revision") is not None:
            nb('<div class="note">Seguridad robusta = el caso se escaló por un motivo de seguridad o de datos, no solo por baja '
               f'confianza del modelo. Casos de tratamiento acertados y sin revisión: {_pct(g.get("tratamiento_sin_revision"))} · '
               f'marcados para revisión: {_pct(g.get("pct_tratamiento_con_revision"))}.</div>')
        if g.get("n_multiopcion") is not None:
            nb(
                '<div class="nb-card yellow"><h3>Dificultad real de la decisión</h3>'
                f'<div>En {g["n_multiopcion"]} de los casos de tratamiento el árbol ESMO dejó <b>2 o más opciones válidas</b> '
                f'y Jev tuvo que elegir (media {g["candidatos_medios"] or 0:.1f} candidatos por caso). '
                "En el resto, las reglas deterministas del árbol ya dejaban una única opción.</div><br>"
                + _hbar(f"Acierto cuando Jev elige entre ≥ 2 opciones (n={g['n_multiopcion']})", g["acierto_multiopcion"], "lilac")
                + "</div>"
            )
        nb(
            '<div class="nb-card">'
            + _hbar("Confianza media en aciertos", g["confianza_aciertos"], "green")
            + _hbar("Confianza media en fallos", g["confianza_fallos"], "red")
            + "</div>"
        )

        por_grupo: dict[str, list[dict]] = {}
        for x in tum.values():
            por_grupo.setdefault(x["grupo"], []).append(x)
        bars = []
        for grupo, xs in sorted(por_grupo.items()):
            n = sum(x["n"] for x in xs)
            ok = sum(x["aciertos"] for x in xs)
            bars.append(_hbar(f"{grupo} ({ok}/{n})", ok / n if n else None, _color(ok / n if n else None) or "cyan"))
        nb('<div class="nb-card"><h3>Acierto por especialidad</h3>' + "".join(bars) + "</div>")

        rows = []
        for x in sorted(tum.values(), key=lambda x: (x["grupo"], x["nombre"])):
            rows.append(
                f'<tr class="{"ok" if x["acierto_global"] and x["acierto_global"] >= .8 else "ko"}">'
                f'<td>{e(x["grupo"])}</td><td><b>{e(x["nombre"])}</b><div class="src">{e(x["version"])}</div></td>'
                f'<td>{x["aciertos"]}/{x["n"]}</td><td>{_pct(x["acierto_tratamiento"])}</td>'
                f'<td>{_pct(x["acierto_preferida"])}</td><td>{_pct(x["acierto_seguridad"])}</td>'
                f'<td>{_pct(x["confianza_aciertos"])}</td></tr>'
            )
        nb(
            '<table class="nb-table"><thead><tr><th>Especialidad</th><th>Tumor</th><th>Aciertos</th>'
            '<th>Tratamiento</th><th>Preferida</th><th>Seguridad</th><th>Conf. aciertos</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>"
        )

        nb('<div class="nb-section right">Detalle por tumor</div>')
        ids = sorted(tum, key=lambda t: (tum[t]["grupo"], tum[t]["nombre"]))
        t = st.selectbox("Tumor", ids, key="eval_tumor",
                         format_func=lambda t: f"{tum[t]['grupo']} · {tum[t]['nombre']} ({tum[t]['aciertos']}/{tum[t]['n']})")
        _vignette_table(tum[t]["casos"])

    # ------------------------------------------------ METABRIC
    m = res["metabric"]
    if not m:
        _render_msk(res.get("msk_chord"))
        return
    g, lum = m["global"], m["luminal_precoz"]
    nb('<div class="nb-section right">B · Cohorte real METABRIC</div>')
    _kpi_row([
        _kpi("Pacientes evaluadas", str(m["n"]), "yellow", "muestra estratificada por subtipo"),
        _kpi("AUC P(quimio)", "—" if lum["auc_p_quimio"] is None else f"{lum['auc_p_quimio']:.2f}", "green",
             "HR+/HER2- precoz: ¿distingue quién recibió quimio?"),
        _kpi("Sensibilidad quimio", _pct(lum["quimio"]["sensibilidad"]), "cyan", "HR+/HER2- precoz"),
        _kpi("Revisión humana", _pct(g["revision_pct"]), "pink", "casos escalados a oncólogo"),
    ])

    pr = lum["pronostico_sin_quimio"]
    hi, lo = pr["jev_alto_riesgo"], pr["jev_bajo_riesgo"]
    nb(
        '<div class="nb-card yellow"><h3>Valor pronóstico · pacientes HR+/HER2- que NO recibieron quimio</h3>'
        "<div>Si Jev acierta al identificar el alto riesgo, las pacientes a las que habría indicado quimio "
        "(y no la recibieron) deberían recaer más.</div><br>"
        + _hbar(f"Jev: alto riesgo · RFS 5 años (n={hi['n']})", hi["rfs_60m"], "red")
        + _hbar(f"Jev: bajo riesgo · RFS 5 años (n={lo['n']})", lo["rfs_60m"], "green")
        + _hbar(f"Jev: alto riesgo · RFS 10 años (n={hi['n']})", hi["rfs_120m"], "red")
        + _hbar(f"Jev: bajo riesgo · RFS 10 años (n={lo['n']})", lo["rfs_120m"], "green")
        + '<div class="note">RFS = supervivencia libre de recaída (Kaplan-Meier).</div></div>'
    )

    c1, c2 = st.columns(2, gap="large")
    with c1:
        q = lum["quimio"]
        kappa = "—" if q["kappa"] is None else f"{q['kappa']:.2f}"
        nb(
            '<div class="nb-card"><h3>Matriz · quimio en HR+/HER2- precoz</h3>'
            '<table class="nb-cm"><tr><th></th><th>Recibió QT</th><th>No recibió</th></tr>'
            f'<tr><th>Jev: QT</th><td class="g">{q["tp"]}</td><td class="y">{q["fp"]}</td></tr>'
            f'<tr><th>Jev: no QT</th><td class="r">{q["fn"]}</td><td class="g">{q["tn"]}</td></tr></table>'
            f'<div class="note">Concordancia {_pct(q["concordancia"])} · especificidad {_pct(q["especificidad"])} · '
            f"kappa {kappa}</div></div>"
        )
    with c2:
        cal = "".join(
            _hbar(f"Conf. {b['rango']} (n={b['n']})", b["concordancia"], "lilac") for b in lum["calibracion"]
        )
        nb(
            '<div class="nb-card"><h3>Concordancia histórica por nivel de confianza</h3>'
            f"{cal}<div class=\"note\">No es una calibración clínica: compara con el tratamiento que se dio en "
            "1977-2005, no con el tratamiento correcto.</div></div>"
        )

    sub_rows = []
    for sub, d in m["por_subtipo"].items():
        sub_rows.append(
            f"<tr><td><b>{e(sub)}</b></td><td>{d['n']}</td>"
            f"<td>{_pct(d['quimio']['concordancia'])}</td><td>{_pct(d['endocrino']['concordancia'])}</td>"
            f"<td>{_pct(d['revision_pct'])}</td></tr>"
        )
    nb(
        '<table class="nb-table"><thead><tr><th>Subtipo</th><th>n</th><th>Concordancia quimio</th>'
        "<th>Concordancia endocrino</th><th>Revisión</th></tr></thead><tbody>" + "".join(sub_rows) + "</tbody></table>"
    )

    nb(
        '<div class="nb-card red"><h3>Cómo interpretar estos resultados</h3><ul>'
        "<li>METABRIC recoge tratamientos de 1977-2005: <b>concordar con la práctica histórica no equivale a acertar</b>. "
        "No existía trastuzumab ni inmunoterapia, y entonces la quimio en HR+ se usaba poco; por eso la concordancia "
        "en HER2+ y TNBC es baja por diseño.</li>"
        "<li>Los resultados más informativos son el <b>AUC</b> y el <b>valor pronóstico</b>: miden si Jev identifica "
        "a las pacientes de alto riesgo.</li>"
        "<li>ECOG no existe en METABRIC y se asume 0. No hay Ki67, BRCA ni PD-L1.</li>"
        "<li>Las viñetas ESMO se han redactado a partir de las guías y <b>deben validarse por un oncólogo</b>. "
        "Son pocas por tumor: un acierto alto no garantiza el rendimiento en casos reales.</li></ul></div>"
    )

    with st.expander(f"Ver los {m['n']} casos METABRIC evaluados"):
        st.dataframe(
            [{k: c[k] for k in ("patient_id", "subtipo", "estadio", "edad", "grado", "tamano_mm", "ganglios",
                                "recomendacion", "confianza", "p_quimio", "real_quimio", "real_endocrino",
                                "rfs_months", "rfs_event")} for c in m["casos"]],
            width="stretch", hide_index=True,
        )

    _render_msk(res.get("msk_chord"))


def _os_txt(o: dict | None) -> str:
    if not o or not o.get("n"):
        return "—"
    med = o.get("mediana_meses")
    return f"{'no alcanzada' if med is None else f'{med:.1f} m'}"


def _render_msk(r: dict | None) -> None:
    if not r or not r.get("tumores"):
        return
    g, tums = r["global"], r["tumores"]
    casos = r.get("casos") or {}
    nb('<div class="nb-section right">C · Cohorte real MSK-CHORD · otros tumores</div>')
    nb(
        f'<span class="nb-tag {"red" if r.get("mock") else "green"}">Modelo · {e(r.get("modelo", ""))}</span>'
        f'<span class="nb-tag">Ejecución · {e(str(r.get("fecha", ""))[:16].replace("T", " "))} UTC</span>'
        f'<span class="nb-tag yellow">MSK-CHORD · CC BY-NC-ND 4.0 · solo métricas agregadas</span>'
    )
    oc, od = g["os_concordante"], g["os_discordante"]
    _kpi_row([
        _kpi("Pacientes evaluables", f"{g['evaluables']}/{g['n']}", "yellow", f"{len(tums)} tumores · 1ª línea metastásica"),
        _kpi("Concordancia compatible", _pct(g["compatible"]), _color(g["compatible"]) or "cyan",
             f"mismo escalón ESMO · sobre todos (ITT) {_pct(g.get('compatible_itt'))}"),
        _kpi("Misma clase terapéutica", _pct(g["exacta"]), "lilac", "p. ej. dirigida, quimio-IO, anti-EGFR (no régimen exacto)"),
        _kpi("SG mediana conc. / disc.", f"{_os_txt(oc)} / {_os_txt(od)}", "pink",
             f"n={oc.get('n', 0)} / {od.get('n', 0)} · observacional"),
    ])

    rows = []
    for tid, x in tums.items():
        rows.append(
            f'<tr class="{"ok" if (x["compatible"] or 0) >= .75 else "ko"}"><td><b>{e(x["nombre"])}</b>'
            f'<div class="src">{e(x.get("compatible_nota", ""))}</div></td>'
            f'<td>{x["evaluables"]}/{x["n"]}</td><td>{_pct(x["exacta"])}</td><td>{_pct(x["compatible"])}</td>'
            f'<td>{x.get("necesita_datos", 0)}</td><td>{_pct(x.get("revision_pct"))}</td>'
            f'<td>{_os_txt(x.get("os_concordante"))} / {_os_txt(x.get("os_discordante"))}</td></tr>'
        )
    nb(
        '<table class="nb-table"><thead><tr><th>Tumor</th><th>Evaluables</th><th>Misma clase</th><th>Compatible</th>'
        '<th>Pide datos</th><th>Revisión</th><th>SG mediana conc./disc.</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table>"
    )

    d = (tums.get("cpnm_metastasico") or {}).get("driver_dirigida")
    if d:
        a, b = d.get("os_recibio_dirigida") or {}, d.get("os_no_recibio_dirigida") or {}
        nb(
            '<div class="nb-card yellow"><h3>CPNM con driver accionable en 1ª línea (EGFR, ALK, ROS1, BRAF, MET, RET, NTRK)</h3>'
            + _hbar("Jev recomienda terapia dirigida", d.get("jev_recomienda_dirigida"), "green")
            + _hbar(f"SG 24 m · recibió dirigida (n={a.get('n', 0)})", a.get("os_24m"), "green")
            + _hbar(f"SG 24 m · no recibió dirigida (n={b.get('n', 0)})", b.get("os_24m"), "red")
            + f'<div class="note">Mediana SG: {_os_txt(a)} con dirigida vs {_os_txt(b)} sin dirigida. '
            "KRAS G12C y HER2 mutado se excluyen: ESMO reserva su terapia dirigida para 2ª línea. "
            "Muestras pequeñas; comparación no aleatorizada.</div></div>"
        )

    nb('<div class="nb-section right">Detalle MSK-CHORD por tumor</div>')
    tid = st.selectbox("Tumor (MSK-CHORD)", list(tums), key="eval_msk_tumor",
                       format_func=lambda k: f"{tums[k]['nombre']} (n={tums[k]['n']})")
    x = tums[tid]
    c1, c2 = st.columns(2, gap="large")
    with c1:
        mat = x.get("matriz") or {}
        cols = sorted({c for row in mat.values() for c in row})
        head = "".join(f"<th>{e(c)}</th>" for c in cols)
        body = "".join(
            f"<tr><th>Jev: {e(rk)}</th>"
            + "".join(f'<td class="{"g" if c == rk else "y"}">{row.get(c, 0)}</td>' for c in cols) + "</tr>"
            for rk, row in mat.items()
        )
        nb(
            '<div class="nb-card"><h3>Matriz · recomendación Jev vs 1ª línea recibida</h3>'
            f'<table class="nb-cm"><tr><th></th>{head}</tr>{body}</table>'
            '<div class="note">Filas: clase recomendada por Jev. Columnas: clase recibida en MSK.</div></div>'
        )
    with c2:
        bars = "".join(
            _hbar(f"{s} (n={v['evaluables']})", v.get("compatible"), _color(v.get("compatible")) or "cyan")
            for s, v in (x.get("por_subgrupo") or {}).items()
        )
        nb(f'<div class="nb-card"><h3>Concordancia compatible por subgrupo</h3>{bars}</div>')
        oc, od = x.get("os_concordante") or {}, x.get("os_discordante") or {}
        nb(
            '<div class="nb-card"><h3>Supervivencia global (Kaplan-Meier)</h3>'
            + _hbar(f"SG 12 m · concordantes (n={oc.get('n', 0)})", oc.get("os_12m"), "green")
            + _hbar(f"SG 12 m · discordantes (n={od.get('n', 0)})", od.get("os_12m"), "red")
            + _hbar(f"SG 24 m · concordantes (n={oc.get('n', 0)})", oc.get("os_24m"), "green")
            + _hbar(f"SG 24 m · discordantes (n={od.get('n', 0)})", od.get("os_24m"), "red")
            + "</div>"
        )

    nb(
        '<div class="nb-card red"><h3>Cómo interpretar MSK-CHORD</h3><ul>'
        "<li><b>Muestra no representativa</b>: 60 pacientes por tumor; en CPNM se alterna deliberadamente con y sin driver "
        "(enriquecida), y solo entran casos con ECOG y 1ª línea registrados. El global no refleja la prevalencia real. "
        "Los biomarcadores MSK-IMPACT pueden haberse obtenido después de iniciar la 1ª línea.</li>"
        "<li><b>Concordar con la práctica de MSK no equivale a acertar</b>: mide si la recomendación es la que "
        "eligen oncólogos expertos en un centro de referencia. Las discordancias pueden deberse a la época "
        "(2014-2022, antes de algunas aprobaciones), a ensayos clínicos, a preferencias o a datos incompletos.</li>"
        "<li>Colorrectal: MSK inicia a menudo FOLFOX sin biológico y lo añade después; se cuenta como "
        "<b>compatible</b> (mismo esqueleto de quimio). Páncreas: FOLFIRINOX y gemcitabina + nab-paclitaxel son "
        "opciones equivalentes en ESMO para ECOG 0-1.</li>"
        "<li>Datos imputados: no hay PD-L1 TPS numérico (solo positivo/negativo), la edad es aproximada, la "
        "localización del páncreas y la resecabilidad del CCR se imputan cuando no constan, y RE/RP de mama "
        "proceden del estado HR global (explica parte de la baja concordancia en triple negativo).</li>"
        "<li>La comparación de supervivencia entre concordantes y discordantes es <b>observacional y con "
        "factores de confusión</b>; es ilustrativa, no causal.</li>"
        "<li>Licencia CC BY-NC-ND 4.0: el repositorio solo publica métricas agregadas; los datos por paciente se "
        "descargan de cBioPortal en local.</li></ul></div>"
    )

    cs = casos.get(tid)
    if cs:
        with st.expander(f"Ver los {len(cs)} casos MSK-CHORD de {x['nombre']} (solo local)"):
            st.dataframe(
                [{k: c.get(k) for k in ("patient_id", "subgrupo", "ecog", "status", "recomendacion", "clase_jev",
                                        "clase_recibida", "agentes_1l", "compatible", "confianza", "os_months",
                                        "os_event")} | {"agentes_1l": ", ".join(c.get("agentes_1l") or [])}
                 for c in cs],
                width="stretch", hide_index=True,
            )


def _fingerprint(tumor_id: str, raw: dict) -> str:
    import hashlib
    import json as _json

    return hashlib.sha256(_json.dumps([tumor_id, raw], sort_keys=True, default=str).encode()).hexdigest()


def main() -> None:
    inject_css()
    client = get_client()

    mode_tag = (
        '<span class="nb-tag red">MODO SIMULADO · sin clave API</span>' if client.is_mock
        else f'<span class="nb-tag green">JEV CONECTADO · {e(client.model)}</span>'
    )
    nb(
        '<div class="nb-hero"><div><h1>JevESMO</h1>'
        f"<p>Apoyo a la decisión clínica · {len(load_all())} tumores ESMO · Guías ESMO + Jev (System One)</p></div>"
        f'<div>{mode_tag}<span class="nb-tag pink">Supervisión humana</span></div></div>'
    )

    tab_rec, tab_eval = st.tabs(["Recomendación", "Evaluación"])

    with tab_rec:
        col_izq, col_der = st.columns([1, 1], gap="large")
        with col_izq:
            spec, raw = render_form()
            calcular = st.button("▶ Calcular recomendación", type="primary", width="stretch")
        huella = _fingerprint(spec.id, raw)
        with col_der:
            if calcular:
                st.session_state.pop("ultimo_resultado", None)  # nunca mostrar un resultado anterior tras un fallo
                with st.spinner("Consultando Jev por capas..."):
                    try:
                        st.session_state["ultimo_resultado"] = {"huella": huella, "res": run(spec.id, raw, client=client)}
                        st.session_state.pop("ultimo_error", None)
                    except Exception as exc:  # errores de red/API: mostrarlos sin romper la UI
                        st.session_state["ultimo_error"] = f"{type(exc).__name__}: {exc}"
            if st.session_state.get("ultimo_error"):
                nb(f'<div class="nb-card red"><h3>Error al consultar a Jev</h3><div class="note">{e(st.session_state["ultimo_error"])}</div></div>')
            guardado = st.session_state.get("ultimo_resultado")
            resultado = None
            if guardado and guardado["huella"] == huella:
                resultado = guardado["res"]
            elif guardado:
                nb('<div class="nb-section right">02 · Resultado</div>')
                nb('<div class="nb-card yellow"><h3>El caso ha cambiado</h3>'
                   "<div>Has modificado datos del paciente después del último cálculo. El resultado anterior se ha "
                   "ocultado para no confundirlo con este caso: pulsa ▶ Calcular de nuevo.</div></div>")
            if resultado:
                nb(f'<span class="nb-tag">Huella del caso · {e(huella[:10])}</span>')
                render_results(resultado)
            elif not guardado and not st.session_state.get("ultimo_error"):
                nb('<div class="nb-section right">02 · Resultado</div>')
                nb('<div class="nb-empty">Rellena el caso a la izquierda<br>y pulsa ▶ Calcular</div>')

    with tab_eval:
        render_evaluation(client)


if __name__ == "__main__":
    main()
