"""
Module 01 — Import & Filtres (v2 multi-sources)
=================================================
Lecture de BDD au format SANDRE/Naïades, ADES, ARS (CAP) ou HB-Naïades
(résultats biologiques). Détection automatique du format source.
Normalisation vers un DataFrame commun avant filtres.

Formats supportés
-----------------
  "naiade"   — Export Naïades/Hub'Eau chimie (CSV ; encodage latin-1)
  "ades"     — Export ADES eaux souterraines (CSV ; encodage latin-1)
  "ars"      — Export ARS / CAP eau potable (CSV ; encodage latin-1)
  "hb"       — Export HB-Naïades biologiques (CSV ; encodage latin-1, BOM possible)

Colonnes du DataFrame normalisé (toutes les sources)
-----------------------------------------------------
  CdStationMesureEauxSurface  — code station (str)
  LbStationMesureEauxSurface  — libellé station (str)
  DatePrel                    — date prélèvement (datetime)
  CdParametre                 — code paramètre SANDRE (int/str)
  LbLongParamètre             — libellé paramètre (str)
  RsAna                       — résultat analytique (float)
  SymUniteMesure              — unité (str)
  CdRqAna                     — code remarque (1=quantifié, 2=<LQ, 3=<LD) (int)
  LqAna                       — limite de quantification (float, peut être NaN)
  CdSupport                   — code support (int, NaN si inconnu)
  LbSupport                   — libellé support (str)
  CdFractionAnalysee          — code fraction (int, NaN si inconnu)
  LbFractionAnalysee          — libellé fraction (str)
  _source                     — origine ('naiade','ades','ars','hb')

Compatible Streamlit : aucun appel à st.* dans ce module.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constantes SANDRE
# ---------------------------------------------------------------------------

CD_DEBIT = 1420          # code paramètre débit instantané

FRACTIONS_DCE_DEFAUT = {
    3:  [23],             # Eau  → Eau brute (23)
    6:  [32],             # Sédiments → Particules < 2 mm (32)
    81: [284],            # Gammares → Gammare entier (284)
}

REMARQUES_ANA = {
    1:  "Valeur quantifiée",
    2:  "Valeur non quantifiée (<LQ)",
    3:  "Valeur non détectée (<LD)",
    7:  "Valeur > seuil de saturation",
    10: "Résultat < au seuil de quantification",
}

# Colonnes obligatoires dans le DataFrame normalisé final
COLONNES_NORM = [
    "CdStationMesureEauxSurface",
    "LbStationMesureEauxSurface",
    "DatePrel",
    "CdParametre",
    "LbLongParamètre",
    "RsAna",
    "SymUniteMesure",
    "CdRqAna",
    "LqAna",
    "CdSupport",
    "LbSupport",
    "CdFractionAnalysee",
    "LbFractionAnalysee",
    "_source",
]

# Colonnes minimales spécifiques à chaque format (pour la détection)
_SIGNATURE = {
    "naiade": {"CdStationMesureEauxSurface", "CdRqAna", "LqAna", "CdFractionAnalysee"},
    "ades":   {"Identifiant national BSS", "Code remarque analyse", "Limite quantification"},
    "ars":    {"cdpointsurv", "rssigne", "cdparametre"},
    "hb":     {"CdParametreResultatBiologique", "ResIndiceResultatBiologique",
               "DateDebutOperationPrelBio"},
}

_EXCEL_ORIGIN = pd.Timestamp("1899-12-30")   # origine série Excel Windows


# ---------------------------------------------------------------------------
# 0. Utilitaires partagés
# ---------------------------------------------------------------------------

def _optimiser_memoire(df: pd.DataFrame) -> pd.DataFrame:
    """
    Réduit la consommation mémoire d'un DataFrame normalisé :
      1. Supprime toutes les colonnes hors COLONNES_NORM (inutiles en aval)
      2. Convertit les colonnes texte à faible cardinalité en 'category'
      3. Downcast les numériques float64→float32, int64→int32/int16

    Gain typique : 80-85 % sur un export Naïades brut.
    """
    # Garder uniquement les colonnes utiles en aval + _source
    cols_a_garder = [c for c in COLONNES_NORM if c in df.columns]
    extra = [c for c in df.columns if c not in COLONNES_NORM]
    if extra:
        df = df.drop(columns=extra)

    # Catégoriser les colonnes texte à faible cardinalité (< 30 % de valeurs uniques)
    n = max(len(df), 1)
    for col in list(df.columns):
        if col not in df.columns:
            continue
        dtype_str = str(df[col].dtype)
        if dtype_str in ('object', 'string', 'str'):
            try:
                if df[col].nunique() / n < 0.30:
                    df[col] = df[col].astype('category')
            except Exception:
                pass

    # Downcast numériques
    for col in df.select_dtypes(include='float64').columns:
        try:
            df[col] = pd.to_numeric(df[col], downcast='float')
        except Exception:
            pass
    for col in df.select_dtypes(include='int64').columns:
        try:
            df[col] = pd.to_numeric(df[col], downcast='integer')
        except Exception:
            pass

    return df

def _lire_csv(chemin: str | Path) -> pd.DataFrame:
    """Lecture CSV robuste : latin-1, séparateur ;, BOM nettoyé."""
    df = pd.read_csv(
        chemin, sep=";", encoding="latin-1",
        dtype=str, low_memory=False,
    )
    # Nettoyage BOM (ex: "ï»¿CdStation…")
    df.columns = [c.replace("ï»¿", "").strip() for c in df.columns]
    return df


def _parse_dates_robuste(serie: pd.Series) -> tuple[pd.Series, str, int]:
    """
    Convertit une série de dates en datetime.
    Gère 3 cas :
      - Série numérique Excel (ex: 40423 → 2010-09-02)
      - Texte JJ/MM/AAAA ou AAAA-MM-JJ
      - Mixte : essaie Excel puis texte ligne par ligne pour les exceptions

    Retourne (serie_datetime, format_detecte, nb_nat).
    """
    serie = serie.copy().astype(str).str.strip().replace("nan", pd.NA)

    # Normalisation des séries Excel avec décimale comma (ex: '33491,41667')
    # avant la détection numérique.
    serie = serie.str.replace(",", ".", regex=False)

    # Détection : combien de valeurs sont numériques ?
    # Utiliser un échantillon et diviser par la taille de CE MÊME échantillon.
    _sample = serie.dropna().head(50)
    _num_sample = pd.to_numeric(_sample, errors="coerce").dropna()
    pct_num = len(_num_sample) / max(len(_sample), 1)

    if pct_num >= 0.8:
        # Format majoritairement Excel
        nums = pd.to_numeric(serie, errors="coerce")
        dates = _EXCEL_ORIGIN + pd.to_timedelta(nums, unit="D")
        # Pour les exceptions non-numériques, tenter le parsing texte
        mask_na = dates.isna() & serie.notna()
        if mask_na.any():
            dates_txt = pd.to_datetime(
                serie[mask_na], dayfirst=True, errors="coerce"
            )
            dates = dates.where(~mask_na, dates_txt)
        fmt = "excel"
    else:
        # Format majoritairement texte
        dates = pd.to_datetime(serie, dayfirst=True, errors="coerce")
        # Pour les exceptions numériques, tenter Excel
        mask_na = dates.isna() & serie.notna()
        if mask_na.any():
            nums = pd.to_numeric(serie[mask_na], errors="coerce")
            dates_excel = _EXCEL_ORIGIN + pd.to_timedelta(nums, unit="D")
            dates = dates.where(~mask_na, dates_excel)
        fmt = "texte"

    nb_nat = int(dates.isna().sum())
    return dates, fmt, nb_nat


def _fmt_date(ts) -> str:
    """Formate un Timestamp en JJ/MM/AAAA, retourne '—' si NaT/None."""
    try:
        return ts.strftime("%d/%m/%Y") if pd.notna(ts) else "—"
    except Exception:
        return "—"


def _virgule_en_point(serie: pd.Series) -> pd.Series:
    """Remplace la virgule décimale par un point et convertit en float."""
    return (
        serie.astype(str)
        .str.replace(",", ".", regex=False)
        .pipe(pd.to_numeric, errors="coerce")
    )


# ---------------------------------------------------------------------------
# 1. Détection automatique du format
# ---------------------------------------------------------------------------

def detecter_format(chemin: str | Path) -> str:
    """
    Lit les premières lignes du CSV et devine le format source.

    Retourne : 'naiade' | 'ades' | 'ars' | 'hb' | 'inconnu'
    """
    try:
        df = _lire_csv(chemin)
        cols = set(df.columns)
    except Exception:
        return "inconnu"

    scores = {}
    for fmt, signature in _SIGNATURE.items():
        scores[fmt] = len(signature & cols) / len(signature)

    best = max(scores, key=scores.get)
    return best if scores[best] >= 0.6 else "inconnu"


# ---------------------------------------------------------------------------
# 2. Lecteurs spécialisés → DataFrame normalisé
# ---------------------------------------------------------------------------

# ── 2a. Naïades chimie ──────────────────────────────────────────────────────

def _lire_naiade(chemin: str | Path) -> tuple[pd.DataFrame, list[str]]:
    alertes = []
    df = _lire_csv(chemin)

    # Colonnes obligatoires
    manquantes = [
        c for c in [
            "CdStationMesureEauxSurface", "DatePrel", "CdParametre",
            "RsAna", "CdRqAna",
        ] if c not in df.columns
    ]
    if manquantes:
        alertes.append(f"⚠️ Colonnes manquantes (Naïades) : {', '.join(manquantes)}")

    # Dates
    if "DatePrel" in df.columns:
        df["DatePrel"], fmt, nb_nat = _parse_dates_robuste(df["DatePrel"])
        msg = f"ℹ️ Dates Naïades — format {fmt} détecté."
        if nb_nat:
            msg += f" {nb_nat} date(s) non convertie(s) (NaT)."
        alertes.append(msg)

    # Numériques
    for col in ["CdSupport", "CdFractionAnalysee", "CdParametre", "CdRqAna"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["RsAna", "LqAna", "LdAna"]:
        if col in df.columns:
            df[col] = _virgule_en_point(df[col])

    # Normalisation des noms de colonnes → schéma commun
    df = df.rename(columns={
        "LbLongParamètre": "LbLongParamètre",    # déjà bon
    })

    # Ajout colonne source
    df["_source"] = "naiade"

    # Garantir les colonnes manquantes avec NaN
    for col in COLONNES_NORM:
        if col not in df.columns:
            df[col] = np.nan

    alertes.append(
        f"ℹ️ Naïades chargé : {len(df):,} lignes | "
        f"{df['CdStationMesureEauxSurface'].nunique()} stations | "
        f"{df['CdParametre'].nunique()} paramètres"
    )
    return df, alertes


# ── 2b. ADES eaux souterraines ───────────────────────────────────────────────

def _lire_ades(chemin: str | Path) -> tuple[pd.DataFrame, list[str]]:
    alertes = []
    df = _lire_csv(chemin)

    # Dates
    if "Date prélèvement" in df.columns:
        df["DatePrel"], fmt, nb_nat = _parse_dates_robuste(df["Date prélèvement"])
        msg = f"ℹ️ Dates ADES — format {fmt} détecté."
        if nb_nat:
            msg += f" {nb_nat} date(s) non convertie(s)."
        alertes.append(msg)
    else:
        df["DatePrel"] = pd.NaT
        alertes.append("⚠️ Colonne 'Date prélèvement' absente dans le fichier ADES.")

    # Numériques
    for col in ["Code paramètre", "Code support", "Code fraction analysée",
                "Code remarque analyse"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["Résultat de l'analyse", "Limite quantification", "Limite détection"]:
        if col in df.columns:
            df[col] = _virgule_en_point(df[col])

    # Mapping remarque ADES → CdRqAna SANDRE
    # ADES : 1=Domaine validité (quantifié), 2=<LD, 3=<seuil sat, 10=<LQ
    # On ramène à : 1=quantifié, 2=<LQ, 3=<LD
    rq_map_ades = {1: 1, 2: 3, 3: 7, 10: 2, 0: 1}
    if "Code remarque analyse" in df.columns:
        df["CdRqAna"] = df["Code remarque analyse"].map(rq_map_ades).fillna(1).astype(int)
    else:
        df["CdRqAna"] = 1

    # Normalisation des noms de colonnes
    rename = {
        "Identifiant national BSS":  "CdStationMesureEauxSurface",
        "Commune dossier BSS":       "LbStationMesureEauxSurface",
        "Code paramètre":            "CdParametre",
        "Paramètre":                 "LbLongParamètre",
        "Résultat de l'analyse":     "RsAna",
        "Unité":                     "SymUniteMesure",
        "Limite quantification":     "LqAna",
        "Code support":              "CdSupport",
        "Support":                   "LbSupport",
        "Code fraction analysée":    "CdFractionAnalysee",
        "Fraction analysée":         "LbFractionAnalysee",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["_source"] = "ades"

    for col in COLONNES_NORM:
        if col not in df.columns:
            df[col] = np.nan

    alertes.append(
        f"ℹ️ ADES chargé : {len(df):,} lignes | "
        f"{df['CdStationMesureEauxSurface'].nunique()} points BSS | "
        f"{df['CdParametre'].nunique()} paramètres"
    )
    return df, alertes


# ── 2c. ARS / CAP eau potable ────────────────────────────────────────────────

def _lire_ars(chemin: str | Path) -> tuple[pd.DataFrame, list[str]]:
    alertes = []
    df = _lire_csv(chemin)

    # Dates
    if "dateprel" in df.columns:
        df["DatePrel"], fmt, nb_nat = _parse_dates_robuste(df["dateprel"])
        msg = f"ℹ️ Dates ARS — format {fmt} détecté."
        if nb_nat:
            msg += f" {nb_nat} date(s) non convertie(s)."
        alertes.append(msg)
    else:
        df["DatePrel"] = pd.NaT
        alertes.append("⚠️ Colonne 'dateprel' absente dans le fichier ARS.")

    # Résultat : quand rssigne='<', rsana=0 → LQ extraite de rqana (ex: '<0,50')
    if "rsana" in df.columns:
        df["RsAna"] = _virgule_en_point(df["rsana"])
    else:
        df["RsAna"] = np.nan

    # LQ extraite du champ rqana (ex: '<0,50' → 0.50)
    if "rqana" in df.columns:
        df["LqAna"] = (
            df["rqana"].astype(str)
            .str.replace("<", "", regex=False)
            .str.replace(",", ".", regex=False)
            .pipe(pd.to_numeric, errors="coerce")
        )
    else:
        df["LqAna"] = np.nan

    # CdRqAna : '<' → 2 (<LQ), 'N' → NaN, sinon 1
    if "rssigne" in df.columns:
        conditions = [
            df["rssigne"] == "<",
            df["rssigne"].isin(["N", "nan"]) | df["rssigne"].isna(),
        ]
        choices = [2, np.nan]
        df["CdRqAna"] = np.select(conditions, choices, default=1)
    else:
        df["CdRqAna"] = 1

    # Numérique CdParametre
    if "cdparametre" in df.columns:
        df["CdParametre"] = pd.to_numeric(df["cdparametre"], errors="coerce")

    # Libellé paramètre : ARS n'a pas de colonne libellé standard → code seul
    df["LbLongParamètre"] = df.get("cdparametresiseeaux", df.get("cdparametre", "")).astype(str)

    # Libellé station : nompointsurv ou cdpointsurv
    if "nompointsurv" in df.columns:
        df["LbStationMesureEauxSurface"] = df["nompointsurv"].astype(str).str.strip()
    elif "nomreseau" in df.columns:
        df["LbStationMesureEauxSurface"] = df["nomreseau"].astype(str).str.strip()
    else:
        df["LbStationMesureEauxSurface"] = df.get("cdpointsurv", "").astype(str)

    # Normalisation colonnes
    rename = {
        "cdpointsurv":              "CdStationMesureEauxSurface",
        "cdunitereferencesiseeaux": "SymUniteMesure",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # Support / fraction : ARS = eau potable → support 3 (Eau), fraction 23 (Eau brute)
    df["CdSupport"] = 3
    df["LbSupport"] = "Eau"
    df["CdFractionAnalysee"] = 23
    df["LbFractionAnalysee"] = "Eau brute"
    df["_source"] = "ars"

    for col in COLONNES_NORM:
        if col not in df.columns:
            df[col] = np.nan

    alertes.append(
        f"ℹ️ ARS chargé : {len(df):,} lignes | "
        f"{df['CdStationMesureEauxSurface'].nunique()} points de surveillance | "
        f"{df['CdParametre'].nunique()} paramètres"
    )
    return df, alertes


# ── 2d. HB-Naïades biologiques ───────────────────────────────────────────────

def _lire_hb(chemin: str | Path) -> tuple[pd.DataFrame, list[str]]:
    alertes = []
    df = _lire_csv(chemin)

    # Dates
    if "DateDebutOperationPrelBio" in df.columns:
        df["DatePrel"], fmt, nb_nat = _parse_dates_robuste(
            df["DateDebutOperationPrelBio"]
        )
        msg = f"ℹ️ Dates HB-Naïades — format {fmt} détecté."
        if nb_nat:
            msg += f" {nb_nat} date(s) non convertie(s)."
        alertes.append(msg)
    else:
        df["DatePrel"] = pd.NaT
        alertes.append("⚠️ Colonne 'DateDebutOperationPrelBio' absente.")

    # Résultat
    if "ResIndiceResultatBiologique" in df.columns:
        df["RsAna"] = _virgule_en_point(df["ResIndiceResultatBiologique"])
    else:
        df["RsAna"] = np.nan

    # Remarque
    if "CdRqIndiceResultatBiologique" in df.columns:
        df["CdRqAna"] = pd.to_numeric(
            df["CdRqIndiceResultatBiologique"], errors="coerce"
        ).fillna(1).astype(int)
    else:
        df["CdRqAna"] = 1

    df["LqAna"] = np.nan   # pas de LQ dans les résultats biologiques

    # Numérique CdSupport/CdParametre
    for col in ["CdSupport", "CdParametreResultatBiologique"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Décodage latin-1 potentiellement mal interprété dans LbLongParametre
    if "LbLongParametre" in df.columns:
        try:
            df["LbLongParamètre"] = (
                df["LbLongParametre"]
                .str.encode("latin-1", errors="replace")
                .str.decode("utf-8", errors="replace")
            )
        except Exception:
            df["LbLongParamètre"] = df["LbLongParametre"]
    elif "LbLongParamètre" not in df.columns:
        df["LbLongParamètre"] = ""

    # Idem pour LbSupport
    if "LbSupport" in df.columns:
        try:
            df["LbSupport"] = (
                df["LbSupport"]
                .str.encode("latin-1", errors="replace")
                .str.decode("utf-8", errors="replace")
            )
        except Exception:
            pass

    # Normalisation colonnes
    rename = {
        "CdParametreResultatBiologique": "CdParametre",
        "SymUniteMesure":               "SymUniteMesure",   # déjà bon
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    df["_source"] = "hb"

    for col in COLONNES_NORM:
        if col not in df.columns:
            df[col] = np.nan

    alertes.append(
        f"ℹ️ HB-Naïades chargé : {len(df):,} lignes | "
        f"{df['CdStationMesureEauxSurface'].nunique()} stations | "
        f"{df['CdParametre'].nunique()} paramètres biologiques"
    )
    return df, alertes


# ---------------------------------------------------------------------------
# 3. Fonction d'entrée principale pour un fichier
# ---------------------------------------------------------------------------

def lire_bdd_source(
    chemin: str | Path,
    format_force: Optional[str] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """
    Lit un fichier CSV et retourne (DataFrame normalisé, alertes).

    Parameters
    ----------
    chemin : chemin vers le CSV
    format_force : forcer le format ('naiade','ades','ars','hb'). Si None,
                   détection automatique.
    """
    fmt = format_force or detecter_format(chemin)
    alertes = [f"ℹ️ Format détecté : **{fmt}**"]

    readers = {
        "naiade": _lire_naiade,
        "ades":   _lire_ades,
        "ars":    _lire_ars,
        "hb":     _lire_hb,
    }

    if fmt not in readers:
        alertes.append(
            f"❌ Format '{fmt}' non reconnu. "
            "Formats supportés : naiade, ades, ars, hb."
        )
        return pd.DataFrame(columns=COLONNES_NORM), alertes

    df, a = readers[fmt](chemin)
    alertes.extend(a)
    df = _optimiser_memoire(df)
    df = _optimiser_memoire(df)
    df = _optimiser_memoire(df)
    df = _optimiser_memoire(df)
    df = _optimiser_memoire(df)
    return df, alertes


# ---------------------------------------------------------------------------
# 4. Fusion multi-sources
# ---------------------------------------------------------------------------

def fusionner_sources(
    sources: list[tuple[pd.DataFrame, str]],
) -> tuple[pd.DataFrame, list[str]]:
    """
    Fusionne plusieurs DataFrames normalisés en un seul.

    Parameters
    ----------
    sources : liste de (DataFrame, nom_fichier) — les DataFrames doivent
              être issus de lire_bdd_source().

    Returns
    -------
    df_fusion : DataFrame concaténé
    alertes : messages
    """
    alertes = []
    dfs = [df for df, _ in sources if not df.empty]
    if not dfs:
        alertes.append("❌ Aucune source valide à fusionner.")
        return pd.DataFrame(columns=COLONNES_NORM), alertes

    df = pd.concat(dfs, ignore_index=True, sort=False)

    # Garantir les colonnes normalisées
    for col in COLONNES_NORM:
        if col not in df.columns:
            df[col] = np.nan

    # Rapport par source
    for src_name in df["_source"].dropna().unique():
        n = (df["_source"] == src_name).sum()
        alertes.append(f"ℹ️ Source {src_name} : {n:,} lignes")

    df = _optimiser_memoire(df)
    mem_mb = df.memory_usage(deep=True).sum() / 1e6
    alertes.append(
        f"ℹ️ Fusion totale : {len(df):,} lignes | "
        f"{df['CdStationMesureEauxSurface'].nunique()} stations | "
        f"{df['CdParametre'].nunique()} paramètres | "
        f"**{mem_mb:.0f} Mo en mémoire**"
    )
    return df, alertes


# ---------------------------------------------------------------------------
# 5. Inventaires (inchangés, opèrent sur le DataFrame normalisé)
# ---------------------------------------------------------------------------

def inventaire_supports_fractions(df: pd.DataFrame) -> pd.DataFrame:
    """Tableau récapitulatif supports/fractions présents dans la BDD."""
    if "CdSupport" not in df.columns or df.empty:
        return pd.DataFrame()
    grp = (
        df.groupby(
            ["CdSupport", "LbSupport", "CdFractionAnalysee", "LbFractionAnalysee",
             "_source"],
            dropna=False,
        )
        .size()
        .reset_index(name="NbMesures")
        .sort_values(["CdSupport", "CdFractionAnalysee"])
    )
    return grp


def inventaire_stations(df: pd.DataFrame) -> pd.DataFrame:
    """Tableau des stations avec métadonnées."""
    if df.empty or "CdStationMesureEauxSurface" not in df.columns:
        return pd.DataFrame()
    agg = (
        df.groupby(
            ["CdStationMesureEauxSurface", "LbStationMesureEauxSurface", "_source"],
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
        .sort_values(["_source", "CdStationMesureEauxSurface"])
    )
    return agg


def synthese_par_station(df: pd.DataFrame, lb_map: dict = None) -> pd.DataFrame:
    """
    Tableau de synthèse par station après filtre support/fraction.

    Colonnes produites :
      Station, Années suivies, Année min, Année max,
      N campagnes total, N campagnes PCH, N campagnes Métaux, N campagnes Micropolluants,
      N paramètres total.

    Catégories :
      PCH           — unité mg/L (hors µg/L)
      Métaux dissous — codes SANDRE typiques (Cu=1433, Pb=1382, Zn=1436, Cd=1388, etc.)
                       + label contenant "métal" ou "dissous"
      Micropolluants — unité µg/L OU ng/L
    """
    if df.empty or "CdStationMesureEauxSurface" not in df.columns:
        return pd.DataFrame()

    lb_map = lb_map or {}

    # Codes SANDRE métaux dissous courants (liste non exhaustive, extensible)
    CODES_METAUX = {
        1433, 1382, 1436, 1388, 1392, 1430, 1394, 1396, 1398, 1400,
        1337, 1372, 1374, 1376, 1378, 1379, 1426, 1428,
    }

    def _categorie(row):
        code = row.get("CdParametre")
        unite = str(row.get("SymUniteMesure", "") or "").strip().lower()
        lb = str(lb_map.get(code, "") or "").lower()
        if "µg/l" in unite or "ng/l" in unite or "ug/l" in unite:
            return "Micropolluants"
        if code in CODES_METAUX or "métal" in lb or "metal" in lb or "dissous" in lb:
            return "Métaux dissous"
        return "PCH"

    df = df.copy()
    df["_categorie"] = df.apply(_categorie, axis=1)
    df["_annee"] = df["DatePrel"].dt.year

    rows = []
    for station, grp in df.groupby("CdStationMesureEauxSurface"):
        lb_st = grp["LbStationMesureEauxSurface"].iloc[0]                 if "LbStationMesureEauxSurface" in grp.columns else str(station)
        annees = grp["_annee"].dropna()
        campagnes = grp["DatePrel"].dropna()
        rows.append({
            "Station":               f"{lb_st} ({station})",
            "N années":              int(annees.nunique()),
            "Année min":             int(annees.min()) if len(annees) else None,
            "Année max":             int(annees.max()) if len(annees) else None,
            "N campagnes total":     int(campagnes.nunique()),
            "Campagnes PCH":         int(grp[grp["_categorie"] == "PCH"]["DatePrel"].nunique()),
            "Campagnes Métaux":      int(grp[grp["_categorie"] == "Métaux dissous"]["DatePrel"].nunique()),
            "Campagnes Micropoll.":  int(grp[grp["_categorie"] == "Micropolluants"]["DatePrel"].nunique()),
            "N paramètres":          int(grp["CdParametre"].nunique()),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 6. Filtres (inchangés, opèrent sur le DataFrame normalisé)
# ---------------------------------------------------------------------------

def filtrer_support_fraction(
    df: pd.DataFrame,
    cd_support: int,
    cd_fractions: Optional[list[int]] = None,
) -> tuple[pd.DataFrame, list[str]]:
    alertes = []
    df_support = df[df["CdSupport"] == cd_support].copy()
    if df_support.empty:
        alertes.append(f"⚠️ Aucune donnée pour le support {cd_support}.")
        return df_support, alertes

    fractions_dispo = df_support["CdFractionAnalysee"].dropna().unique().tolist()

    # Cas spécial : données biologiques HB sans fraction SANDRE (toutes NaN)
    # → on retourne toutes les lignes du support sans filtrer la fraction
    if not fractions_dispo:
        alertes.append(
            f"ℹ️ Support {cd_support} : aucune fraction SANDRE renseignée "
            "(données biologiques) — toutes les lignes retenues."
        )
        return df_support.copy(), alertes

    if cd_fractions is None:
        fractions_defaut = FRACTIONS_DCE_DEFAUT.get(cd_support, [])
        fractions_ok = [f for f in fractions_defaut if f in fractions_dispo]
        if fractions_ok:
            cd_fractions = fractions_ok
            alertes.append(
                f"ℹ️ Fraction(s) DCE par défaut retenue(s) : {fractions_ok}"
            )
        else:
            cd_fractions = fractions_dispo
            alertes.append(
                f"⚠️ Fraction DCE absente pour support {cd_support}. "
                f"Fractions disponibles : {fractions_dispo}. Toutes retenues."
            )
    else:
        absentes = [f for f in cd_fractions if f not in fractions_dispo]
        if absentes:
            alertes.append(
                f"⚠️ Fraction(s) absentes du fichier : {absentes}."
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


def filtrer_stations(
    df: pd.DataFrame,
    codes_stations: Optional[list] = None,
) -> pd.DataFrame:
    if not codes_stations:
        return df.copy()
    return df[
        df["CdStationMesureEauxSurface"].isin([str(c) for c in codes_stations])
    ].copy()


def filtrer_periode(
    df: pd.DataFrame,
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
) -> tuple[pd.DataFrame, list[str]]:
    alertes = []
    df = df.copy()

    if "DatePrel" not in df.columns:
        alertes.append("⚠️ Colonne DatePrel absente — filtre période ignoré.")
        return df, alertes

    if date_debut:
        d = pd.to_datetime(date_debut, dayfirst=True, errors="coerce")
        if pd.isna(d):
            alertes.append(f"⚠️ Date début '{date_debut}' non reconnue — ignorée.")
        else:
            df = df[df["DatePrel"] >= d]

    if date_fin:
        d = pd.to_datetime(date_fin, dayfirst=True, errors="coerce")
        if pd.isna(d):
            alertes.append(f"⚠️ Date fin '{date_fin}' non reconnue — ignorée.")
        else:
            df = df[df["DatePrel"] <= d]

    min_date = df["DatePrel"].min()
    max_date = df["DatePrel"].max()
    alertes.append(
        f"ℹ️ Après filtre période : {len(df):,} lignes | "
        f"{_fmt_date(min_date)} → {_fmt_date(max_date)}"
    )
    return df, alertes


# ---------------------------------------------------------------------------
# 7. Débit (Naïades uniquement — code 1420)
# ---------------------------------------------------------------------------

def extraire_debit(df_brut: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Extrait les mesures de débit instantané (CdParametre = 1420).
    Fonctionne sur un DataFrame normalisé (toute source).
    """
    alertes = []
    if "CdParametre" not in df_brut.columns:
        return pd.DataFrame(), ["⚠️ CdParametre absent — débit non extrait."]

    df_q = df_brut[df_brut["CdParametre"] == CD_DEBIT].copy()
    if df_q.empty:
        alertes.append(
            "ℹ️ Pas de débit instantané (code 1420) dans le fichier."
        )
        return pd.DataFrame(), alertes

    nb_q = df_q["CdStationMesureEauxSurface"].nunique()
    alertes.append(f"ℹ️ Débit trouvé pour {nb_q} station(s) | {len(df_q)} mesures.")

    df_debit = df_q[[
        "CdStationMesureEauxSurface", "LbStationMesureEauxSurface",
        "DatePrel", "RsAna",
    ]].copy().rename(columns={"RsAna": "Debit_m3s"})
    df_debit = df_debit.dropna(subset=["Debit_m3s"])

    stations_avec = set(df_debit["CdStationMesureEauxSurface"].unique())
    stations_sans = set(df_brut["CdStationMesureEauxSurface"].unique()) - stations_avec
    if stations_sans:
        alertes.append(
            f"⚠️ {len(stations_sans)} station(s) sans débit disponible."
        )
    return df_debit, alertes


# ---------------------------------------------------------------------------
# 8. Pipeline complet (rétrocompatible avec l'ancienne API)
# ---------------------------------------------------------------------------

def importer_bdd(
    chemin: str | Path,
    cd_support: Optional[int] = None,
    cd_fractions: Optional[list[int]] = None,
    codes_stations: Optional[list] = None,
    date_debut: Optional[str] = None,
    date_fin: Optional[str] = None,
    format_force: Optional[str] = None,
) -> dict:
    """
    Pipeline complet pour UN fichier source :
    lecture → normalisation → filtre support/fraction →
    filtre stations → filtre période → extraction débit.

    Pour fusionner plusieurs sources, utilisez lire_bdd_source() +
    fusionner_sources() + les fonctions de filtre directement.

    Returns
    -------
    dict :
        'df'                   : DataFrame filtré principal
        'df_debit'             : DataFrame débit
        'alertes'              : tous les messages
        'inventaire_stations'  : tableau stations
        'inventaire_supports'  : tableau supports/fractions
    """
    toutes = []

    df_brut, a = lire_bdd_source(chemin, format_force=format_force)
    toutes.extend(a)

    inv_supports = inventaire_supports_fractions(df_brut)

    df_debit, a = extraire_debit(df_brut)
    toutes.extend(a)

    # Filtre support/fraction (optionnel)
    if cd_support is not None:
        df, a = filtrer_support_fraction(df_brut, cd_support, cd_fractions)
        toutes.extend(a)
    else:
        df = df_brut.copy()
        toutes.append(
            "ℹ️ Pas de filtre support/fraction appliqué "
            "(cd_support non spécifié)."
        )

    df = filtrer_stations(df, codes_stations)
    df, a = filtrer_periode(df, date_debut, date_fin)
    toutes.extend(a)

    inv_stations = inventaire_stations(df)

    return {
        "df":                   df,
        "df_debit":             df_debit,
        "alertes":              toutes,
        "inventaire_stations":  inv_stations,
        "inventaire_supports":  inv_supports,
    }


# ---------------------------------------------------------------------------
# Alias de rétrocompatibilité (ancienne API)
# ---------------------------------------------------------------------------

def lire_bdd_sandre(chemin, encodage="latin-1", separateur=";"):
    """Alias rétrocompatible → lire_bdd_source(format_force='naiade')."""
    return lire_bdd_source(chemin, format_force="naiade")


# ---------------------------------------------------------------------------
# Test rapide CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    chemin_test = sys.argv[1] if len(sys.argv) > 1 else None
    fmt_force   = sys.argv[2] if len(sys.argv) > 2 else None

    if not chemin_test:
        print("Usage : python m01_import.py <chemin_csv> [naiade|ades|ars|hb]")
        sys.exit(0)

    fmt_detecte = fmt_force or detecter_format(chemin_test)
    print(f"Format : {fmt_detecte}\n")

    res = importer_bdd(chemin_test, format_force=fmt_force)
    for msg in res["alertes"]:
        print(msg)
    print("\n--- Inventaire stations ---")
    print(res["inventaire_stations"].to_string())
    print("\n--- Inventaire supports ---")
    print(res["inventaire_supports"].to_string())
    print("\n--- Aperçu données ---")
    print(res["df"].head())
