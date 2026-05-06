"""
generate_config.py — Génère config.yaml pour streamlit-authenticator 0.4.x
"""
import yaml, bcrypt

USERS = {
    "admin": {
        "email":    "admin@cdeaux.fr",
        "name":     "Administrateur",
        "role":     "admin",
        "password": "Olivier",
    },
    "collaborateur": {
        "email":    "collaborateur@cdeaux.fr",
        "name":     "Collaborateur",
        "role":     "collaborateur",
        "password": "CDEau",
    },
    "client": {
        "email":    "client@cdeaux.fr",
        "name":     "Client",
        "role":     "client",
        "password": "CDEau",
    },
}

credentials = {"usernames": {}}
for username, info in USERS.items():
    hashed = bcrypt.hashpw(info["password"].encode(), bcrypt.gensalt()).decode()
    credentials["usernames"][username] = {
        "email":    info["email"],
        "name":     info["name"],
        "role":     info["role"],
        "password": hashed,
        "logged_in": False,   # requis par 0.4.x
    }
    print(f"✅ {username}")

config = {
    "credentials": credentials,
    "cookie": {
        "expiry_days": 1,
        "key":  "cdeaux_chimie_globale_2024",
        "name": "cdeaux_auth_cookie",
    },
    "pre-authorized": {"emails": []},  # clé avec tiret en 0.4.x
}

with open("config.yaml", "w", encoding="utf-8") as f:
    yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

print("\n✅ config.yaml généré (format 0.4.x).")
