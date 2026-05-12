"""
pages/3_Empreinte_chimique.py — Empreinte chimique (M03)
"""
import streamlit as st, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Empreinte chimique", page_icon="🧪", layout="wide")

from modules.auth import verifier_auth, afficher_bandeau_utilisateur
from modules.session import init_session, statut_module, afficher_bandeau_statut

init_session()
auth_ok, _, role = verifier_auth()
if not auth_ok: st.stop()
afficher_bandeau_utilisateur()

st.title("🧪 Empreinte chimique")
emoji, msg = statut_module("m03_calcule", "Empreinte chimique")
afficher_bandeau_statut(emoji, msg)
if emoji == "🔒":
    st.info("➡️ Complétez les onglets **Données** et **Configuration** d'abord.")
    st.stop()

try:
    from modules.m03_empreinte import (
        pivoter_percentile, calculer_classes_pct,
        radar_stations, heatmap_stations, heatmap_frequence, matrice_distances,
    )
    from modules.m07_referentiels import calculer_frequence_depassement
except ImportError as e:
    st.error(f"❌ Module introuvable : {e}"); st.stop()

pivot_norm  = st.session_state.get("pivot_norm")
pivot       = st.session_state.get("pivot")
df_stats    = st.session_state.get("df_stats")
df_seuils   = st.session_state.get("df_seuils")
df_ref      = st.session_state.get("df_ref")
df_clean    = st.session_state.get("df_clean")
lb_map      = st.session_state.get("lb_map", {})
lb_stations = st.session_state.get("lb_stations", {})
params_sel  = st.session_state.get("params_selectionnes")

# ── Options ───────────────────────────────────────────────────────────────────
with st.expander("⚙️ Options", expanded=False):
    c1, c2 = st.columns(2)
    n_top    = c1.slider("N paramètres radar", 5, 20, 12)
    ph_borne = c2.selectbox("Borne pH",
        ["max","min"], format_func=lambda x: {"max":"Maximum (défaut)","min":"Minimum"}[x])

# ── Calcul ────────────────────────────────────────────────────────────────────
can_run = (pivot_norm is not None and df_stats is not None
           and df_seuils is not None and df_ref is not None)

if st.button("🔬 Calculer l'empreinte chimique", type="primary",
             use_container_width=True, disabled=not can_run):
    with st.spinner("Calcul en cours…"):
        try:
            figs = {}
            params_retenus = list(pivot_norm.columns)

            # 1. Pivot percentile P90/P10
            pivot_pct, pct_info = pivoter_percentile(
                df_stats, params_retenus, ph_borne=ph_borne,
            )

            # 2. Classification
            pivot_classes_pct, _ = calculer_classes_pct(pivot_pct, df_seuils)

            # 3. Dépassements TBE/BE
            df_dep = None
            if df_clean is not None:
                try:
                    df_dep = calculer_frequence_depassement(
                        df_clean, df_ref, ph_borne=ph_borne,
                    )
                except Exception as e_dep:
                    st.warning(f"⚠️ Calcul dépassements : {e_dep}")

            # 4. Figures
            try:
                figs["radar"] = radar_stations(
                    pivot_norm, lb_map, lb_stations=lb_stations,
                    n_top=n_top, params_selectionnes=params_sel,
                )
            except Exception as e: st.warning(f"⚠️ Radar : {e}")

            try:
                figs["heatmap_classes"] = heatmap_stations(
                    pivot_classes_pct, lb_map, lb_stations=lb_stations,
                    params_selectionnes=params_sel,
                )
            except Exception as e: st.warning(f"⚠️ Heatmap classes : {e}")

            if df_dep is not None and not df_dep.empty:
                try:
                    figs["heatmap_freq"] = heatmap_frequence(
                        df_dep, lb_stations=lb_stations,
                        lb_map=lb_map, params_selectionnes=params_sel,
                    )
                except Exception as e: st.warning(f"⚠️ Heatmap fréquences : {e}")

            try:
                figs["distances"] = matrice_distances(
                    pivot_norm, pivot_brut=pivot,
                    lb_stations=lb_stations, params_selectionnes=params_sel,
                )
            except Exception as e: st.warning(f"⚠️ Distances : {e}")

            # Convertir les figures en bytes AVANT de les stocker en session
            # → évite le crash thread-safety quand Streamlit re-rend les objets
            #   Figure lors d'un scroll ou d'un rerun
            import io, matplotlib.pyplot as plt
            figs_bytes = {}
            for nom_fig, fig_obj in figs.items():
                buf = io.BytesIO()
                fig_obj.savefig(buf, format="png", dpi=150, bbox_inches="tight")
                buf.seek(0)
                figs_bytes[nom_fig] = buf.read()
                plt.close(fig_obj)

            st.session_state["figs_m03"]      = figs_bytes
            st.session_state["pivot_classes"] = pivot_classes_pct
            st.session_state["m03_calcule"]   = True
            st.success(f"✅ {len(figs_bytes)} figure(s) générée(s).")
            st.rerun()

        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

# ── Affichage ─────────────────────────────────────────────────────────────────
# Les figures sont stockées en bytes PNG (pas en objets Figure) pour éviter
# le crash thread-safety de matplotlib lors des reruns Streamlit.
figs_bytes = st.session_state.get("figs_m03")
if figs_bytes:
    TITRES = {
        "radar":           "Radar — profil normalisé",
        "heatmap_classes": "Heatmap — classes de qualité",
        "heatmap_freq":    "Heatmap — fréquences de dépassement",
        "distances":       "Matrice des distances inter-stations",
    }
    tabs = st.tabs([TITRES.get(k, k) for k in figs_bytes.keys()])
    for tab, (nom, png_bytes) in zip(tabs, figs_bytes.items()):
        with tab:
            st.image(png_bytes, use_container_width=True)
            st.download_button("⬇️ PNG", png_bytes,
                f"m03_{nom}.png", "image/png", key=f"png3_{nom}")

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>',
            unsafe_allow_html=True)
