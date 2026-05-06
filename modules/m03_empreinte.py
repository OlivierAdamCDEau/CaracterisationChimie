"""
Module 03 — Empreinte chimique (v3)
=====================================
Graphiques de comparaison et caractérisation des profils chimiques inter-stations.

Conventions :
  - Classification P90 (défaut) ou P10 pour O₂, sat O₂, pH borne MIN
  - Paramètres groupés par famille (bilan O₂ → azote → phosphore → ...)
  - Conductivité : fusion 20°C / 25°C en un seul axe
  - Débit (1420) exclu des analyses chimiques
  - * en exposant si référentiel SEQ-Eau, rien si DCE
  - Watermark @CDEau discret sur toutes les figures
  - Police minimum 8 pt partout
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.colors as mcolors
from matplotlib.gridspec import GridSpec
from scipy.spatial.distance import pdist, squareform
from typing import Optional

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PALETTE_CLASSES = {
    "TBE": "#1a6faf",
    "BE":  "#74b74a",
    "EMO": "#f7c94b",
    "EME": "#e07b39",
    "ME":  "#c0392b",
    "ND":  "#d5d5d5",
}
PALETTE_STATIONS = [
    "#2563eb", "#16a34a", "#dc2626", "#d97706",
    "#7c3aed", "#0891b2", "#be185d", "#4d7c0f",
]

# Codes O₂ et saturation : axe inversé sur les radars + classification P10
CODES_INVERSES_RADAR = {1311, 1312}
CODES_P10            = {1311, 1312}

# Débit : exclu des figures chimiques
CD_DEBIT = 1420

# Conductivité : codes à fusionner en un seul paramètre
CD_COND_25 = 1303
CD_COND_20 = 1304
CD_COND_FUSIONNE = 1303   # code de référence après fusion

# Référentiel SEQ-Eau pour ces codes (annotation "*")
# ==========================================================================
# RÉFÉRENTIELS PAR PARAMÈTRE — source : Guide DCE 2023
# ==========================================================================
#
# DCE état écologique - PCH généraux (Annexe 6, page 79) :
#   1311 O₂ dissous | 1312 Sat. O₂ | 1313 DBO5 | 1841 COD
#   1301 Température | 1433 PO4 | 1350 P total | 1335 NH4+ | 1339 NO2-
#   1302 pH min/max
#   Conductivité (1303) : * dans le Guide DCE (pas de seuil fixé) → SEQ-Eau
#   Nitrates (1340) : seuil DCE = 10 mg/L → mais on préfère SEQ-Eau (2 mg/L, plus protecteur)
#
# DCE état écologique - Polluants spécifiques non synthétiques (Annexe 8, p.94) :
#   1383 Zinc (7.8 µg/l) | 1369 Arsenic (0.83) | 1392 Cuivre (1.0) | 1389 Chrome (3.4)
#   → Eau filtrée uniquement
#
# DCE état chimique - Substances prioritaires (Annexe 14, p.125-127) :
#   Cf. _NQE_DCE_CHIMIQUE dans m07_referentiels.py
#
# SEQ-Eau v2 (Section III - Classes et indices par altération) :
#   Tout ce qui n'a pas de seuil DCE : conductivité, MES, turbidité, TAC,
#   Mg, Ca, Na, Chlorophylle, et paramètres sans NQE disponible
#
# AUCUN SEUIL DISPONIBLE :
#   1367 Potassium | 1439 Phéopigments (individualisé) | 1551 NGL/NTK
#   1319 NKJ (absent de l'Annexe 6 DCE) | 1314 DCO (absent Annexe 6 DCE)
#   → Classement en ND dans les figures jusqu'à confirmation des seuils

# Codes dont le référentiel est SEQ-Eau v2 (annotation "*" dans les figures)
CODES_SEQ_EAU = {
    1340,        # Nitrates : SEQ-Eau forcé (seuil TB/B=2 mg/L, plus protecteur que DCE=10)
    1303, 1304,  # Conductivité : pas de seuil DCE fixé ("*" dans Guide, p.79)
    1337, 1338,  # Chlorures, Sulfates : pas de seuil DCE fixé
    1305,        # MES : SEQ-Eau
    1295,        # Turbidité : SEQ-Eau
    1347,        # TAC : SEQ-Eau
    1372,        # Magnésium : SEQ-Eau
    1374,        # Calcium : SEQ-Eau
    1375,        # Sodium : SEQ-Eau
    1323,        # Résidu sec : SEQ-Eau
    1314,        # DCO : SEQ-Eau (absent Annexe 6 DCE — confirmé)
    1319,        # NKJ (Azote Kjeldahl total) : SEQ-Eau (absent Annexe 6 DCE — confirmé)
    1436,        # Chlorophylle a : SEQ-Eau — seuil commun avec Phéopigments
    1439,        # Phéopigments : SEQ-Eau — même seuil que Chlorophylle a (1436)
    # Pas de seuil disponible : 1551 NGL, 1367 Potassium
}

# Codes dont le référentiel est DCE état écologique (Annexe 6 ou 8, Guide 2023)
# Sans annotation "*" dans les figures
CODES_DCE_ECO = {
    # Annexe 6 — Bilan oxygène
    1311, 1312,  # O₂ dissous (P10), Sat. O₂ (P10)
    1313,        # DBO5 (P90) ← CONFIRMÉ page 79
    1841,        # COD (P90)
    # Annexe 6 — Température
    1301,        # Température (P90)
    # Annexe 6 — Nutriments
    1433,        # PO4 orthophosphates (P90)
    1350,        # Phosphore total (P90)
    1335,        # NH4+ ammonium (P90)
    1339,        # NO2- nitrites (P90)
    # Annexe 6 — Acidification
    1302,        # pH (P10 pour min, P90 pour max)
    # Annexe 8 — Polluants spécifiques non synthétiques (eau filtrée)
    1383,        # Zinc NQE-MA = 7.8 µg/l
    1369,        # Arsenic NQE-MA = 0.83 µg/l
    1392,        # Cuivre NQE-MA = 1.0 µg/l
    1389,        # Chrome NQE-MA = 3.4 µg/l
}

# Codes sans seuil disponible actuellement → classés ND dans les figures
# À compléter au fur et à mesure (transmission seuils SEQ-Eau NKJ, DCO, NGL, K)
CODES_SANS_SEUIL = {
    1367,   # Potassium : aucun seuil disponible
    1551,   # NGL : aucun seuil disponible
}

# Ordre des familles de paramètres et leurs codes SANDRE
FAMILLES_ORDRE = [
    ("Bilan O₂",        [1311, 1312, 1313, 1314, 1841]),
    ("Azote",           [1335, 1339, 1340, 1319, 1551]),
    ("Phosphore",       [1433, 1350]),
    ("Proliférations",  [1436, 1439]),
    ("Minéralisation",  [1303, 1304, 1347, 1374, 1372, 1375, 1323, 1367]),
    ("MES/Turbidité",   [1305, 1295, 1297]),
    ("Acidification",   [1302]),
    ("Température",     [1301]),
    ("Micropolluants",  []),   # tout le reste (hors débit)
]

plt.rcParams.update({
    "font.family":       "DejaVu Sans",
    "font.size":         9,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.3,
    "figure.dpi":        120,
    "savefig.dpi":       200,
    "savefig.bbox":      "tight",
})

# ---------------------------------------------------------------------------
# Watermark
# ---------------------------------------------------------------------------

def _ajouter_watermark(fig, ax=None, texte="@CDEau",
                       alpha=0.60, fontsize=8, couleur="#999999"):
    """
    Ajoute @CDEau dans la continuité des labels X de l'axe principal,
    positionné à droite du dernier label (impossible à rogner sans couper les labels).
    Si ax est None, se positionne en bas à droite dans la zone axes de la figure.
    """
    target = ax if ax is not None else (fig.axes[-1] if fig.axes else None)
    if target is not None:
        target.annotate(
            texte,
            xy=(1.0, -0.02),
            xycoords="axes fraction",
            ha="right", va="top",
            fontsize=fontsize,
            color=couleur,
            alpha=alpha,
            style="italic",
            annotation_clip=False,
        )
    else:
        fig.text(0.99, 0.01, texte, fontsize=fontsize, color=couleur,
                 alpha=alpha, ha="right", va="bottom", style="italic")


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

SUBS_LABELS = [
    ("Taux de saturation en oxygène",                              "Sat. O₂ (%)"),
    ("Demande Biochimique en oxygène en 5 jours (D.B.O.5)",        "DBO₅"),
    ("Demande Chimique en Oxygène (DCO)",                          "DCO"),
    ("Titre alcalimétrique complet (T.A.C.)",                      "TAC"),
    ("Potentiel en Hydrogène (pH)",                                "pH"),
    ("Température de l'Eau",                                       "Température"),
    ("Conductivité (25°C / 20°C)",                                 "Conductivité"),
    ("Conductivité à 25°C",                                        "Conductivité"),
    ("Conductivité à 20°C",                                        "Conductivité"),
    ("Chlorophylle a + phéopigments",                              "Chloro. a"),
    ("Chlorophylle a",                                             "Chloro. a"),
    ("Phéopigments",                                               "Phéopigments"),
    ("Matières en suspension",                                     "MES"),
    ("Turbidité Formazine Néphélométrique",                        "Turbidité"),
    ("Orthophosphates",                                            "PO₄³⁻"),
    ("Phosphore total",                                            "P total"),
    ("Ammonium",                                                   "NH₄⁺"),
    ("Azote Kjeldahl",                                             "NKJ"),
    ("Azote global (N.GL.)",                                       "N global"),
    ("Oxygène dissous",                                            "O₂ dissous"),
    ("Magnésium",                                                  "Mg"),
    ("Calcium",                                                    "Ca"),
    ("Sodium",                                                     "Na"),
    ("Potassium",                                                   "K"),
    ("n-Butyl Phtalate",                                           "n-Butyl Phtalate"),
]

def _lb_court(code, lb_map, max_len=20):
    lb = lb_map.get(code, str(code))
    for old, new in SUBS_LABELS:
        lb = lb.replace(old, new)
    if len(lb) > max_len:
        lb = lb[:max_len - 1] + "…"
    return lb


def _lb_court_avec_ref(code, lb_map, codes_seq=CODES_SEQ_EAU, max_len=20):
    """Libellé court + '*' si référentiel SEQ-Eau."""
    lb = _lb_court(code, lb_map, max_len)
    if code in codes_seq:
        lb = lb + " *"
    return lb


def _couleur_station(i):
    return PALETTE_STATIONS[i % len(PALETTE_STATIONS)]


def _nom_court_station(lb, max_len=26):
    lb = (lb.replace("RUISSEAU DE ", "Ruisseau de ")
            .replace("LISON À ", "Lison à ").replace("LISON A ", "Lison à ")
            .replace("BIENNE À ", "Bienne à ").replace("BIENNE A ", "Bienne à "))
    lb = lb.title()
    if len(lb) > max_len:
        lb = lb[:max_len - 1] + "…"
    return lb


def _legende_classes(ax, title="Classe de qualité", loc="upper right"):
    patches = [mpatches.Patch(color=v, label=k)
               for k, v in PALETTE_CLASSES.items() if k != "ND"]
    patches.append(mpatches.Patch(color=PALETTE_CLASSES["ND"], label="ND"))
    ax.legend(handles=patches, title=title, loc=loc,
              fontsize=8, title_fontsize=8.5,
              framealpha=0.88, edgecolor="#cccccc")


def _source_court(src):
    src = str(src)
    if "SEQ" in src or "nitrates" in src:
        return "SEQ"
    if "DCE" in src or "NQE" in src:
        return "DCE"
    return src[:6]


# ---------------------------------------------------------------------------
# Ordonnancement des stations
# ---------------------------------------------------------------------------

def ordonner_stations(
    df: pd.DataFrame,
    ordre: Optional[list] = None,
    lb_stations: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Réordonne les lignes d'un DataFrame (pivot) selon un ordre explicite.

    Parameters
    ----------
    df     : DataFrame avec les codes station en index
    ordre  : liste de codes station dans l'ordre souhaité
             (ex : amont → aval, ou ordre logique du BV).
             Les codes absents du DataFrame sont ignorés.
             Les codes du DataFrame absents de la liste sont ajoutés à la fin.
    lb_stations : dict optionnel pour valider les codes par libellé

    Returns
    -------
    DataFrame réordonné
    """
    if ordre is None or len(ordre) == 0:
        return df

    # Codes valides (présents dans le DataFrame)
    codes_df   = list(df.index)
    codes_ok   = [c for c in ordre if c in codes_df]
    codes_rest = [c for c in codes_df if c not in codes_ok]
    ordre_final = codes_ok + codes_rest

    return df.reindex(ordre_final)


# ---------------------------------------------------------------------------
# Fusion conductivité + tri par famille
# ---------------------------------------------------------------------------

def fusionner_conductivite(pivot: pd.DataFrame, lb_map: dict) -> tuple[pd.DataFrame, dict]:
    """
    Fusionne les colonnes conductivité 20°C (1304) et 25°C (1303) en une seule.
    Pour chaque station, prend la valeur non-NaN disponible.
    Met à jour lb_map en conséquence.
    """
    has_25 = CD_COND_25 in pivot.columns
    has_20 = CD_COND_20 in pivot.columns

    if has_25 and has_20:
        # Fusionner : priorité 25°C, sinon 20°C
        cond_fusionnee = pivot[CD_COND_25].combine_first(pivot[CD_COND_20])
        pivot = pivot.drop(columns=[CD_COND_25, CD_COND_20])
        pivot[CD_COND_FUSIONNE] = cond_fusionnee
        lb_map = lb_map.copy()
        lb_map[CD_COND_FUSIONNE] = "Conductivité (25°C / 20°C)"
    elif has_20 and not has_25:
        # Renommer 1304 → 1303
        pivot = pivot.rename(columns={CD_COND_20: CD_COND_FUSIONNE})
        lb_map = lb_map.copy()
        lb_map[CD_COND_FUSIONNE] = "Conductivité"

    return pivot, lb_map


def ordonner_par_famille(codes: list) -> list:
    """
    Trie les codes paramètres selon l'ordre des familles définies,
    avec les micropolluants à la fin (hors débit).
    """
    codes_set = set(codes)
    ordonne   = []
    non_class = set(codes_set) - {CD_DEBIT}

    for famille, fam_codes in FAMILLES_ORDRE:
        for cd in fam_codes:
            if cd in codes_set:
                ordonne.append(cd)
                non_class.discard(cd)

    # Micropolluants restants (hors débit)
    non_class.discard(CD_DEBIT)
    ordonne.extend(sorted(non_class))

    return ordonne


def _separateurs_familles(codes_ordonnes: list) -> list[tuple[int, str]]:
    """
    Retourne la liste (position, nom_famille) pour tracer les séparateurs.
    """
    seps = []
    pos  = 0
    codes_set = set(codes_ordonnes)

    for famille, fam_codes in FAMILLES_ORDRE:
        codes_fam_presents = [c for c in fam_codes if c in codes_set]
        if not codes_fam_presents:
            continue
        if pos > 0:
            seps.append((pos, famille))
        pos += len(codes_fam_presents)

    # Micropolluants restants
    non_class = [c for c in codes_ordonnes
                 if not any(c in fc for _, fc in FAMILLES_ORDRE) and c != CD_DEBIT]
    if non_class and pos > 0:
        seps.append((pos, "Micropolluants"))

    return seps


def _ajouter_separateurs(ax, codes_ordonnes, orientation="vertical",
                          couleur="#555555", lw=1.2):
    """
    Ajoute des lignes de séparation entre les familles de paramètres.
    orientation : 'vertical' (heatmap colonnes) | 'horizontal' (heatmap lignes)
    """
    seps = _separateurs_familles(codes_ordonnes)
    for pos, _ in seps:
        if orientation == "vertical":
            ax.axvline(pos - 0.5, color=couleur, linewidth=lw, linestyle="-", alpha=0.5)
        else:
            ax.axhline(pos - 0.5, color=couleur, linewidth=lw, linestyle="-", alpha=0.5)


# ---------------------------------------------------------------------------
# Pivot P90 / P10 pour la classification
# ---------------------------------------------------------------------------

def pivoter_percentile(
    df_stats: pd.DataFrame,
    params_retenus: list,
    ph_borne: str = "max",
    col_station: str = "CdStationMesureEauxSurface",
    col_param:   str = "CdParametre",
) -> tuple[pd.DataFrame, dict]:
    """
    Construit le tableau pivot avec le bon percentile par paramètre :
      - CODES_P10 (O₂, sat) → P10
      - pH borne MIN         → P10
      - Autres              → P90

    Returns pivot_pct et pct_info {code → 'P10'|'P90'}.
    """
    CD_PH = 1302
    pivot_rows, info = {}, {}

    for cd in params_retenus:
        if cd == CD_DEBIT:
            continue
        sub = df_stats[df_stats[col_param] == cd]
        if sub.empty:
            continue
        col_pct = ("P10" if (cd in CODES_P10 or (cd == CD_PH and ph_borne == "min"))
                   else "P90")
        info[cd] = col_pct
        pivot_rows[cd] = sub.set_index(col_station)[col_pct]

    pivot_pct = pd.DataFrame(pivot_rows)
    pivot_pct.index.name = "Station"
    return pivot_pct, info


# ---------------------------------------------------------------------------
# Classification avec le bon percentile
# ---------------------------------------------------------------------------

def calculer_classes_pct(
    pivot_pct: pd.DataFrame,
    df_ref_seuils: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Classifie le pivot P90/P10 selon les seuils de référence."""
    CLASSES_RANG = {"TBE": 1, "BE": 2, "EMO": 3, "EME": 4, "ME": 5, "ND": 0}

    if "CdParametre" not in df_ref_seuils.columns:
        df_ref_seuils = df_ref_seuils.reset_index()
    ref_dict = df_ref_seuils.set_index("CdParametre").to_dict("index")

    pivot_classes = pd.DataFrame(index=pivot_pct.index, columns=pivot_pct.columns)
    pivot_rangs   = pd.DataFrame(index=pivot_pct.index, columns=pivot_pct.columns, dtype=float)

    def _classer(val, row):
        if pd.isna(val) or not row:
            return "ND"
        sens    = row.get("Sens", "<")
        tbe_be  = row.get("TBE_BE")
        be_emo  = row.get("BE_EMO")
        emo_eme = row.get("EMO_EME")
        eme_me  = row.get("EME_ME")
        v = float(val)

        def _notna(x):
            return x is not None and not (isinstance(x, float) and np.isnan(x))

        if _notna(tbe_be) and not _notna(be_emo):
            return ("TBE" if (v <= float(tbe_be) if sens == "<" else v >= float(tbe_be))
                    else "ME")
        if sens == "<":
            if _notna(tbe_be)  and v <= float(tbe_be):  return "TBE"
            if _notna(be_emo)  and v <= float(be_emo):  return "BE"
            if _notna(omo_eme := emo_eme) and v <= float(omo_eme): return "EMO"
            if _notna(eme_me)  and v <= float(eme_me):  return "EME"
            return "ME"
        else:
            if _notna(tbe_be)  and v >= float(tbe_be):  return "TBE"
            if _notna(be_emo)  and v >= float(be_emo):  return "BE"
            if _notna(omo_eme := emo_eme) and v >= float(omo_eme): return "EMO"
            if _notna(eme_me)  and v >= float(eme_me):  return "EME"
            return "ME"

    for cd in pivot_pct.columns:
        row = ref_dict.get(cd, {})
        # Essayer aussi le code fusionné conductivité
        if not row and cd == CD_COND_FUSIONNE:
            row = ref_dict.get(CD_COND_25, ref_dict.get(CD_COND_20, {}))
        for station in pivot_pct.index:
            cl = _classer(pivot_pct.loc[station, cd], row)
            pivot_classes.loc[station, cd] = cl
            pivot_rangs.loc[station, cd]   = float(CLASSES_RANG.get(cl, 0))

    return pivot_classes, pivot_rangs


# ---------------------------------------------------------------------------
# 1. RADAR PLOTS
# ---------------------------------------------------------------------------

def radar_stations(
    pivot_norm: pd.DataFrame,
    lb_map: dict,
    lb_stations: Optional[dict] = None,
    ordre_stations: Optional[list] = None,
    params_selectionnes: Optional[list] = None,
    titre: str = "Profil chimique normalisé — comparaison inter-stations",
    mode: str = "superpose",
    figsize: Optional[tuple] = None,
) -> plt.Figure:
    """
    Radar plots Z-score normalisés.
    O₂ et Sat. O₂ : axe inversé (valeur éloignée du centre = bon état).
    """
    df = pivot_norm.copy()
    # Exclure débit
    df = df[[c for c in df.columns if c != CD_DEBIT]]
    # Ordre des stations
    df = ordonner_stations(df, ordre_stations, lb_stations)
    if params_selectionnes:
        df = df[[c for c in params_selectionnes if c in df.columns]]
    df = df.dropna(axis=1, how="all")

    # Fusion conductivité + tri familles
    df, lb_map2 = fusionner_conductivite(df, lb_map)
    codes_ord = ordonner_par_famille(list(df.columns))
    df = df[[c for c in codes_ord if c in df.columns]]
    codes  = list(df.columns)
    N      = len(codes)

    if N < 3:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "Pas assez de paramètres (minimum 3).",
                ha="center", va="center", transform=ax.transAxes, fontsize=10)
        ax.axis("off")
        _ajouter_watermark(fig, ax=fig.axes[0] if fig.axes else None)
        return fig

    # Inversion O₂ / sat
    df_radar = df.copy()
    for cd in CODES_INVERSES_RADAR:
        if cd in df_radar.columns:
            df_radar[cd] = -df_radar[cd]

    labels_radar = []
    for cd in codes:
        lb = _lb_court(cd, lb_map2)
        if cd in CODES_INVERSES_RADAR:
            lb = "← " + lb
        labels_radar.append(lb)

    stations = list(df_radar.index)
    angles   = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles  += angles[:1]

    if mode == "superpose":
        if figsize is None:
            figsize = (9, 9)
        fig, ax = plt.subplots(figsize=figsize, subplot_kw={"polar": True})

        for i, station in enumerate(stations):
            vals  = df_radar.loc[station].fillna(0).tolist()
            vals += [vals[0]]
            color = _couleur_station(i)
            lb_st = _nom_court_station(lb_stations.get(station, station)) if lb_stations else station
            ax.plot(angles, vals, linewidth=2.0, color=color, label=lb_st, zorder=3)
            ax.fill(angles, vals, alpha=0.07, color=color)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels_radar, size=8.5, color="#222222")
        ax.set_rlabel_position(30)
        ax.tick_params(axis="y", labelsize=8)
        ax.axhline(0, color="#999999", linewidth=0.8, linestyle="--", alpha=0.5)
        ax.legend(loc="upper right", bbox_to_anchor=(1.4, 1.12),
                  fontsize=9, title="Stations", title_fontsize=9,
                  framealpha=0.9, edgecolor="#cccccc")
        ax.set_title(titre, size=11, fontweight="bold", pad=20, y=1.08)
        ax.grid(color="#cccccc", linewidth=0.5, linestyle="--", alpha=0.7)
        fig.text(0.02, 0.01,
                 "Z-score : valeur relative à la distribution globale. "
                 "← : axe inversé (éloigné du centre = bon état).",
                 fontsize=7.5, color="#666666", style="italic")

    else:  # grille
        ncols = min(3, len(stations))
        nrows = (len(stations) + ncols - 1) // ncols
        if figsize is None:
            figsize = (5.5 * ncols, 5.5 * nrows)
        fig = plt.figure(figsize=figsize)
        fig.suptitle(titre, size=12, fontweight="bold", y=1.01)

        for i, station in enumerate(stations):
            ax    = fig.add_subplot(nrows, ncols, i + 1, polar=True)
            raw   = df_radar.loc[station].fillna(0).tolist()
            vals  = raw + [raw[0]]
            color = _couleur_station(i)
            lb_st = _nom_court_station(lb_stations.get(station, station)) if lb_stations else station
            ax.plot(angles, vals, linewidth=2.2, color=color, zorder=3)
            ax.fill(angles, vals, alpha=0.18, color=color)
            ax.set_xticks(angles[:-1])
            ax.set_xticklabels(labels_radar, size=8)
            ax.set_title(lb_st, size=9.5, fontweight="bold", pad=14, color=color)
            ax.tick_params(axis="y", labelsize=7.5)
            ax.axhline(0, color="#999999", linewidth=0.8, linestyle="--", alpha=0.5)
            ax.grid(color="#cccccc", linewidth=0.5, linestyle="--", alpha=0.7)

        for j in range(len(stations), nrows * ncols):
            fig.add_subplot(nrows, ncols, j + 1).axis("off")

        fig.text(0.02, -0.01,
                 "Z-score normalisé. ← : axe inversé (éloigné = bon état). "
                 "Cercle central = moyenne globale.",
                 fontsize=8, color="#666666", style="italic")

    fig.tight_layout()
    _ajouter_watermark(fig, ax=fig.axes[0] if fig.axes else None)
    return fig


# ---------------------------------------------------------------------------
# 2. HEATMAP STATIONS × PARAMÈTRES
# ---------------------------------------------------------------------------

def heatmap_stations(
    pivot: pd.DataFrame,
    pivot_pct: Optional[pd.DataFrame] = None,
    pivot_classes: Optional[pd.DataFrame] = None,
    df_ref_seuils: Optional[pd.DataFrame] = None,
    lb_map: Optional[dict] = None,
    lb_stations: Optional[dict] = None,
    ordre_stations: Optional[list] = None,
    params_selectionnes: Optional[list] = None,
    pct_info: Optional[dict] = None,
    mode: str = "classes_annot",
    titre: str = "Profil chimique inter-stations",
    largeur_col: float = 0.85,
    figsize: Optional[tuple] = None,
) -> plt.Figure:
    """
    Heatmap stations × paramètres, colonnes groupées par famille.

    mode :
      'valeurs'       → valeurs relatives, inversion O₂/sat
      'classes'       → couleurs classes qualité
      'classes_annot' → classes + valeurs P90/P10 + * SEQ-Eau
    """
    lb_map = lb_map or {}
    df_base = (pivot_pct if pivot_pct is not None else pivot).copy()

    # Exclure débit + ordre stations
    df_base = df_base[[c for c in df_base.columns if c != CD_DEBIT]]
    df_base = ordonner_stations(df_base, ordre_stations, lb_stations)

    if params_selectionnes:
        df_base = df_base[[c for c in params_selectionnes if c in df_base.columns]]

    # Fusion conductivité
    df_base, lb_map2 = fusionner_conductivite(df_base, lb_map)
    if pivot_pct is not None and CD_COND_20 in pivot_pct.columns and CD_COND_25 in pivot_pct.columns:
        pivot_pct_f, _ = fusionner_conductivite(pivot_pct.copy(), lb_map)
    else:
        pivot_pct_f = pivot_pct

    # Tri par famille
    codes_ord = ordonner_par_famille(list(df_base.columns))
    df_base   = df_base[[c for c in codes_ord if c in df_base.columns]]
    codes     = list(df_base.columns)

    # Libellés avec * SEQ-Eau
    labels_p  = [_lb_court_avec_ref(c, lb_map2) for c in codes]
    stations  = list(df_base.index)
    labels_s  = [_nom_court_station(lb_stations.get(s, s)) if lb_stations else s
                 for s in stations]

    nrows, ncols = len(stations), len(codes)
    if figsize is None:
        w = max(7, ncols * largeur_col + 3.0)
        h = max(4, nrows * 0.85 + 2.5)
        figsize = (w, h)

    fig, ax = plt.subplots(figsize=figsize)

    # ---- MODE VALEURS ----
    if mode == "valeurs":
        data = df_base.values.astype(float)
        col_min = np.nanmin(data, axis=0)
        col_max = np.nanmax(data, axis=0)
        col_rng = np.where(col_max - col_min == 0, 1, col_max - col_min)
        data_norm = (data - col_min) / col_rng

        for j, cd in enumerate(codes):
            if cd in CODES_INVERSES_RADAR:
                data_norm[:, j] = 1 - data_norm[:, j]

        im = ax.imshow(data_norm, cmap="RdYlBu_r", aspect="auto",
                       vmin=0, vmax=1, interpolation="nearest")

        for i in range(nrows):
            for j in range(ncols):
                val = df_base.iloc[i, j]
                txt = f"{val:.2g}" if pd.notna(val) else "—"
                br  = data_norm[i, j] if not np.isnan(data_norm[i, j]) else 0.5
                ct  = "white" if br > 0.65 or br < 0.25 else "#333333"
                ax.text(j, i, txt, ha="center", va="center",
                        fontsize=8, color=ct, fontweight="bold")

        plt.colorbar(im, ax=ax, label="Valeur relative (rouge=élevé, inversé O₂/sat)",
                     shrink=0.5)

    # ---- MODE CLASSES (± annotations) ----
    elif mode in ("classes", "classes_annot"):
        # Aligner pivot_classes avec les codes ordonnés (après fusion conductivité)
        pc = pivot_classes.copy() if pivot_classes is not None else pd.DataFrame()
        if CD_COND_20 in pc.columns and CD_COND_25 not in pc.columns:
            pc[CD_COND_FUSIONNE] = pc[CD_COND_20]

        color_matrix = np.zeros((nrows, ncols, 3))
        for i, station in enumerate(stations):
            for j, code in enumerate(codes):
                cl  = pc.loc[station, code] if (not pc.empty and code in pc.columns) else "ND"
                color_matrix[i, j] = mcolors.to_rgb(
                    PALETTE_CLASSES.get(cl, PALETTE_CLASSES["ND"])
                )

        ax.imshow(color_matrix, aspect="auto", interpolation="nearest")

        if mode == "classes_annot":
            ref_src = {}
            if df_ref_seuils is not None and "CdParametre" in df_ref_seuils.columns:
                ref_src = df_ref_seuils.set_index("CdParametre")["Source_retenue"].to_dict()

            for i, station in enumerate(stations):
                for j, code in enumerate(codes):
                    val = df_base.iloc[i, j]
                    cl  = (pc.loc[station, code]
                           if (not pc.empty and code in pc.columns) else "ND")
                    txt = f"{val:.2g}" if pd.notna(val) else "—"
                    rgb = mcolors.to_rgb(PALETTE_CLASSES.get(cl, PALETTE_CLASSES["ND"]))
                    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
                    ax.text(j, i, txt, ha="center", va="center", fontsize=8,
                            color="white" if lum < 0.55 else "#222222",
                            fontweight="bold")

        _legende_classes(ax)

    # Séparateurs familles
    _ajouter_separateurs(ax, codes, orientation="vertical")

    # Axes
    ax.set_xticks(range(ncols))
    ax.set_xticklabels(labels_p, rotation=40, ha="right", fontsize=8.5)
    ax.set_yticks(range(nrows))
    ax.set_yticklabels(labels_s, fontsize=9)
    ax.set_title(titre, fontsize=11, fontweight="bold", pad=12)

    # Note référentiel
    fig.text(0.01, -0.03,
             "* Référentiel SEQ-Eau v2 | Autres : DCE (état éco. ou NQE-MA)",
             fontsize=8, color="#666666", style="italic")

    for x in np.arange(-0.5, ncols, 1):
        ax.axvline(x, color="white", linewidth=0.6, alpha=0.5)
    for y in np.arange(-0.5, nrows, 1):
        ax.axhline(y, color="white", linewidth=0.6, alpha=0.5)
    ax.tick_params(axis="both", which="both", length=0)

    fig.tight_layout()
    _ajouter_watermark(fig, ax=fig.axes[0] if fig.axes else None)
    return fig


# ---------------------------------------------------------------------------
# 3. HEATMAP FRÉQUENCES DE DÉPASSEMENT
# ---------------------------------------------------------------------------

def heatmap_frequence(
    df_depassement: pd.DataFrame,
    lb_stations: Optional[dict] = None,
    lb_map: Optional[dict] = None,
    ordre_stations: Optional[list] = None,
    params_selectionnes: Optional[list] = None,
    titre: str = "Fréquence de dépassement du seuil TBE/BE (%)",
    largeur_col: float = 0.95,
    figsize: Optional[tuple] = None,
) -> plt.Figure:
    """
    Heatmap fréquences de dépassement, paramètres triés par famille.
    * = référentiel SEQ-Eau.
    """
    lb_map = lb_map or {}
    df = df_depassement.copy()
    if params_selectionnes:
        df = df[df["CdParametre"].isin(params_selectionnes)]
    df = df[df["CdParametre"] != CD_DEBIT]

    if df.empty:
        fig, ax = plt.subplots(figsize=(6, 2))
        ax.text(0.5, 0.5, "Aucun dépassement à afficher.",
                ha="center", va="center", transform=ax.transAxes, fontsize=10)
        ax.axis("off")
        _ajouter_watermark(fig, ax=fig.axes[0] if fig.axes else None)
        return fig

    # Pivot sur CdParametre (pas LbParametre) pour éviter les libellés issus
    # du référentiel M07 (ex: "pH (max)") qui diffèrent du lb_map M02
    pivot_dep = (df.pivot_table(
        index="CdStation", columns="CdParametre",
        values="FreqDepass_pct", aggfunc="mean"
        # PAS de fillna(0) : NaN = paramètre non recherché dans cette station
    ))

    # Ordre des stations
    pivot_dep = ordonner_stations(pivot_dep, ordre_stations, lb_stations)

    # Tri par famille + libellés avec * (construits depuis lb_map M02)
    codes_ord = ordonner_par_famille(list(pivot_dep.columns))
    codes_ok  = [c for c in codes_ord if c in pivot_dep.columns]
    pivot_dep = pivot_dep[codes_ok]

    labels_p  = [_lb_court_avec_ref(c, lb_map) for c in codes_ok]
    stations  = list(pivot_dep.index)
    labels_s  = [_nom_court_station(lb_stations.get(s, s)) if lb_stations else s
                 for s in stations]

    nrows, ncols = len(stations), len(codes_ok)
    if figsize is None:
        figsize = (max(8, ncols * largeur_col + 3), max(3.5, nrows * 0.9 + 2.5))

    fig, ax = plt.subplots(figsize=figsize)

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "dep", ["#ffffff", "#f7c94b", "#e07b39", "#c0392b"]
    )
    data = pivot_dep.values.astype(float)  # NaN conservés pour les non-recherchés

    # Masque des valeurs présentes (paramètre recherché dans la station)
    masque_present = ~np.isnan(data)
    data_affich    = np.where(masque_present, data, np.nan)

    # Colorier uniquement les cellules où le paramètre a été recherché
    # Les cellules NaN (non recherché) restent blanches/grises
    data_pour_cmap = np.where(masque_present, data, -1)  # -1 → hors colormap
    cmap_ext = mcolors.LinearSegmentedColormap.from_list(
        "dep_ext", [(0, "#f5f5f5"), (1/101, "#ffffff"),
                    (20/101, "#f7c94b"), (60/101, "#e07b39"), (1.0, "#c0392b")]
    )
    im = ax.imshow(data_pour_cmap + 1, cmap=cmap_ext, aspect="auto",
                   vmin=0, vmax=101, interpolation="nearest")

    for i in range(nrows):
        for j in range(ncols):
            val = data[i, j]
            if np.isnan(val):
                # Paramètre non recherché : cellule grisée, aucun texte
                ax.add_patch(mpatches.Rectangle(
                    (j - 0.5, i - 0.5), 1, 1,
                    color="#f0f0f0", zorder=1
                ))
            else:
                ax.text(j, i, f"{val:.0f}%", ha="center", va="center",
                        fontsize=8.5, fontweight="bold", zorder=2,
                        color="white" if val > 55 else "#333333")

    # Colorbar (0–100% seulement, sans le -1 des absents)
    sm = plt.cm.ScalarMappable(
        cmap=mcolors.LinearSegmentedColormap.from_list(
            "dep", ["#ffffff", "#f7c94b", "#e07b39", "#c0392b"]),
        norm=plt.Normalize(vmin=0, vmax=100)
    )
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.5, label="Fréquence de dépassement (%)")
    cbar.ax.tick_params(labelsize=8)

    # Séparateurs familles
    _ajouter_separateurs(ax, codes_ok, orientation="vertical")

    ax.set_xticks(range(ncols))
    ax.set_xticklabels(labels_p, rotation=40, ha="right", fontsize=8.5)
    ax.set_yticks(range(nrows))
    ax.set_yticklabels(labels_s, fontsize=9)
    ax.set_title(titre, fontsize=11, fontweight="bold", pad=12)

    fig.text(0.01, -0.03,
             "* Référentiel SEQ-Eau v2 | Autres : DCE | Cellule grisée = paramètre non recherché",
             fontsize=8, color="#666666", style="italic")

    for x in np.arange(-0.5, ncols, 1):
        ax.axvline(x, color="white", linewidth=0.6, zorder=3)
    for y in np.arange(-0.5, nrows, 1):
        ax.axhline(y, color="white", linewidth=0.6, zorder=3)
    ax.tick_params(axis="both", which="both", length=0)

    fig.tight_layout()
    _ajouter_watermark(fig, ax=fig.axes[0] if fig.axes else None)
    return fig


# ---------------------------------------------------------------------------
# 4. MATRICE DE DISTANCES INTER-STATIONS
# ---------------------------------------------------------------------------

def matrice_distances(
    pivot_norm: pd.DataFrame,
    pivot_brut: Optional[pd.DataFrame] = None,
    lb_stations: Optional[dict] = None,
    ordre_stations: Optional[list] = None,
    params_selectionnes: Optional[list] = None,
    methode: str = "euclidean",
    titre: str = "Distance chimique inter-stations",
    seuil_alerte_nan: float = 30.0,
    figsize: Optional[tuple] = None,
) -> plt.Figure:
    """
    Matrice de distances inter-stations.

    pivot_norm : tableau normalisé (NaN imputés) — utilisé pour le calcul des distances.
    pivot_brut : tableau brut avec NaN réels (médianes avant imputation, sortie M02 clé 'pivot').
                 Utilisé UNIQUEMENT pour calculer le corpus commun réel.
                 Si absent, le corpus commun sera surestimé (pivot_norm n'a plus de NaN).
    """
    df = pivot_norm.copy()
    df = df[[c for c in df.columns if c != CD_DEBIT]]
    # Ordre des stations
    df = ordonner_stations(df, ordre_stations, lb_stations)
    if params_selectionnes:
        df = df[[c for c in params_selectionnes if c in df.columns]]

    # Corpus vraiment commun : calculé sur le pivot BRUT (avant imputation NaN).
    # pivot_norm a déjà subi l'imputation par médiane → plus aucun NaN → calcul faussé.
    # On utilise pivot_brut si fourni, sinon on avertit.
    if pivot_brut is not None:
        df_ref_nan = pivot_brut.copy()
        df_ref_nan = df_ref_nan[[c for c in df_ref_nan.columns if c != CD_DEBIT]]
        if params_selectionnes:
            df_ref_nan = df_ref_nan[[c for c in params_selectionnes if c in df_ref_nan.columns]]
        # Aligner sur les mêmes stations que df (après ordre)
        df_ref_nan = df_ref_nan.reindex(index=df.index)
        masque_commun = df_ref_nan.notna().all(axis=0)
        nb_total      = int(df_ref_nan.shape[1])
    else:
        # Fallback : pivot_norm imputé → tous les paramètres semblent communs (surestimé)
        masque_commun = df.notna().all(axis=0)
        nb_total      = int(df.shape[1])

    nb_commun = int(masque_commun.sum())

    # Conductivité : 1303 et 1304 sont complémentaires entre stations
    # → si leur union couvre toutes les stations, compter comme 1 paramètre commun
    cond_both = (CD_COND_25 in (df_ref_nan if pivot_brut is not None else df).columns and
                 CD_COND_20 in (df_ref_nan if pivot_brut is not None else df).columns)
    cond_union_complete = False
    if cond_both:
        df_c = df_ref_nan if pivot_brut is not None else df
        if CD_COND_25 in df_c.columns and CD_COND_20 in df_c.columns:
            cond_union = df_c[[CD_COND_25, CD_COND_20]].apply(
                lambda row: row.notna().any(), axis=1
            )
            if cond_union.all():
                cond_union_complete = True
                if not masque_commun.get(CD_COND_25, False) and not masque_commun.get(CD_COND_20, False):
                    nb_commun += 1   # union conductivité = 1 paramètre commun
                    nb_total  -= 1   # 2 codes → 1 paramètre logique

    # Détection biais NaN par station
    pct_nan = df.isna().mean(axis=1) * 100
    stations_pb = pct_nan[pct_nan > seuil_alerte_nan]
    alerte = ""
    if not stations_pb.empty:
        noms = [_nom_court_station(lb_stations.get(s, s)) if lb_stations else s
                for s in stations_pb.index]
        alerte = (f"⚠ Données éparses : {', '.join(noms)} "
                  f"(>{seuil_alerte_nan:.0f}% de paramètres manquants → distances sous-estimées).")

    df_imp = df.fillna(df.median())
    stations  = list(df_imp.index)
    labels_s  = [_nom_court_station(lb_stations.get(s, s)) if lb_stations else s
                 for s in stations]
    n = len(stations)

    dist_vect = pdist(df_imp.values, metric=methode)
    dist_mat  = squareform(dist_vect)

    if figsize is None:
        figsize = (max(5.5, n * 1.35 + 2), max(4.5, n * 1.1 + 2.5))

    fig, ax = plt.subplots(figsize=figsize)

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "dist", ["#f0f8ff", "#74b74a", "#f7c94b", "#e07b39", "#c0392b"]
    )
    im = ax.imshow(dist_mat, cmap=cmap, aspect="equal", interpolation="nearest")

    for i in range(n):
        for j in range(n):
            val = dist_mat[i, j]
            lum = val / (dist_mat.max() + 1e-9)
            ax.text(j, i, "0" if i == j else f"{val:.2f}",
                    ha="center", va="center", fontsize=8.5,
                    color="white" if lum > 0.6 else "#222222",
                    fontweight="bold" if i == j else "normal")

    plt.colorbar(im, ax=ax, label=f"Distance {methode}", shrink=0.65)
    ax.set_xticks(range(n))
    ax.set_xticklabels(labels_s, rotation=40, ha="right", fontsize=9)
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels_s, fontsize=9)
    ax.set_title(titre, fontsize=11, fontweight="bold", pad=12)
    ax.tick_params(length=0)

    for k in range(n):
        ax.add_patch(mpatches.Rectangle(
            (k - 0.5, k - 0.5), 1, 1,
            linewidth=1.8, edgecolor="#555555", facecolor="none", zorder=3
        ))

    note = (f"Méthode : {methode} | Corpus commun ({nb_commun}/{nb_total} paramètres présents "
            f"dans toutes les stations)")
    if alerte:
        note = alerte + "\n" + note
    fig.text(0.01, -0.05, note, fontsize=8, color="#555555", style="italic")

    fig.tight_layout()
    _ajouter_watermark(fig, ax=fig.axes[0] if fig.axes else None)
    return fig


# ---------------------------------------------------------------------------
# 5. FIGURE MULTI-PANNEAUX SYNTHÉTIQUE
# ---------------------------------------------------------------------------

def figure_empreinte_complete(
    pivot: pd.DataFrame,
    pivot_pct: pd.DataFrame,
    pivot_classes: pd.DataFrame,
    df_depassement: pd.DataFrame,
    lb_map: dict,
    df_ref_seuils: Optional[pd.DataFrame] = None,
    lb_stations: Optional[dict] = None,
    ordre_stations: Optional[list] = None,
    params_pch: Optional[list] = None,
    pct_info: Optional[dict] = None,
    titre_bv: str = "Analyse de l'empreinte chimique",
    figsize: Optional[tuple] = None,
) -> plt.Figure:
    """
    Figure multi-panneaux : classes qualité (gauche) + fréquences dépassement (droite).
    Colonnes groupées par famille, * = SEQ-Eau, sans mention P90/P10.
    """
    # Préparer pivot_pct avec fusion conductivité + ordre stations
    pct_f, lb_map2 = fusionner_conductivite(pivot_pct.copy(), lb_map)
    pct_f = ordonner_stations(pct_f, ordre_stations, lb_stations)
    pct_f = pct_f[[c for c in pct_f.columns if c != CD_DEBIT]]

    if params_pch:
        cols_pch = [c for c in params_pch if c in pct_f.columns]
        # Ajouter conductivité fusionnée si présente
        if CD_COND_FUSIONNE in pct_f.columns and CD_COND_FUSIONNE not in cols_pch:
            cols_pch.append(CD_COND_FUSIONNE)
        pct_f = pct_f[[c for c in cols_pch if c in pct_f.columns]]

    # Tri famille
    codes_ord = ordonner_par_famille(list(pct_f.columns))
    pct_f     = pct_f[[c for c in codes_ord if c in pct_f.columns]]
    codes_pch = list(pct_f.columns)

    # Aligner pivot_classes
    pc = pivot_classes.copy()
    if CD_COND_20 in pc.columns and CD_COND_FUSIONNE not in pc.columns:
        pc[CD_COND_FUSIONNE] = pc[CD_COND_20]

    stations  = list(pct_f.index)
    labels_s  = [_nom_court_station(lb_stations.get(s, s)) if lb_stations else s
                 for s in stations]
    labels_p  = [_lb_court_avec_ref(c, lb_map2) for c in codes_pch]

    ref_src = {}
    if df_ref_seuils is not None and "CdParametre" in df_ref_seuils.columns:
        ref_src = df_ref_seuils.set_index("CdParametre")["Source_retenue"].to_dict()

    if figsize is None:
        nc = len(codes_pch)
        figsize = (max(16, nc * 0.95 + 6), max(5, len(stations) * 0.95 + 3.5))

    fig = plt.figure(figsize=figsize)
    fig.suptitle(titre_bv, fontsize=13, fontweight="bold", y=1.02)
    gs  = GridSpec(1, 2, figure=fig, wspace=0.40)

    # --- Panneau gauche : classes qualité ---
    ax1 = fig.add_subplot(gs[0])
    color_matrix = np.zeros((len(stations), len(codes_pch), 3))
    for i, station in enumerate(stations):
        for j, code in enumerate(codes_pch):
            cl  = pc.loc[station, code] if code in pc.columns else "ND"
            color_matrix[i, j] = mcolors.to_rgb(
                PALETTE_CLASSES.get(cl, PALETTE_CLASSES["ND"])
            )
    ax1.imshow(color_matrix, aspect="auto", interpolation="nearest")

    for i, station in enumerate(stations):
        for j, code in enumerate(codes_pch):
            val = pct_f.iloc[i, j]
            cl  = pc.loc[station, code] if code in pc.columns else "ND"
            txt = f"{val:.2g}" if pd.notna(val) else "—"
            rgb = mcolors.to_rgb(PALETTE_CLASSES.get(cl, PALETTE_CLASSES["ND"]))
            lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
            ax1.text(j, i, txt, ha="center", va="center", fontsize=8,
                     color="white" if lum < 0.55 else "#222222", fontweight="bold")

    _ajouter_separateurs(ax1, codes_pch, orientation="vertical", couleur="#888888")
    _legende_classes(ax1)
    ax1.set_xticks(range(len(codes_pch)))
    ax1.set_xticklabels(labels_p, rotation=40, ha="right", fontsize=8.5)
    ax1.set_yticks(range(len(stations)))
    ax1.set_yticklabels(labels_s, fontsize=9)
    ax1.set_title("Classes de qualité (P90 / P10*)", fontsize=10, fontweight="bold")
    for x in np.arange(-0.5, len(codes_pch), 1):
        ax1.axvline(x, color="white", linewidth=0.6, alpha=0.5)
    for y in np.arange(-0.5, len(stations), 1):
        ax1.axhline(y, color="white", linewidth=0.6, alpha=0.5)
    ax1.tick_params(length=0)

    # --- Panneau droit : fréquences ---
    ax2 = fig.add_subplot(gs[1])
    df_dep = df_depassement.copy()
    if params_pch:
        df_dep = df_dep[df_dep["CdParametre"].isin(params_pch)]

    if df_dep.empty:
        ax2.text(0.5, 0.5, "Aucun dépassement disponible.",
                 ha="center", va="center", transform=ax2.transAxes, fontsize=10)
        ax2.axis("off")
    else:
        piv_dep = (df_dep.pivot_table(
            index="CdStation", columns="CdParametre",
            values="FreqDepass_pct", aggfunc="mean"
        ).reindex(index=stations).fillna(0))
        codes_dep = ordonner_par_famille(list(piv_dep.columns))
        codes_dep = [c for c in codes_dep if c in piv_dep.columns]
        piv_dep   = piv_dep[codes_dep]
        labels_dep = [_lb_court_avec_ref(c, lb_map2) for c in codes_dep]

        cmap_dep = mcolors.LinearSegmentedColormap.from_list(
            "dep", ["#ffffff", "#f7c94b", "#e07b39", "#c0392b"]
        )
        im2 = ax2.imshow(piv_dep.values, cmap=cmap_dep, aspect="auto",
                         vmin=0, vmax=100, interpolation="nearest")

        for i in range(len(stations)):
            for j in range(len(codes_dep)):
                val = piv_dep.iloc[i, j]
                ax2.text(j, i, f"{val:.0f}%", ha="center", va="center",
                         fontsize=8, fontweight="bold",
                         color="white" if val > 55 else "#333333")

        _ajouter_separateurs(ax2, codes_dep, orientation="vertical", couleur="#888888")
        plt.colorbar(im2, ax=ax2, label="Fréquence (%)", shrink=0.5)
        ax2.set_xticks(range(len(codes_dep)))
        ax2.set_xticklabels(labels_dep, rotation=40, ha="right", fontsize=8.5)
        ax2.set_yticks(range(len(stations)))
        ax2.set_yticklabels(labels_s, fontsize=9)
        ax2.set_title("Fréquences de dépassement seuil TBE/BE", fontsize=10, fontweight="bold")
        for x in np.arange(-0.5, len(codes_dep), 1):
            ax2.axvline(x, color="white", linewidth=0.6, alpha=0.5)
        for y in np.arange(-0.5, len(stations), 1):
            ax2.axhline(y, color="white", linewidth=0.6, alpha=0.5)
        ax2.tick_params(length=0)

    fig.text(0.01, -0.03,
             "* Référentiel SEQ-Eau v2 | Autres : DCE (état éco. ou NQE-MA) | "
             "P10 pour O₂, Sat. O₂ et pH borne MIN | P90 pour les autres paramètres",
             fontsize=8, color="#666666", style="italic")

    fig.tight_layout()
    _ajouter_watermark(fig, ax=fig.axes[0] if fig.axes else None)
    return fig


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from m01_import import importer_bdd
    from m02_nettoyage import nettoyer_et_pivoter
    from m07_referentiels import (fusionner_referentiels, selectionner_seuil_reference,
                                   calculer_frequence_depassement,
                                   CODES_PCH, CODES_NITRATES, CD_COND)

    chemin = sys.argv[1] if len(sys.argv) > 1 else None
    outdir = sys.argv[2] if len(sys.argv) > 2 else "/tmp"
    if not chemin:
        print("Usage: python m03_empreinte.py <csv> [outdir]"); sys.exit(1)

    print("Chargement…")
    res1      = importer_bdd(chemin, cd_support=3)
    res2      = nettoyer_et_pivoter(res1["df"], seuil_pch_pct=30, seuil_micropolluants_pct=10)
    df_ref    = fusionner_referentiels()
    df_seuils = selectionner_seuil_reference(df_ref, ph_borne="max", cond_borne="max")
    df_dep    = calculer_frequence_depassement(res2["df_clean"], df_ref)

    lb_stations = (res1["inventaire_stations"]
                   .set_index("CdStationMesureEauxSurface")["LbStationMesureEauxSurface"]
                   .to_dict())

    params_pch = [c for c in res2["pivot"].columns
                  if c in CODES_PCH | CODES_NITRATES | {1302} | CD_COND and c != CD_DEBIT]

    pivot_pct, pct_info = pivoter_percentile(res2["df_stats"], res2["params_retenus"])
    classes, rangs      = calculer_classes_pct(pivot_pct, df_seuils)

    print("Génération des figures…")
    figs = {
        "radar_superpose":   lambda: radar_stations(res2["pivot_norm"], res2["lb_map"],
                                lb_stations=lb_stations, mode="superpose",
                                titre="Profil chimique normalisé — Bienne et affluents"),
        "radar_grille":      lambda: radar_stations(res2["pivot_norm"], res2["lb_map"],
                                lb_stations=lb_stations, mode="grille",
                                titre="Profil chimique par station"),
        "heatmap_classes":   lambda: heatmap_stations(res2["pivot"], pivot_pct=pivot_pct,
                                pivot_classes=classes, df_ref_seuils=df_seuils,
                                lb_map=res2["lb_map"], lb_stations=lb_stations,
                                params_selectionnes=params_pch, pct_info=pct_info,
                                mode="classes_annot",
                                titre="Classes de qualité (P90/P10 selon paramètre)"),
        "heatmap_valeurs":   lambda: heatmap_stations(res2["pivot"], pivot_pct=pivot_pct,
                                lb_map=res2["lb_map"], lb_stations=lb_stations,
                                pct_info=pct_info, mode="valeurs",
                                titre="Profil chimique — valeurs relatives"),
        "heatmap_frequence": lambda: heatmap_frequence(df_dep, lb_stations=lb_stations,
                                lb_map=res2["lb_map"],
                                titre="Fréquences de dépassement du seuil TBE/BE"),
        "matrice_distances": lambda: matrice_distances(res2["pivot_norm"],
                                pivot_brut=res2["pivot"],
                                lb_stations=lb_stations,
                                titre="Distance chimique inter-stations"),
        "empreinte_complete":lambda: figure_empreinte_complete(
                                res2["pivot"], pivot_pct, classes, df_dep,
                                res2["lb_map"], df_ref_seuils=df_seuils,
                                lb_stations=lb_stations, params_pch=params_pch,
                                pct_info=pct_info,
                                titre_bv="Empreinte chimique — Bienne et affluents"),
    }

    for nom, fn in figs.items():
        fig = fn()
        path = f"{outdir}/m03_{nom}.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  → {path}")
    print("Terminé.")
