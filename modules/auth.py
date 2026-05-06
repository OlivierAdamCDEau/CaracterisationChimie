"""
modules/auth.py — Authentification streamlit-authenticator 0.4.x
"""
import yaml, streamlit as st
from pathlib import Path

DROITS = {
    "admin":         {"config":True,  "calculs":True,  "figures":True,  "export":True,  "credentials":True},
    "collaborateur": {"config":True,  "calculs":True,  "figures":True,  "export":True,  "credentials":False},
    "client":        {"config":False, "calculs":True,  "figures":True,  "export":True,  "credentials":False},
}
ROLE_LABELS = {
    "admin":         "👑 Administrateur",
    "collaborateur": "🔧 Collaborateur",
    "client":        "👁️ Client",
}

def _charger_config() -> dict:
    for chemin in [
        Path(__file__).parent.parent / "config.yaml",
        Path("config.yaml"),
    ]:
        if chemin.exists():
            with open(chemin, encoding="utf-8") as f:
                return yaml.safe_load(f)
    st.error("❌ config.yaml introuvable. Exécutez : python generate_config.py")
    st.stop()


def verifier_auth() -> tuple[bool, str, str]:
    """
    Gère l'authentification avec streamlit-authenticator 0.4.x.
    Retourne (authentifie, username, role).
    """
    import streamlit_authenticator as stauth

    config = _charger_config()

    # En 0.4.x, Authenticate prend directement le dict credentials
    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    # Stocker pour le bouton logout
    st.session_state["_authenticator"] = authenticator

    # En 0.4.x, login() retourne directement le statut via session_state
    # et affiche le widget. On appelle login() sans récupérer de valeur de retour.
    try:
        # API 0.4.x : login retourne None, résultats dans session_state
        authenticator.login(
            location="main",
            fields={
                "Form name":  "🌊 Qualité Eau — Connexion",
                "Username":   "Identifiant",
                "Password":   "Mot de passe",
                "Login":      "Se connecter",
            },
        )
    except TypeError:
        # Fallback si l'API ne supporte pas fields=
        authenticator.login(location="main")

    # Lire les résultats depuis session_state (convention 0.4.x)
    auth_status = st.session_state.get("authentication_status")
    username    = st.session_state.get("username", "")
    name        = st.session_state.get("name", "")

    if auth_status is False:
        st.error("❌ Identifiant ou mot de passe incorrect.")
        return False, "", ""

    if auth_status is None:
        # Widget affiché, en attente de saisie
        return False, "", ""

    # Authentifié — récupérer le rôle depuis config.yaml
    role = (
        config["credentials"]["usernames"]
        .get(username, {})
        .get("role", "client")
    )
    st.session_state["role"]      = role
    st.session_state["user_name"] = name

    return True, username, role


def get_role() -> str:
    return st.session_state.get("role", "client")


def get_username() -> str:
    return st.session_state.get("username", "")


def afficher_bandeau_utilisateur():
    """Bandeau utilisateur dans la sidebar avec bouton de déconnexion."""
    role = get_role()
    name = st.session_state.get("user_name", get_username())

    with st.sidebar:
        st.markdown("---")
        role_emoji = {"admin": "👑", "collaborateur": "🔧", "client": "👁️"}.get(role, "👤")
        st.markdown(
            f"<div style='padding:8px 12px;background:#dbeafe;border-radius:6px;"
            f"margin-bottom:6px;'>"
            f"<b style='color:#1e3a5f;'>{role_emoji} {name}</b><br>"
            f"<span style='color:#2563eb;font-size:0.82em;'>{ROLE_LABELS.get(role, role)}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        auth = st.session_state.get("_authenticator")
        if auth:
            try:
                auth.logout("🚪 Déconnexion", location="sidebar")
            except Exception:
                if st.sidebar.button("🚪 Déconnexion"):
                    for k in ["authentication_status","username","name","role","user_name","_authenticator"]:
                        st.session_state.pop(k, None)
                    st.rerun()
        st.markdown("---")


def verifier_droit(droit: str) -> bool:
    return DROITS.get(get_role(), {}).get(droit, False)


def exiger_droit(droit: str, message: str = ""):
    if not verifier_droit(droit):
        st.warning(message or
            f"⛔ Rôle {ROLE_LABELS.get(get_role(), get_role())} : action non autorisée.")
        st.stop()
