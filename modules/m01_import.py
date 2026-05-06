"""
Module 01 — Import & Filtres
=============================
Lecture d'une BDD au format SANDRE/Naïades (CSV ; séparateur ';' ; encodage latin-1).
Filtres : support, fraction analysée, période, stations.
Détection automatique du débit (CdParametre 1420).
Sortie : DataFrame nettoyé prêt pour le Module 02.

Compatible Streamlit : toutes les fonctions retournent des objets Python,
aucun appel à st.* ici.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constantes SANDRE
# ---------------------------------------------------------------------------

# Code paramètre débit instantané
CD_DEBIT = 1420

# Fractions par défaut préconisées DCE selon le support
FRACTIONS_DCE_DEFAUT = {
    3:  [23],         # Eau  → Eau brute (23)
    6:  [32],         # Sédiments → Particules < 2 mm (32)
    81: [284],        # Gammares → Gammare entier (284)
}

# Libellés des codes de remarque analytique (CdRqAna)
REMARQUES_ANA = {
    1:  "Valeur quantifiée",
    2:  "Valeur non quantifiée (<LQ)",
    3:  "Valeur non détectée (<LD)",
    7:  "Valeur > seuil de saturation",
    10: "Résultat < au seuil de quantification",
    # Ajout au besoin selon les exports Naïades
}

# Colonnes minimales attendues dans le CSV SANDRE
COLONNES_OBLIGATOIRES = [
    "CdStationMesureEauxSurface",
    "LbStationMesureEauxSurface",
    "CdSupport",
    "LbSupport",
    "CdFractionAnalysee",
    "LbFractionAnalysee",
    "DatePrel",
    "CdParametre",
    "LbLongParamètre",
    "RsAna",
    "SymUniteMesure",
    "CdRqAna",
    "LqAna",
]

# ---------------------------------------------------------------------------
# 1. Lecture du fichier brut
# ---------------------------------------------------------------------------

def lire_bdd_sandre(
    chemin: str | Path,
    encodage: str = "latin-1",
    separateur: str = ";",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Lit un CSV SANDRE/Naïades et renvoie (DataFrame brut, liste d'alertes).

    Parameters
    ----------
    chemin : chemin vers le CSV
    encodage : encodage du fichier (défaut : latin-1)
    separateur : séparateur de colonnes (défaut : ;)

    Returns
    -------
    df : DataFrame brut avec colonnes typées
    alertes : liste de messages d'avertissement (colonnes manquantes, etc.)
    """
    alertes = []

    df = pd.read_csv(
        chemin,
        sep=separateur,
        encoding=encodage,
        dtype=str,          # tout en str pour éviter les surprises
        low_memory=False,
    )

    # Vérification des colonnes obligatoires
    manquantes = [c for c in COLONNES_OBLIGATOIRES if c not in df.columns]
    if manquantes:
        alertes.append(
            f"⚠️ Colonnes manquantes dans le fichier : {', '.join(manquantes)}"
        )

    # Typage des colonnes numériques clés
    for col in ["CdSupport", "CdFractionAnalysee", "CdParametre", "CdRqAna"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Conversion date
    if "DatePrel" in df.columns:
        df["DatePrel"] = pd.to_datetime(df["DatePrel"], dayfirst=True, errors="coerce")
        nb_nulls = df["DatePrel"].isna().sum()
        if nb_nulls > 0:
            alertes.append(f"⚠️ {nb_nulls} date(s) de prélèvement non parsées (ignorées).")

    # Conversion résultat analytique (virgule → point)
    for col in ["RsAna", "LqAna", "LdAna"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .str.replace(",", ".", regex=False)
                .pipe(pd.to_numeric, errors="coerce")
            )

    # Statistiques rapides pour info
    nb_lignes = len(df)
    nb_stations = df["CdStationMesureEauxSurface"].nunique() if "CdStationMesureEauxSurface" in df.columns else "?"
    nb_params = df["CdParametre"].nunique() if "CdParametre" in df.columns else "?"
    alertes.append(
        f"ℹ️ Fichier chargé : {nb_lignes:,} lignes | {nb_stations} stations | {nb_params} paramètres distincts"
    )

    return df, alertes


# ---------------------------------------------------------------------------
# 2. Inventaire des supports et fractions présents
# ---------------------------------------------------------------------------

def inventaire_supports_fractions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Retourne un tableau récapitulatif des supports et fractions présents
    dans la BDD, avec le nombre de mesures par combinaison.

    Utile pour alimenter les widgets de sélection dans Streamlit.
    """
    if "CdSupport" not in df.columns:
        return pd.DataFrame()

    grp = (
        df.groupby(
            ["CdSupport", "LbSupport", "CdFractionAnalysee", "LbFractionAnalysee"],
            dropna=False,
        )
        .size()
        .reset_index(name="NbMesures")
        .sort_values(["CdSupport", "CdFractionAnalysee"])
    )
    return grp


# ---------------------------------------------------------------------------
# 3. Filtre support / fraction
# ---------------------------------------------------------------------------

def filtrer_support_fraction(
    df: pd.DataFrame,
    cd_support: int,
    cd_fractions: Optional[list[int]] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Filtre le DataFrame sur un support donné et une liste de fractions.

    Parameters
    ----------
    df : DataFrame SANDRE brut
    cd_support : code support à retenir (3=Eau, 6=Sédiments, 81=Gammares…)
    cd_fractions : liste de codes fraction à retenir.
                   Si None → utilise la fraction DCE par défaut pour ce support.
                   Si la fraction DCE est absente du fichier, toutes les fractions
                   du support sont proposées avec un avertissement.

    Returns
    -------
    df_filtre : DataFrame filtré
    alertes : liste de messages
    """
    alertes = []

    df_support = df[df["CdSupport"] == cd_support].copy()

    if df_support.empty:
        alertes.append(f"⚠️ Aucune donnée pour le support {cd_support}.")
        return df_support, alertes

    fractions_dispo = df_support["CdFractionAnalysee"].dropna().unique().tolist()

    if cd_fractions is None:
        # Fractions DCE par défaut
        fractions_defaut = FRACTIONS_DCE_DEFAUT.get(cd_support, [])
        fractions_ok = [f for f in fractions_defaut if f in fractions_dispo]

        if fractions_ok:
            cd_fractions = fractions_ok
            alertes.append(
                f"ℹ️ Fraction(s) DCE par défaut retenue(s) pour support {cd_support} : {fractions_ok}"
            )
        else:
            # La fraction DCE n'est pas présente → on garde tout et on avertit
            cd_fractions = fractions_dispo
            alertes.append(
                f"⚠️ Fraction DCE par défaut absente pour support {cd_support}. "
                f"Fractions disponibles : {fractions_dispo}. Toutes retenues."
            )
    else:
        # Vérifier que les fractions demandées existent
        absentes = [f for f in cd_fractions if f not in fractions_dispo]
        if absentes:
            alertes.append(
                f"⚠️ Fraction(s) demandée(s) absentes du fichier : {absentes}. "
                f"Fractions disponibles : {fractions_dispo}."
            )
        cd_fractions = [f for f in cd_fractions if f in fractions_dispo]

    if not cd_fractions:
        alertes.append("❌ Aucune fraction valide après filtrage.")
        return pd.DataFrame(), alertes

    df_filtre = df_support[df_support["CdFractionAnalysee"].isin(cd_fractions)].copy()
    alertes.append(
        f"ℹ️ Après filtre support/fraction : {len(df_filtre):,} lignes conservées."
    )
    return df_filtre, alertes


# ---------------------------------------------------------------------------
# 4. Filtre stations
# ---------------------------------------------------------------------------

def filtrer_stations(
    df: pd.DataFrame,
    codes_stations: Optional[list] = None,
) -> pd.DataFrame:
    """
    Filtre sur une liste de codes station.
    Si codes_stations est None ou vide, retourne toutes les stations.
    """
    if not codes_stations:
        return df.copy()
    return df[df["CdStationMesureEauxSurface"].isin([str(c) for c in codes_stations])].copy()


# ---------------------------------------------------------------------------
# 5. Filtre période
# ---------------------------------------------------------------------------

def filtrer_periode(
    df: pd.DataFrame,
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Filtre sur une période (dates au format 'YYYY-MM-DD' ou 'DD/MM/YYYY').
    Si les deux sont None, pas de filtre.
    """
    alertes = []
    df = df.copy()

    if "DatePrel" not in df.columns:
        alertes.append("⚠️ Colonne DatePrel absente — filtre période ignoré.")
        return df, alertes

    if date_debut:
        d_debut = pd.to_datetime(date_debut, dayfirst=True, errors="coerce")
        if pd.isna(d_debut):
            alertes.append(f"⚠️ Date début '{date_debut}' non reconnue — ignorée.")
        else:
            df = df[df["DatePrel"] >= d_debut]

    if date_fin:
        d_fin = pd.to_datetime(date_fin, dayfirst=True, errors="coerce")
        if pd.isna(d_fin):
            alertes.append(f"⚠️ Date fin '{date_fin}' non reconnue — ignorée.")
        else:
            df = df[df["DatePrel"] <= d_fin]

    alertes.append(
        f"ℹ️ Après filtre période : {len(df):,} lignes | "
        f"{df['DatePrel'].min().strftime('%d/%m/%Y') if not df.empty else '—'} "
        f"→ {df['DatePrel'].max().strftime('%d/%m/%Y') if not df.empty else '—'}"
    )
    return df, alertes


# ---------------------------------------------------------------------------
# 6. Détection et extraction du débit
# ---------------------------------------------------------------------------

def extraire_debit(df_brut: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Extrait les mesures de débit instantané (CdParametre = 1420) du DataFrame
    SANDRE brut (avant filtre support/fraction, car le débit est souvent
    sur le support Eau).

    Returns
    -------
    df_debit : DataFrame [CdStation, DatePrel, Debit_m3s] ou DataFrame vide
    alertes : messages d'info
    """
    alertes = []

    if "CdParametre" not in df_brut.columns:
        return pd.DataFrame(), ["⚠️ CdParametre absent — débit non extrait."]

    df_q = df_brut[df_brut["CdParametre"] == CD_DEBIT].copy()

    if df_q.empty:
        alertes.append(
            "ℹ️ Pas de débit instantané (code 1420) dans le fichier. "
            "L'axe C-Q ne sera pas disponible."
        )
        return pd.DataFrame(), alertes

    nb_stations_q = df_q["CdStationMesureEauxSurface"].nunique()
    alertes.append(
        f"ℹ️ Débit trouvé pour {nb_stations_q} station(s) | {len(df_q)} mesures."
    )

    df_debit = df_q[
        ["CdStationMesureEauxSurface", "LbStationMesureEauxSurface", "DatePrel", "RsAna"]
    ].copy()
    df_debit = df_debit.rename(columns={"RsAna": "Debit_m3s"})
    df_debit = df_debit.dropna(subset=["Debit_m3s"])

    # Avertir si stations sans débit
    if "CdStationMesureEauxSurface" in df_brut.columns:
        stations_totales = set(df_brut["CdStationMesureEauxSurface"].unique())
        stations_avec_debit = set(df_debit["CdStationMesureEauxSurface"].unique())
        sans_debit = stations_totales - stations_avec_debit
        if sans_debit:
            alertes.append(
                f"⚠️ Stations sans débit disponible : {len(sans_debit)} "
                f"(l'analyse C-Q sera partielle)."
            )

    return df_debit, alertes


# ---------------------------------------------------------------------------
# 7. Inventaire des stations avec leurs métadonnées
# ---------------------------------------------------------------------------

def inventaire_stations(df: pd.DataFrame) -> pd.DataFrame:
    """
    Retourne un tableau des stations présentes dans le DataFrame filtré :
    code, libellé, nombre de campagnes, plage de dates, liste des paramètres.
    """
    if df.empty or "CdStationMesureEauxSurface" not in df.columns:
        return pd.DataFrame()

    def _liste_params(grp):
        return grp["LbLongParamètre"].dropna().unique().tolist() if "LbLongParamètre" in grp.columns else []

    agg = (
        df.groupby(
            ["CdStationMesureEauxSurface", "LbStationMesureEauxSurface"],
            dropna=False,
        )
        .agg(
            NbMesures=("CdParametre", "count"),
            NbParametres=("CdParametre", "nunique"),
            NbCampagnes=("DatePrel", "nunique"),
            DateMin=("DatePrel", "min"),
            DateMax=("DatePrel", "max"),
        )
        .reset_index()
        .sort_values("CdStationMesureEauxSurface")
    )
    return agg


# ---------------------------------------------------------------------------
# 8. Fonction principale d'import (pipeline complet)
# ---------------------------------------------------------------------------

def importer_bdd(
    chemin: str | Path,
    cd_support: int,
    cd_fractions: Optional[list[int]] = None,
    codes_stations: Optional[list] = None,
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
) -> dict:
    """
    Pipeline complet d'import : lecture → filtre support/fraction →
    filtre stations → filtre période → extraction débit.

    Returns
    -------
    dict avec les clés :
        'df'          : DataFrame filtré principal (hors débit)
        'df_debit'    : DataFrame débit (peut être vide)
        'alertes'     : liste de tous les messages
        'inventaire_stations' : tableau récapitulatif des stations
        'inventaire_supports' : tableau supports/fractions disponibles
    """
    toutes_alertes = []

    # Lecture brute
    df_brut, alertes = lire_bdd_sandre(chemin)
    toutes_alertes.extend(alertes)

    # Inventaire complet des supports (avant filtre)
    inv_supports = inventaire_supports_fractions(df_brut)

    # Extraction débit (avant filtre support pour ne pas le perdre)
    df_debit, alertes = extraire_debit(df_brut)
    toutes_alertes.extend(alertes)

    # Filtre support / fraction
    df, alertes = filtrer_support_fraction(df_brut, cd_support, cd_fractions)
    toutes_alertes.extend(alertes)

    # Filtre stations
    df = filtrer_stations(df, codes_stations)

    # Filtre période
    df, alertes = filtrer_periode(df, date_debut, date_fin)
    toutes_alertes.extend(alertes)

    # Inventaire des stations après filtres
    inv_stations = inventaire_stations(df)

    return {
        "df": df,
        "df_debit": df_debit,
        "alertes": toutes_alertes,
        "inventaire_stations": inv_stations,
        "inventaire_supports": inv_supports,
    }


# ---------------------------------------------------------------------------
# Test rapide (à supprimer en production)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    chemin_test = sys.argv[1] if len(sys.argv) > 1 else None
    if chemin_test:
        resultat = importer_bdd(chemin_test, cd_support=3)
        for msg in resultat["alertes"]:
            print(msg)
        print("\n--- Inventaire stations ---")
        print(resultat["inventaire_stations"].to_string())
        print("\n--- Inventaire supports ---")
        print(resultat["inventaire_supports"].to_string())
        print("\n--- Aperçu données ---")
        print(resultat["df"].head())
        print("\n--- Aperçu débit ---")
        print(resultat["df_debit"].head())
