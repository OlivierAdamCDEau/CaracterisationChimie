# 🌊 Caractérisation Qualité Eau

Outil d'analyse des chroniques de qualité physico-chimique des eaux de surface.  
Application Streamlit — accès restreint aux personnes autorisées.

---

## Fonctionnalités

| Module | Description |
|--------|-------------|
| 📂 Données | Import CSV NAIADES/Hub'Eau, filtres support/fraction/période |
| ⚙️ Configuration | Sélection paramètres, référentiels qualité DCE/SEQ-Eau |
| 🧪 Empreinte chimique | Profils normalisés, heatmaps, distances inter-stations |
| 📊 Analyses multivariées | ACP biplot, clustering, corrélations |
| 📈 Variabilité temporelle | Distributions, séries chronologiques, saisonnalité |
| 💧 Débit et chimie | Relations C-Q, comportements chimio-dynamiques |
| 📤 Export | Figures PNG/SVG, Excel, rapport PDF, bundle ZIP |

---

## Structure du projet

```
app.py                    # Point d'entrée Streamlit (accueil + authentification)
generate_config.py        # Script de génération des credentials (exécuter en local)
config.yaml               # Credentials hachés bcrypt (versionné, mots de passe illisibles)
requirements.txt
README.md
.gitignore
.streamlit/
  config.toml             # Thème et paramètres Streamlit
  secrets.toml            # ⚠️ NON versionné — clés sensibles (créer sur Streamlit Cloud)
modules/
  auth.py                 # Authentification et gestion des rôles
  session.py              # Gestion centralisée du session_state
  m01_import.py           # Import et filtrage des données NAIADES
  m02_nettoyage.py        # Nettoyage, pivot, normalisation
  m03_empreinte.py        # Empreinte chimique
  m04_multivar.py         # Analyses multivariées
  m05_variabilite.py      # Variabilité temporelle
  m06_cq.py               # Relation Concentration-Débit
  m07_referentiels.py     # Référentiels qualité DCE/SEQ-Eau
  m08_export.py           # Export figures, Excel, PDF, ZIP
pages/
  1_Données.py
  2_Configuration.py
  3_Empreinte_chimique.py
  4_Analyses_multivariees.py
  5_Variabilite_temporelle.py
  6_Débit_et_chimie.py
  7_Export.py
```

---

## Rôles et droits

| Action | Admin | Collaborateur | Client |
|--------|-------|---------------|--------|
| Charger données / lancer calculs | ✅ | ✅ | ✅ |
| Modifier la configuration | ✅ | ✅ | ❌ |
| Voir figures + exports | ✅ | ✅ | ✅ |
| Gérer les utilisateurs | ✅ | ❌ | ❌ |

---

## 🚀 Guide de déploiement pas-à-pas

### Étape 1 — Préparer votre machine locale

Installez Python 3.10+ et les dépendances :

```bash
pip install -r requirements.txt
```

### Étape 2 — Générer les credentials

Exécutez le script de génération des mots de passe hachés :

```bash
python3 generate_config.py
```

Cela crée (ou met à jour) `config.yaml` avec les mots de passe bcrypt.  
Vérifiez que les identifiants et mots de passe dans `generate_config.py` sont corrects avant de lancer.

> ⚠️ Ne modifiez jamais `config.yaml` manuellement — les hashes bcrypt doivent être générés par le script.

### Étape 3 — Tester en local

```bash
streamlit run app.py
```

Ouvrez http://localhost:8501 et testez la connexion avec les trois comptes.

### Étape 4 — Créer le dépôt GitHub (repo privé)

1. Connectez-vous sur [github.com](https://github.com)
2. Cliquez sur **"New repository"** (bouton vert en haut à droite)
3. Donnez un nom au repo, ex. `analyse-qualite-eau`
4. **Sélectionnez "Private"** (important — code non public)
5. Laissez les autres options par défaut et cliquez **"Create repository"**

### Étape 5 — Envoyer le code sur GitHub

Dans votre terminal, depuis le dossier du projet :

```bash
# Initialiser Git (si pas déjà fait)
git init

# Ajouter les fichiers (le .gitignore exclut automatiquement secrets.toml)
git add .

# Vérifier ce qui va être envoyé (secrets.toml NE doit PAS apparaître)
git status

# Premier commit
git commit -m "Initial commit — Analyse Qualité Eau"

# Lier à votre repo GitHub (remplacer VOTRE_USERNAME et VOTRE_REPO)
git remote add origin https://github.com/VOTRE_USERNAME/VOTRE_REPO.git

# Envoyer
git branch -M main
git push -u origin main
```

> Si Git vous demande vos identifiants GitHub, entrez votre email et un **token d'accès**  
> (pas votre mot de passe). Créez-en un sur GitHub → Settings → Developer settings → Personal access tokens.

### Étape 6 — Déployer sur Streamlit Community Cloud

1. Allez sur [share.streamlit.io](https://share.streamlit.io)
2. Connectez-vous avec votre compte GitHub
3. Cliquez **"New app"**
4. Sélectionnez :
   - **Repository** : `VOTRE_USERNAME/VOTRE_REPO`
   - **Branch** : `main`
   - **Main file path** : `app.py`
5. Cliquez **"Deploy!"**

### Étape 7 — Configurer les secrets sur Streamlit Cloud

Une fois l'app déployée, configurez les secrets (ne jamais mettre dans le repo) :

1. Dans votre app Streamlit Cloud, cliquez **"Settings"** (roue dentée)
2. Cliquez sur l'onglet **"Secrets"**
3. Collez le contenu suivant (en remplaçant la clé si souhaité) :

```toml
# secrets.toml — à coller dans Streamlit Cloud > Settings > Secrets
# NE PAS mettre dans le repo GitHub

[general]
app_name = "Analyse Qualité Eau"
```

> Note : la clé de cookie est déjà dans `config.yaml` (versionné).  
> Les secrets Streamlit servent pour des clés API externes si besoin.

### Étape 8 — Restreindre l'accès à l'app

Sur Streamlit Community Cloud, l'authentification est gérée par `streamlit-authenticator`  
(widget de login dans l'app elle-même). Pour une sécurité renforcée :

1. Dans les Settings de votre app → onglet **"Sharing"**
2. Sélectionnez **"Only specific people can view this app"**
3. Ajoutez les emails des personnes autorisées

Ainsi, même si quelqu'un connaît l'URL, il devra d'abord être invité **ET** connaître  
les identifiants/mots de passe de l'application.

---

## Mettre à jour l'application

Pour déployer une mise à jour après modification du code :

```bash
git add .
git commit -m "Description de la modification"
git push
```

Streamlit Cloud redéploie automatiquement dans les minutes qui suivent.

---

## Changer un mot de passe

1. Modifiez le mot de passe dans `generate_config.py`
2. Exécutez `python3 generate_config.py`
3. Committez et pushez `config.yaml` mis à jour :
   ```bash
   git add config.yaml
   git commit -m "Mise à jour credentials"
   git push
   ```

---

## Données attendues

Fichier CSV au format **NAIADES / Hub'Eau** (export standard).  
Encodage : latin-1. Séparateur : `;`.

Colonnes obligatoires :
- `CdStationMesureEauxSurface`, `LbStationMesureEauxSurface`
- `CdParametre`, `LbLongParamètre`
- `DatePrel`, `RsAna`, `LqAna`, `CdRqAna`
- `CdSupport`, `CdFractionAnalysee`

Fichier familles (optionnel) : colonnes `CdParametre`, `NomGroupeParametres`.

---

*Produit par @CDEau*
