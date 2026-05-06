"""
Module 07 — Référentiels de qualité
=====================================
Chargement et gestion des seuils de qualité :
  - SEQ-Eau v2 (classes par altération, section III du document)
  - DCE état écologique (PCH généraux + polluants spécifiques)
  - DCE état chimique (substances prioritaires NQE-MA et NQE-CMA)

Fonctions principales :
  - charger_referentiel_csv()   : lit le CSV partiel fourni (Referentiel_partiel.csv)
  - construire_seq_eau()        : construit le référentiel SEQ-Eau complet codé en dur
  - construire_nqe_dce()        : construit les NQE DCE état chimique codées en dur
  - fusionner_referentiels()    : assemble tout en un seul DataFrame de référence
  - classifier_valeur()         : classe une valeur dans sa classe SEQ-Eau / DCE
  - calculer_classes_par_station(): applique la classification au pivot médianes/P90

Les seuils sont encodés directement dans ce module pour garantir la reproductibilité.
Le CSV partiel vient en complément et peut écraser / compléter les valeurs codées en dur.

Structure de sortie standard du référentiel :
  CdParametre | LbParametre | Support | Seuil_type | TBE_BE | BE_EMO | EMO_EME | EME_ME |
  Unite | Sens ('>' ou '<') | Source | Note

  Sens :
    '>'  → la valeur doit être SUPERIEURE au seuil pour être en bonne classe
           (ex : O2 dissous — plus c'est haut, mieux c'est)
    '<'  → la valeur doit être INFERIEURE au seuil (cas général)
    'IN' → intervalle (pH, conductivité min/max) — géré séparément
"""

import pandas as pd
import numpy as np
from typing import Optional

# ===========================================================================
# 1. REFERENTIEL SEQ-EAU v2 — Section III (Classes et indices par altération)
#    encodé en dur depuis le document source
# ===========================================================================
# Structure : (CdParametre, Libellé, Support, Unité, Sens,
#              TBE/BE, BE/EMO, EMO/EME, EME/ME, Note)
# Support : 'eau', 'sediment', 'mes', 'bryophyte'
# Sens    : '<' (plus c'est bas, mieux c'est) | '>' (plus c'est haut, mieux c'est)
#           'IN' (valeur doit être dans un intervalle — nécessite TBE_min/TBE_max)

_SEQ_EAU_RAW = [
    # --- 1 MOOX — Matières organiques et oxydables ---
    (1311, "Oxygène dissous",            "eau",  "mg/l O2", ">",   8,    6,    4,    3,    "P10"),
    (1312, "Taux de saturation en O2",   "eau",  "%",       ">",  90,   70,   50,   30,    "P10"),
    (1313, "DBO5",                       "eau",  "mg/l O2", "<",   3,    6,   10,   25,    "P90"),
    (1314, "DCO",                        "eau",  "mg/l O2", "<",  20,   30,   40,   80,    "P90"),
    (1841, "Carbone organique dissous",  "eau",  "mg/l C",  "<",   5,    7,   10,   15,    "P90"),
    (1335, "Ammonium NH4+",              "eau",  "mg/l NH4","<",   0.5,  1.5,  4,    8,    "P90 MOOX"),
    (1319, "Azote Kjeldahl NKJ",         "eau",  "mg/l N",  "<",   1,    2,    4,    6,    "P90 MOOX"),
    # --- 2 AZOT — Matières azotées hors nitrates ---
    (1335, "Ammonium NH4+ (azot)",       "eau",  "mg/l NH4","<",   0.1,  0.5,  2,    5,    "P90 AZOT"),
    (1319, "NKJ (azot)",                 "eau",  "mg/l N",  "<",   1,    2,    4,   10,    "P90 AZOT"),
    (1339, "Nitrites NO2-",              "eau",  "mg/l NO2","<",   0.03, 0.3,  0.5,  1,    "P90"),
    # --- 3 NITR — Nitrates ---
    (1340, "Nitrates NO3-",              "eau",  "mg/l NO3","<",   2,   10,   25,   50,    "P90 SEQ-Eau"),
    # --- 4 PHOS — Matières phosphorées ---
    (1433, "Orthophosphates PO43-",      "eau",  "mg/l PO4","<",   0.1,  0.5,  1,    2,    "P90"),
    (1350, "Phosphore total",            "eau",  "mg/l P",  "<",   0.05, 0.2,  0.5,  1,    "P90"),
    # --- 5 EPRV — Effets proliférations végétales ---
    (1436, "Chlorophylle a + phéopigm.", "eau",  "µg/l",    "<",  10,   60,  120,  240,   "P90"),
    # --- 6 PAES — Particules en suspension ---
    (1305, "MES",                        "eau",  "mg/l",    "<",   2,   25,   38,   50,    "P90"),
    (1295, "Turbidité",                  "eau",  "NTU",     "<",   1,   35,   70,  100,   "P90"),
    # --- 7 TEMP — Température ---
    (1301, "Température (salmonicole)",  "eau",  "°C",      "<",  20,   21.5, 25,   28,   "P90"),
    # --- 8 ACID — Acidification (pH bipolaire) ---
    # Note : le pH est géré comme intervalle — seuils MIN et MAX séparés
    # --- 9 MINE — Minéralisation ---
    (1303, "Conductivité à 25°C (max)",  "eau",  "µS/cm",   "<", 2500, 3000, 3500, 4000, "P90"),
    (1304, "Conductivité à 20°C (max)",  "eau",  "µS/cm",   "<", 2500, 3000, 3500, 4000, "P90"),
    (1337, "Chlorures",                  "eau",  "mg/l",    "<",  50,  100,  150,  200,   "P90"),
    (1338, "Sulfates",                   "eau",  "mg/l",    "<",  60,  120,  190,  250,   "P90"),
    (1374, "Calcium (max)",              "eau",  "mg/l",    "<", 160,  230,  300,  500,   "P90"),
    (1372, "Magnésium",                  "eau",  "mg/l",    "<",  50,   75,  100,  400,   "P90"),
    (1375, "Sodium",                     "eau",  "mg/l",    "<", 200,  225,  250,  750,   "P90"),
    (1347, "TAC",                        "eau",  "d°F",     "<",  40,   58,   75,  100,   "P90"),
    # --- 10 COUL —Couleur ---
    (1306, "Couleur",                    "eau",  "mg/l Pt", "<",  15,   60,  100,  200,   "P90"),
    # --- 12 MPMI — Micropolluants minéraux eau brute (dureté moyenne par défaut) ---
    (1369, "Arsenic",                    "eau",  "µg/l",    "<",   1,   35,   70,  100,   "P90"),
    (1389, "Chrome total (dureté moy.)", "eau",  "µg/l",    "<",   0.18, 1.8, 18,   50,  "P90"),
    (1382, "Plomb (dureté moy.)",        "eau",  "µg/l",    "<",   0.52, 5.2, 27,   50,  "P90"),
    (1383, "Zinc (dureté moy.)",         "eau",  "µg/l",    "<",   0.43, 4.3, 43,   98,  "P90"),
    (1386, "Nickel (dureté moy.)",       "eau",  "µg/l",    "<",   0.62, 6.2, 23,   40,  "P90"),
    (1387, "Mercure",                    "eau",  "µg/l",    "<",   0.007,0.07, 0.7,  1,  "P90"),
    (1388, "Cadmium (dureté moy.)",      "eau",  "µg/l",    "<",   0.004,0.04, 0.37, 1.3,"P90"),
    (1392, "Cuivre (dureté moy.)",       "eau",  "µg/l",    "<",   0.1,  1,   10,   15,  "P90"),
    # --- 12 MPMI — Sédiments ---
    (1369, "Arsenic sédiments",          "sediment","µg/g", "<",   1,    9.8, 33,   None,"Médiane"),
    (1388, "Cadmium sédiments",          "sediment","µg/g", "<",   0.1,  1,    5,   None,"Médiane"),
    (1389, "Chrome sédiments",           "sediment","µg/g", "<",   4.3, 43,  110,  None,"Médiane"),
    (1392, "Cuivre sédiments",           "sediment","µg/g", "<",   3.1, 31,  140,  None,"Médiane"),
    (1387, "Mercure sédiments",          "sediment","µg/g", "<",   0.02, 0.2,  1,  None,"Médiane"),
    (1386, "Nickel sédiments",           "sediment","µg/g", "<",   2.2, 22,   48,  None,"Médiane"),
    (1382, "Plomb sédiments",            "sediment","µg/g", "<",   3.5, 35,  120,  None,"Médiane"),
    (1383, "Zinc sédiments",             "sediment","µg/g", "<",  12,  120,  460,  None,"Médiane"),
]

# pH — traitement bipolaire séparé
_PH_SEUILS = {
    "pH_min": {"CdParametre": 1302, "Sens": ">", "TBE_BE": 6.5, "BE_EMO": 6.0, "EMO_EME": 5.5, "EME_ME": 4.5},
    "pH_max": {"CdParametre": 1302, "Sens": "<", "TBE_BE": 8.2, "BE_EMO": 9.0, "EMO_EME": 9.5, "EME_ME":10.0},
}


# ===========================================================================
# 1b. Paramètres bipolaires — seuils MIN et MAX stockés séparément
#     Utilisés quand l'utilisateur choisit quel seuil appliquer
# ===========================================================================
# pH — source DCE (Annexe 6, Guide 2023)
#   pH min : évalue l'acidification  (sens ">", valeur doit être > seuil)
#   pH max : évalue l'alcalinisation (sens "<", valeur doit être < seuil)
_PH_DCE = {
    "min": {"TBE_BE": 6.5, "BE_EMO": 6.0, "EMO_EME": 5.5, "EME_ME": 4.5, "Sens": ">",
            "Unite": "-", "Source": "DCE éco.", "Note": "P10"},
    "max": {"TBE_BE": 8.2, "BE_EMO": 9.0, "EMO_EME": 9.5, "EME_ME": 10.0, "Sens": "<",
            "Unite": "-", "Source": "DCE éco.", "Note": "P90"},
}

# Conductivité — source SEQ-Eau v2 (altération MINE)
#   min : détecte une eau trop douce (sens ">", valeur doit être > seuil)
#   max : détecte une minéralisation excessive (sens "<", valeur doit être < seuil)
_COND_SEQ = {
    "min": {"TBE_BE": 180,  "BE_EMO": 120, "EMO_EME": 60,   "EME_ME": 0,    "Sens": ">",
            "Unite": "µS/cm", "Source": "SEQ-Eau v2", "Note": "Cond. min — eau trop douce"},
    "max": {"TBE_BE": 2500, "BE_EMO": 3000,"EMO_EME": 3500, "EME_ME": 4000, "Sens": "<",
            "Unite": "µS/cm", "Source": "SEQ-Eau v2", "Note": "Cond. max — minéralisation excessive"},
}

# Codes concernés
CD_PH   = 1302
CD_COND = {1303, 1304}   # Conductivité à 25°C et à 20°C

# ===========================================================================
# 2. NQE DCE ÉTAT CHIMIQUE — substances prioritaires
#    Source : Guide 2023, Annexe 14 (p.125-127), eaux de surface intérieures
# ===========================================================================
_NQE_DCE_CHIMIQUE = [
    # (CdSandre, Nom, NQE-MA µg/l, NQE-CMA µg/l, Note)
    (1101,  "Alachlore",                    0.3,     0.7,   ""),
    (1458,  "Anthracène",                   0.1,     0.1,   ""),
    (1107,  "Atrazine",                     0.6,     2.0,   ""),
    (1114,  "Benzène",                     10.0,    50.0,   ""),
    (1388,  "Cadmium (cl.2 dureté moy.)",   0.08,    0.45,  "Dureté-dépendant"),
    (1276,  "Tétrachlorure de carbone",    12.0,    None,   ""),
    (1955,  "Chloroalcanes C10-13",         0.4,     1.4,   ""),
    (1464,  "Chlorfenvinphos",              0.1,     0.3,   ""),
    (1083,  "Chlorpyrifos éthyl",           0.03,    0.1,   ""),
    (1161,  "1,2-dichloroéthane",          10.0,   None,   ""),
    (1168,  "Dichlorométhane",             20.0,   None,   ""),
    (6616,  "DEHP",                         1.3,   None,   ""),
    (1177,  "Diuron",                       0.2,     1.8,   ""),
    (1743,  "Endosulfan",                   0.005,   0.01,  ""),
    (1191,  "Fluoranthène",                 0.0063,  0.12,  ""),
    (1199,  "Hexachlorobenzène",           None,     0.05,  "SDP"),
    (1652,  "Hexachlorobutadiène",         None,     0.6,   "SDP"),
    (5537,  "Hexachlorocyclohexane",        0.02,    0.04,  ""),
    (1208,  "Isoproturon",                  0.3,     1.0,   ""),
    (1382,  "Plomb",                        1.2,    14.0,   ""),
    (1387,  "Mercure",                     None,     0.07,  "SDP"),
    (1517,  "Naphtalène",                   2.0,   130.0,   ""),
    (1386,  "Nickel",                       4.0,    34.0,   ""),
    (1958,  "Nonylphénols",                 0.3,     2.0,   ""),
    (1959,  "Octylphénols",                 0.1,    None,   ""),
    (1888,  "Pentachlorobenzène",           0.007,  None,   "SDP"),
    (1235,  "Pentachlorophénol",            0.4,     1.0,   ""),
    (1115,  "Benzo(a)pyrène",               0.00017, 0.27,  "HAP"),
    (1116,  "Benzo(b)fluoranthène",        None,     0.017, "HAP somme"),
    (1117,  "Benzo(k)fluoranthène",        None,     0.017, "HAP somme"),
    (1118,  "Benzo(g,h,i)pérylène",        None,     0.0082,"HAP somme"),
    (1204,  "Indéno(1,2,3-cd)pyrène",      None,    None,   "HAP somme"),
    (1263,  "Simazine",                     1.0,     4.0,   ""),
    (1272,  "Tétrachloroéthylène",         10.0,   None,   ""),
    (1286,  "Trichloroéthylène",           10.0,   None,   ""),
    (2879,  "TBT cation",                   0.0002,  0.0015,""),
    (1774,  "Trichlorobenzène",             0.4,    None,   ""),
    (1135,  "Trichlorométhane",             2.5,    None,   ""),
    (1289,  "Trifluraline",                 0.03,   None,   ""),
    (1688,  "Aclonifène",                   0.12,    0.12,  ""),
    (1119,  "Bifénox",                      0.012,   0.04,  ""),
    (1935,  "Cybutryne",                    0.0025,  0.016, ""),
    (1140,  "Cyperméthrine",                0.00008, 0.0006,""),
    (1170,  "Dichlorvos",                   0.0006,  0.0007,""),
    (1269,  "Terbutryne",                   0.065,   0.34,  ""),
    # NQE état écologique — métaux non synthétiques (Annexe 8)
    (1383,  "Zinc (NQE éco.)",              7.8,    None,   "Eau filtrée, état écologique"),
    (1369,  "Arsenic (NQE éco.)",           0.83,   None,   "Eau filtrée, état écologique"),
    (1392,  "Cuivre (NQE éco.)",            1.0,    None,   "Eau filtrée, état écologique"),
    (1389,  "Chrome (NQE éco.)",            3.4,    None,   "Eau filtrée, état écologique"),
]


# ===========================================================================
# 3. Construction des DataFrames de référence
# ===========================================================================

def construire_seq_eau() -> pd.DataFrame:
    """
    Construit le DataFrame SEQ-Eau à partir des données encodées en dur.
    Retourne un DataFrame avec les colonnes standards.
    """
    rows = []
    for (cd, lb, support, unite, sens, tbe_be, be_emo, emo_eme, eme_me, note) in _SEQ_EAU_RAW:
        rows.append({
            "CdParametre": cd,
            "LbParametre": lb,
            "Support":     support,
            "Unite":       unite,
            "Sens":        sens,
            "TBE_BE":      tbe_be,
            "BE_EMO":      be_emo,
            "EMO_EME":     emo_eme,
            "EME_ME":      eme_me,
            "Source":      "SEQ-Eau v2",
            "Note":        note,
        })
    # Phéopigments (1439) : même seuil SEQ-Eau que Chlorophylle a (1436)
    # Seuil commun confirmé — pas de seuil individualisé DCE
    rows.append({
        "CdParametre": 1439,
        "LbParametre": "Phéopigments",
        "Support":     "eau",
        "Unite":       "µg/l",
        "Sens":        "<",
        "TBE_BE":      10.0,
        "BE_EMO":      60.0,
        "EMO_EME":     120.0,
        "EME_ME":      240.0,
        "Source":      "SEQ-Eau v2",
        "Note":        "Même seuil que Chlorophylle a (1436)",
    })
    df = pd.DataFrame(rows)
    return df


def construire_nqe_dce() -> pd.DataFrame:
    """
    Construit le DataFrame NQE DCE à partir des données encodées en dur.
    """
    rows = []
    for (cd, lb, nqe_ma, nqe_cma, note) in _NQE_DCE_CHIMIQUE:
        rows.append({
            "CdParametre": cd,
            "LbParametre": lb,
            "Support":     "eau",
            "Unite":       "µg/l",
            "Sens":        "<",
            "NQE_MA":      nqe_ma,
            "NQE_CMA":     nqe_cma,
            "TBE_BE":      nqe_ma,    # seuil de bon état = NQE-MA
            "BE_EMO":      None,
            "EMO_EME":     None,
            "EME_ME":      None,
            "Source":      "DCE état chimique",
            "Note":        note,
        })
    df = pd.DataFrame(rows)
    return df


def charger_referentiel_csv(chemin: str) -> pd.DataFrame:
    """
    Charge le CSV partiel de référentiel (Referentiel_partiel.csv).
    Restructure en format large (un seuil par ligne → une ligne par paramètre).
    """
    df = pd.read_csv(chemin, sep=None, engine="python", encoding="latin-1")
    df["Cd_Par"] = pd.to_numeric(df["Cd_Par"], errors="coerce")
    df["Valeur"] = df["Valeur"].astype(str).str.replace(",", ".").pipe(pd.to_numeric, errors="coerce")
    df["Alternative"] = df["Alternative"].astype(str).str.replace(",", ".").pipe(pd.to_numeric, errors="coerce")

    # Pivot : une ligne par paramètre × seuil → une ligne par paramètre
    seuils_map = {"TBE/BE": "TBE_BE", "BE/EMO": "BE_EMO",
                  "EMO/EME": "EMO_EME", "EME/ME": "EME_ME", "NQE": "NQE_MA"}

    rows = []
    for cd, grp in df.groupby("Cd_Par"):
        row = {"CdParametre": int(cd), "LbParametre": grp["Lib_lg_Par"].iloc[0],
               "Source": "CSV partiel"}
        for _, r in grp.iterrows():
            col = seuils_map.get(r["Seuil"])
            if col:
                row[col] = r["Valeur"] if pd.notna(r["Valeur"]) else None
                if col == "TBE_BE" and pd.notna(r.get("Alternative")):
                    row[col + "_alt"] = r["Alternative"]  # ex : pH min / max
        rows.append(row)

    df_out = pd.DataFrame(rows)
    # Colonnes manquantes → None
    for col in ["TBE_BE","BE_EMO","EMO_EME","EME_ME","NQE_MA"]:
        if col not in df_out.columns:
            df_out[col] = None
    return df_out


def fusionner_referentiels(
    chemin_csv: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fusionne les trois sources de référentiel :
      1. SEQ-Eau v2 (encodé en dur)
      2. NQE DCE état chimique (encodé en dur)
      3. CSV partiel fourni (optionnel, vient compléter / écraser)

    Returns
    -------
    DataFrame complet avec toutes les lignes de référentiel.
    Plusieurs lignes par CdParametre sont normales (ex : même paramètre
    sur eau et sédiment, ou avec des notes différentes).
    """
    frames = [construire_seq_eau(), construire_nqe_dce()]

    if chemin_csv:
        try:
            df_csv = charger_referentiel_csv(chemin_csv)
            df_csv["Support"] = df_csv.get("Support", "eau")
            df_csv["Unite"]   = df_csv.get("Unite",   "")
            df_csv["Sens"]    = df_csv.get("Sens",    "<")
            frames.append(df_csv)
        except Exception as e:
            print(f"⚠️ Impossible de charger le CSV référentiel : {e}")

    return pd.concat(frames, ignore_index=True, sort=False)


# ===========================================================================
# 3b. Logique de priorité : quel seuil utiliser par paramètre ?
# ===========================================================================

# ---------------------------------------------------------------------------
# Catégorisation des paramètres pour la logique de priorité
# ---------------------------------------------------------------------------

# Nitrates → SEQ-Eau (seuil TB/B = 2 mg/L NO3, plus protecteur que DCE = 10)
CODES_NITRATES = {1340}

# Paramètres bipolaires (pH et conductivité) — traités séparément
CODES_BIPOLAIRES = {1302, 1303, 1304}

# PCH généraux DCE (hors nitrates et bipolaires)
# → priorité DCE état éco. si disponible, sinon SEQ-Eau
CODES_PCH = {
    1311, 1312, 1313, 1314, 1841,   # Bilan O2
    1335, 1339, 1319,                # Azote hors nitrates
    1433, 1350,                      # Phosphore
    1436, 1439,                      # Phytoplancton
    1305, 1295, 1297,                # MES / turbidité
    1301,                            # Température
    1337, 1338, 1347, 1374, 1372, 1375, 1323, 1306,  # Minéralisation / couleur
}

# Micropolluants et métaux → NQE-MA DCE uniquement
# (pas de fallback SEQ-Eau — les ordres de grandeur sont différents)
# Tout CdParametre non classé dans les catégories ci-dessus est traité comme micropolluant


def selectionner_seuil_reference(
    df_ref: pd.DataFrame,
    support: str = "eau",
    ph_borne: str = "max",          # "min" (acidification) | "max" (alcalinisation)
    cond_borne: str = "max",        # "min" (eau trop douce) | "max" (minéralisation)
) -> pd.DataFrame:
    """
    Sélectionne le seuil de référence pertinent par paramètre selon la logique :

      • Nitrates (1340)          → SEQ-Eau (forcé, seuil TB/B = 2 mg/L)
      • pH (1302)                → bipolaire DCE : borne choisie par ph_borne
      • Conductivité (1303/1304) → bipolaire SEQ-Eau : borne choisie par cond_borne
      • PCH généraux             → DCE état éco. si disponible, sinon SEQ-Eau
      • Micropolluants & métaux  → NQE-MA DCE uniquement (pas de fallback SEQ-Eau)

    La NQE-CMA est exclue de l'analyse principale.

    Parameters
    ----------
    ph_borne   : "min" pour évaluer l'acidification (pH < 6.5 = dégradé)
                 "max" pour évaluer l'alcalinisation (pH > 8.2 = dégradé)
    cond_borne : "min" pour eau trop douce | "max" pour minéralisation excessive

    Returns
    -------
    DataFrame : une ligne par CdParametre, colonnes standards + 'Source_retenue' + 'Borne'
    """
    ref = df_ref[df_ref["Support"].str.lower() == support.lower()].copy()
    resultats = []

    # Tous les codes présents dans le référentiel + codes bipolaires
    tous_codes = set(ref["CdParametre"].unique()) | CODES_BIPOLAIRES

    for cd in tous_codes:
        grp = ref[ref["CdParametre"] == cd]

        # ---- pH bipolaire (DCE) ----
        if cd == 1302:
            borne = _PH_DCE[ph_borne]
            r = {
                "CdParametre": cd,
                "LbParametre": f"pH ({ph_borne})",
                "Support": support,
                "Unite": borne["Unite"],
                "Sens": borne["Sens"],
                "TBE_BE":  borne["TBE_BE"],
                "BE_EMO":  borne["BE_EMO"],
                "EMO_EME": borne["EMO_EME"],
                "EME_ME":  borne["EME_ME"],
                "NQE_MA":  None,
                "Source":  borne["Source"],
                "Source_retenue": f"DCE éco. pH {ph_borne}",
                "Borne": ph_borne,
                "Note": borne["Note"],
            }
            resultats.append(r)
            continue

        # ---- Conductivité bipolaire (SEQ-Eau) ----
        if cd in CD_COND:
            borne = _COND_SEQ[cond_borne]
            r = {
                "CdParametre": cd,
                "LbParametre": f"Conductivité ({cond_borne})",
                "Support": support,
                "Unite": borne["Unite"],
                "Sens": borne["Sens"],
                "TBE_BE":  borne["TBE_BE"],
                "BE_EMO":  borne["BE_EMO"],
                "EMO_EME": borne["EMO_EME"],
                "EME_ME":  borne["EME_ME"],
                "NQE_MA":  None,
                "Source":  borne["Source"],
                "Source_retenue": f"SEQ-Eau conductivité {cond_borne}",
                "Borne": cond_borne,
                "Note": borne["Note"],
            }
            resultats.append(r)
            continue

        if grp.empty:
            continue

        # ---- Nitrates → SEQ-Eau forcé ----
        if cd in CODES_NITRATES:
            seq = grp[grp["Source"] == "SEQ-Eau v2"]
            if not seq.empty:
                r = seq.iloc[0].copy()
                r["Source_retenue"] = "SEQ-Eau v2 (nitrates)"
                r["Borne"] = None
                resultats.append(r)
            continue

        # ---- PCH généraux : DCE éco. > SEQ-Eau ----
        if cd in CODES_PCH:
            dce_eco = grp[grp["Source"].str.contains("DCE", na=False)]
            if not dce_eco.empty:
                r = dce_eco.iloc[0].copy()
                if pd.notna(r.get("TBE_BE")):
                    r["Source_retenue"] = "DCE éco."
                    r["Borne"] = None
                    resultats.append(r)
                    continue
            seq = grp[grp["Source"] == "SEQ-Eau v2"]
            if not seq.empty:
                # Pour NH4+ (1335) et NKJ (1319) : prioriser la ligne AZOT
                # (seuils Annexe 6 DCE, plus protecteurs que MOOX)
                # Note contenant "AZOT" → ligne à retenir
                seq_azot = seq[seq["Note"].str.contains("AZOT", na=False)]
                r = seq_azot.iloc[0].copy() if not seq_azot.empty else seq.iloc[0].copy()
                r["Source_retenue"] = "SEQ-Eau v2"
                r["Borne"] = None
                resultats.append(r)
            continue

        # ---- Micropolluants & métaux : NQE-MA DCE uniquement ----
        dce = grp[grp["Source"] == "DCE état chimique"]
        if not dce.empty:
            r = dce.iloc[0].copy()
            if pd.notna(r.get("NQE_MA")):
                r["TBE_BE"] = r["NQE_MA"]   # seuil unique : NQE-MA
                r["Source_retenue"] = "NQE-MA DCE"
                r["Borne"] = None
                resultats.append(r)
            # Pas de fallback SEQ-Eau pour les micropolluants
            continue

        # Pas de seuil disponible → on n'ajoute pas (ND dans la classification)

    if not resultats:
        return pd.DataFrame()

    # Uniformiser : certains éléments sont des pd.Series, d'autres des dicts
    resultats_norm = [r.to_dict() if hasattr(r, "to_dict") else r for r in resultats]
    df_out = pd.DataFrame(resultats_norm).reset_index(drop=True)
    # S'assurer que les colonnes clés existent
    for col in ["TBE_BE", "BE_EMO", "EMO_EME", "EME_ME", "Sens", "Source_retenue", "Borne"]:
        if col not in df_out.columns:
            df_out[col] = None
    return df_out


# ===========================================================================
# 4. Classification d'une valeur
# ===========================================================================

# Couleurs et labels des classes
CLASSES_QUALITE = {
    "TBE": {"label": "Très bon état", "couleur": "#1a6faf", "rang": 1},
    "BE":  {"label": "Bon état",      "couleur": "#74b74a", "rang": 2},
    "EMO": {"label": "État moyen",    "couleur": "#f7c94b", "rang": 3},
    "EME": {"label": "Médiocre",      "couleur": "#e07b39", "rang": 4},
    "ME":  {"label": "Mauvais",       "couleur": "#c0392b", "rang": 5},
    "ND":  {"label": "Non déterminé", "couleur": "#cccccc", "rang": 0},
}


def classifier_valeur(
    valeur: float,
    tbe_be: Optional[float],
    be_emo: Optional[float],
    emo_eme: Optional[float],
    eme_me: Optional[float],
    sens: str = "<",
) -> str:
    """
    Classe une valeur numérique selon les seuils SEQ-Eau / DCE.

    Parameters
    ----------
    valeur  : valeur à classer
    tbe_be  : seuil de transition TBE/BE
    be_emo  : seuil BE/EMO
    omo_eme : seuil EMO/EME
    eme_me  : seuil EME/ME
    sens    : '<' (valeur doit être basse) | '>' (valeur doit être haute)
              Pour les NQE DCE sans classes intermédiaires : seul TBE_BE est renseigné
              → résultat : 'TBE' si ≤ NQE, 'ME' si > NQE

    Returns
    -------
    Code classe : 'TBE', 'BE', 'EMO', 'EME', 'ME', 'ND'
    """
    if pd.isna(valeur):
        return "ND"

    # NQE simple (pas de classes intermédiaires)
    if tbe_be is not None and be_emo is None and emo_eme is None:
        if sens == "<":
            return "TBE" if valeur <= tbe_be else "ME"
        else:
            return "TBE" if valeur >= tbe_be else "ME"

    if sens == "<":
        # Plus la valeur est basse, meilleure est la classe
        if tbe_be  is not None and valeur <= tbe_be:  return "TBE"
        if be_emo  is not None and valeur <= be_emo:  return "BE"
        if omo_eme := omo_eme if (omo_eme := emo_eme) is not None else None:
            if valeur <= omo_eme: return "EMO"
        if eme_me  is not None and valeur <= eme_me:  return "EME"
        return "ME"
    else:  # sens == ">"
        # Plus la valeur est haute, meilleure est la classe
        if tbe_be  is not None and valeur >= tbe_be:  return "TBE"
        if be_emo  is not None and valeur >= be_emo:  return "BE"
        if emo_eme is not None and valeur >= emo_eme: return "EMO"
        if eme_me  is not None and valeur >= eme_me:  return "EME"
        return "ME"


def _classifier_valeur_safe(valeur, row):
    """Version interne robuste appelée par apply()."""
    try:
        sens    = row.get("Sens", "<")
        tbe_be  = row.get("TBE_BE")
        be_emo  = row.get("BE_EMO")
        emo_eme = row.get("EMO_EME")
        eme_me  = row.get("EME_ME")

        if pd.isna(valeur): return "ND"

        # NQE simple
        if (tbe_be is not None and not pd.isna(tbe_be)
                and (be_emo is None or pd.isna(be_emo))
                and (emo_eme is None or pd.isna(emo_eme))):
            if sens == "<": return "TBE" if float(valeur) <= float(tbe_be) else "ME"
            else:           return "TBE" if float(valeur) >= float(tbe_be) else "ME"

        v = float(valeur)
        if sens == "<":
            if tbe_be  is not None and not pd.isna(tbe_be)  and v <= float(tbe_be):  return "TBE"
            if be_emo  is not None and not pd.isna(be_emo)  and v <= float(be_emo):  return "BE"
            if emo_eme is not None and not pd.isna(omo_eme := emo_eme) and v <= float(omo_eme): return "EMO"
            if eme_me  is not None and not pd.isna(eme_me)  and v <= float(eme_me):  return "EME"
            return "ME"
        else:
            if tbe_be  is not None and not pd.isna(tbe_be)  and v >= float(tbe_be):  return "TBE"
            if be_emo  is not None and not pd.isna(be_emo)  and v >= float(be_emo):  return "BE"
            if emo_eme is not None and not pd.isna(emo_eme) and v >= float(emo_eme): return "EMO"
            if eme_me  is not None and not pd.isna(eme_me)  and v >= float(eme_me):  return "EME"
            return "ME"
    except Exception:
        return "ND"


# ===========================================================================
# 5. Classification du tableau pivot
# ===========================================================================

def calculer_classes_par_station(
    pivot: pd.DataFrame,
    df_ref: pd.DataFrame,
    support: str = "eau",
    ph_borne: str = "max",
    cond_borne: str = "max",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Applique la classification qualité à chaque cellule du tableau pivot.

    Parameters
    ----------
    pivot    : tableau stations × paramètres (codes SANDRE en colonnes)
               Valeurs représentant médianes ou P90 selon le paramètre.
    df_ref   : référentiel fusionné (sortie de fusionner_referentiels())
    support  : 'eau', 'sediment', 'mes', etc.
    priorite_source : si plusieurs seuils pour le même code + support,
                      quelle source prioriser.

    Returns
    -------
    pivot_classes : même structure que pivot mais avec codes de classes ('TBE', 'BE', etc.)
    pivot_rangs   : même structure avec rang numérique (1=TBE…5=ME, 0=ND)
                    Utile pour les heatmaps.
    """
    # Utiliser la logique de priorité DCE > SEQ-Eau (sauf nitrates)
    ref_unique = selectionner_seuil_reference(df_ref, support=support, ph_borne=ph_borne, cond_borne=cond_borne)
    if ref_unique.empty or "CdParametre" not in ref_unique.columns:
        return pd.DataFrame(index=pivot.index, columns=pivot.columns).fillna("ND"), \
               pd.DataFrame(index=pivot.index, columns=pivot.columns).fillna(0)
    ref_dict = ref_unique.set_index("CdParametre").to_dict("index")

    pivot_classes = pd.DataFrame(index=pivot.index, columns=pivot.columns)
    pivot_rangs   = pd.DataFrame(index=pivot.index, columns=pivot.columns, dtype=float)

    for cd in pivot.columns:
        if cd not in ref_dict:
            pivot_classes[cd] = "ND"
            pivot_rangs[cd]   = 0
            continue
        row = ref_dict[cd]
        for station in pivot.index:
            val    = pivot.loc[station, cd]
            classe = _classifier_valeur_safe(val, row)
            pivot_classes.loc[station, cd] = classe
            pivot_rangs.loc[station, cd]   = CLASSES_QUALITE.get(classe, {}).get("rang", 0)

    return pivot_classes, pivot_rangs


# ===========================================================================
# 6. Fréquence de dépassement par station × paramètre
# ===========================================================================

def calculer_frequence_depassement(
    df_clean: pd.DataFrame,
    df_ref: pd.DataFrame,
    support: str = "eau",
    seuil_type: str = "TBE_BE",
    ph_borne: str = "max",
    cond_borne: str = "max",
    col_station: str = "CdStationMesureEauxSurface",
    col_param:   str = "CdParametre",
    col_valeur:  str = "Valeur",
) -> pd.DataFrame:
    """
    Calcule la fréquence de dépassement du seuil TBE/BE (ou autre) pour
    chaque combinaison station × paramètre.

    Returns
    -------
    DataFrame : CdParametre | CdStation | NbMesures | NbDepass | FreqDepass_pct
    """
    # Utiliser la même logique de priorité que pour la classification
    ref_unique = selectionner_seuil_reference(df_ref, support=support, ph_borne=ph_borne, cond_borne=cond_borne)
    if ref_unique.empty:
        return pd.DataFrame()
    ref_dict = ref_unique.set_index("CdParametre").to_dict("index")

    rows = []
    for (station, cd), grp in df_clean.groupby([col_station, col_param]):
        if cd not in ref_dict:
            continue
        row    = ref_dict[cd]
        seuil  = row.get(seuil_type)
        sens   = row.get("Sens", "<")
        lb     = row.get("LbParametre", str(cd))
        unite  = row.get("Unite", "")
        source = row.get("Source", "")

        if seuil is None or pd.isna(seuil):
            continue

        vals = grp[col_valeur].dropna()
        n    = len(vals)
        if n == 0:
            continue

        try:
            seuil_f = float(seuil)
            if sens == "<":
                n_depass = int((vals > seuil_f).sum())
            else:
                n_depass = int((vals < seuil_f).sum())
        except Exception:
            continue

        rows.append({
            "CdParametre":      cd,
            "LbParametre":      lb,
            "CdStation":        station,
            "NbMesures":        n,
            "NbDepassements":   n_depass,
            "FreqDepass_pct":   round(100 * n_depass / n, 1),
            "Seuil":            seuil_f,
            "Unite":            unite,
            "Source":           source,
        })

    return pd.DataFrame(rows)


# ===========================================================================
# Test rapide
# ===========================================================================

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from m01_import import importer_bdd
    from m02_nettoyage import nettoyer_et_pivoter

    chemin     = sys.argv[1] if len(sys.argv) > 1 else None
    chemin_ref = sys.argv[2] if len(sys.argv) > 2 else None

    if chemin:
        res1 = importer_bdd(chemin, cd_support=3)
        res2 = nettoyer_et_pivoter(res1["df"], seuil_pch_pct=30, seuil_micropolluants_pct=10)

        df_ref = fusionner_referentiels(chemin_ref)
        print(f"Référentiel fusionné : {len(df_ref)} lignes, "
              f"{df_ref['CdParametre'].nunique()} paramètres uniques")
        print(df_ref[df_ref["CdParametre"].isin(res2["params_retenus"])]
              [["CdParametre","LbParametre","Support","TBE_BE","BE_EMO","EMO_EME","EME_ME","Sens","Source"]]
              .drop_duplicates("CdParametre")
              .to_string(index=False))

        print("\n--- Classification pivot médianes ---")
        # Utiliser les codes en colonnes pour le pivot
        pivot_codes = res2["pivot"]
        classes, rangs = calculer_classes_par_station(pivot_codes, df_ref)
        print(classes.to_string())

        print("\n--- Fréquences de dépassement (TBE/BE) ---")
        df_depass = calculer_frequence_depassement(res2["df_clean"], df_ref)
        print(df_depass.sort_values("FreqDepass_pct", ascending=False).head(20).to_string(index=False))
