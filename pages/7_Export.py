"""
pages/7_Export.py — Export (M08)
"""
import streamlit as st, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Export", page_icon="📤", layout="wide")
from modules.auth import verifier_auth, afficher_bandeau_utilisateur
from modules.session import init_session, afficher_bandeau_statut, statut_donnees

init_session()
auth_ok, _, role = verifier_auth()
if not auth_ok: st.stop()
afficher_bandeau_utilisateur()

st.title("📤 Export")
emoji_d, msg_d = statut_donnees()
afficher_bandeau_statut(emoji_d, f"Données : {msg_d}")
if emoji_d == "🔒":
    st.info("➡️ Chargez d'abord les données.")
    st.stop()

try:
    from modules.m08_export import (
        exporter_figure, exporter_excel_m03, exporter_excel_m04,
        exporter_excel_m05, exporter_excel_m06, generer_rapport_pdf, generer_zip,
    )
except ImportError as e:
    st.error(f"❌ {e}"); st.stop()

import datetime

# ── Récupération des figures disponibles ─────────────────────────────────────
toutes_figs = {}
for cle, prefix in [("figs_m03","m03"), ("figs_m04","m04"), ("figs_m05","m05"), ("figs_m06","m06")]:
    figs = st.session_state.get(cle) or {}
    for nom, fig in figs.items():
        # Les figures sont stockées sous forme dict {"png":..., "svg":...}
        # On conserve le dict complet pour l'export (PNG+SVG) et l'affichage
        toutes_figs[f"{prefix}_{nom}"] = fig

lb_map      = st.session_state.get("lb_map", {})
lb_stations = st.session_state.get("lb_stations", {})
meta        = st.session_state.get("meta_fichier", {})

st.markdown(f"**{len(toutes_figs)} figure(s) disponibles** dans la session.")

# ── Section 0 : Récapitulatif du paramétrage ─────────────────────────────────
st.markdown("### 📋 Récapitulatif du paramétrage")
with st.expander("Voir le détail des filtres et options appliqués", expanded=True):

    # ── Données ────────────────────────────────────────────────────────────────
    st.markdown("**📂 Données chargées**")
    col_d1, col_d2, col_d3 = st.columns(3)
    col_d1.metric("Fichier(s)", meta.get("nom", "—"))
    col_d2.metric("Stations", meta.get("n_stations", "—"))
    col_d3.metric("Période", meta.get("periode", "—"))

    sources = meta.get("sources", {})
    if sources:
        LABELS_SRC = {
            "naiade": "Naïades chimie", "ades": "ADES",
            "ars": "ARS/CAP", "hb": "HB-Naïades",
        }
        src_txt = " | ".join(
            f"**{LABELS_SRC.get(k,k)}** : {v:,}" for k, v in sources.items()
        )
        st.markdown(f"Sources : {src_txt}")

    bv_nom = st.session_state.get("bv_actif_nom")
    ordre  = st.session_state.get("ordre_stations")
    if bv_nom and ordre:
        st.markdown(
            f"BV actif : **{bv_nom}** — "
            + " → ".join(lb_stations.get(s, s) for s in ordre)
        )

    st.markdown("---")

    # ── Configuration ──────────────────────────────────────────────────────────
    cfg = st.session_state.get("config_params", {})
    if cfg:
        st.markdown("**⚙️ Configuration appliquée**")
        col_c1, col_c2, col_c3, col_c4 = st.columns(4)
        col_c1.metric("N paramètres", cfg.get("n_params", "—"))
        col_c2.metric("N stations (pivot)", cfg.get("n_stations", "—"))
        col_c3.metric("Normalisation", cfg.get("normalisation", "—"))
        col_c4.metric("Valeur pivot", cfg.get("valeur_pivot", "—"))
        col_c5, col_c6, col_c7, col_c8 = st.columns(4)
        col_c5.metric("Seuil PCH (%)", cfg.get("seuil_pch_pct", "—"))
        col_c6.metric("Seuil Micropoll. (%)", cfg.get("seuil_micro_pct", "—"))
        col_c7.metric("Censure <LQ", cfg.get("methode_censure", "—"))
        col_c8.metric("Familles chargées", "Oui" if cfg.get("familles_chargees") else "Non")

    params_sel = st.session_state.get("params_selectionnes", [])
    if params_sel:
        st.markdown(f"**Paramètres analysés** ({len(params_sel)}) :")
        _lb_map_exp = st.session_state.get("lb_map", {})
        params_txt = ", ".join(
            _lb_map_exp.get(p, str(p)) for p in sorted(params_sel)[:30]
        )
        if len(params_sel) > 30:
            params_txt += f" … (+{len(params_sel)-30} autres)"
        st.caption(params_txt)

    st.markdown("---")

    # ── Modules calculés ──────────────────────────────────────────────────────
    st.markdown("**🔬 Modules calculés**")
    MODULES = {
        "Empreinte signature":    "m03_calcule",
        "Analyses multivariées": "m04_calcule",
        "Variabilité temporelle":"m05_calcule",
        "Débit et chimie":       "m06_calcule",
    }
    cols_m = st.columns(4)
    for col_m, (nom_m, cle_m) in zip(cols_m, MODULES.items()):
        done = st.session_state.get(cle_m, False)
        col_m.markdown(
            f"{'✅' if done else '⬜'} {nom_m}",
        )

# ── Section 1 : Figures individuelles ────────────────────────────────────────
st.markdown("### 1. Figures individuelles")
if toutes_figs:
    for nom, fig_data in toutes_figs.items():
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.markdown(f"📊 `{nom}`")
        # Figures stockées comme dict {"png": bytes, "svg": bytes} depuis v5
        if isinstance(fig_data, dict):
            png_data = fig_data.get("png", b"")
            svg_data = fig_data.get("svg", b"")
        elif isinstance(fig_data, (bytes, bytearray)):
            png_data = bytes(fig_data)
            svg_data = b""
        else:
            png_data = exporter_figure(fig_data, "png", dpi=200)
            svg_data = exporter_figure(fig_data, "svg")
        c2.download_button("⬇️ PNG", png_data,
            f"{nom}.png", "image/png", key=f"png_{nom}")
        if svg_data:
            c3.download_button("⬇️ SVG", svg_data,
                f"{nom}.svg", "image/svg+xml", key=f"svg_{nom}")
        else:
            c3.caption("SVG N/A")
else:
    st.info("Aucune figure générée. Calculez au moins un module d'analyse.")

# ── Section 2 : Tableaux Excel ────────────────────────────────────────────────
st.markdown("### 2. Tableaux Excel par module")
excels = {}

col1, col2 = st.columns(2)

with col1:
    df_stats        = st.session_state.get("df_stats")
    pivot_classes   = st.session_state.get("pivot_classes")
    if df_stats is not None:
        xlsx_m03 = exporter_excel_m03(df_stats, pivot_classes=pivot_classes,
            lb_map=lb_map, lb_stations=lb_stations)
        excels["m03_empreinte"] = xlsx_m03
        st.download_button("📥 Excel M03 — Empreinte chimique", xlsx_m03,
            "m03_empreinte.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("M03 : données non disponibles.")

    pivot_norm = st.session_state.get("pivot_norm")
    if pivot_norm is not None:
        xlsx_m04 = exporter_excel_m04(pivot_norm, lb_stations=lb_stations)
        excels["m04_multivar"] = xlsx_m04
        st.download_button("📥 Excel M04 — Analyses multivariées", xlsx_m04,
            "m04_multivar.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("M04 : données non disponibles.")

with col2:
    df_clean = st.session_state.get("df_clean")
    if df_clean is not None:
        xlsx_m05 = exporter_excel_m05(df_clean, lb_map=lb_map, lb_stations=lb_stations)
        excels["m05_variabilite"] = xlsx_m05
        st.download_button("📥 Excel M05 — Variabilité temporelle", xlsx_m05,
            "m05_variabilite.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("M05 : données non disponibles.")

    df_reg = st.session_state.get("df_reg_cq")
    if df_reg is not None and not df_reg.empty:
        xlsx_m06 = exporter_excel_m06(df_reg, lb_map=lb_map, lb_stations=lb_stations)
        excels["m06_cq"] = xlsx_m06
        st.download_button("📥 Excel M06 — Débit et chimie", xlsx_m06,
            "m06_cq.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("M06 : données non disponibles.")

# ── Section 3 : Rapport PDF ───────────────────────────────────────────────────
st.markdown("### 3. Rapport PDF structuré")

with st.expander("Options du rapport", expanded=True):
    titre_rapport = st.text_input("Titre du rapport",
        value=f"Rapport d'analyse — Qualité Eau — {meta.get('periode', '')}")
    auteur = st.text_input("Auteur / Structure", value="@CDEau")

if st.button("📄 Générer le rapport PDF", type="primary", disabled=(not toutes_figs)):
    with st.spinner("Génération du rapport PDF…"):
        try:
            # Construire les sections par module
            GROUPES = {
                "Empreinte signature":   ("figs_m03", False),
                "Analyses multivariées": ("figs_m04", False),
                "Variabilité temporelle":("figs_m05", True),   # paysage
                "Débit et chimie":       ("figs_m06", True),
            }
            sections = []
            for titre_sec, (cle, paysage) in GROUPES.items():
                # Les valeurs sont des dicts {"png":..., "svg":...} — les passer tels quels
                # generer_rapport_pdf sait maintenant gérer ce format
                figs_sec = list((st.session_state.get(cle) or {}).values())
                if figs_sec:
                    tableau = None
                    if cle == "figs_m06" and df_reg is not None:
                        import pandas as pd
                        tableau = df_reg[["LbStation","CdParametre","n_paires",
                                          "b","r2","Comportement"]].head(20)
                    sections.append({"titre": titre_sec, "figures": figs_sec,
                                     "tableau": tableau, "paysage": paysage})

            stations_lb = list(lb_stations.values())
            stations_cd = list(lb_stations.keys())

            # Récapitulatif paramétrage pour la page de garde PDF
            _cfg = st.session_state.get("config_params", {})
            _params_sel = st.session_state.get("params_selectionnes", [])
            _lb_map_pdf = st.session_state.get("lb_map", {})
            parametrage_pdf = {
                "Fichier(s)": meta.get("nom", "—"),
                "Période": meta.get("periode", "—"),
                "N stations": meta.get("n_stations", "—"),
                "Sources": ", ".join(meta.get("sources", {}).keys()) or "—",
                "N paramètres": len(_params_sel),
                "Normalisation": _cfg.get("normalisation", "—"),
                "Valeur pivot": _cfg.get("valeur_pivot", "—"),
                "Censure <LQ": _cfg.get("methode_censure", "—"),
                "Seuil PCH (%)": _cfg.get("seuil_pch_pct", "—"),
                "Seuil Micropoll. (%)": _cfg.get("seuil_micro_pct", "—"),
                "Familles chimiques": "Oui" if _cfg.get("familles_chargees") else "Non",
                "BV actif": st.session_state.get("bv_actif_nom", "—") or "—",
                "Paramètres": (", ".join(_lb_map_pdf.get(p, str(p))
                               for p in sorted(_params_sel)[:20])
                               + (f" (+{len(_params_sel)-20} autres)"
                                  if len(_params_sel) > 20 else ""))
            }

            pdf_bytes = generer_rapport_pdf(
                sections,
                titre_rapport=titre_rapport,
                stations=stations_lb,
                stations_codes=stations_cd,
                periode=meta.get("periode", ""),
                auteur=auteur,
                parametrage=parametrage_pdf,
            )
            st.download_button(
                "⬇️ Télécharger le rapport PDF",
                pdf_bytes,
                f"rapport_qualite_eau_{datetime.date.today():%Y%m%d}.pdf",
                "application/pdf",
            )
            st.success("✅ Rapport PDF généré.")
        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

# ── Section 4 : Bundle ZIP ────────────────────────────────────────────────────
st.markdown("### 4. Bundle complet (ZIP)")
st.markdown("Télécharger en une seule archive : toutes les figures (PNG + SVG) + fichiers Excel + rapport PDF.")

if st.button("📦 Générer le bundle ZIP", disabled=(not toutes_figs)):
    with st.spinner("Assemblage du bundle…"):
        try:
            # Régénérer le PDF pour l'inclure
            GROUPES = {
                "Empreinte signature":   ("figs_m03", False),
                "Analyses multivariées": ("figs_m04", False),
                "Variabilité temporelle":("figs_m05", True),
                "Débit et chimie":       ("figs_m06", True),
            }
            sections = []
            for titre_sec, (cle, paysage) in GROUPES.items():
                # Les valeurs sont des dicts {"png":..., "svg":...} — les passer tels quels
                # generer_rapport_pdf sait maintenant gérer ce format
                figs_sec = list((st.session_state.get(cle) or {}).values())
                if figs_sec:
                    sections.append({"titre": titre_sec, "figures": figs_sec, "paysage": paysage})

            pdf_bytes = generer_rapport_pdf(
                sections, titre_rapport=titre_rapport,
                stations=list(lb_stations.values()),
                stations_codes=list(lb_stations.keys()),
                periode=meta.get("periode", ""), auteur=auteur,
                parametrage=parametrage_pdf if "parametrage_pdf" in dir() else {},
            ) if sections else None

            zip_bytes = generer_zip(
                figures=toutes_figs,
                excels=excels,
                pdf_bytes=pdf_bytes,
                nom_projet="qualite_eau",
            )
            st.download_button(
                "⬇️ Télécharger le bundle ZIP",
                zip_bytes,
                f"qualite_eau_export_{datetime.date.today():%Y%m%d}.zip",
                "application/zip",
            )
            st.success("✅ Bundle ZIP généré.")
        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>', unsafe_allow_html=True)
