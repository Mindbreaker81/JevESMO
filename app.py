"""App visual JevESMO (Streamlit).

Multi-tumor: cada tumor ESMO es un spec JSON (src/jevesmo/tumors) y el
formulario se genera dinamicamente a partir de el.

Panel izquierdo: descripcion del paciente y del tumor.
Panel derecho: recomendacion, ranking de alternativas y explicabilidad
(que se le pregunto a Jev en cada capa y que respondio, con su confianza).

Si faltan datos clinicos imprescindibles, la app pregunta antes de intentar
generar ninguna recomendacion.

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

st.set_page_config(page_title="JevESMO — Guias ESMO + Jev", layout="wide")
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
                          format_func=lambda x: "— desconocido —" if x == UNK else labels.get(x, x))
        return None if v == UNK else v
    if c.tipo == "bool":
        v = box.selectbox(label, [UNK, "si", "no"], key=k, help=c.ayuda,
                          format_func=lambda x: "— desconocido / no testado —" if x == UNK else x)
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
       f'<div class="src">📘 {guias}</div></div>')

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
    nb('<div class="note">* obligatorio. Deja en "desconocido" lo que no sepas: la app te preguntara lo imprescindible.</div>')
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
            '<div class="nb-card yellow"><h3>❓ Necesito mas datos</h3>'
            "<div>Faltan datos clinicos imprescindibles. No voy a recomendar nada hasta que me respondas:</div>"
            f"<ul>{items}</ul></div>"
        )
        return

    rec = resultado["recomendacion_principal"]
    conf = resultado["confianza"]

    nb(
        f'<span class="nb-tag yellow">{e(resultado.get("grupo"))} · {e(resultado.get("tumor_nombre"))}</span>'
        + "".join(f'<span class="nb-tag lilac">{e(k)} · {e(v)}</span>' for k, v in (resultado.get("derivados") or {}).items() if v)
        + f'<span class="nb-tag">Arbol · {e(resultado["esmo_tree_version"])}</span>'
    )

    if resultado["requiere_revision_humana"]:
        motivo = (
            "No hay ninguna opcion segura." if rec is None
            else f"La confianza del modelo ({(conf or 0):.0%}) esta por debajo del umbral ({CONFIDENCE_THRESHOLD:.0%})."
        )
        nb(
            '<div class="nb-card red"><h3>⚠ Revision obligatoria por oncologo</h3>'
            f"<div>{e(motivo)}</div></div>"
        )

    if rec:
        nb(
            '<div class="nb-card green"><h3>Recomendacion principal</h3>'
            f'<div class="big">{e(rec["label"])}</div>'
            f'<div class="note">{e(rec["esmo_note"])}</div>'
            f"{_meter(conf)}</div>"
        )
    else:
        nb('<div class="nb-card"><h3>Sin recomendacion</h3>Ninguna opcion candidata es segura.</div>')

    if resultado["avisos_datos_faltantes"]:
        items = "".join(f"<li>{e(a)}</li>" for a in resultado["avisos_datos_faltantes"])
        nb(f'<div class="nb-card yellow"><h3>Datos que mejorarian la decision</h3><ul>{items}</ul></div>')

    nb('<div class="nb-section right">03 · Alternativas ESMO</div>')
    chosen_id = rec["id"] if rec else None
    for i, c in enumerate(resultado["candidatos"], start=1):
        cls = "blocked" if c["contraindicado"] else ("chosen" if c["id"] == chosen_id else "")
        extra = f'<div class="n">🚫 {e(c["motivo_contraindicacion"])}</div>' if c["contraindicado"] else ""
        nb(
            f'<div class="nb-option {cls}"><div class="badge">{i}</div><div>'
            f'<div class="t">{e(c["label"])}</div><div class="n">{e(c["esmo_note"])}'
            f'{" · evidencia " + e(c["evidencia"]) if c.get("evidencia") else ""}</div>{extra}</div></div>'
        )

    nb('<div class="nb-section right">04 · Explicabilidad</div>')
    for capa in resultado["explicabilidad"]:
        n = len(capa["preguntas"])
        with st.expander(f'{capa["capa"]} · {n} pregunta{"s" if n != 1 else ""}', expanded=False):
            if not n:
                nb('<div class="note">Esta capa no necesito preguntar nada a Jev para este caso.</div>')
                continue
            for key, q in capa["preguntas"].items():
                ans = capa["respuestas"].get(key, {})
                tags = f'<span class="nb-tag cyan">{e(q["tipo"])}</span>'
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
    nb('<div class="nb-section">Evaluacion</div>')
    nb(
        '<div class="nb-card"><b>Como se evalua JevESMO.</b> Dos pruebas complementarias:'
        f"<ul><li><b>Casos de referencia ESMO</b> ({len(specs)} tumores): viñetas con la respuesta que marca la guia "
        "vigente de cada tumor. Mide si acierta el tratamiento y si se comporta con seguridad (pregunta cuando faltan "
        "datos, bloquea opciones peligrosas).</li>"
        "<li><b>METABRIC</b> (cBioPortal, Curtis et al. 2012 · Pereira et al. 2016): cohorte real de "
        "pacientes con cancer de mama. Compara la recomendacion con el tratamiento que realmente recibieron "
        "y con su evolucion (supervivencia libre de recaida).</li></ul></div>"
    )

    with st.expander("▶ Ejecutar una nueva evaluacion", expanded=False):
        sel = st.multiselect("Tumores (viñetas)", sorted(specs), default=sorted(specs),
                             format_func=lambda t: f"{specs[t].grupo} · {specs[t].nombre}")
        do_met = st.checkbox("Incluir cohorte METABRIC (mama, ~200 pacientes)", value=False)
        c1, c2, c3, c4, c5 = st.columns(5)
        strata = {
            "HR+/HER2-": c1.number_input("HR+/HER2-", 0, 1000, DEFAULT_STRATA["HR+/HER2-"], step=10),
            "TNBC": c2.number_input("TNBC", 0, 300, DEFAULT_STRATA["TNBC"], step=10),
            "HER2+": c3.number_input("HER2+", 0, 100, DEFAULT_STRATA["HER2+"], step=10),
            "HR+/HER2+": c4.number_input("HR+/HER2+", 0, 100, DEFAULT_STRATA["HR+/HER2+"], step=10),
        }
        seed = c5.number_input("Semilla", 0, 9999, 42)
        if client.is_mock:
            nb('<div class="nb-card red">Modo MOCK: los resultados no reflejaran el rendimiento real de Jev.</div>')
        if st.button("▶ Ejecutar evaluacion", width="stretch", disabled=not (sel or do_met)):
            bar = st.progress(0.0, text="Iniciando...")

            def prog(done: int, total: int, label: str) -> None:
                bar.progress(done / total, text=f"{label}: {done}/{total}")

            try:
                run_all(client=client, tumors=sel or [], metabric_too=do_met,
                        strata={k: int(v) for k, v in strata.items()}, seed=int(seed), progress=prog)
                st.rerun()
            except Exception as exc:
                nb(f'<div class="nb-card red"><h3>Error en la evaluacion</h3><div class="note">{e(exc)}</div></div>')

    res = load_results()
    if not res["tumores"] and not res["metabric"]:
        nb('<div class="nb-empty">Aun no hay resultados.<br>Ejecuta una evaluacion.</div>')
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
            f'<span class="nb-tag">Ultima ejecucion · {e(fechas[-1][:16].replace("T", " "))} UTC</span>'
            f'<span class="nb-tag">Umbral confianza · {_pct(CONFIDENCE_THRESHOLD)}</span>'
        )
        nb('<div class="nb-section right">A · Casos de referencia ESMO · todas las especialidades</div>')
        _kpi_row([
            _kpi("Acierto global", _pct(g["acierto_global"]), _color(g["acierto_global"]),
                 f"{g['aciertos']}/{g['n']} casos · {len(tum)} tumores"),
            _kpi("Tratamiento correcto", _pct(g["acierto_tratamiento"]), "cyan", "top-1 dentro de lo aceptable"),
            _kpi("Opcion preferida", _pct(g["acierto_preferida"]), "lilac", "la primera eleccion de ESMO"),
            _kpi("Seguridad", _pct(g["acierto_seguridad"]), "pink", "pregunta / escala cuando debe"),
        ])
        if g.get("n_multiopcion") is not None:
            nb(
                '<div class="nb-card yellow"><h3>Dificultad real de la decision</h3>'
                f'<div>En {g["n_multiopcion"]} de los casos de tratamiento el arbol ESMO dejo <b>2 o mas opciones validas</b> '
                f'y Jev tuvo que elegir (media {g["candidatos_medios"] or 0:.1f} candidatos por caso). '
                "En el resto, las reglas deterministas del arbol ya dejaban una unica opcion.</div><br>"
                + _hbar(f"Acierto cuando Jev elige entre >=2 opciones (n={g['n_multiopcion']})", g["acierto_multiopcion"], "lilac")
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
        return
    g, lum = m["global"], m["luminal_precoz"]
    nb('<div class="nb-section right">B · Cohorte real METABRIC</div>')
    _kpi_row([
        _kpi("Pacientes evaluadas", str(m["n"]), "yellow", "muestra estratificada por subtipo"),
        _kpi("AUC P(quimio)", "—" if lum["auc_p_quimio"] is None else f"{lum['auc_p_quimio']:.2f}", "green",
             "HR+/HER2- precoz: ¿separa quien recibio quimio?"),
        _kpi("Sensibilidad quimio", _pct(lum["quimio"]["sensibilidad"]), "cyan", "HR+/HER2- precoz"),
        _kpi("Revision humana", _pct(g["revision_pct"]), "pink", "casos escalados a oncologo"),
    ])

    pr = lum["pronostico_sin_quimio"]
    hi, lo = pr["jev_alto_riesgo"], pr["jev_bajo_riesgo"]
    nb(
        '<div class="nb-card yellow"><h3>Valor pronostico · pacientes HR+/HER2- que NO recibieron quimio</h3>'
        "<div>Si Jev acierta al identificar el alto riesgo, las pacientes a las que habria indicado quimio "
        "(y no la recibieron) deberian recaer mas.</div><br>"
        + _hbar(f"Jev: alto riesgo · RFS 5 a (n={hi['n']})", hi["rfs_60m"], "red")
        + _hbar(f"Jev: bajo riesgo · RFS 5 a (n={lo['n']})", lo["rfs_60m"], "green")
        + _hbar(f"Jev: alto riesgo · RFS 10 a (n={hi['n']})", hi["rfs_120m"], "red")
        + _hbar(f"Jev: bajo riesgo · RFS 10 a (n={lo['n']})", lo["rfs_120m"], "green")
        + '<div class="note">RFS = supervivencia libre de recaida (Kaplan-Meier).</div></div>'
    )

    c1, c2 = st.columns(2, gap="large")
    with c1:
        q = lum["quimio"]
        kappa = "—" if q["kappa"] is None else f"{q['kappa']:.2f}"
        nb(
            '<div class="nb-card"><h3>Matriz · quimio en HR+/HER2- precoz</h3>'
            '<table class="nb-cm"><tr><th></th><th>Recibio QT</th><th>No recibio</th></tr>'
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
            '<div class="nb-card"><h3>Calibracion · concordancia por nivel de confianza</h3>'
            f"{cal}<div class=\"note\">Una buena calibracion: mas confianza → mas concordancia.</div></div>"
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
        "<th>Concordancia endocrino</th><th>Revision</th></tr></thead><tbody>" + "".join(sub_rows) + "</tbody></table>"
    )

    nb(
        '<div class="nb-card red"><h3>Como interpretar estos resultados</h3><ul>'
        "<li>METABRIC recoge tratamientos de 1977-2005: <b>concordar con la practica historica no equivale a acertar</b>. "
        "No existia trastuzumab ni inmunoterapia, y entonces la quimio en HR+ se usaba poco; por eso la concordancia "
        "en HER2+ y TNBC es baja por diseño.</li>"
        "<li>Los resultados mas informativos son el <b>AUC</b> y el <b>valor pronostico</b>: miden si Jev identifica "
        "a las pacientes de alto riesgo.</li>"
        "<li>ECOG no existe en METABRIC y se asume 0. No hay Ki67, BRCA ni PD-L1.</li>"
        "<li>Las viñetas ESMO se han redactado a partir de las guias y <b>deben validarse por un oncologo</b>. "
        "Son pocas por tumor: un acierto alto no garantiza el rendimiento en casos reales.</li></ul></div>"
    )

    with st.expander(f"Ver los {m['n']} casos METABRIC evaluados"):
        st.dataframe(
            [{k: c[k] for k in ("patient_id", "subtipo", "estadio", "edad", "grado", "tamano_mm", "ganglios",
                                "recomendacion", "confianza", "p_quimio", "real_quimio", "real_endocrino",
                                "rfs_months", "rfs_event")} for c in m["casos"]],
            width="stretch", hide_index=True,
        )


def main() -> None:
    inject_css()
    client = get_client()

    mode_tag = (
        '<span class="nb-tag red">MODO MOCK · sin API key</span>' if client.is_mock
        else f'<span class="nb-tag green">JEV CONECTADO · {e(client.model)}</span>'
    )
    nb(
        '<div class="nb-hero"><div><h1>JevESMO</h1>'
        f"<p>Apoyo a la decision clinica · {len(load_all())} tumores ESMO · Guias ESMO + Jev (System One)</p></div>"
        f'<div>{mode_tag}<span class="nb-tag pink">Human-in-the-loop</span></div></div>'
    )

    tab_rec, tab_eval = st.tabs(["🩺 Recomendacion", "📊 Evaluacion"])

    with tab_rec:
        col_izq, col_der = st.columns([1, 1], gap="large")
        with col_izq:
            spec, raw = render_form()
            calcular = st.button("▶ Calcular recomendacion", type="primary", width="stretch")
        with col_der:
            if calcular:
                with st.spinner("Consultando Jev por capas..."):
                    try:
                        st.session_state["ultimo_resultado"] = run(spec.id, raw, client=client)
                        st.session_state.pop("ultimo_error", None)
                    except Exception as exc:  # errores de red/API: mostrarlos sin romper la UI
                        st.session_state["ultimo_error"] = f"{type(exc).__name__}: {exc}"
            if st.session_state.get("ultimo_error"):
                nb(f'<div class="nb-card red"><h3>Error llamando a Jev</h3><div class="note">{e(st.session_state["ultimo_error"])}</div></div>')
            resultado = st.session_state.get("ultimo_resultado")
            if resultado and resultado.get("tumor") != spec.id:
                resultado = None
            if resultado:
                render_results(resultado)
            elif not st.session_state.get("ultimo_error"):
                nb('<div class="nb-section right">02 · Resultado</div>')
                nb('<div class="nb-empty">Rellena el caso a la izquierda<br>y pulsa ▶ Calcular</div>')

    with tab_eval:
        render_evaluation(client)


if __name__ == "__main__":
    main()
