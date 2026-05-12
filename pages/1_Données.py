"""
pages/1_Données.py — Chargement des données (M01 v2 multi-sources)

Formats supportés :
  • Naïades chimie     (export Hub'Eau, CSV latin-1)
  • ADES               (eaux souterraines, CSV latin-1)
  • ARS / CAP          (eau potable, CSV latin-1)
  • HB-Naïades         (données biologiques, CSV latin-1)

Logique :
  1. Uploader un ou plusieurs fichiers CSV (formats mélangés acceptés)
  2. Chaque fichier est auto-détecté (ou forcé manuellement)
  3. Fusion en un DataFrame commun normalisé
  4. Filtres optionnels (support, fraction, période, stations)
  5. Groupement optionnel par Bassin Versant
"""
import streamlit as st, sys, tempfile, os, json
import datetime
import pandas as pd
import numpy as np
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
    from modules.m01_import import (
        lire_bdd_source, fusionner_sources,
        inventaire_supports_fractions,
        filtrer_support_fraction, filtrer_stations,
        filtrer_periode, extraire_debit,
        inventaire_stations, detecter_format,
        importer_bdd,
    )
except ImportError as e:
    st.error(f"❌ Module m01_import introuvable : {e}"); st.stop()

LABELS_FORMAT = {
    "naiade": "🔵 Naïades chimie",
    "ades":   "🟢 ADES (eaux souterraines)",
    "ars":    "🟠 ARS / CAP (eau potable)",
    "hb":     "🟣 HB-Naïades (biologie)",
    "inconnu":"⚪ Format inconnu",
}

# ── Étape 1 : Upload ──────────────────────────────────────────────────────────
st.markdown("### 1. Charger le(s) fichier(s) de données")
st.markdown(
    "Formats acceptés : **Naïades**, **ADES**, **ARS/CAP**, **HB-Naïades**. "
    "Vous pouvez charger plusieurs fichiers de formats différents — ils seront fusionnés."
)

uploaded_files = st.file_uploader(
    "Fichier(s) CSV",
    type=["csv"],
    accept_multiple_files=True,
    help="Séparateur ';', encodage latin-1. Détection automatique du format.",
)

if not uploaded_files:
    st.info("⬆️ Chargez au moins un fichier CSV pour commencer.")
    st.stop()

# ── Lecture brute de chaque fichier ──────────────────────────────────────────
@st.cache_data(show_spinner="Lecture des fichiers…")
def lire_tous_bruts(files_data: list[tuple[str, bytes]]) -> list[tuple]:
    """
    Lit chaque fichier brut et retourne une liste de
    (nom, df_norm, format_detecte, alertes).
    """
    resultats = []
    for nom, data in files_data:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        fmt = detecter_format(tmp_path)
        df, alertes = lire_bdd_source(tmp_path, format_force=None)
        os.unlink(tmp_path)
        resultats.append((nom, df, fmt, alertes))
    return resultats

files_data = [(f.name, f.getvalue()) for f in uploaded_files]
resultats_lecture = lire_tous_bruts(files_data)

# ── Affichage par fichier ─────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 2. Fichiers chargés")

format_forces = {}   # {nom_fichier: format_force ou None}

for nom, df, fmt_auto, alertes in resultats_lecture:
    with st.expander(f"📄 {nom} — {LABELS_FORMAT.get(fmt_auto, fmt_auto)}", expanded=True):
        # Alertes
        for a in alertes:
            (st.error if a.startswith("❌")
             else st.warning if a.startswith("⚠️")
             else st.info)(a)

        if df.empty:
            st.error("❌ Fichier vide ou non reconnu.")
            format_forces[nom] = None
            continue

        # Métriques rapides
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Lignes",    f"{len(df):,}")
        c2.metric("Stations",  df["CdStationMesureEauxSurface"].nunique())
        c3.metric("Paramètres", df["CdParametre"].nunique())
        c4.metric("Format",    LABELS_FORMAT.get(fmt_auto, fmt_auto))

        # Option : forcer le format si la détection est douteuse
        fmt_choix = st.selectbox(
            "Format (correction manuelle si nécessaire)",
            options=["Auto (" + fmt_auto + ")", "naiade", "ades", "ars", "hb"],
            index=0,
            key=f"fmt_{nom}",
            help="La détection automatique est fiable dans la grande majorité des cas.",
        )
        format_forces[nom] = None if fmt_choix.startswith("Auto") else fmt_choix

# ── Inventaire global avant filtres ──────────────────────────────────────────
@st.cache_data(show_spinner="Fusion des sources…")
def fusionner_tout(files_data, format_forces):
    resultats = []
    for nom, data in files_data:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        fmt = format_forces.get(nom) or None
        df, _ = lire_bdd_source(tmp_path, format_force=fmt)
        os.unlink(tmp_path)
        resultats.append((df, nom))
    df_fusion, alertes = fusionner_sources(resultats)
    inv = inventaire_supports_fractions(df_fusion)
    return df_fusion, inv, alertes

df_brut, inv_supports, alertes_fusion = fusionner_tout(files_data, format_forces)

st.markdown("---")
for a in alertes_fusion:
    (st.error if a.startswith("❌")
     else st.warning if a.startswith("⚠️")
     else st.info)(a)

if df_brut.empty:
    st.error("❌ Aucune donnée lisible dans les fichiers fournis.")
    st.stop()

st.success(
    f"✅ **{len(df_brut):,} lignes** fusionnées — "
    f"**{df_brut['CdStationMesureEauxSurface'].nunique()} station(s)** — "
    f"**{df_brut['CdParametre'].nunique()} paramètres**"
)

# ── Étape 3 : Sélection support / fraction ───────────────────────────────────
st.markdown("### 3. Sélection du support et de la fraction")

if inv_supports.empty:
    st.error("❌ Impossible de lire les supports/fractions.")
    st.stop()

with st.expander("📋 Supports et fractions présents dans le fichier", expanded=True):
    st.dataframe(
        inv_supports.rename(columns={
            "CdSupport":          "Code support",
            "LbSupport":          "Support",
            "CdFractionAnalysee": "Code fraction",
            "LbFractionAnalysee": "Fraction",
            "NbMesures":          "N mesures",
            "_source":            "Source",
        }),
        use_container_width=True, hide_index=True,
    )

supports_dispo = inv_supports[["CdSupport","LbSupport"]].drop_duplicates()
support_options = {
    row["CdSupport"]: (
        f"{int(row['CdSupport'])} — "
        f"{str(row['LbSupport']).strip() if pd.notna(row['LbSupport']) else 'Support inconnu'}"
    )
    for _, row in supports_dispo.iterrows()
    if pd.notna(row["CdSupport"])
}

cd_support = st.selectbox(
    "Support à analyser",
    options=list(support_options.keys()),
    format_func=lambda x: support_options[x],
)

fractions_du_support = inv_supports[inv_supports["CdSupport"] == cd_support]
fraction_options = {
    row["CdFractionAnalysee"]: (
        f"{int(row['CdFractionAnalysee'])} — "
        f"{str(row['LbFractionAnalysee']).strip()} "
        f"({row['NbMesures']:,} mesures)"
    )
    for _, row in fractions_du_support.iterrows()
    if pd.notna(row["CdFractionAnalysee"])
}

# Fraction par défaut : la plus mesurée, en ignorant les NaN (cas supports biologiques)
_fracs_valides = fractions_du_support[fractions_du_support["CdFractionAnalysee"].notna()]
if not _fracs_valides.empty:
    fraction_defaut = [_fracs_valides.loc[_fracs_valides["NbMesures"].idxmax(), "CdFractionAnalysee"]]
else:
    fraction_defaut = []   # supports biologiques : pas de fraction SANDRE

cd_fractions = st.multiselect(
    "Fraction(s) à analyser",
    options=list(fraction_options.keys()),
    default=fraction_defaut,
    format_func=lambda x: fraction_options.get(x, str(x)),
    help=(
        "En cas de doute, gardez la fraction avec le plus de mesures. "
        "Pour les données biologiques (HB), aucune fraction n'est requise."
    ),
)

if not cd_fractions and not _fracs_valides.empty:
    # Only block if fractions exist but none selected (not the case for HB/biological)
    st.warning("⚠️ Sélectionnez au moins une fraction.")
    st.stop()

# ── Étape 4 : Filtres optionnels ─────────────────────────────────────────────
st.markdown("### 4. Filtres optionnels")

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Période**")
    ca, cb = st.columns(2)
    date_debut = ca.date_input(
        "Du", value=None,
        min_value=datetime.date(1800, 1, 1),
        max_value=datetime.date(2100, 12, 31),
        help="Laisser vide = pas de filtre",
    )
    date_fin = cb.date_input(
        "Au", value=None,
        min_value=datetime.date(1800, 1, 1),
        max_value=datetime.date(2100, 12, 31),
        help="Laisser vide = pas de filtre",
    )

with col2:
    st.markdown("**Stations** (optionnel)")
    stations_dispo = sorted(df_brut["CdStationMesureEauxSurface"].dropna().unique().tolist())
    lb_dispo = {}
    if "LbStationMesureEauxSurface" in df_brut.columns:
        lb_dispo = dict(zip(
            df_brut["CdStationMesureEauxSurface"],
            df_brut["LbStationMesureEauxSurface"].fillna("").str.strip(),
        ))
    stations_selectionnees = st.multiselect(
        "Restreindre aux stations",
        options=stations_dispo,
        default=[],
        format_func=lambda x: f"{lb_dispo.get(x, x)} ({x})",
        help="Laisser vide = toutes les stations",
    )

# ── Étape 5 : Groupement par Bassin Versant ───────────────────────────────────
st.markdown("### 5. Groupement par Bassin Versant *(optionnel)*")

with st.expander("🗺️ Configurer les Bassins Versants", expanded=False):
    st.markdown(
        "Regroupez vos stations en Bassins Versants (BV). "
        "L'ordre des stations sera respecté dans les graphiques et tableaux."
    )

    if "bv_config" not in st.session_state:
        st.session_state["bv_config"] = {}
    bv_config: dict = st.session_state["bv_config"]

    col_add1, col_add2 = st.columns([3, 1])
    with col_add1:
        nouveau_bv = st.text_input(
            "Nom du nouveau BV",
            placeholder="ex: Bienne amont, BV Lac de Vouglans…",
            key="nouveau_bv_input",
        )
    with col_add2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ Créer le BV", use_container_width=True):
            nom = nouveau_bv.strip()
            if not nom:
                st.warning("⚠️ Donnez un nom au BV.")
            elif nom in bv_config:
                st.warning(f"⚠️ Le BV « {nom} » existe déjà.")
            else:
                bv_config[nom] = []
                st.session_state["bv_config"] = bv_config
                st.rerun()

    if not bv_config:
        st.info("Aucun BV configuré. Créez-en un ci-dessus.")
    else:
        stations_pool = stations_selectionnees if stations_selectionnees else stations_dispo

        for nom_bv in list(bv_config.keys()):
            st.markdown(f"---\n#### 🗂️ BV : *{nom_bv}*")
            col_bv1, col_bv2 = st.columns([4, 1])

            with col_bv1:
                stations_bv = bv_config[nom_bv]

                # ── Ajout de stations ─────────────────────────────────────
                # IMPORTANT : on NE déclenche PAS de rerun() sur le multiselect
                # lui-même — ça provoquerait un conflit d'état Streamlit quand
                # les options changent entre deux reruns.
                # Pattern correct : multiselect + bouton "Ajouter" séparé.
                non_assignees = [s for s in stations_pool if s not in stations_bv]
                # Clé du widget multiselect (NE JAMAIS écrire dessus directement)
                key_ms = f"add_ms_{nom_bv}"
                # Clé intermédiaire : stocke la sélection validée par le bouton
                key_pending = f"_pending_{nom_bv}"

                # Si une sélection en attente existe (bouton cliqué au run précédent),
                # on l'applique maintenant — AVANT de dessiner le widget
                if st.session_state.get(key_pending):
                    pending = st.session_state.pop(key_pending)
                    bv_config[nom_bv] = stations_bv + [
                        s for s in pending if s not in stations_bv
                    ]
                    st.session_state["bv_config"] = bv_config
                    st.rerun()

                st.multiselect(
                    f"Sélectionner les stations à ajouter au BV « {nom_bv} »",
                    options=non_assignees,
                    default=[],
                    format_func=lambda x: f"{lb_dispo.get(x, x)} ({x})",
                    key=key_ms,
                )
                if st.button(f"➕ Ajouter au BV « {nom_bv} »",
                             key=f"add_btn_{nom_bv}", use_container_width=True):
                    selections = st.session_state.get(key_ms, [])
                    if selections:
                        # On stocke dans la clé intermédiaire, pas dans le widget
                        st.session_state[key_pending] = list(selections)
                        st.rerun()
                    else:
                        st.warning("⚠️ Sélectionnez au moins une station.")

                # ── Liste des stations déjà dans le BV ───────────────────
                if stations_bv:
                    st.markdown(f"**Stations dans ce BV** ({len(stations_bv)}) — "
                                "↑ / ↓ pour réordonner, ✖ pour retirer :")
                    for i, s in enumerate(list(stations_bv)):
                        c1, c2, c3, c4 = st.columns([7, 1, 1, 1])
                        c1.markdown(f"`{i+1}.` {lb_dispo.get(s, s)} `({s})`")
                        # Bouton ↑ : seulement si pas en première position
                        if i > 0:
                            if c2.button("↑", key=f"up_{nom_bv}_{i}", help="Monter"):
                                lst = list(bv_config[nom_bv])
                                lst[i-1], lst[i] = lst[i], lst[i-1]
                                bv_config[nom_bv] = lst
                                st.session_state["bv_config"] = bv_config
                                st.rerun()
                        else:
                            c2.empty()
                        # Bouton ↓ : seulement si pas en dernière position
                        if i < len(stations_bv) - 1:
                            if c3.button("↓", key=f"dn_{nom_bv}_{i}", help="Descendre"):
                                lst = list(bv_config[nom_bv])
                                lst[i], lst[i+1] = lst[i+1], lst[i]
                                bv_config[nom_bv] = lst
                                st.session_state["bv_config"] = bv_config
                                st.rerun()
                        else:
                            c3.empty()
                        # Bouton ✖ : toujours disponible
                        if c4.button("✖", key=f"rm_{nom_bv}_{i}", help="Retirer du BV"):
                            lst = list(bv_config[nom_bv])
                            lst.pop(i)
                            bv_config[nom_bv] = lst
                            st.session_state["bv_config"] = bv_config
                            st.rerun()
                else:
                    st.caption("Aucune station assignée.")

            with col_bv2:
                st.markdown("<br><br>", unsafe_allow_html=True)
                if st.button(f"🗑️ Supprimer\n« {nom_bv} »", key=f"del_{nom_bv}", use_container_width=True):
                    del bv_config[nom_bv]
                    st.session_state["bv_config"] = bv_config
                    st.rerun()

        st.markdown("---")
        bv_valides = {n: s for n, s in bv_config.items() if s}
        if bv_valides:
            bv_choisi = st.selectbox(
                "BV actif pour les calculs",
                options=list(bv_valides.keys()),
                index=(
                    list(bv_valides.keys()).index(st.session_state.get("bv_actif"))
                    if st.session_state.get("bv_actif") in bv_valides else 0
                ),
            )
            st.session_state["bv_actif"] = bv_choisi
            stations_selectionnees = bv_valides[bv_choisi]
            st.success(
                f"✅ BV actif : **{bv_choisi}** — "
                + ", ".join(f"`{lb_dispo.get(s,s)}`" for s in stations_selectionnees)
            )
        else:
            st.session_state["bv_actif"] = None

        with st.expander("💾 Sauvegarder / Charger la configuration BV"):
            bv_json = json.dumps(bv_config, ensure_ascii=False, indent=2)
            st.download_button("⬇️ Télécharger la config BV (JSON)",
                               data=bv_json, file_name="config_bv.json",
                               mime="application/json")
            uploaded_cfg = st.file_uploader("⬆️ Charger une config BV (JSON)",
                                            type=["json"], key="bv_cfg_upload")
            if uploaded_cfg:
                try:
                    loaded = json.loads(uploaded_cfg.read())
                    if isinstance(loaded, dict):
                        st.session_state["bv_config"] = loaded
                        st.success("✅ Configuration BV chargée.")
                        st.rerun()
                except Exception as ex:
                    st.error(f"❌ Erreur : {ex}")

# ── Étape 6 : Lancement ──────────────────────────────────────────────────────
st.markdown("---")
if st.button("🚀 Appliquer les filtres et charger", type="primary", use_container_width=True):
    with st.spinner("Filtrage et analyse en cours…"):
        try:
            # Relire et fusionner (déjà en cache)
            resultats = []
            for nom, data in files_data:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
                    tmp.write(data); tmp_path = tmp.name
                fmt = format_forces.get(nom) or None
                df_src, _ = lire_bdd_source(tmp_path, format_force=fmt)
                os.unlink(tmp_path)
                resultats.append((df_src, nom))

            df_fus, _ = fusionner_sources(resultats)

            # Extraire débit (Naïades uniquement)
            df_debit, a_deb = extraire_debit(df_fus)
            for a in a_deb:
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)

            # Filtre support/fraction (cd_fractions=None = pas de filtre fraction, ex: données biologiques)
            fracs_arg = list(cd_fractions) if cd_fractions else None
            df, a_sf = filtrer_support_fraction(df_fus, cd_support, fracs_arg)
            for a in a_sf:
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)

            if df.empty:
                st.error("❌ Aucune donnée après filtre support/fraction.")
                st.stop()

            # Filtre stations
            stations_finales = stations_selectionnees if stations_selectionnees else None
            df = filtrer_stations(df, stations_finales)

            # Filtre période
            kwargs_periode = {}
            if date_debut: kwargs_periode["date_debut"] = date_debut.strftime("%d/%m/%Y")
            if date_fin:   kwargs_periode["date_fin"]   = date_fin.strftime("%d/%m/%Y")
            df, a_per = filtrer_periode(df, **kwargs_periode)
            for a in a_per:
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)

            if df.empty:
                st.error("❌ Aucune donnée après filtrage. Vérifiez les critères.")
                st.stop()

            invalider_depuis_donnees()

            # Ordre stations (BV actif)
            bv_actif = st.session_state.get("bv_actif")
            bv_cfg = st.session_state.get("bv_config", {})
            ordre_stations = bv_cfg.get(bv_actif) if bv_actif else None

            inv_st = inventaire_stations(df)

            st.session_state.update({
                "df_filtre":           df,
                "df_debit":            df_debit,
                "inventaire_stations": inv_st,
                "lb_stations": dict(zip(
                    inv_st["CdStationMesureEauxSurface"],
                    inv_st["LbStationMesureEauxSurface"].fillna("").str.strip(),
                )),
                "ordre_stations":  ordre_stations,
                "bv_actif_nom":    bv_actif,
                "meta_fichier": {
                    "nom": " + ".join(f.name for f in uploaded_files),
                    "n_lignes":   len(df),
                    "n_stations": df["CdStationMesureEauxSurface"].nunique(),
                    "n_params":   df["CdParametre"].nunique(),
                    "sources":    df["_source"].value_counts().to_dict(),
                    "periode": (
                        f"{df['DatePrel'].min().strftime('%d/%m/%Y') if df['DatePrel'].notna().any() else '?'}"
                        " → "
                        f"{df['DatePrel'].max().strftime('%d/%m/%Y') if df['DatePrel'].notna().any() else '?'}"
                    ),
                },
                "donnees_chargees": True,
            })

            st.success("✅ Données chargées avec succès.")
            st.rerun()

        except Exception as e:
            import traceback
            st.error(f"❌ Erreur : {e}")
            st.code(traceback.format_exc())

# ── Récapitulatif si données chargées ────────────────────────────────────────
if st.session_state.get("donnees_chargees"):
    meta = st.session_state["meta_fichier"]
    st.markdown("---")
    st.markdown("### ✅ Données chargées")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stations",   meta.get("n_stations", "?"))
    m2.metric("Paramètres", meta.get("n_params",   "?"))
    m3.metric("Lignes",     f"{meta.get('n_lignes', 0):,}")
    m4.metric("Fichier(s)", meta.get("nom", "?"))

    st.markdown(f"📅 Période : `{meta.get('periode', '?')}`")

    sources = meta.get("sources", {})
    if sources:
        src_str = " | ".join(
            f"**{LABELS_FORMAT.get(k,k)}** : {v:,}" for k, v in sources.items()
        )
        st.markdown(f"📊 Sources : {src_str}")

    bv_nom = st.session_state.get("bv_actif_nom")
    ordre  = st.session_state.get("ordre_stations")
    lb     = st.session_state.get("lb_stations", {})
    if bv_nom and ordre:
        st.markdown(
            f"🗺️ BV actif : **{bv_nom}** — "
            + " → ".join(f"`{lb.get(s,s)}`" for s in ordre)
        )

    inv = st.session_state.get("inventaire_stations")
    if inv is not None and not inv.empty:
        st.markdown("**Stations retenues**")
        st.dataframe(inv, use_container_width=True, hide_index=True)

    df_debit = st.session_state.get("df_debit")
    if df_debit is not None and not df_debit.empty:
        st.info(
            f"💧 Débits disponibles pour **{df_debit['CdStationMesureEauxSurface'].nunique()} station(s)** "
            f"({len(df_debit)} mesures)."
        )
    else:
        st.warning("💧 Aucun débit co-localisé trouvé.")

    st.markdown("➡️ Passez à l'onglet **Configuration**.")

st.markdown("---")
st.markdown(
    '<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>',
    unsafe_allow_html=True,
)
