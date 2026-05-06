"""modules/session.py — Gestion centralisée du session_state"""
import streamlit as st

ETAT_DEFAUT = {
    "df_filtre":None,"df_debit":None,"lb_stations":None,"inventaire_stations":None,
    "meta_fichier":None,"donnees_chargees":False,
    "df_clean":None,"df_stats":None,"pivot":None,"pivot_norm":None,
    "pivot_fam_norm":None,"pivot_classes":None,"lb_map":None,"fam_map":None,
    "df_ref":None,"df_seuils":None,"df_familles":None,"params_selectionnes":None,
    "config_chargee":False,
    "figs_m03":None,"m03_calcule":False,
    "figs_m04":None,"scores_acp":None,"loadings_acp":None,"matrice_dist":None,"m04_calcule":False,
    "figs_m05":None,"m05_calcule":False,
    "figs_m06":None,"df_cq":None,"df_reg_cq":None,"m06_calcule":False,
    "exports_generes":None,
}

def init_session():
    for k,v in ETAT_DEFAUT.items():
        if k not in st.session_state: st.session_state[k]=v

def invalider_depuis_donnees():
    cles = [k for k in ETAT_DEFAUT if k not in ("donnees_chargees","df_filtre","df_debit","lb_stations","inventaire_stations","meta_fichier")]
    for k in cles: st.session_state[k]=ETAT_DEFAUT[k]

def invalider_depuis_config():
    cles=["figs_m03","m03_calcule","figs_m04","scores_acp","loadings_acp","matrice_dist",
          "m04_calcule","figs_m05","m05_calcule","figs_m06","df_cq","df_reg_cq","m06_calcule","exports_generes"]
    for k in cles: st.session_state[k]=ETAT_DEFAUT[k]

def statut_donnees():
    if not st.session_state.get("donnees_chargees"): return "🔒","Données non chargées"
    meta=st.session_state.get("meta_fichier",{})
    return "✅",f"{meta.get('n_stations','?')} station(s) — {meta.get('periode','')}"

def statut_config():
    if not st.session_state.get("donnees_chargees"): return "🔒","Charger les données d'abord"
    if not st.session_state.get("config_chargee"):   return "⚠️","Configuration non appliquée"
    n=len(st.session_state.get("params_selectionnes") or [])
    return "✅",f"{n} paramètre(s)"

def statut_module(cle_calcule, nom):
    if not st.session_state.get("donnees_chargees"): return "🔒","Charger les données d'abord"
    if not st.session_state.get("config_chargee"):   return "🔒","Appliquer la configuration d'abord"
    if not st.session_state.get(cle_calcule):        return "⚠️",f"{nom} non calculé"
    return "✅",f"{nom} calculé"

def afficher_bandeau_statut(emoji, message):
    couleurs={"✅":("#bbf7d0","#166534"),"⚠️":("#fef9c3","#854d0e"),"🔒":("#fee2e2","#991b1b")}
    bg,fg=couleurs.get(emoji,("#f0f7ff","#1e3a5f"))
    st.markdown(f'<div style="background:{bg};color:{fg};padding:8px 14px;border-radius:6px;'
                f'font-size:0.9em;margin-bottom:12px;">{emoji} {message}</div>',
                unsafe_allow_html=True)
