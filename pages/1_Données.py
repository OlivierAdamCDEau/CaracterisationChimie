"""
pages/1_Données.py — Chargement des données (M01 v3)

Architecture BV robuste :
  - Tout l'état BV vit dans st.session_state["bv_config"]
  - Toutes les mutations sont traitées en haut de page, avant tout widget
  - Les boutons ne font QUE stocker une action dans _bv_action, jamais muter directement
  - Un seul st.rerun() centralisé après mutation
  - Aucun expander imbriqué
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
    st.error(f"❌ Module m01_import introuvable : {e}"); st.stop()

LABELS_FORMAT = {
    "naiade": "🔵 Naïades chimie",
    "ades":   "🟢 ADES (eaux souterraines)",
    "ars":    "🟠 ARS / CAP (eau potable)",
    "hb":     "🟣 HB-Naïades (biologie)",
    "inconnu":"⚪ Format inconnu",
}

# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 0 — Traitement centralisé des actions BV
# ═══════════════════════════════════════════════════════════════════════════════
# RÈGLE ABSOLUE : ce bloc s'exécute AVANT tout widget.
# Les boutons ne font que stocker {"action": ..., ...} dans st.session_state["_bv_action"].
# Ce bloc lit l'action, l'applique, la supprime, puis rerun.
# Aucune mutation n'a lieu ailleurs dans la page.
# ═══════════════════════════════════════════════════════════════════════════════

if "bv_config" not in st.session_state:
    st.session_state["bv_config"] = {}

_act = st.session_state.pop("_bv_action", None)
if _act is not None:
    _cfg = st.session_state["bv_config"]
    _type = _act.get("type")

    if _type == "creer":
        _nom = _act["nom"]
        if _nom and _nom not in _cfg:
            _cfg[_nom] = []

    elif _type == "ajouter":
        _bv  = _act["bv"]
        _lst = list(_cfg.get(_bv, []))
        for _s in _act["stations"]:
            if _s not in _lst:
                _lst.append(_s)
        _cfg[_bv] = _lst

    elif _type == "retirer":
        _bv  = _act["bv"]
        _lst = list(_cfg.get(_bv, []))
        _i   = _act["index"]
        if 0 <= _i < len(_lst):
            _lst.pop(_i)
        _cfg[_bv] = _lst

    elif _type == "monter":
        _bv  = _act["bv"]
        _lst = list(_cfg.get(_bv, []))
        _i   = _act["index"]
        if 0 < _i < len(_lst):
            _lst[_i-1], _lst[_i] = _lst[_i], _lst[_i-1]
        _cfg[_bv] = _lst

    elif _type == "descendre":
        _bv  = _act["bv"]
        _lst = list(_cfg.get(_bv, []))
        _i   = _act["index"]
        if 0 <= _i < len(_lst) - 1:
            _lst[_i], _lst[_i+1] = _lst[_i+1], _lst[_i]
        _cfg[_bv] = _lst

    elif _type == "supprimer_bv":
        _cfg.pop(_act["bv"], None)
        # Si le BV actif est supprimé, réinitialiser
        if st.session_state.get("bv_actif") == _act["bv"]:
            st.session_state["bv_actif"] = None

    elif _type == "charger_json":
        _cfg.clear()
        _cfg.update(_act["data"])

    st.session_state["bv_config"] = _cfg
    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 1 — Upload fichiers
# ═══════════════════════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 2 — Lecture + fusion (avec cache)
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner="Lecture et fusion des fichiers…")
def charger_et_fusionner(files_data: list[tuple[str, bytes]], format_forces: dict):
    """Lit, détecte, normalise et fusionne tous les fichiers. Résultat mis en cache."""
    resultats = []
    tous_alertes = []
    for nom, data in files_data:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        fmt = format_forces.get(nom) or detecter_format(tmp_path)
        df, alertes = lire_bdd_source(tmp_path, format_force=fmt)
        os.unlink(tmp_path)
        resultats.append((df, nom, fmt, alertes))
        tous_alertes.extend(alertes)

    dfs = [(df, nom) for df, nom, _, _ in resultats]
    df_fusion, a_fus = fusionner_sources(dfs)
    tous_alertes.extend(a_fus)

    inv = inventaire_supports_fractions(df_fusion)
    meta_fichiers = [(nom, fmt, alertes) for _, nom, fmt, alertes in resultats]
    return df_fusion, inv, tous_alertes, meta_fichiers

# Premier passage : détection automatique pour affichage
files_data_0 = [(f.name, f.getvalue()) for f in uploaded_files]
format_forces_0 = {f.name: None for f in uploaded_files}
df_brut_0, inv_0, alertes_0, meta_0 = charger_et_fusionner(
    files_data_0, format_forces_0
)

# ── Affichage des fichiers + sélecteurs de format ────────────────────────────
st.markdown("---")
st.markdown("### 2. Fichiers chargés")

format_forces = {}
for nom, fmt_auto, alertes in meta_0:
    with st.expander(f"📄 {nom} — {LABELS_FORMAT.get(fmt_auto, fmt_auto)}", expanded=False):
        for a in alertes:
            (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)
        fmt_choix = st.selectbox(
            "Format (correction si nécessaire)",
            options=["Auto (" + fmt_auto + ")", "naiade", "ades", "ars", "hb"],
            index=0, key=f"fmt_{nom}",
        )
        format_forces[nom] = None if fmt_choix.startswith("Auto") else fmt_choix

# Recharger si des formats ont été forcés manuellement
files_data = [(f.name, f.getvalue()) for f in uploaded_files]
df_brut, inv_supports, alertes_fusion, _ = charger_et_fusionner(
    files_data, format_forces
)

st.markdown("---")
for a in alertes_fusion:
    (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)

if df_brut.empty:
    st.error("❌ Aucune donnée lisible."); st.stop()

st.success(
    f"✅ **{len(df_brut):,} lignes** — "
    f"**{df_brut['CdStationMesureEauxSurface'].nunique()} station(s)** — "
    f"**{df_brut['CdParametre'].nunique()} paramètres**"
)

# ── Catalogue stations disponibles (pour tout le reste de la page) ────────────
stations_dispo = sorted(df_brut["CdStationMesureEauxSurface"].dropna().unique().tolist())
lb_dispo = {}
if "LbStationMesureEauxSurface" in df_brut.columns:
    lb_dispo = (
        df_brut[["CdStationMesureEauxSurface","LbStationMesureEauxSurface"]]
        .drop_duplicates("CdStationMesureEauxSurface")
        .set_index("CdStationMesureEauxSurface")["LbStationMesureEauxSurface"]
        .fillna("").str.strip()
        .to_dict()
    )

def _label_station(code):
    lb = lb_dispo.get(code, "")
    return f"{lb} ({code})" if lb else str(code)

# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 3 — Support / fraction
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("### 3. Sélection du support et de la fraction")

if inv_supports.empty:
    st.error("❌ Impossible de lire les supports/fractions."); st.stop()

with st.expander("📋 Supports et fractions disponibles", expanded=True):
    st.dataframe(
        inv_supports.rename(columns={
            "CdSupport": "Code support", "LbSupport": "Support",
            "CdFractionAnalysee": "Code fraction",
            "LbFractionAnalysee": "Fraction",
            "NbMesures": "N mesures", "_source": "Source",
        }),
        use_container_width=True, hide_index=True,
    )

supports_dispo = inv_supports[["CdSupport","LbSupport"]].drop_duplicates()
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
_fracs_valides = fractions_du_support[fractions_du_support["CdFractionAnalysee"].notna()]
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
    help="Laisser vide uniquement pour les données biologiques HB (pas de fraction SANDRE).",
)

if not cd_fractions and not _fracs_valides.empty:
    st.warning("⚠️ Sélectionnez au moins une fraction.")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 4 — Filtres période + stations
# ═══════════════════════════════════════════════════════════════════════════════

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
    st.markdown("**Stations** (optionnel — remplacé par le BV actif si défini)")
    stations_manuelles = st.multiselect(
        "Restreindre aux stations",
        options=stations_dispo,
        default=[],
        format_func=_label_station,
        help="Ignoré si un BV actif est sélectionné ci-dessous.",
        key="stations_manuelles_sel",
    )

# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 5 — Gestion des Bassins Versants
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("### 5. Groupement par Bassin Versant *(optionnel)*")

bv_config = st.session_state["bv_config"]   # référence directe (lecture seule ici)

with st.expander("🗺️ Configurer les Bassins Versants", expanded=bool(bv_config)):

    # ── Sauvegarde / Chargement (en tête, toujours accessible) ───────────────
    st.markdown("**💾 Sauvegarder / Charger**")
    sc1, sc2, sc3 = st.columns([2, 1, 2])

    nom_fichier = sc1.text_input(
        "Nom de fichier", value="config_bv", key="bv_save_name",
        help="Sans extension — .json ajouté automatiquement",
    )
    nom_propre = (nom_fichier.strip() or "config_bv").replace(" ", "_")
    sc2.markdown("<br>", unsafe_allow_html=True)
    sc2.download_button(
        "⬇️ Sauvegarder",
        data=json.dumps(bv_config, ensure_ascii=False, indent=2),
        file_name=f"{nom_propre}.json",
        mime="application/json",
        use_container_width=True,
        disabled=not bv_config,
    )

    uploaded_cfg = sc3.file_uploader(
        "⬆️ Charger un fichier JSON", type=["json"], key="bv_cfg_upload",
    )
    if uploaded_cfg and "_bv_action" not in st.session_state:
        try:
            loaded = json.loads(uploaded_cfg.read())
            if isinstance(loaded, dict):
                st.session_state["_bv_action"] = {"type": "charger_json", "data": loaded}
                # Vider l'uploader avant rerun pour éviter la boucle
                del st.session_state["bv_cfg_upload"]
                st.rerun()
            else:
                st.error("❌ Format JSON invalide.")
        except Exception as ex:
            st.error(f"❌ Erreur : {ex}")

    st.markdown("---")

    # ── Créer un nouveau BV ───────────────────────────────────────────────────
    st.markdown("**Créer un nouveau BV**")
    nb1, nb2 = st.columns([3, 1])
    with nb1:
        nouveau_bv_nom = st.text_input(
            "Nom du BV", placeholder="ex: Bienne amont…",
            key="nouveau_bv_input", label_visibility="collapsed",
        )
    with nb2:
        if st.button("➕ Créer", use_container_width=True, key="btn_creer_bv"):
            nom = st.session_state.get("nouveau_bv_input", "").strip()
            if not nom:
                st.warning("⚠️ Saisissez un nom.")
            elif nom in bv_config:
                st.warning(f"⚠️ « {nom} » existe déjà.")
            else:
                st.session_state["_bv_action"] = {"type": "creer", "nom": nom}
                st.rerun()

    # ── Liste des BV et gestion des stations ──────────────────────────────────
    if not bv_config:
        st.info("Aucun BV pour l'instant. Créez-en un ci-dessus ou chargez un fichier.")
    else:
        stations_pool = stations_manuelles if stations_manuelles else stations_dispo

        for nom_bv in list(bv_config.keys()):
            st.markdown(f"---\n**🗂️ {nom_bv}**")

            stations_bv    = list(bv_config[nom_bv])   # copie locale, lecture seule
            non_assignees  = [s for s in stations_pool if s not in stations_bv]

            # Colonne principale + bouton suppression BV
            col_main, col_del = st.columns([5, 1])

            with col_main:
                # ── Ajouter des stations ──────────────────────────────────
                add_key = f"ms_add_{nom_bv}"
                st.multiselect(
                    "Stations à ajouter",
                    options=non_assignees,
                    default=[],
                    format_func=_label_station,
                    key=add_key,
                    label_visibility="collapsed",
                    placeholder=f"Sélectionner pour ajouter à « {nom_bv} »…",
                )
                if st.button(
                    f"➕ Ajouter la sélection à « {nom_bv} »",
                    key=f"btn_add_{nom_bv}",
                    use_container_width=True,
                ):
                    sel = list(st.session_state.get(add_key, []))
                    if sel:
                        st.session_state["_bv_action"] = {
                            "type": "ajouter", "bv": nom_bv, "stations": sel,
                        }
                        st.rerun()
                    else:
                        st.warning("⚠️ Aucune station sélectionnée.")

                # ── Liste ordonnée des stations ───────────────────────────
                if stations_bv:
                    st.markdown(
                        f"**Stations** ({len(stations_bv)}) "
                        "— ↑ monter · ↓ descendre · ✖ retirer"
                    )
                    for i, s in enumerate(stations_bv):
                        r1, r2, r3, r4 = st.columns([7, 1, 1, 1])
                        r1.markdown(f"`{i+1}.` {lb_dispo.get(s, s)} `({s})`")

                        # ↑ monter
                        if i > 0:
                            if r2.button("↑", key=f"btn_up_{nom_bv}_{i}",
                                         help="Monter"):
                                st.session_state["_bv_action"] = {
                                    "type": "monter", "bv": nom_bv, "index": i,
                                }
                                st.rerun()
                        else:
                            r2.empty()

                        # ↓ descendre
                        if i < len(stations_bv) - 1:
                            if r3.button("↓", key=f"btn_dn_{nom_bv}_{i}",
                                         help="Descendre"):
                                st.session_state["_bv_action"] = {
                                    "type": "descendre", "bv": nom_bv, "index": i,
                                }
                                st.rerun()
                        else:
                            r3.empty()

                        # ✖ retirer
                        if r4.button("✖", key=f"btn_rm_{nom_bv}_{i}",
                                     help="Retirer du BV"):
                            st.session_state["_bv_action"] = {
                                "type": "retirer", "bv": nom_bv, "index": i,
                            }
                            st.rerun()
                else:
                    st.caption("Aucune station encore assignée.")

            with col_del:
                st.markdown("<br><br><br>", unsafe_allow_html=True)
                if st.button(
                    "🗑️ Supprimer", key=f"btn_del_bv_{nom_bv}",
                    use_container_width=True, help=f"Supprimer le BV « {nom_bv} »",
                ):
                    st.session_state["_bv_action"] = {
                        "type": "supprimer_bv", "bv": nom_bv,
                    }
                    st.rerun()

    # ── Sélecteur BV actif ────────────────────────────────────────────────────
    bv_valides = {n: s for n, s in bv_config.items() if s}
    if bv_valides:
        st.markdown("---")
        bv_actif_options = list(bv_valides.keys())
        bv_actif_defaut  = (
            bv_actif_options.index(st.session_state.get("bv_actif"))
            if st.session_state.get("bv_actif") in bv_actif_options else 0
        )
        bv_choisi = st.selectbox(
            "**BV actif pour les calculs**",
            options=bv_actif_options,
            index=bv_actif_defaut,
            key="bv_actif_sel",
        )
        st.session_state["bv_actif"] = bv_choisi
        stations_selectionnees = bv_valides[bv_choisi]
        st.success(
            f"✅ BV actif : **{bv_choisi}** — "
            f"{len(stations_selectionnees)} station(s) : "
            + ", ".join(f"`{lb_dispo.get(s,s)}`" for s in stations_selectionnees)
        )
    else:
        st.session_state["bv_actif"] = None
        stations_selectionnees = stations_manuelles   # fallback sur sélection manuelle

# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 6 — Lancement du filtrage
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("---")
if st.button("🚀 Appliquer les filtres et charger",
             type="primary", use_container_width=True):
    with st.spinner("Filtrage en cours…"):
        try:
            df_fus = df_brut   # déjà en cache, pas de relecture

            # Débit
            df_debit, a_deb = extraire_debit(df_fus)
            for a in a_deb:
                (st.error if a.startswith("❌")
                 else st.warning if a.startswith("⚠️") else st.info)(a)

            # Support / fraction
            fracs_arg = list(cd_fractions) if cd_fractions else None
            df, a_sf = filtrer_support_fraction(df_fus, cd_support, fracs_arg)
            for a in a_sf:
                (st.error if a.startswith("❌")
                 else st.warning if a.startswith("⚠️") else st.info)(a)

            if df.empty:
                st.error("❌ Aucune donnée pour ce support/fraction."); st.stop()

            # Stations
            df = filtrer_stations(df, stations_selectionnees or None)

            # Période
            kw = {}
            if date_debut: kw["date_debut"] = date_debut.strftime("%d/%m/%Y")
            if date_fin:   kw["date_fin"]   = date_fin.strftime("%d/%m/%Y")
            df, a_per = filtrer_periode(df, **kw)
            for a in a_per:
                (st.error if a.startswith("❌")
                 else st.warning if a.startswith("⚠️") else st.info)(a)

            if df.empty:
                st.error("❌ Aucune donnée après filtrage."); st.stop()

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
                    "nom":      " + ".join(f.name for f in uploaded_files),
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

# ═══════════════════════════════════════════════════════════════════════════════
# BLOC 7 — Récapitulatif
# ═══════════════════════════════════════════════════════════════════════════════

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
                f"**{LABELS_FORMAT.get(k,k)}** : {v:,}" for k, v in sources.items()
            )
        )

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
            f"💧 Débits disponibles pour "
            f"**{df_debit['CdStationMesureEauxSurface'].nunique()} station(s)** "
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
