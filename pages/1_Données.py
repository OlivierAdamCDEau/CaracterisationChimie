"""
pages/1_Données.py — v4
=======================
Corrections majeures :
  - df_brut stocké en session_state → survit aux reruns sans perdre le fichier
  - BV géré via st.data_editor → zéro rerun pendant l'édition, zéro conflit
  - Filtre stations appliqué AVANT extraire_debit → évite l'OOM sur grosse BDD
  - Suppression du bouton reboot (impossible sur l'écran d'erreur Streamlit Cloud)
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
if not auth_ok:
    st.stop()
afficher_bandeau_utilisateur()

st.title("📂 Données")
emoji, msg = statut_donnees()
if emoji == "✅":
    afficher_bandeau_statut(emoji, msg)

try:
    from modules.m01_import import (
        lire_bdd_source, fusionner_sources,
        inventaire_supports_fractions,
        filtrer_support_fraction, filtrer_stations,
        filtrer_periode, extraire_debit,
        inventaire_stations, detecter_format,
    )
except ImportError as e:
    st.error(f"❌ Module m01_import introuvable : {e}")
    st.stop()

LABELS_FORMAT = {
    "naiade": "🔵 Naïades chimie",
    "ades":   "🟢 ADES (eaux souterraines)",
    "ars":    "🟠 ARS / CAP (eau potable)",
    "hb":     "🟣 HB-Naïades (biologie)",
    "inconnu": "⚪ Format inconnu",
}

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Upload
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("### 1. Charger le(s) fichier(s) de données")
st.caption(
    "Formats acceptés : Naïades, ADES, ARS/CAP, HB-Naïades. "
    "Plusieurs fichiers simultanément acceptés."
)

uploaded_files = st.file_uploader(
    "Fichier(s) CSV",
    type=["csv"],
    accept_multiple_files=True,
    help="Séparateur ';', encodage latin-1.",
)

# ── Lecture et mise en cache dans session_state ───────────────────────────────
# On stocke df_brut dans session_state (pas uniquement dans st.cache_data)
# pour qu'il survive aux reruns déclenchés par les actions BV.
# La clé de cache est le hash des noms+tailles des fichiers.

def _cache_key(files):
    return tuple((f.name, len(f.getvalue())) for f in files)

if uploaded_files:
    ck = _cache_key(uploaded_files)
    if st.session_state.get("_upload_cache_key") != ck:
        # Nouveau fichier — relire
        with st.spinner("Lecture des fichiers…"):
            resultats = []
            for f in uploaded_files:
                data = f.getvalue()
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".csv", mode="wb"
                ) as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                fmt = detecter_format(tmp_path)
                df, alertes = lire_bdd_source(tmp_path, format_force=None)
                os.unlink(tmp_path)
                resultats.append((df, f.name, fmt, alertes))

            dfs      = [(df, nom) for df, nom, _, _ in resultats]
            df_fus, a_fus = fusionner_sources(dfs)
            inv      = inventaire_supports_fractions(df_fus)
            meta_fic = [(nom, fmt, al) for _, nom, fmt, al in resultats]

            st.session_state["_upload_cache_key"] = ck
            st.session_state["_df_brut"]          = df_fus
            st.session_state["_inv_supports"]     = inv
            st.session_state["_alertes_fusion"]   = a_fus
            st.session_state["_meta_fichiers"]    = meta_fic

# Récupérer depuis session (même si file_uploader a perdu son état après un rerun)
df_brut     = st.session_state.get("_df_brut")
inv_supports = st.session_state.get("_inv_supports")

if df_brut is None or df_brut.empty:
    st.info("⬆️ Chargez au moins un fichier CSV pour commencer.")
    st.stop()

# ── Alertes de lecture ────────────────────────────────────────────────────────
for a in st.session_state.get("_alertes_fusion", []):
    (st.error if a.startswith("❌")
     else st.warning if a.startswith("⚠️")
     else st.info)(a)

st.success(
    f"✅ **{len(df_brut):,} lignes** — "
    f"**{df_brut['CdStationMesureEauxSurface'].nunique()} stations** — "
    f"**{df_brut['CdParametre'].nunique()} paramètres**"
)

# ── Détails par fichier (repliés par défaut) ──────────────────────────────────
for nom, fmt, alertes in st.session_state.get("_meta_fichiers", []):
    with st.expander(f"📄 {nom} — {LABELS_FORMAT.get(fmt, fmt)}", expanded=False):
        for a in alertes:
            (st.error if a.startswith("❌")
             else st.warning if a.startswith("⚠️")
             else st.info)(a)

# ── Catalogue stations ────────────────────────────────────────────────────────
stations_dispo = sorted(
    df_brut["CdStationMesureEauxSurface"].dropna().unique().tolist()
)
lb_dispo = {}
if "LbStationMesureEauxSurface" in df_brut.columns:
    lb_dispo = (
        df_brut[["CdStationMesureEauxSurface", "LbStationMesureEauxSurface"]]
        .drop_duplicates("CdStationMesureEauxSurface")
        .set_index("CdStationMesureEauxSurface")["LbStationMesureEauxSurface"]
        .fillna("").str.strip()
        .to_dict()
    )

def _label(code):
    lb = lb_dispo.get(code, "")
    return f"{lb} ({code})" if lb else str(code)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Support / Fraction
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---\n### 2. Support et fraction")

if inv_supports is None or inv_supports.empty:
    st.error("❌ Impossible de lire les supports/fractions.")
    st.stop()

with st.expander("📋 Supports et fractions disponibles", expanded=True):
    st.dataframe(
        inv_supports.rename(columns={
            "CdSupport": "Support", "LbSupport": "Libellé support",
            "CdFractionAnalysee": "Fraction", "LbFractionAnalysee": "Libellé fraction",
            "NbMesures": "N mesures", "_source": "Source",
        }),
        use_container_width=True, hide_index=True,
    )

supports_dispo = inv_supports[["CdSupport", "LbSupport"]].drop_duplicates()
support_options = {
    row["CdSupport"]: (
        f"{int(row['CdSupport'])} — "
        f"{str(row['LbSupport']).strip() if pd.notna(row['LbSupport']) else '?'}"
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
_fracs_valides = fractions_du_support[
    fractions_du_support["CdFractionAnalysee"].notna()
]
fraction_options = {
    row["CdFractionAnalysee"]: (
        f"{int(row['CdFractionAnalysee'])} — "
        f"{str(row['LbFractionAnalysee']).strip()} ({row['NbMesures']:,} mesures)"
    )
    for _, row in _fracs_valides.iterrows()
}

fraction_defaut = (
    [_fracs_valides.loc[_fracs_valides["NbMesures"].idxmax(), "CdFractionAnalysee"]]
    if not _fracs_valides.empty else []
)

cd_fractions = st.multiselect(
    "Fraction(s) à analyser",
    options=list(fraction_options.keys()),
    default=fraction_defaut,
    format_func=lambda x: fraction_options.get(x, str(x)),
)

if not cd_fractions and not _fracs_valides.empty:
    st.warning("⚠️ Sélectionnez au moins une fraction.")
    st.stop()

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Filtres période + stations manuelles
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---\n### 3. Filtres optionnels")

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
    )

with col2:
    st.markdown("**Stations** (si pas de BV actif)")
    stations_manuelles = st.multiselect(
        "Restreindre aux stations",
        options=stations_dispo,
        default=[],
        format_func=_label,
        help="Ignoré si un BV actif est configuré ci-dessous.",
        key="stations_manuelles_sel",
    )

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Bassins Versants
# ══════════════════════════════════════════════════════════════════════════════
#
# Architecture sans rerun pendant l'édition :
#   - st.data_editor gère l'affichage et la suppression de lignes directement
#   - L'ajout de nouvelles stations se fait via un multiselect + bouton unique
#   - Les modifications sont lues au moment du clic "Appliquer les filtres"
#   - Aucun st.rerun() n'est déclenché pendant l'édition du BV
#
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---\n### 4. Groupement par Bassin Versant *(optionnel)*")

if "bv_config" not in st.session_state:
    st.session_state["bv_config"] = {}   # {nom_bv: [liste_codes_stations]}
if "bv_actif" not in st.session_state:
    st.session_state["bv_actif"] = None

with st.expander("🗺️ Configurer les Bassins Versants", expanded=bool(st.session_state["bv_config"])):

    # ── Sauvegarde / Chargement ───────────────────────────────────────────────
    sc1, sc2, sc3 = st.columns([2, 1, 2])
    nom_fic = sc1.text_input(
        "Nom de fichier", value="config_bv", key="bv_save_name",
        help="Sans extension",
    )
    sc2.markdown("<br>", unsafe_allow_html=True)
    sc2.download_button(
        "⬇️ Sauvegarder",
        data=json.dumps(st.session_state["bv_config"], ensure_ascii=False, indent=2),
        file_name=f"{(nom_fic.strip() or 'config_bv').replace(' ','_')}.json",
        mime="application/json",
        use_container_width=True,
        disabled=not st.session_state["bv_config"],
    )
    uploaded_cfg = sc3.file_uploader(
        "⬆️ Charger JSON", type=["json"], key="bv_cfg_upload",
    )
    if uploaded_cfg:
        try:
            loaded = json.loads(uploaded_cfg.read())
            if isinstance(loaded, dict):
                st.session_state["bv_config"] = {
                    k: list(v) for k, v in loaded.items()
                }
                # Réinitialiser le BV actif si il n'existe plus
                if st.session_state["bv_actif"] not in st.session_state["bv_config"]:
                    st.session_state["bv_actif"] = None
                st.success("✅ Configuration BV chargée.")
                # PAS de rerun — l'expander se rafraîchit naturellement
            else:
                st.error("❌ Format JSON invalide.")
        except Exception as ex:
            st.error(f"❌ Erreur : {ex}")

    st.markdown("---")

    # ── Créer un nouveau BV ───────────────────────────────────────────────────
    nb1, nb2 = st.columns([3, 1])
    nouveau_nom = nb1.text_input(
        "Nom du BV", placeholder="ex: Bienne amont…",
        key="nouveau_bv_nom", label_visibility="collapsed",
    )
    nb2.markdown("<br>", unsafe_allow_html=True)
    if nb2.button("➕ Créer BV", use_container_width=True):
        nom = st.session_state.get("nouveau_bv_nom", "").strip()
        if not nom:
            st.warning("⚠️ Saisissez un nom.")
        elif nom in st.session_state["bv_config"]:
            st.warning(f"⚠️ « {nom} » existe déjà.")
        else:
            st.session_state["bv_config"][nom] = []
            st.session_state["bv_actif"] = nom
            # st.rerun() nécessaire ici UNIQUEMENT pour afficher le nouveau BV
            # C'est safe car on écrit dans bv_config (pas une clé widget)
            st.rerun()

    # ── Édition des BV existants ──────────────────────────────────────────────
    bv_config = st.session_state["bv_config"]

    if not bv_config:
        st.info("Aucun BV. Créez-en un ci-dessus ou chargez un fichier JSON.")
    else:
        # Sélecteur du BV à éditer (tabs si plusieurs BV)
        bv_noms = list(bv_config.keys())
        if len(bv_noms) == 1:
            bv_edite = bv_noms[0]
        else:
            bv_edite = st.radio(
                "BV à éditer",
                options=bv_noms,
                horizontal=True,
                key="bv_edite_sel",
            )

        st.markdown(f"**BV : {bv_edite}**")

        # ── Ajouter des stations (multiselect — PAS de rerun) ─────────────────
        stations_bv     = list(bv_config.get(bv_edite, []))
        non_assignees   = [s for s in stations_dispo if s not in stations_bv]

        nouvelles = st.multiselect(
            "Stations à ajouter",
            options=non_assignees,
            default=[],
            format_func=_label,
            placeholder="Sélectionner des stations à ajouter…",
            key=f"ms_add_{bv_edite}",
        )
        if st.button("➕ Ajouter", key=f"btn_add_{bv_edite}"):
            sel = list(st.session_state.get(f"ms_add_{bv_edite}", []))
            if sel:
                for s in sel:
                    if s not in stations_bv:
                        stations_bv.append(s)
                bv_config[bv_edite] = stations_bv
                st.session_state["bv_config"] = bv_config
                st.rerun()
            else:
                st.warning("⚠️ Aucune station sélectionnée.")

        # ── Tableau éditable des stations (data_editor) ───────────────────────
        # L'utilisateur peut :
        #   • Supprimer des lignes (icône corbeille à gauche)
        #   • Modifier le numéro d'ordre (colonne Ordre) pour réordonner
        # Un clic sur "Appliquer l'ordre / suppressions" valide les changements.

        if stations_bv:
            st.markdown(
                f"**{len(stations_bv)} station(s)** — "
                "Modifiez l'ordre en éditant la colonne **Ordre**, "
                "supprimez une ligne via la corbeille à gauche, "
                "puis cliquez **Valider**."
            )
            df_edit = pd.DataFrame({
                "Ordre":   list(range(1, len(stations_bv) + 1)),
                "Code":    stations_bv,
                "Station": [lb_dispo.get(s, s) for s in stations_bv],
            })

            edited = st.data_editor(
                df_edit,
                key=f"de_{bv_edite}",
                num_rows="dynamic",   # permet la suppression de lignes
                column_config={
                    "Ordre":   st.column_config.NumberColumn(
                        "Ordre", min_value=1, max_value=999, step=1, width="small"
                    ),
                    "Code":    st.column_config.TextColumn("Code", disabled=True, width="small"),
                    "Station": st.column_config.TextColumn("Station", disabled=True),
                },
                use_container_width=True,
                hide_index=True,
            )

            if st.button("✅ Valider ordre / suppressions", key=f"btn_val_{bv_edite}",
                         use_container_width=True, type="primary"):
                # Trier par ordre, reconstruire la liste
                try:
                    df_valid = edited.dropna(subset=["Code"]).copy()
                    df_valid["Ordre"] = pd.to_numeric(
                        df_valid["Ordre"], errors="coerce"
                    ).fillna(999)
                    df_valid = df_valid.sort_values("Ordre")
                    nouvelle_liste = df_valid["Code"].tolist()
                    bv_config[bv_edite] = nouvelle_liste
                    st.session_state["bv_config"] = bv_config
                    st.success(f"✅ {len(nouvelle_liste)} station(s) enregistrée(s).")
                    st.rerun()
                except Exception as ex:
                    st.error(f"❌ Erreur lors de la validation : {ex}")
        else:
            st.caption("Aucune station dans ce BV.")

        # ── Supprimer le BV entier ────────────────────────────────────────────
        if st.button(
            f"🗑️ Supprimer le BV « {bv_edite} »",
            key=f"btn_del_{bv_edite}",
            help="Supprime ce BV (les données ne sont pas affectées)",
        ):
            del bv_config[bv_edite]
            st.session_state["bv_config"] = bv_config
            if st.session_state.get("bv_actif") == bv_edite:
                st.session_state["bv_actif"] = (
                    list(bv_config.keys())[0] if bv_config else None
                )
            st.rerun()

    # ── Sélecteur BV actif pour les calculs ──────────────────────────────────
    bv_valides = {n: s for n, s in st.session_state["bv_config"].items() if s}
    if bv_valides:
        st.markdown("---")
        bv_actif_options = list(bv_valides.keys())
        bv_actif_idx = (
            bv_actif_options.index(st.session_state["bv_actif"])
            if st.session_state["bv_actif"] in bv_actif_options else 0
        )
        bv_choisi = st.selectbox(
            "**BV actif pour les calculs**",
            options=bv_actif_options,
            index=bv_actif_idx,
            key="bv_actif_sel",
        )
        st.session_state["bv_actif"] = bv_choisi
        st.info(
            f"🗺️ **{bv_choisi}** — "
            f"{len(bv_valides[bv_choisi])} station(s) : "
            + ", ".join(
                lb_dispo.get(s, s) for s in bv_valides[bv_choisi]
            )
        )
    else:
        st.session_state["bv_actif"] = None

# Stations effectives pour le filtrage
_bv_actif = st.session_state.get("bv_actif")
_bv_stations = (
    st.session_state["bv_config"].get(_bv_actif, [])
    if _bv_actif else []
)
stations_selectionnees = _bv_stations if _bv_stations else stations_manuelles

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Lancement du filtrage
# ══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
if st.button("🚀 Appliquer les filtres et charger",
             type="primary", use_container_width=True):
    with st.spinner("Filtrage en cours…"):
        try:
            df = df_brut.copy()

            # ── Étape 1 : filtre stations EN PREMIER (réduit le volume) ──────
            # IMPORTANT : on filtre avant extraire_debit pour éviter l'OOM
            # sur les grosses BDD avec beaucoup de stations.
            if stations_selectionnees:
                df = filtrer_stations(df, stations_selectionnees)
                if df.empty:
                    st.error("❌ Aucune donnée pour les stations sélectionnées.")
                    st.stop()

            # ── Étape 2 : extraire débit (sur le sous-ensemble) ──────────────
            df_debit, a_deb = extraire_debit(df)
            for a in a_deb:
                (st.error if a.startswith("❌")
                 else st.warning if a.startswith("⚠️") else st.info)(a)

            # ── Étape 3 : filtre support / fraction ──────────────────────────
            fracs_arg = list(cd_fractions) if cd_fractions else None
            df, a_sf = filtrer_support_fraction(df, cd_support, fracs_arg)
            for a in a_sf:
                (st.error if a.startswith("❌")
                 else st.warning if a.startswith("⚠️") else st.info)(a)

            if df.empty:
                st.error("❌ Aucune donnée pour ce support/fraction.")
                st.stop()

            # ── Étape 4 : filtre période ──────────────────────────────────────
            kw = {}
            if date_debut:
                kw["date_debut"] = date_debut.strftime("%d/%m/%Y")
            if date_fin:
                kw["date_fin"] = date_fin.strftime("%d/%m/%Y")
            df, a_per = filtrer_periode(df, **kw)
            for a in a_per:
                (st.error if a.startswith("❌")
                 else st.warning if a.startswith("⚠️") else st.info)(a)

            if df.empty:
                st.error("❌ Aucune donnée après filtrage.")
                st.stop()

            # ── Enregistrement ────────────────────────────────────────────────
            invalider_depuis_donnees()

            bv_actif = st.session_state.get("bv_actif")
            ordre_stations = (
                st.session_state["bv_config"].get(bv_actif)
                if bv_actif else None
            )

            inv_st = inventaire_stations(df)

            st.session_state.update({
                "df_filtre":           df,
                "df_debit":            df_debit,
                "inventaire_stations": inv_st,
                "lb_stations": dict(zip(
                    inv_st["CdStationMesureEauxSurface"],
                    inv_st["LbStationMesureEauxSurface"].fillna("").str.strip(),
                )),
                "ordre_stations": ordre_stations,
                "bv_actif_nom":   bv_actif,
                "meta_fichier": {
                    "nom": " + ".join(f.name for f in uploaded_files)
                           if uploaded_files else "—",
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

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Récapitulatif
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.get("donnees_chargees"):
    meta = st.session_state["meta_fichier"]
    st.markdown("---\n### ✅ Données chargées")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Stations",   meta.get("n_stations", "?"))
    m2.metric("Paramètres", meta.get("n_params",   "?"))
    m3.metric("Lignes",     f"{meta.get('n_lignes', 0):,}")
    m4.metric("Fichier(s)", meta.get("nom", "?"))

    st.markdown(f"📅 Période : `{meta.get('periode', '?')}`")

    sources = meta.get("sources", {})
    if sources:
        st.markdown(
            "📊 Sources : " + " | ".join(
                f"**{LABELS_FORMAT.get(k, k)}** : {v:,}"
                for k, v in sources.items()
            )
        )

    bv_nom = st.session_state.get("bv_actif_nom")
    ordre  = st.session_state.get("ordre_stations")
    lb_st  = st.session_state.get("lb_stations", {})
    if bv_nom and ordre:
        st.markdown(
            f"🗺️ BV actif : **{bv_nom}** — "
            + " → ".join(f"`{lb_st.get(s, s)}`" for s in ordre)
        )

    inv = st.session_state.get("inventaire_stations")
    if inv is not None and not inv.empty:
        with st.expander("Stations retenues", expanded=False):
            st.dataframe(inv, use_container_width=True, hide_index=True)

    df_debit = st.session_state.get("df_debit")
    if df_debit is not None and not df_debit.empty:
        st.info(
            f"💧 Débits disponibles pour "
            f"**{df_debit['CdStationMesureEauxSurface'].nunique()} station(s)** "
            f"({len(df_debit)} mesures)."
        )
    else:
        st.warning("💧 Aucun débit co-localisé.")

    st.markdown("➡️ Passez à l'onglet **Configuration**.")

st.markdown("---")
st.markdown(
    '<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>',
    unsafe_allow_html=True,
)
