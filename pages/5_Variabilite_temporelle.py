"""
pages/5_Variabilite_temporelle.py — Variabilité temporelle (M05)
Options réservées aux rôles admin/collaborateur.
"""
import streamlit as st, sys, io
import matplotlib.pyplot as plt
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

if peut_configurer:
    with st.expander("⚙️ Options", expanded=False):
        c1, c2, c3, c4, c5 = st.columns(5)
        statistique      = c1.selectbox("Statistique saisonnalité", ["mediane","moyenne"],
            format_func=lambda x: {"mediane":"Médiane","moyenne":"Moyenne"}[x])
        n_colonnes       = c2.slider("Colonnes", 2, 5, 4)
        n_params_max     = c3.slider("N paramètres max", 6, 30, 18)
        afficher_lissage = c4.toggle("Lissage séries", True)
        afficher_ic      = c5.toggle("Bande IC saisonnalité", True)

# ── Calcul ────────────────────────────────────────────────────────────────────
if st.button("🔬 Calculer la variabilité temporelle", type="primary",
             use_container_width=True, disabled=(df_clean is None)):
    with st.spinner("Calcul en cours…"):
        try:
            figs, alertes = figure_variabilite_complete(
                df_clean, lb_map,
                df_seuils=df_seuils,
                lb_stations=lb_stations,
                statistique_saison=statistique,
                n_colonnes=n_colonnes,
                n_params_max=n_params_max,
                afficher_lissage=afficher_lissage,
                afficher_ic=afficher_ic,
            )
            # Convertir en bytes PNG avant stockage → survit à la nav entre pages
            figs_bytes = {}
            for _nom, _fig in figs.items():
                _buf_png = io.BytesIO()
                _fig.savefig(_buf_png, format="png", dpi=150, bbox_inches="tight")
                _buf_png.seek(0)
                _buf_svg = io.BytesIO()
                try:
                    _fig.savefig(_buf_svg, format="svg", bbox_inches="tight")
                    _buf_svg.seek(0)
                    _svg = _buf_svg.read()
                except Exception:
                    _svg = b""
                figs_bytes[_nom] = {"png": _buf_png.read(), "svg": _svg}
                plt.close(_fig)
            import gc; gc.collect()
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
    figs = figs_bytes   # alias pour compatibilité
    TITRES = {
        "boxplots": "Distributions",
        "series":   "Séries temporelles",
        "saison":   "Profils saisonniers",
    }
    tabs = st.tabs([TITRES.get(k, k) for k in figs.keys()])
    for tab, (nom, fig_data) in zip(tabs, figs.items()):
        with tab:
            png_data = fig_data["png"] if isinstance(fig_data, dict) else fig_data
            svg_data = fig_data.get("svg", b"") if isinstance(fig_data, dict) else b""
            st.image(png_data, use_container_width=True)

            # Légende stations sous la figure
            lb_stations = st.session_state.get("lb_stations", {})
            if lb_stations:
                PALETTE = ["#2563eb","#16a34a","#dc2626","#d97706",
                           "#7c3aed","#0891b2","#be185d","#4d7c0f"]
                stations = list(lb_stations.items())
                cols_leg = st.columns(min(len(stations), 4))
                for i, (cd, lb) in enumerate(stations):
                    couleur = PALETTE[i % len(PALETTE)]
                    cols_leg[i % len(cols_leg)].markdown(
                        f"<span style='display:inline-block;width:12px;height:12px;"
                        f"background:{couleur};border-radius:2px;margin-right:6px;'></span>"
                        f"<small>{lb.strip()}</small>",
                        unsafe_allow_html=True,
                    )

            dl1, dl2 = st.columns(2)
            dl1.download_button("⬇️ PNG", png_data,
                f"m05_{nom}.png", "image/png", key=f"png5_{nom}")
            if svg_data:
                dl2.download_button("⬇️ SVG", svg_data,
                    f"m05_{nom}.svg", "image/svg+xml", key=f"svg5_{nom}")

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>', unsafe_allow_html=True)
