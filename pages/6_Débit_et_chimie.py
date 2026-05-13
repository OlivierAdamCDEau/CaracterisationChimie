"""
pages/6_Débit_et_chimie.py — Débit et chimie (M06)
Options réservées aux rôles admin/collaborateur.
Affichage corrigé des stations avec débit co-localisé.
"""
import streamlit as st, sys, io
import matplotlib.pyplot as plt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Débit et chimie", page_icon="💧", layout="wide")

from modules.auth import verifier_auth, afficher_bandeau_utilisateur, verifier_droit
from modules.session import init_session, statut_module, afficher_bandeau_statut

init_session()
auth_ok, _, role = verifier_auth()
if not auth_ok: st.stop()
afficher_bandeau_utilisateur()

st.title("💧 Débit et chimie")
emoji, msg = statut_module("m06_calcule", "Débit et chimie")
afficher_bandeau_statut(emoji, msg)
if emoji == "🔒":
    st.info("➡️ Complétez les onglets **Données** et **Configuration** d'abord.")
    st.stop()

try:
    from modules.m06_cq import figure_cq_complete, lire_hydroportail
except ImportError as e:
    st.error(f"❌ {e}"); st.stop()

df_clean    = st.session_state.get("df_clean")
df_debit    = st.session_state.get("df_debit")
lb_map      = st.session_state.get("lb_map", {})
lb_stations = st.session_state.get("lb_stations", {})
params_sel  = st.session_state.get("params_selectionnes")

peut_configurer = verifier_droit("config")

# ── Sélection mode débit ──────────────────────────────────────────────────────
st.markdown("### Mode d'apport des débits")
st.info(
    "**Deux modes exclusifs** — choisissez un seul mode par analyse "
    "pour garantir la comparabilité inter-stations."
)

mode = st.radio(
    "Source des débits",
    options=["colocal", "hydro"],
    format_func=lambda x: {
        "colocal": "📍 Débits co-localisés (mesurés lors des prélèvements, issus du fichier NAIADES)",
        "hydro":   "📡 Station hydrométrique externe (chronique Hydroportail)",
    }[x],
)

df_debit_hydro = None
rattachement   = None

if mode == "colocal":
    # Identifier les stations du df_clean qui ont un débit dans df_debit
    if df_debit is None or df_debit.empty:
        st.warning(
            "⚠️ Aucun débit co-localisé trouvé dans le fichier NAIADES. "
            "Utilisez le mode Station hydrométrique externe."
        )
    else:
        # Stations chimiques actives (après filtrage configuration)
        stations_chimie = set()
        if df_clean is not None:
            stations_chimie = set(df_clean["CdStationMesureEauxSurface"].unique())

        # Stations avec débit dans df_debit ET présentes dans df_clean
        stations_avec_q = set(df_debit["CdStationMesureEauxSurface"].unique())
        stations_communes = stations_avec_q & stations_chimie

        if stations_communes:
            noms = [lb_stations.get(s, s).strip() for s in sorted(stations_communes)]
            st.success(
                f"✅ Débits co-localisés disponibles pour "
                f"**{len(stations_communes)} station(s)** "
                f"sur les {len(stations_chimie)} station(s) chargées : "
                + ", ".join(noms)
            )
            if len(stations_communes) < len(stations_chimie):
                manquantes = stations_chimie - stations_communes
                noms_mq = [lb_stations.get(s, s).strip() for s in sorted(manquantes)]
                st.warning(
                    f"⚠️ {len(manquantes)} station(s) sans débit co-localisé "
                    f"(exclues de l'analyse C-Q) : " + ", ".join(noms_mq)
                )
        else:
            st.warning(
                "⚠️ Aucune des stations chargées ne dispose de débit co-localisé. "
                "Utilisez le mode Station hydrométrique externe."
            )

elif mode == "hydro":
    st.markdown("#### Fichier Hydroportail")
    uploaded_hydro = st.file_uploader(
        "Export Hydroportail (CSV journalier)", type=["csv"],
        help="Format Hydroportail standard : Date (TU), Valeur (en m³/s), Statut…",
    )
    if uploaded_hydro:
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
            tmp.write(uploaded_hydro.getvalue()); tmp_path = tmp.name
        df_debit_hydro, msgs_h = lire_hydroportail(tmp_path)
        os.unlink(tmp_path)
        for m in msgs_h:
            (st.error if m.startswith("❌") else st.warning if m.startswith("⚠️") else st.info)(m)

    if lb_stations:
        st.markdown("#### Rattachement stations → débit hydro")
        stations_rattachees = st.multiselect(
            "Stations chimiques rattachées à cette station hydro",
            options=list(lb_stations.keys()),
            default=list(lb_stations.keys()),
            format_func=lambda k: lb_stations.get(k, k).strip(),
        )
        rattachement = {s: "hydro" for s in stations_rattachees} if stations_rattachees else None

# ── Options (admin/collaborateur uniquement) ──────────────────────────────────
seuil_b    = 0.20
r2_min     = 0.20
n_colonnes = 3

if peut_configurer:
    with st.expander("⚙️ Options", expanded=False):
        c1, c2, c3 = st.columns(3)
        seuil_b    = c1.slider("Seuil |b| classification", 0.1, 0.5, 0.2, 0.05,
            help="Seuil de l'exposant b pour Enrichissement/Dilution.")
        r2_min     = c2.slider("R² minimum affiché", 0.0, 0.8, 0.2, 0.05,
            help="Cellules heatmap grisées si R² inférieur à ce seuil.")
        n_colonnes = c3.slider("Colonnes figures C-Q", 2, 5, 3)

# ── Calcul ────────────────────────────────────────────────────────────────────
pret = (df_clean is not None) and (
    (mode == "colocal" and df_debit is not None and not df_debit.empty) or
    (mode == "hydro"   and df_debit_hydro is not None and not df_debit_hydro.empty)
)

if st.button("🔬 Calculer les relations C-Q", type="primary",
             use_container_width=True, disabled=not pret):
    with st.spinner("Calcul en cours…"):
        try:
            figs, df_reg, alertes = figure_cq_complete(
                df_clean, lb_map,
                source=mode,
                df_debit=df_debit if mode == "colocal" else None,
                df_debit_hydro=df_debit_hydro if mode == "hydro" else None,
                rattachement=rattachement,
                params_selectionnes=params_sel,
                lb_stations=lb_stations,
                n_colonnes=n_colonnes,
                seuil_b=seuil_b,
                r2_min=r2_min,
            )
            # Convertir en bytes PNG avant stockage → survit à la nav entre pages
            figs_bytes = {}
            for _nom, _fig in figs.items():
                _buf = io.BytesIO()
                _fig.savefig(_buf, format="png", dpi=150, bbox_inches="tight")
                _buf.seek(0)
                figs_bytes[_nom] = _buf.read()
                plt.close(_fig)
            import gc; gc.collect()
            st.session_state["figs_m06"]    = figs_bytes
            st.session_state["df_reg_cq"]   = df_reg
            st.session_state["m06_calcule"] = True
            for a in alertes:
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)
            st.success("✅ Relations C-Q calculées.")
            st.rerun()
        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

# ── Affichage ─────────────────────────────────────────────────────────────────
figs_bytes = st.session_state.get("figs_m06")
figs       = figs_bytes   # alias pour compatibilité
df_reg     = st.session_state.get("df_reg_cq")

if figs_bytes:
    TITRES = {
        "cq_params":        "Nuages C-Q par paramètre",
        "cq_comportements": "Heatmap des comportements chimio-dynamiques",
    }
    tabs = st.tabs([TITRES.get(k, k) for k in figs.keys()])
    for tab, (nom, png_bytes) in zip(tabs, figs_bytes.items()):
        with tab:
            st.image(png_bytes, use_container_width=True)
            from modules.m08_export import exporter_figure
            c1, c2 = st.columns(2)
            c1.download_button("⬇️ PNG", exporter_figure(png_bytes,"png"),
                f"m06_{nom}.png","image/png", key=f"png6_{nom}")
            c2.download_button("⬇️ SVG", exporter_figure(png_bytes,"svg"),
                f"m06_{nom}.svg","image/svg+xml", key=f"svg6_{nom}")

    if df_reg is not None and not df_reg.empty:
        st.markdown("### Tableau des régressions")
        cols_show = [c for c in ["LbStation","CdParametre","n_paires","b","r2",
                                  "Comportement","Source_debit"] if c in df_reg.columns]
        st.dataframe(df_reg[cols_show], use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>', unsafe_allow_html=True)
