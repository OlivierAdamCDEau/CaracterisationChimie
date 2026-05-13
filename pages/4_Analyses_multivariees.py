"""
pages/4_Analyses_multivariees.py — Analyses multivariées (M04)
Options réservées aux rôles admin/collaborateur.
"""
import streamlit as st, sys, io
import matplotlib.pyplot as plt
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
pivot_norm_raw = st.session_state.get("pivot_norm_raw", pivot_norm)
pivot_fam_norm = st.session_state.get("pivot_fam_norm")
lb_map         = st.session_state.get("lb_map", {})
lb_stations    = st.session_state.get("lb_stations", {})
fam_map        = st.session_state.get("fam_map") or {}

# Nettoyer fam_map : exclure les valeurs NaN/None
fam_map = {k: str(v) for k, v in fam_map.items()
           if v is not None and str(v) not in ("nan", "", "None")}

peut_configurer = verifier_droit("config")

# ── Options ───────────────────────────────────────────────────────────────────
n_vecteurs          = 10
n_clusters          = 0
corpus_commun       = False
seuil_imputation    = 0.20
methode_linkage     = "ward"
echelle_vecteur     = 1.0
label_offset        = 0.06
corr_labels_complets = False
biplot_separe       = False

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

        st.markdown("**Dendrogramme**")
        n_clusters = st.slider(
            "N groupes à délimiter (0 = automatique)",
            min_value=0, max_value=10, value=0, step=1,
            help="0 = pas de coupure forcée, le dendrogramme suggère le nombre optimal. "
                 "Sinon, force la coupure à N groupes et les colorie.",
        )

        st.markdown("**Biplot ACP — étiquettes et projection**")
        c5, c6, c7, c8 = st.columns(4)
        echelle_vecteur = c5.slider(
            "Longueur des vecteurs", 0.5, 2.0, 1.0, 0.05,
            help="Facteur d'échelle des flèches de loading.",
        )
        label_offset = c6.slider(
            "Écartement étiquettes", 0.03, 0.20, 0.06, 0.01,
            help="Distance entre la pointe du vecteur et son étiquette.",
        )
        corr_labels_complets = c7.toggle(
            "Libellés complets (heatmap + biplots)", False,
            help="Affiche les libellés entiers plutôt que tronqués.",
        )
        biplot_separe = c8.toggle(
            "Biplots séparés stations / paramètres", False,
            help="Génère en plus deux figures séparées : une avec les stations seules, "
                 "une avec les paramètres seuls. Utile quand les données sont denses.",
        )

# ── Calcul ────────────────────────────────────────────────────────────────────
if st.button("🔬 Calculer les analyses multivariées", type="primary",
             use_container_width=True, disabled=(pivot_norm is None)):
    with st.spinner("Calcul en cours…"):
        try:
            # corpus_commun : utiliser pivot_norm_raw (NaN préservés)
            # pour que _prepare_pivot puisse identifier les paramètres communs
            pivot_input = pivot_norm_raw if corpus_commun else pivot_norm
            figs, alertes = figure_multivar_complete(
                pivot_input, lb_map,
                pivot_fam_norm=pivot_fam_norm,
                fam_map=fam_map if fam_map else None,
                lb_stations=lb_stations,
                ordre_stations=st.session_state.get("ordre_stations"),
                n_vecteurs=n_vecteurs,
                echelle_vecteur=echelle_vecteur,
                label_offset=label_offset,
                biplot_separe=biplot_separe,
                corpus_commun=corpus_commun,
                seuil_imputation=seuil_imputation,
                n_clusters=n_clusters,
                methode_linkage=methode_linkage,
                corr_labels_complets=corr_labels_complets,
            )

            for a in alertes:
                (st.error if a.startswith("❌")
                 else st.warning if a.startswith("⚠️")
                 else st.info)(a)

            # Convertir en bytes PNG pour éviter le crash thread-safety matplotlib
            figs_bytes = {}
            for nom_fig, fig_obj in figs.items():
                buf = io.BytesIO()
                fig_obj.savefig(buf, format="png", dpi=150, bbox_inches="tight")
                buf.seek(0)
                figs_bytes[nom_fig] = buf.read()
                plt.close(fig_obj)
            import gc; gc.collect()

            st.session_state["figs_m04"]    = figs_bytes
            st.session_state["m04_calcule"] = True
            st.success("✅ Analyses multivariées calculées.")
            st.rerun()

        except Exception as e:
            import traceback
            st.error(f"❌ {e}")
            st.code(traceback.format_exc())

# ── Affichage ─────────────────────────────────────────────────────────────────
figs_bytes = st.session_state.get("figs_m04")
if figs_bytes:
    TITRES = {
        "biplot":          "Biplot ACP — complet",
        "biplot_stations": "ACP — Stations seules",
        "biplot_params":   "ACP — Paramètres seuls",
        "biplot_fam":      "Double projection — familles",
        "dendro":          "Dendrogramme — clustering",
        "corr":            "Matrice de corrélations",
        "scree":           "Éboulis des valeurs propres",
    }

    # Légende couleurs stations
    lb_st_disp = st.session_state.get("lb_stations", {})
    ordre_disp = st.session_state.get("ordre_stations") or list(lb_st_disp.keys())
    if lb_st_disp:
        PALETTE = ["#2563eb","#16a34a","#dc2626","#d97706",
                   "#7c3aed","#0891b2","#be185d","#4d7c0f"]
        cols_leg = st.columns(min(len(ordre_disp), 6))
        for _i, _cd in enumerate(ordre_disp):
            _lb  = lb_st_disp.get(_cd, _cd)
            _col = PALETTE[_i % len(PALETTE)]
            cols_leg[_i % len(cols_leg)].markdown(
                f"<span style='display:inline-block;width:12px;height:12px;"
                f"background:{_col};border-radius:50%;margin-right:5px;'></span>"
                f"<small><b>{_lb}</b></small>",
                unsafe_allow_html=True,
            )
        st.caption(
            "Couleurs stations : chaque couleur correspond à une station dans "
            "l'ordre du BV actif. Les vecteurs paramètres sont colorés par "
            "famille chimique (si configuration disponible)."
        )

    tabs = st.tabs([TITRES.get(k, k) for k in figs_bytes.keys()])
    for tab, (nom, png_bytes) in zip(tabs, figs_bytes.items()):
        with tab:
            st.image(png_bytes, use_container_width=True)
            st.download_button(
                "⬇️ PNG", png_bytes,
                f"m04_{nom}.png", "image/png",
                key=f"png4_{nom}",
            )

st.markdown("---")
st.markdown(
    '<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>',
    unsafe_allow_html=True,
)
