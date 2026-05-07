"""
pages/4_Analyses_multivariees.py — Analyses multivariées (M04)
Options réservées aux rôles admin/collaborateur.
"""
import streamlit as st, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Analyses multivariées", page_icon="📊", layout="wide")

from modules.auth import verifier_auth, afficher_bandeau_utilisateur, verifier_droit
from modules.session import init_session, statut_module, afficher_bandeau_statut

init_session()
auth_ok, _, role = verifier_auth()
if not auth_ok: st.stop()
afficher_bandeau_utilisateur()

st.title("📊 Analyses multivariées")
emoji, msg = statut_module("m04_calcule", "Analyses multivariées")
afficher_bandeau_statut(emoji, msg)
if emoji == "🔒":
    st.info("➡️ Complétez les onglets **Données** et **Configuration** d'abord.")
    st.stop()

try:
    from modules.m04_multivar import figure_multivar_complete
except ImportError as e:
    st.error(f"❌ {e}"); st.stop()

pivot_norm     = st.session_state.get("pivot_norm")
pivot_fam_norm = st.session_state.get("pivot_fam_norm")
lb_map         = st.session_state.get("lb_map", {})
lb_stations    = st.session_state.get("lb_stations", {})
fam_map        = st.session_state.get("fam_map") or {}

# Nettoyer fam_map : exclure les valeurs NaN/None (cause du bug TypeError)
fam_map = {k: str(v) for k, v in fam_map.items() if v is not None and str(v) not in ("nan", "", "None")}

peut_configurer = verifier_droit("config")

# ── Options (admin/collaborateur uniquement) ──────────────────────────────────
n_vecteurs       = 10
corpus_commun    = False
seuil_imputation = 0.20
methode_linkage  = "ward"

if peut_configurer:
    with st.expander("⚙️ Options", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        n_vecteurs       = c1.slider("N vecteurs biplot", 5, 20, 10)
        corpus_commun    = c2.toggle("Corpus commun (ACP)", False,
            help="Restreindre l'ACP aux paramètres analysés dans toutes les stations.")
        seuil_imputation = c3.slider("Seuil imputation (%)", 10, 50, 20, 5,
            help="Stations dépassant ce taux s'affichent en cercle creux.") / 100
        methode_linkage  = c4.selectbox("Méthode clustering", ["ward","complete","average"],
            format_func=lambda x: {"ward":"Ward (défaut)","complete":"Complet","average":"Moyen"}[x])

# ── Calcul ────────────────────────────────────────────────────────────────────
if st.button("🔬 Calculer les analyses multivariées", type="primary",
             use_container_width=True, disabled=(pivot_norm is None)):
    with st.spinner("Calcul en cours…"):
        try:
            figs, alertes = figure_multivar_complete(
                pivot_norm, lb_map,
                pivot_fam_norm=pivot_fam_norm,
                fam_map=fam_map if fam_map else None,
                lb_stations=lb_stations,
                n_vecteurs=n_vecteurs,
                corpus_commun=corpus_commun,
                seuil_imputation=seuil_imputation,
                methode_linkage=methode_linkage,
            )
            st.session_state["figs_m04"]    = figs
            st.session_state["m04_calcule"] = True
            for a in alertes:
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)
            st.success("✅ Analyses multivariées calculées.")
            st.rerun()
        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

# ── Affichage ─────────────────────────────────────────────────────────────────
figs = st.session_state.get("figs_m04")
if figs:
    TITRES = {
        "biplot":     "Biplot ACP — paramètres individuels",
        "biplot_fam": "Double projection — familles",
        "dendro":     "Dendrogramme — clustering",
        "corr":       "Matrice de corrélations",
        "scree":      "Éboulis des valeurs propres",
    }
    tabs = st.tabs([TITRES.get(k, k) for k in figs.keys()])
    for tab, (nom, fig) in zip(tabs, figs.items()):
        with tab:
            st.pyplot(fig, use_container_width=True)
            from modules.m08_export import exporter_figure
            c1, c2 = st.columns(2)
            c1.download_button("⬇️ PNG", exporter_figure(fig,"png"),
                f"m04_{nom}.png","image/png", key=f"png4_{nom}")
            c2.download_button("⬇️ SVG", exporter_figure(fig,"svg"),
                f"m04_{nom}.svg","image/svg+xml", key=f"svg4_{nom}")

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>', unsafe_allow_html=True)
