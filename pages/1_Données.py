"""
pages/1_Données.py — Chargement des données (M01)
"""
import streamlit as st, sys, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Données — Qualité Eau", page_icon="📂", layout="wide")

from modules.auth import verifier_auth, afficher_bandeau_utilisateur
from modules.session import init_session, invalider_depuis_donnees, statut_donnees, afficher_bandeau_statut

init_session()
auth_ok, username, role = verifier_auth()
if not auth_ok: st.stop()
afficher_bandeau_utilisateur()

st.title("📂 Données")
emoji, msg = statut_donnees()
afficher_bandeau_statut(emoji, msg)

try:
    from modules.m01_import import importer_bdd
except ImportError as e:
    st.error(f"❌ Module m01_import introuvable : {e}"); st.stop()

# ── Upload ────────────────────────────────────────────────────────────────────
st.markdown("### 1. Charger le fichier de données")
st.markdown("Format attendu : export **NAIADES / Hub'Eau** (CSV séparateur `;`, encodage latin-1).")
uploaded_file = st.file_uploader("Fichier CSV NAIADES", type=["csv"])

# ── Options de filtrage ───────────────────────────────────────────────────────
st.markdown("### 2. Options de filtrage")
c1, c2, c3 = st.columns(3)
cd_support = c1.selectbox("Support", [3, 23, 4, 6],
    format_func=lambda x: {3:"3 — Eau cours d'eau", 23:"23 — Eau plan d'eau",
                            4:"4 — Sédiment", 6:"6 — Biote"}[x])
cd_fractions = c2.multiselect("Fraction(s)", [23, 3, 1], default=[23],
    format_func=lambda x: {23:"23 — Dissoute", 3:"3 — Totale", 1:"1 — Non filtrée"}[x])

c3.markdown("**Période (optionnel)**")
ca, cb = c3.columns(2)
date_debut = ca.date_input("Du", value=None)
date_fin   = cb.date_input("Au", value=None)

# ── Chargement ───────────────────────────────────────────────────────────────
if uploaded_file and st.button("🚀 Charger et analyser", type="primary", use_container_width=True):
    with st.spinner("Chargement…"):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
                tmp.write(uploaded_file.getvalue()); tmp_path = tmp.name
            kwargs = dict(cd_support=cd_support, cd_fractions=cd_fractions)
            if date_debut: kwargs["date_debut"] = date_debut.strftime("%d/%m/%Y")
            if date_fin:   kwargs["date_fin"]   = date_fin.strftime("%d/%m/%Y")
            res = importer_bdd(tmp_path, **kwargs)
            os.unlink(tmp_path)
            invalider_depuis_donnees()
            df = res["df"]
            st.session_state.update({
                "df_filtre":           df,
                "df_debit":            res["df_debit"],
                "inventaire_stations": res["inventaire_stations"],
                "lb_stations":         dict(zip(
                    res["inventaire_stations"]["CdStationMesureEauxSurface"],
                    res["inventaire_stations"]["LbStationMesureEauxSurface"],
                )),
                "meta_fichier": {
                    "nom":        uploaded_file.name,
                    "n_lignes":   len(df),
                    "n_stations": df["CdStationMesureEauxSurface"].nunique(),
                    "n_params":   df["CdParametre"].nunique(),
                    "periode":    f"{df['DatePrel'].min()} → {df['DatePrel'].max()}",
                },
                "donnees_chargees": True,
            })
            for a in res.get("alertes", []):
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)
            st.success("✅ Données chargées avec succès.")
            st.rerun()
        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

# ── Inventaire ────────────────────────────────────────────────────────────────
if st.session_state.get("donnees_chargees"):
    meta = st.session_state["meta_fichier"]
    st.markdown("---")
    st.markdown("### 3. Inventaire")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stations",   meta.get("n_stations", "?"))
    m2.metric("Paramètres", meta.get("n_params",   "?"))
    m3.metric("Lignes",     f"{meta.get('n_lignes', 0):,}")
    m4.metric("Fichier",    meta.get("nom", "?"))

    inv = st.session_state.get("inventaire_stations")
    if inv is not None and not inv.empty:
        st.markdown("**Stations disponibles**")
        st.dataframe(inv, use_container_width=True, hide_index=True)

    df_debit = st.session_state.get("df_debit")
    if df_debit is not None and not df_debit.empty:
        n_q = df_debit["CdStationMesureEauxSurface"].nunique()
        st.info(f"💧 Débits co-localisés disponibles pour **{n_q} station(s)** ({len(df_debit)} mesures).")
    else:
        st.warning("💧 Aucun débit co-localisé trouvé. Utilisez une station hydrométrique externe dans l'onglet **Débit et chimie**.")

    st.markdown("➡️ Passez à l'onglet **Configuration**.")

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>', unsafe_allow_html=True)
