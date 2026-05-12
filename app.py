"""
app.py — Point d'entrée Streamlit
Analyse Chroniques Qualité Eau 🌊
Authentification 3 rôles : admin / collaborateur / client
"""
import streamlit as st
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

st.set_page_config(
    page_title="Qualité Eau — CDEau",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS global
st.markdown("""
<style>
    h1, h2, h3 { color: #1e3a5f; }
    footer { visibility: hidden; }
    [data-testid="stSidebarNav"] { font-size: 0.92em; }
</style>
""", unsafe_allow_html=True)

from modules.auth import verifier_auth, afficher_bandeau_utilisateur, ROLE_LABELS
from modules.session import init_session, statut_donnees, statut_config, statut_module

# Initialisation session
init_session()

# Authentification
auth_ok, username, role = verifier_auth()
if not auth_ok:
    # Afficher un écran de bienvenue sous le widget de login
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(
            "<h2 style='text-align:center;color:#2563eb;'>🌊 Qualité Eau — CDEau</h2>"
            "<p style='text-align:center;color:#6b7280;'>Application réservée aux personnes autorisées</p>",
            unsafe_allow_html=True,
        )
    st.stop()

# ── Bouton de rechargement d'urgence (affiché en cas de plantage) ─────────────
# Injecté via JavaScript : si l'app ne répond plus, un bouton flottant permet
# de recharger sans passer par le tableau de bord Streamlit Cloud.
st.markdown("""
<style>
#reload-btn {
    position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
    z-index: 9999; display: none;
    background: #dc2626; color: white; border: none; border-radius: 8px;
    padding: 10px 24px; font-size: 15px; font-weight: 600; cursor: pointer;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
</style>
<button id="reload-btn" onclick="window.location.reload(true)">
    🔄 Recharger l'app
</button>
<script>
// Affiche le bouton de rechargement si la page est bloquée > 30 secondes
// (absence de heartbeat Streamlit = app gelée)
(function() {
    var btn = document.getElementById('reload-btn');
    if (!btn) return;
    var timeout = setTimeout(function() {
        btn.style.display = 'block';
    }, 30000);
    // Annuler si Streamlit répond (mutation du DOM = app vivante)
    var obs = new MutationObserver(function() {
        clearTimeout(timeout);
        timeout = setTimeout(function() { btn.style.display = 'block'; }, 30000);
    });
    obs.observe(document.body, { childList: true, subtree: true });
})();
</script>
""", unsafe_allow_html=True)

# Bandeau utilisateur dans la sidebar
afficher_bandeau_utilisateur()

# Sidebar : indicateurs d'état
with st.sidebar:
    st.markdown("**État de la session**")
    for emoji, msg, label in [
        statut_donnees()                          + ("Données",),
        statut_config()                           + ("Configuration",),
        statut_module("m03_calcule", "M03")       + ("Empreinte",),
        statut_module("m04_calcule", "M04")       + ("Multivariée",),
        statut_module("m05_calcule", "M05")       + ("Variabilité",),
        statut_module("m06_calcule", "M06")       + ("C-Q",),
    ]:
        couleur = {"✅": "#16a34a", "⚠️": "#d97706", "🔒": "#9ca3af"}.get(emoji, "#9ca3af")
        st.markdown(
            f"<small style='color:{couleur};'>{emoji} {label}</small>",
            unsafe_allow_html=True,
        )
    st.markdown(
        "<p style='font-size:0.72em;color:#9ca3af;text-align:center;margin-top:16px;'>@CDEau</p>",
        unsafe_allow_html=True,
    )

# ── PAGE ACCUEIL ──────────────────────────────────────────────────────────────
name = st.session_state.get("user_name", username)
st.markdown(f"<h1>🌊 Analyse Chroniques Qualité Eau</h1>", unsafe_allow_html=True)
st.markdown(
    f"<p style='color:#6b7280;font-size:1.05em;'>"
    f"Bienvenue, <b>{name}</b> — {ROLE_LABELS.get(role, role)}</p>",
    unsafe_allow_html=True,
)
st.markdown("---")

# Séquence de travail
st.subheader("🗺️ Séquence de travail")

etapes = [
    ("1", "📂", "Données",               "Charger fichier CSV NAIADES",                        "donnees_chargees"),
    ("2", "⚙️", "Configuration",         "Paramètres, référentiels, normalisation",             "config_chargee"),
    ("3", "🧪", "Empreinte chimique",     "Profils radar, heatmaps, distances inter-stations",   "m03_calcule"),
    ("4", "📊", "Analyses multivariées",  "ACP biplot, dendrogramme, corrélations",              "m04_calcule"),
    ("5", "📈", "Variabilité temporelle", "Distributions, séries chronologiques, saisonnalité",  "m05_calcule"),
    ("6", "💧", "Débit et chimie",        "Relations C-Q, comportements chimio-dynamiques",      "m06_calcule"),
    ("7", "📥", "Export",                 "PNG/SVG, Excel, rapport PDF, bundle ZIP",             None),
]

cols = st.columns(len(etapes))
for col, (num, emoji, titre, desc, key) in zip(cols, etapes):
    done = bool(st.session_state.get(key)) if key else False
    bg   = "#dbeafe" if done else "#f8faff"
    bord = "#2563eb" if done else "#bfdbfe"
    ck   = "✅ " if done else ""
    col.markdown(
        f"<div style='background:{bg};border:1.5px solid {bord};border-radius:10px;"
        f"padding:12px 8px;text-align:center;min-height:120px;'>"
        f"<div style='font-size:1.4em;'>{emoji}</div>"
        f"<b style='color:#1e3a5f;font-size:0.85em;'>{ck}{num}. {titre}</b><br>"
        f"<span style='font-size:0.75em;color:#6b7280;'>{desc}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# Interdépendances
with st.expander("📌 Interdépendances entre onglets"):
    st.markdown("""
| Onglet | Requis avant de lancer |
|--------|------------------------|
| Configuration | Données chargées |
| Empreinte chimique | Données + Configuration |
| Analyses multivariées | Données + Configuration |
| Variabilité temporelle | Données + Configuration |
| Débit et chimie | Données + Configuration + source de débit |
| Export | Au moins un module calculé |

> ⚠️ Si vous rechargez un nouveau fichier dans **Données**, tous les résultats sont réinitialisés.
""")

# Résumé session si données chargées
if st.session_state.get("donnees_chargees"):
    meta = st.session_state.get("meta_fichier", {})
    with st.expander("📋 Résumé de la session", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Stations",   meta.get("n_stations", "?"))
        c2.metric("Paramètres", meta.get("n_params",   "?"))
        c3.metric("Lignes",     f"{meta.get('n_lignes', 0):,}")
        c4.metric("Période",    meta.get("periode",    "?"))

with st.expander("ℹ️ À propos"):
    st.markdown("""
**Modules :** M01 Import · M02 Nettoyage · M03 Empreinte · M04 Multivariée ·
M05 Variabilité · M06 C-Q · M07 Référentiels · M08 Export

**Données compatibles :** Export NAIADES / Hub'Eau (format SANDRE)

**Développé par :** @CDEau
""")
