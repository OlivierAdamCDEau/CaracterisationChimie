"""
pages/2_Configuration.py — Configuration de l'analyse (M02 + M07)
Paramètres alignés sur la signature réelle de nettoyer_et_pivoter().
"""
import streamlit as st, sys, tempfile, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Configuration", page_icon="⚙️", layout="wide")

from modules.auth import verifier_auth, afficher_bandeau_utilisateur, verifier_droit
from modules.session import (
    init_session, invalider_depuis_config,
    statut_donnees, statut_config, afficher_bandeau_statut,
)
import pandas as pd

init_session()
auth_ok, username, role = verifier_auth()
if not auth_ok: st.stop()
afficher_bandeau_utilisateur()

st.title("⚙️ Configuration")

# Bandeau état données
emoji_d, msg_d = statut_donnees()
afficher_bandeau_statut(emoji_d, f"Données : {msg_d}")
if emoji_d == "🔒":
    st.info("➡️ Chargez d'abord les données dans l'onglet **Données**.")
    st.stop()

# Bandeau état configuration
afficher_bandeau_statut(*statut_config())

peut_configurer = verifier_droit("config")
if not peut_configurer:
    st.warning(
        "⛔ Rôle Client : la configuration est en lecture seule. "
        "Les valeurs par défaut s'appliquent automatiquement."
    )

try:
    from modules.m02_nettoyage import nettoyer_et_pivoter
    from modules.m07_referentiels import (
        fusionner_referentiels,
        selectionner_seuil_reference,
        calculer_classes_par_station,
    )
except ImportError as e:
    st.error(f"❌ Module introuvable : {e}"); st.stop()

df_filtre   = st.session_state.get("df_filtre")
df_familles = st.session_state.get("df_familles")

# ── Section 1 : Fichier familles ──────────────────────────────────────────────
st.markdown("### 1. Fichier de familles SANDRE (optionnel)")
st.markdown(
    "Fichier CSV de correspondance `CdParametre` → `NomGroupeParametres`. "
    "Permet de grouper les paramètres par famille chimique dans les analyses."
)

if peut_configurer:
    uploaded_familles = st.file_uploader(
        "Fichier familles CSV", type=["csv"], key="upload_familles",
        help="Colonnes attendues : CdParametre, NomGroupeParametres",
    )
    if uploaded_familles:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
                tmp.write(uploaded_familles.getvalue()); tmp_path = tmp.name
            def corriger(s):
                if not isinstance(s, str): return s
                try: return s.encode('latin-1').decode('utf-8')
                except: return s
            df_fam = pd.read_csv(tmp_path, sep=None, engine='python', encoding='latin-1')
            df_fam['CdParametre'] = pd.to_numeric(df_fam['CdParametre'], errors='coerce')
            for col in df_fam.columns:
                if df_fam[col].dtype == object:
                    df_fam[col] = df_fam[col].apply(corriger)
            os.unlink(tmp_path)
            st.session_state["df_familles"] = df_fam
            df_familles = df_fam
            st.success(f"✅ {len(df_fam)} entrées de familles chargées.")
        except Exception as e:
            st.error(f"❌ Erreur lecture familles : {e}")
else:
    if df_familles is not None:
        st.info(f"✅ Fichier familles chargé ({len(df_familles)} entrées).")
    else:
        st.info("Aucun fichier de familles chargé.")

# ── Section 2 : Options de nettoyage ─────────────────────────────────────────
st.markdown("### 2. Options de nettoyage")

if peut_configurer:
    c1, c2, c3 = st.columns(3)

    seuil_pch = c1.slider(
        "Taux de renseignement min — PCH (%)",
        min_value=5, max_value=80, value=30, step=5,
        help=(
            "Taux minimum de stations où le paramètre doit être détecté "
            "pour être conservé dans l'analyse (paramètres physico-chimiques généraux). "
            "Défaut : 30 %. Augmentez pour être plus sélectif."
        ),
    )

    seuil_micro = c2.slider(
        "Taux de renseignement min — Micropolluants (%)",
        min_value=1, max_value=30, value=10, step=1,
        help=(
            "Même critère pour les micropolluants et métaux, "
            "dont la détection est naturellement plus rare. "
            "Défaut : 10 %."
        ),
    )

    methode_censure = c3.selectbox(
        "Traitement des valeurs < LQ",
        options=["LQ/2", "LQ", "0"],
        index=0,
        help=(
            "LQ/2 : convention DCE recommandée (estimateur non biaisé). "
            "LQ : surestime légèrement. "
            "0 : sous-estime (déconseillé sauf cas particulier)."
        ),
    )
else:
    seuil_pch, seuil_micro, methode_censure = 30, 10, "LQ/2"
    st.info(
        "Options par défaut : taux renseignement PCH ≥ 30 %, "
        "micropolluants ≥ 10 %, traitement < LQ = LQ/2."
    )

# ── Section 3 : Statistique pivot ────────────────────────────────────────────
st.markdown("### 3. Statistique de synthèse")

if peut_configurer:
    c1, c2 = st.columns(2)
    valeur_pivot = c1.selectbox(
        "Statistique pour le tableau pivot",
        options=["Mediane", "P90", "Moyenne", "P10"],
        index=0,
        help=(
            "Statistique utilisée pour construire le tableau station × paramètre "
            "(base des analyses multivariées et de l'empreinte chimique). "
            "La médiane est recommandée (robuste aux valeurs extrêmes)."
        ),
    )
    normalisation = c2.selectbox(
        "Méthode de normalisation",
        options=["log_zscore", "zscore", "minmax"],
        index=0,
        format_func=lambda x: {
            "log_zscore": "Log + Z-score (recommandé)",
            "zscore":     "Z-score simple",
            "minmax":     "Min-Max [0-1]",
        }[x],
        help=(
            "Normalisation appliquée avant les analyses multivariées (ACP, distances). "
            "Log + Z-score est recommandé pour les données chimiques à distribution asymétrique."
        ),
    )
else:
    valeur_pivot, normalisation = "Mediane", "log_zscore"

# ── Section 4 : Référentiel qualité ──────────────────────────────────────────
st.markdown("### 4. Référentiel de qualité")

if peut_configurer:
    c1, c2 = st.columns(2)
    ph_borne = c1.selectbox(
        "Borne pH évaluée",
        options=["max", "min"],
        format_func=lambda x: {
            "max": "Borne supérieure — alcalinisation (pH > 8,2 = dégradé)",
            "min": "Borne inférieure — acidification (pH < 6,5 = dégradé)",
        }[x],
        index=0,
        help="Choisissez selon la problématique de votre masse d'eau.",
    )
    cond_borne = c2.selectbox(
        "Borne conductivité évaluée",
        options=["max", "min"],
        format_func=lambda x: {
            "max": "Borne supérieure — minéralisation excessive (défaut)",
            "min": "Borne inférieure — eau trop douce",
        }[x],
        index=0,
    )
else:
    ph_borne, cond_borne = "max", "max"

# ── Bouton d'application ─────────────────────────────────────────────────────
st.markdown("---")
btn_label = "✅ Appliquer la configuration" if peut_configurer else "✅ Appliquer avec les valeurs par défaut"

if st.button(btn_label, type="primary", use_container_width=True, disabled=(df_filtre is None)):
    with st.spinner("Application de la configuration en cours…"):
        try:
            # Appel M02 avec les vrais paramètres
            res = nettoyer_et_pivoter(
                df_filtre,
                df_familles=df_familles,
                seuil_pch_pct=seuil_pch,
                seuil_micropolluants_pct=seuil_micro,
                methode_censure=methode_censure,
                valeur_pivot=valeur_pivot,
                normalisation=normalisation,
            )

            # M07 : référentiel qualité
            df_ref    = fusionner_referentiels()
            df_seuils = selectionner_seuil_reference(
                df_ref, ph_borne=ph_borne, cond_borne=cond_borne
            )

            # Pivot classes de qualité (pour export Excel M03)
            pivot_classes, _ = calculer_classes_par_station(
                res["pivot"], df_ref,
                ph_borne=ph_borne, cond_borne=cond_borne,
            )

            # fam_map pour les analyses multivariées
            fam_map = {}
            if df_familles is not None and "CdParametre" in df_familles.columns:
                col_fam = next(
                    (c for c in df_familles.columns if "Groupe" in c or "Famille" in c or "famille" in c.lower()),
                    df_familles.columns[-1],
                )
                fam_map = dict(zip(
                    df_familles["CdParametre"].astype(int),
                    df_familles[col_fam],
                ))

            # Invalider les modules d'analyse en aval
            invalider_depuis_config()

            # Stocker en session_state
            st.session_state.update({
                "df_clean":            res["df_clean"],
                "df_stats":            res["df_stats"],
                "pivot":               res["pivot"],
                "pivot_norm":          res["pivot_norm"],
                "pivot_fam_norm":      res["pivot_fam_norm"],
                "pivot_classes":       pivot_classes,
                "lb_map":              res["lb_map"],
                "fam_map":             fam_map,
                "df_ref":              df_ref,
                "df_seuils":           df_seuils,
                "params_selectionnes": list(res["pivot_norm"].columns),
                "config_chargee":      True,
            })

            # Afficher les alertes M02
            for a in res.get("alertes", []):
                (st.error   if a.startswith("❌") else
                 st.warning if a.startswith("⚠️") else
                 st.info)(a)

            n_p = res["pivot_norm"].shape[1]
            n_s = res["pivot_norm"].shape[0]
            st.success(
                f"✅ Configuration appliquée — "
                f"**{n_p} paramètre(s)** × **{n_s} station(s)**. "
                "Passez aux onglets d'analyse."
            )
            st.rerun()

        except Exception as e:
            import traceback
            st.error(f"❌ Erreur : {e}")
            st.code(traceback.format_exc())

# ── Résumé si configuration active ───────────────────────────────────────────
if st.session_state.get("config_chargee"):
    st.markdown("---")
    st.markdown("### Configuration active")
    n_p  = len(st.session_state.get("params_selectionnes") or [])
    pn   = st.session_state.get("pivot_norm")
    n_s  = pn.shape[0] if pn is not None else "?"
    c1, c2, c3 = st.columns(3)
    c1.metric("Paramètres retenus", n_p)
    c2.metric("Stations",           n_s)
    c3.metric("Familles chargées",  "Oui" if df_familles is not None else "Non")
    st.markdown("➡️ Passez aux onglets d'analyse.")

st.markdown("---")
st.markdown(
    '<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>',
    unsafe_allow_html=True,
)
