"""
pages/1_Données.py — Chargement des données (M01)
Logique en 2 temps :
  1. Lecture brute du fichier → affichage des supports/fractions réellement présents
  2. Sélection par l'utilisateur → import filtré
"""
import streamlit as st, sys, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Données — Qualité Eau", page_icon="📂", layout="wide")

from modules.auth import verifier_auth, afficher_bandeau_utilisateur
from modules.session import (
    init_session, invalider_depuis_donnees,
    statut_donnees, afficher_bandeau_statut,
)

init_session()
auth_ok, username, role = verifier_auth()
if not auth_ok: st.stop()
afficher_bandeau_utilisateur()

st.title("📂 Données")
emoji, msg = statut_donnees()
afficher_bandeau_statut(emoji, msg)

try:
    from modules.m01_import import lire_bdd_sandre, inventaire_supports_fractions, importer_bdd
except ImportError as e:
    st.error(f"❌ Module m01_import introuvable : {e}"); st.stop()

# ── Étape 1 : Upload et lecture brute ────────────────────────────────────────
st.markdown("### 1. Charger le fichier de données")
st.markdown(
    "Format attendu : export **NAIADES / Hub'Eau** "
    "(CSV séparateur `;`, encodage latin-1)."
)

uploaded_file = st.file_uploader(
    "Fichier CSV NAIADES",
    type=["csv"],
    help="Colonnes SANDRE obligatoires : CdStationMesureEauxSurface, "
         "CdParametre, DatePrel, RsAna, LqAna, CdRqAna, CdSupport, CdFractionAnalysee",
)

if uploaded_file is None:
    st.info("⬆️ Chargez un fichier CSV pour commencer.")
    st.stop()

# Lecture brute pour inventaire (mise en cache par nom+taille de fichier)
@st.cache_data(show_spinner="Lecture du fichier…")
def lire_brut(file_bytes, file_name):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
        tmp.write(file_bytes); tmp_path = tmp.name
    df_brut, alertes = lire_bdd_sandre(tmp_path)
    inv = inventaire_supports_fractions(df_brut)
    os.unlink(tmp_path)
    return df_brut, inv, alertes

df_brut, inv_supports, alertes_lecture = lire_brut(
    uploaded_file.getvalue(), uploaded_file.name
)

# Alertes de lecture
for a in alertes_lecture:
    (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)

if df_brut.empty:
    st.error("❌ Fichier vide ou format non reconnu.")
    st.stop()

st.success(
    f"✅ Fichier lu : **{len(df_brut):,} lignes** — "
    f"**{df_brut['CdStationMesureEauxSurface'].nunique()} station(s)** détectées avant filtre."
)

# ── Étape 2 : Sélection support / fraction ───────────────────────────────────
st.markdown("### 2. Sélection du support et de la fraction")

if inv_supports.empty:
    st.error("❌ Impossible de lire les supports/fractions du fichier.")
    st.stop()

# Afficher l'inventaire disponible
with st.expander("📋 Supports et fractions présents dans le fichier", expanded=True):
    st.dataframe(
        inv_supports.rename(columns={
            "CdSupport":           "Code support",
            "LbSupport":           "Support",
            "CdFractionAnalysee":  "Code fraction",
            "LbFractionAnalysee":  "Fraction",
            "NbMesures":           "N mesures",
        }),
        use_container_width=True,
        hide_index=True,
    )

# Sélection du support parmi ceux présents
supports_dispo = inv_supports[["CdSupport","LbSupport"]].drop_duplicates()
support_options = {
    row["CdSupport"]: f"{row['CdSupport']} — {row['LbSupport'].strip()}"
    for _, row in supports_dispo.iterrows()
}

cd_support = st.selectbox(
    "Support à analyser",
    options=list(support_options.keys()),
    format_func=lambda x: support_options[x],
    help="Sélectionnez le support correspondant à votre analyse.",
)

# Fractions disponibles pour ce support
fractions_du_support = inv_supports[inv_supports["CdSupport"] == cd_support]
fraction_options = {
    row["CdFractionAnalysee"]: f"{row['CdFractionAnalysee']} — {row['LbFractionAnalysee'].strip()} ({row['NbMesures']:,} mesures)"
    for _, row in fractions_du_support.iterrows()
}

# Pré-sélection intelligente : fraction avec le plus de mesures
fraction_defaut = fractions_du_support.loc[
    fractions_du_support["NbMesures"].idxmax(), "CdFractionAnalysee"
]
cd_fractions = st.multiselect(
    "Fraction(s) à analyser",
    options=list(fraction_options.keys()),
    default=[fraction_defaut],
    format_func=lambda x: fraction_options[x],
    help="En cas de doute, gardez la fraction avec le plus de mesures (pré-sélectionnée).",
)

if not cd_fractions:
    st.warning("⚠️ Sélectionnez au moins une fraction.")
    st.stop()

# ── Étape 3 : Filtre période et stations ─────────────────────────────────────
st.markdown("### 3. Filtres optionnels")

col1, col2 = st.columns(2)
with col1:
    st.markdown("**Période**")
    ca, cb = st.columns(2)
    date_debut = ca.date_input("Du", value=None, help="Laisser vide = pas de filtre")
    date_fin   = cb.date_input("Au", value=None)

with col2:
    st.markdown("**Stations** (optionnel)")
    stations_dispo = sorted(df_brut["CdStationMesureEauxSurface"].unique().tolist())
    lb_dispo = {}
    if "LbStationMesureEauxSurface" in df_brut.columns:
        lb_dispo = dict(zip(
            df_brut["CdStationMesureEauxSurface"],
            df_brut["LbStationMesureEauxSurface"].str.strip(),
        ))
    stations_selectionnees = st.multiselect(
        "Restreindre aux stations",
        options=stations_dispo,
        default=[],
        format_func=lambda x: f"{lb_dispo.get(x, x)} ({x})",
        help="Laisser vide = toutes les stations",
    )

# ── Étape 4 : Lancement du filtrage ──────────────────────────────────────────
st.markdown("---")
if st.button("🚀 Appliquer les filtres et charger", type="primary", use_container_width=True):
    with st.spinner("Filtrage et analyse en cours…"):
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
                tmp.write(uploaded_file.getvalue()); tmp_path = tmp.name

            kwargs = dict(
                cd_support=cd_support,
                cd_fractions=cd_fractions,
                codes_stations=stations_selectionnees if stations_selectionnees else None,
            )
            if date_debut: kwargs["date_debut"] = date_debut.strftime("%d/%m/%Y")
            if date_fin:   kwargs["date_fin"]   = date_fin.strftime("%d/%m/%Y")

            res = importer_bdd(tmp_path, **kwargs)
            os.unlink(tmp_path)

            # Invalider les résultats précédents
            invalider_depuis_donnees()

            df = res["df"]
            if df.empty:
                st.error("❌ Aucune donnée après filtrage. Vérifiez les critères.")
            else:
                st.session_state.update({
                    "df_filtre":           df,
                    "df_debit":            res["df_debit"],
                    "inventaire_stations": res["inventaire_stations"],
                    "lb_stations":         dict(zip(
                        res["inventaire_stations"]["CdStationMesureEauxSurface"],
                        res["inventaire_stations"]["LbStationMesureEauxSurface"].str.strip(),
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
                    (st.error if a.startswith("❌") else
                     st.warning if a.startswith("⚠️") else st.info)(a)

                st.success("✅ Données chargées avec succès.")
                st.rerun()

        except Exception as e:
            import traceback
            st.error(f"❌ Erreur : {e}")
            st.code(traceback.format_exc())

# ── Inventaire si données chargées ───────────────────────────────────────────
if st.session_state.get("donnees_chargees"):
    meta = st.session_state["meta_fichier"]
    st.markdown("---")
    st.markdown("### ✅ Données chargées")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stations",   meta.get("n_stations", "?"))
    m2.metric("Paramètres", meta.get("n_params",   "?"))
    m3.metric("Lignes",     f"{meta.get('n_lignes', 0):,}")
    m4.metric("Fichier",    meta.get("nom", "?"))

    st.markdown(f"📅 Période : `{meta.get('periode', '?')}`")

    inv = st.session_state.get("inventaire_stations")
    if inv is not None and not inv.empty:
        st.markdown("**Stations retenues**")
        st.dataframe(inv, use_container_width=True, hide_index=True)

    df_debit = st.session_state.get("df_debit")
    if df_debit is not None and not df_debit.empty:
        n_q = df_debit["CdStationMesureEauxSurface"].nunique()
        st.info(
            f"💧 Débits co-localisés disponibles pour **{n_q} station(s)** "
            f"({len(df_debit)} mesures) — utilisables dans l'onglet **Débit et chimie**."
        )
    else:
        st.warning(
            "💧 Aucun débit co-localisé trouvé. "
            "Vous pourrez utiliser une station hydrométrique externe "
            "dans l'onglet **Débit et chimie**."
        )

    st.markdown("➡️ Passez à l'onglet **Configuration**.")

st.markdown("---")
st.markdown(
    '<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>',
    unsafe_allow_html=True,
)
