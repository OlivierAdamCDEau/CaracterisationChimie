"""
pages/2_Configuration.py — Configuration de l'analyse
"""
import streamlit as st, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
st.set_page_config(page_title="Configuration", page_icon="⚙️", layout="wide")
from modules.auth import verifier_auth, afficher_bandeau_utilisateur, verifier_droit
from modules.session import init_session, invalider_depuis_config, statut_donnees, statut_config, afficher_bandeau_statut
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
if not peut_configurer:
    st.warning("⛔ Rôle Client : configuration en lecture seule. Les valeurs par défaut s'appliquent.")

try:
    from modules.m02_nettoyage import nettoyer_et_pivoter
    from modules.m07_referentiels import fusionner_referentiels, selectionner_seuil_reference, calculer_classes_par_station
except ImportError as e:
    st.error(f"❌ Module introuvable : {e}"); st.stop()

df_filtre = st.session_state.get("df_filtre")

# ── Fichier familles ──────────────────────────────────────────────────────────
st.markdown("### 1. Fichier de familles SANDRE (optionnel)")
uploaded_familles = st.file_uploader("Fichier familles CSV", type=["csv"], key="upload_familles")
df_familles = st.session_state.get("df_familles")

if uploaded_familles and peut_configurer:
    try:
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="wb") as tmp:
            tmp.write(uploaded_familles.getvalue()); tmp_path = tmp.name
        def corriger(s):
            if not isinstance(s, str): return s
            try: return s.encode('latin-1').decode('utf-8')
            except: return s
        df_fam = pd.read_csv(tmp_path, sep=None, engine='python', encoding='latin-1')
        df_fam['CdParametre'] = pd.to_numeric(df_fam['CdParametre'], errors='coerce')
        for col in df_fam.columns:
            if df_fam[col].dtype == object: df_fam[col] = df_fam[col].apply(corriger)
        os.unlink(tmp_path)
        st.session_state["df_familles"] = df_fam; df_familles = df_fam
        st.success(f"✅ {len(df_fam)} familles chargées.")
    except Exception as e:
        st.error(f"❌ {e}")

# ── Options nettoyage ─────────────────────────────────────────────────────────
st.markdown("### 2. Options de nettoyage")
if peut_configurer:
    c1, c2, c3 = st.columns(3)
    n_min = c1.number_input("N min mesures", 1, 50, 3)
    taux_max = c2.slider("Taux censure max (%)", 0, 100, 80, 5)
    methode_lq = c3.selectbox("Traitement < LQ", ["lq_demi","lq","zero"],
        format_func=lambda x: {"lq_demi":"LQ/2 (recommandé)","lq":"LQ","zero":"0"}[x])
else:
    n_min, taux_max, methode_lq = 3, 80, "lq_demi"
    st.info("Valeurs par défaut : N≥3, censure≤80%, LQ/2.")

# ── Référentiel ───────────────────────────────────────────────────────────────
st.markdown("### 3. Référentiel de qualité")
if peut_configurer:
    c1, c2 = st.columns(2)
    ph_borne   = c1.selectbox("Borne pH", ["max","min"], format_func=lambda x: {"max":"Maximum (défaut)","min":"Minimum"}[x])
    cond_borne = c2.selectbox("Borne conductivité", ["max","min"], format_func=lambda x: {"max":"Maximum (défaut)","min":"Minimum"}[x])
else:
    ph_borne = cond_borne = "max"

# ── Application ───────────────────────────────────────────────────────────────
st.markdown("---")
if st.button("✅ Appliquer la configuration", type="primary", use_container_width=True, disabled=(df_filtre is None)):
    with st.spinner("Application en cours…"):
        try:
            res = nettoyer_et_pivoter(df_filtre, df_familles=df_familles,
                n_min_mesures=n_min, taux_censure_max=taux_max, methode_lq=methode_lq)
            df_ref    = fusionner_referentiels()
            df_seuils = selectionner_seuil_reference(df_ref, ph_borne=ph_borne, cond_borne=cond_borne)
            pivot_classes, _ = calculer_classes_par_station(res["pivot"], df_ref)
            fam_map = {}
            if df_familles is not None:
                fam_map = dict(zip(df_familles["CdParametre"].astype(int), df_familles["NomGroupeParametres"]))
            invalider_depuis_config()
            st.session_state.update({
                "df_clean": res["df_clean"], "df_stats": res["df_stats"],
                "pivot": res["pivot"], "pivot_norm": res["pivot_norm"],
                "pivot_fam_norm": res["pivot_fam_norm"], "pivot_classes": pivot_classes,
                "lb_map": res["lb_map"], "fam_map": fam_map,
                "df_ref": df_ref, "df_seuils": df_seuils,
                "params_selectionnes": list(res["pivot_norm"].columns),
                "config_chargee": True,
            })
            for a in res.get("alertes", []):
                (st.error if a.startswith("❌") else st.warning if a.startswith("⚠️") else st.info)(a)
            n_p, n_s = res["pivot_norm"].shape[1], res["pivot_norm"].shape[0]
            st.success(f"✅ {n_p} paramètre(s) × {n_s} station(s). Analyses disponibles.")
            st.rerun()
        except Exception as e:
            import traceback; st.error(f"❌ {e}"); st.code(traceback.format_exc())

if st.session_state.get("config_chargee"):
    st.markdown("---")
    st.markdown("### Configuration active")
    n_p = len(st.session_state.get("params_selectionnes") or [])
    pn  = st.session_state.get("pivot_norm")
    c1, c2 = st.columns(2)
    c1.metric("Paramètres", n_p)
    c2.metric("Stations", pn.shape[0] if pn is not None else "?")
    st.markdown("➡️ Passez aux onglets d'analyse.")

st.markdown("---")
st.markdown('<div style="text-align:right;color:#999;font-size:0.8em;">@CDEau</div>', unsafe_allow_html=True)
