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
        toutes_figs[f"{prefix}_{nom}"] = fig

lb_map      = st.session_state.get("lb_map", {})
lb_stations = st.session_state.get("lb_stations", {})
meta        = st.session_state.get("meta_fichier", {})

st.markdown(f"**{len(toutes_figs)} figure(s) disponibles** dans la session.")

# ── Section 1 : Figures individuelles ────────────────────────────────────────
st.markdown("### 1. Figures individuelles")
if toutes_figs:
    for nom, fig in toutes_figs.items():
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.markdown(f"📊 `{nom}`")
        # Toutes les figures sont stockées en bytes PNG depuis la v4
        png_data = exporter_figure(fig, "png", dpi=200)
        c2.download_button("⬇️ PNG", png_data,
            f"{nom}.png", "image/png", key=f"png_{nom}")
        # SVG uniquement si objet matplotlib (pas bytes)
        if not isinstance(fig, (bytes, bytearray)):
            svg_data = exporter_figure(fig, "svg")
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
                "Empreinte chimique":    ("figs_m03", False),
                "Analyses multivariées": ("figs_m04", False),
                "Variabilité temporelle":("figs_m05", True),   # paysage
                "Débit et chimie":       ("figs_m06", True),
            }
            sections = []
            for titre_sec, (cle, paysage) in GROUPES.items():
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

            pdf_bytes = generer_rapport_pdf(
                sections,
                titre_rapport=titre_rapport,
                stations=stations_lb,
                stations_codes=stations_cd,
                periode=meta.get("periode", ""),
                auteur=auteur,
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
                "Empreinte chimique":    ("figs_m03", False),
                "Analyses multivariées": ("figs_m04", False),
                "Variabilité temporelle":("figs_m05", True),
                "Débit et chimie":       ("figs_m06", True),
            }
            sections = []
            for titre_sec, (cle, paysage) in GROUPES.items():
                figs_sec = list((st.session_state.get(cle) or {}).values())
                if figs_sec:
                    sections.append({"titre": titre_sec, "figures": figs_sec, "paysage": paysage})

            pdf_bytes = generer_rapport_pdf(
                sections, titre_rapport=titre_rapport,
                stations=list(lb_stations.values()),
                stations_codes=list(lb_stations.keys()),
                periode=meta.get("periode", ""), auteur=auteur,
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
