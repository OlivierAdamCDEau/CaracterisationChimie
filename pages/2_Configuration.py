"""
pages/2_Configuration.py — Configuration de l'analyse (M02 + M07)
Rôle client : peut valider avec les valeurs par défaut sans modifier les options.
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

emoji_d, msg_d = statut_donnees()
afficher_bandeau_statut(emoji_d, f"Données : {msg_d}")
if emoji_d == "🔒":
    st.info("➡️ Chargez d'abord les données dans l'onglet **Données**.")
    st.stop()

afficher_bandeau_statut(*statut_config())

peut_configurer = verifier_droit("config")

# ── Message rôle client ───────────────────────────────────────────────────────
if not peut_configurer:
    st.info(
        "👁️ **Rôle Client** — Les options de configuration sont gérées par @CDEau. "
        "Cliquez sur **Appliquer les paramètres par défaut** pour accéder aux analyses."
    )

try:
    from modules.m02_nettoyage import nettoyer_et_pivoter
    from modules.m07_referentiels import (
        fusionner_referentiels, selectionner_seuil_reference, calculer_classes_par_station,
    )
except ImportError as e:
    st.error(f"❌ Module introuvable : {e}"); st.stop()

df_filtre   = st.session_state.get("df_filtre")
df_familles = st.session_state.get("df_familles")

# ── Section 1 : Fichier familles (collaborateur/admin uniquement) ─────────────
if peut_configurer:
    st.markdown("### 1. Fichier de familles SANDRE (optionnel)")
    st.markdown("Fichier CSV `CdParametre` → `NomGroupeParametres`.")
    uploaded_familles = st.file_uploader(
        "Fichier familles CSV", type=["csv"], key="upload_familles",
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
            st.error(f"❌ {e}")

# ── Section 2 : Options de nettoyage (collaborateur/admin uniquement) ─────────
if peut_configurer:
    st.markdown("### 2. Options de nettoyage")
    c1, c2, c3 = st.columns(3)
    seuil_pch = c1.slider(
        "Taux de renseignement min — PCH (%)", 5, 80, 30, 5,
        help="Taux minimum de stations où le paramètre PCH doit être détecté. Défaut : 30 %.",
    )
    seuil_micro = c2.slider(
        "Taux de renseignement min — Micropolluants (%)", 1, 30, 10, 1,
        help="Même critère pour les micropolluants, naturellement plus rarement détectés. Défaut : 10 %.",
    )
    methode_censure = c3.selectbox(
        "Traitement des valeurs < LQ",
        options=["LQ/2", "LQ", "0"], index=0,
        help="LQ/2 : convention DCE recommandée.",
    )

    st.markdown("### 3. Statistique et normalisation")
    c1, c2 = st.columns(2)
    valeur_pivot = c1.selectbox(
        "Statistique pivot", ["Mediane","P90","Moyenne","P10"], index=0,
        help="Statistique pour le tableau station × paramètre. Médiane recommandée.",
    )
    normalisation = c2.selectbox(
        "Normalisation", ["log_zscore","zscore","minmax"], index=0,
        format_func=lambda x: {"log_zscore":"Log + Z-score (recommandé)","zscore":"Z-score","minmax":"Min-Max"}[x],
    )

    st.markdown("### 4. Référentiel de qualité")
    c1, c2 = st.columns(2)
    ph_borne = c1.selectbox(
        "Borne pH", ["max","min"],
        format_func=lambda x: {"max":"Supérieure — alcalinisation","min":"Inférieure — acidification"}[x],
    )
    cond_borne = c2.selectbox(
        "Borne conductivité", ["max","min"],
        format_func=lambda x: {"max":"Supérieure — minéralisation (défaut)","min":"Inférieure — eau trop douce"}[x],
    )
else:
    # Valeurs par défaut silencieuses pour le client
    seuil_pch, seuil_micro, methode_censure = 30, 10, "LQ/2"
    valeur_pivot, normalisation = "Mediane", "log_zscore"
    ph_borne, cond_borne = "max", "max"

# ── Bouton ────────────────────────────────────────────────────────────────────
st.markdown("---")
btn_label = (
    "✅ Appliquer la configuration"
    if peut_configurer else
    "✅ Appliquer les paramètres par défaut et accéder aux analyses"
)

if st.button(btn_label, type="primary", use_container_width=True, disabled=(df_filtre is None)):
    with st.spinner("Application en cours…"):
        try:
            res = nettoyer_et_pivoter(
                df_filtre,
                df_familles=df_familles,
                seuil_pch_pct=seuil_pch,
                seuil_micropolluants_pct=seuil_micro,
                methode_censure=methode_censure,
                valeur_pivot=valeur_pivot,
                normalisation=normalisation,
            )
            df_ref    = fusionner_referentiels()
            df_seuils = selectionner_seuil_reference(df_ref, ph_borne=ph_borne, cond_borne=cond_borne)
            pivot_classes, _ = calculer_classes_par_station(res["pivot"], df_ref, ph_borne=ph_borne, cond_borne=cond_borne)

            fam_map = {}
            if df_familles is not None and "CdParametre" in df_familles.columns:
                col_fam = next(
                    (c for c in df_familles.columns if any(k in c.lower() for k in ["groupe","famille","nom"])),
                    df_familles.columns[-1],
                )
                fam_map = {
                    int(k): str(v) for k, v in
                    zip(df_familles["CdParametre"], df_familles[col_fam])
                    if pd.notna(k) and pd.notna(v)
                }

            invalider_depuis_config()
            st.session_state.update({
                "df_clean": res["df_clean"], "df_stats": res["df_stats"],
                "pivot": res["pivot"], "pivot_norm": res["pivot_norm"],
                "pivot_norm_raw": res.get("pivot_norm_raw", res["pivot_norm"]),
                "pivot_fam_norm": res["pivot_fam_norm"], "pivot_classes": pivot_classes,
                "lb_map": res["lb_map"], "fam_map": fam_map,
                "df_ref": df_ref, "df_seuils": df_seuils,
                "params_selectionnes": list(res["pivot_norm"].columns),
                "config_chargee": True,
            })
            for a in res.get("alertes", []):
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)
            n_p, n_s = res["pivot_norm"].shape[1], res["pivot_norm"].shape[0]
            st.success(f"✅ {n_p} paramètre(s) × {n_s} station(s). Passez aux onglets d'analyse.")
            st.rerun()
        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

if st.session_state.get("config_chargee"):
    st.markdown("---")
    n_p = len(st.session_state.get("params_selectionnes") or [])
    pn  = st.session_state.get("pivot_norm")
    c1, c2, c3 = st.columns(3)
    c1.metric("Paramètres", n_p)
    c2.metric("Stations", pn.shape[0] if pn is not None else "?")
    c3.metric("Familles", "Oui" if df_familles is not None else "Non")
    st.markdown("➡️ Passez aux onglets d'analyse.")

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>', unsafe_allow_html=True)
