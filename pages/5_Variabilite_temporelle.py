"""
pages/5_Variabilite_temporelle.py — Variabilité temporelle (M05)
Options réservées aux rôles admin/collaborateur.
"""
import streamlit as st, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Variabilité temporelle", page_icon="📈", layout="wide")

from modules.auth import verifier_auth, afficher_bandeau_utilisateur, verifier_droit
from modules.session import init_session, statut_module, afficher_bandeau_statut

init_session()
auth_ok, _, role = verifier_auth()
if not auth_ok: st.stop()
afficher_bandeau_utilisateur()

st.title("📈 Variabilité temporelle")
emoji, msg = statut_module("m05_calcule", "Variabilité temporelle")
afficher_bandeau_statut(emoji, msg)
if emoji == "🔒":
    st.info("➡️ Complétez les onglets **Données** et **Configuration** d'abord.")
    st.stop()

try:
    from modules.m05_variabilite import figure_variabilite_complete
except ImportError as e:
    st.error(f"❌ {e}"); st.stop()

df_clean    = st.session_state.get("df_clean")
lb_map      = st.session_state.get("lb_map", {})
lb_stations = st.session_state.get("lb_stations", {})
df_seuils   = st.session_state.get("df_seuils")

peut_configurer = verifier_droit("config")

# ── Options (admin/collaborateur uniquement) ──────────────────────────────────
statistique      = "mediane"
n_colonnes       = 4
n_params_max     = 18
afficher_lissage = True
afficher_ic      = True
params_choisis   = None   # None = tous

if peut_configurer:
    with st.expander("⚙️ Options", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        statistique      = c1.selectbox("Statistique saisonnalité", ["mediane","moyenne"],
            format_func=lambda x: {"mediane":"Médiane","moyenne":"Moyenne"}[x])
        n_colonnes       = c2.slider("Colonnes", 2, 5, 4)
        n_params_max     = c3.slider("N paramètres max", 6, 30, 18)
        afficher_lissage    = c4.toggle("Lissage séries", True)
        afficher_ic         = c5.toggle("Bande IC saisonnalité", True)
        labels_complets_x   = st.toggle(
            "Noms complets des stations sur l'axe X (boxplots)",
            False,
            help="Si activé, les noms de stations ne sont pas tronqués.",
        )

        # Sélection des paramètres à analyser
        if df_clean is not None and "CdParametre" in df_clean.columns:
            params_dispo = sorted(df_clean["CdParametre"].dropna().unique().tolist())
            lb_map_disp  = st.session_state.get("lb_map", {})
            params_choisis_raw = st.multiselect(
                "Paramètres à analyser (laisser vide = tous)",
                options=params_dispo,
                default=[],
                format_func=lambda x: f"{lb_map_disp.get(x, x)} ({x})",
                key="m05_params_sel",
            )
            params_choisis = params_choisis_raw if params_choisis_raw else None

        # Sélection des stations à afficher
        if df_clean is not None and "CdStationMesureEauxSurface" in df_clean.columns:
            stations_dispo_m05 = sorted(df_clean["CdStationMesureEauxSurface"].dropna().unique().tolist())
            lb_st_disp = st.session_state.get("lb_stations", {})
            stations_choisies_raw = st.multiselect(
                "Stations à afficher (laisser vide = toutes)",
                options=stations_dispo_m05,
                default=[],
                format_func=lambda x: f"{lb_st_disp.get(x, x)} ({x})",
                key="m05_stations_sel",
            )
            if stations_choisies_raw:
                lb_stations = {k: v for k, v in lb_stations.items() if k in stations_choisies_raw}

# ── Calcul ────────────────────────────────────────────────────────────────────
if st.button("🔬 Calculer la variabilité temporelle", type="primary",
             use_container_width=True, disabled=(df_clean is None)):
    with st.spinner("Calcul en cours…"):
        try:
            # Filtrer df_clean sur les stations sélectionnées si nécessaire
            _df_calc = df_clean
            if lb_stations and set(lb_stations.keys()) < set(df_clean["CdStationMesureEauxSurface"].unique()):
                _df_calc = df_clean[df_clean["CdStationMesureEauxSurface"].isin(lb_stations.keys())]

            figs, alertes = figure_variabilite_complete(
                _df_calc, lb_map,
                df_seuils=df_seuils,
                params_selectionnes=params_choisis,
                ordre_stations=st.session_state.get("ordre_stations"),
                lb_stations=lb_stations,
                statistique_saison=statistique,
                n_colonnes=n_colonnes,
                n_params_max=n_params_max,
                afficher_lissage=afficher_lissage,
                afficher_ic=afficher_ic,
                labels_complets_x=labels_complets_x,
            )
            import io, matplotlib.pyplot as plt
            figs_bytes = {}
            for _nom, _fig in figs.items():
                _buf = io.BytesIO()
                _fig.savefig(_buf, format="png", dpi=150, bbox_inches="tight")
                _buf.seek(0)
                figs_bytes[_nom] = _buf.read()
                plt.close(_fig)
            st.session_state["figs_m05"]    = figs_bytes
            st.session_state["m05_calcule"] = True
            for a in alertes:
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)
            st.success("✅ Variabilité temporelle calculée.")
            st.rerun()
        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

# ── Affichage ─────────────────────────────────────────────────────────────────
figs_bytes = st.session_state.get("figs_m05")
if figs_bytes:
    TITRES = {
        "boxplots": "Distributions",
        "series":   "Séries temporelles",
        "saison":   "Profils saisonniers",
    }
    tabs = st.tabs([TITRES.get(k, k) for k in figs_bytes.keys()])
    for tab, (nom, png_bytes) in zip(tabs, figs_bytes.items()):
        with tab:
            st.image(png_bytes, use_container_width=True)
            st.download_button("⬇️ PNG", png_bytes,
                f"m05_{nom}.png", "image/png", key=f"png5_{nom}")

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>', unsafe_allow_html=True)
