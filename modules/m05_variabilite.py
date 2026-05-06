"""
Module 05 — Variabilité temporelle (v2)
========================================
Analyse de la variabilité intra-station et des dynamiques temporelles
des profils chimiques.

Fonctions disponibles :
  - boxplots_stations()           : un graphique par paramètre, une boîte par station
  - series_temporelles()          : évolution chronologique, une ligne par station
  - saisonnalite_stations()       : profils mensuels médians/moyens, une ligne par station
  - figure_variabilite_complete() : appel groupé → dict de figures pour Streamlit

Conventions (identiques à M03/M04) :
  - Watermark @CDEau : bas à droite de la zone de tracé, #999999, alpha 0.60, 8pt
  - Police minimum 8pt sur toutes les figures
  - Palette stations : PALETTE_STATIONS (cyclique, identique M03/M04)
  - Paramètres groupés par famille SANDRE (Bilan O₂ → Azote → Phosphore → ...)
  - * en fin de titre = référentiel SEQ-Eau ; sans * = DCE
  - Débit (1420) exclu
  - Conductivité 20°C (1304) et 25°C (1303) traitées comme un seul paramètre

Seuils de qualité :
  - Lignes pointillées, couleur de la classe SUPÉRIEURE du seuil :
      TBE/BE → bleu  (#1a6faf, lw=0.8)
      BE/EMO → vert  (#74b74a, lw=1.0)
      EMO/EME→ jaune (#f7c94b, lw=1.3)
      EME/ME → orange(#e07b39, lw=1.6)
  - pH et conductivité : deux lignes de seuil (MIN + MAX)
  - Axe Y toujours étendu pour inclure le seuil TBE/BE

Entrées attendues :
  - df_clean    : DataFrame brut nettoyé (issu de m02), colonnes clés :
                  CdStationMesureEauxSurface, DatePrel, CdParametre,
                  Valeur (ou RsAna_val), SymUniteMesure
  - lb_map      : dict {CdParametre (int): LbLongParamètre (str)}
  - lb_stations : dict {CdStation: libellé court} (optionnel)
  - df_seuils   : DataFrame issu de m07.selectionner_seuil_reference() (optionnel)
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
from matplotlib.lines import Line2D
from typing import Optional

# ---------------------------------------------------------------------------
# Constantes (alignées avec M03/M04)
# ---------------------------------------------------------------------------

PALETTE_STATIONS = [
    "#2563eb", "#16a34a", "#dc2626", "#d97706",
    "#7c3aed", "#0891b2", "#be185d", "#4d7c0f",
]

PALETTE_CLASSES = {
    "TBE": "#1a6faf",
    "BE":  "#74b74a",
    "EMO": "#f7c94b",
    "EME": "#e07b39",
    "ME":  "#c0392b",
}

# Couleur du pointillé = couleur de la classe SUPÉRIEURE (meilleure) du seuil
# Seuil TBE/BE → couleur BE (vert) : on franchit vers le BE
# Seuil BE/EMO → couleur EMO (jaune) : on franchit vers l'EMO
# Seuil EMO/EME → couleur EME (orange) : on franchit vers l'EME
# Seuil EME/ME  → couleur ME (rouge) : on franchit vers le ME
COULEUR_SEUIL = {
    "TBE_BE":  PALETTE_CLASSES["BE"],    # vert   — frontière TBE/BE
    "BE_EMO":  PALETTE_CLASSES["EMO"],   # jaune  — frontière BE/EMO
    "EMO_EME": PALETTE_CLASSES["EME"],   # orange — frontière EMO/EME
    "EME_ME":  PALETTE_CLASSES["ME"],    # rouge  — frontière EME/ME
}
EPAISSEUR_SEUILS = {
    "TBE_BE":  0.8,
    "BE_EMO":  1.0,
    "EMO_EME": 1.3,
    "EME_ME":  1.6,
}

FAMILLES_ORDRE = [
    ("Bilan O\u2082",    [1311, 1312, 1313, 1314, 1841]),
    ("Azote",           [1335, 1339, 1340, 1319, 1551]),
    ("Phosphore",       [1433, 1350]),
    ("Proliférations",  [1436, 1439]),
    ("Minéralisation",  [1303, 1304, 1347, 1374, 1372, 1375, 1323, 1367]),
    ("MES/Turbidité",   [1305, 1295, 1297]),
    ("Acidification",   [1302]),
    ("Température",     [1301]),
    ("Micropolluants",  []),
]

CODES_SEQ_EAU = {
    1340, 1303, 1304, 1337, 1338, 1305, 1295, 1347,
    1372, 1374, 1375, 1323, 1314, 1319, 1436, 1439,
}

CD_DEBIT = 1420
CD_PH    = 1302
CD_COND  = {1303, 1304}

# Paramètres exemptés de la contrainte d'affichage du seuil TBE/BE
# (seuils très élevés qui décaleraient inutilement l'axe Y)
CODES_SANS_CONTRAINTE_YLIM = {1303, 1304, 1337, 1338}  # Conductivité, Cl⁻, SO₄²⁻

# Seuils bipolaires embarqués (même source que m07)
_PH_DCE = {
    "min": {"TBE_BE": 6.5,  "BE_EMO": 6.0,  "EMO_EME": 5.5,  "EME_ME": 4.5,  "Sens": ">"},
    "max": {"TBE_BE": 8.2,  "BE_EMO": 9.0,  "EMO_EME": 9.5,  "EME_ME": 10.0, "Sens": "<"},
}
_COND_SEQ = {
    "min": {"TBE_BE": 180,  "BE_EMO": 120,  "EMO_EME": 60,   "EME_ME": 0,    "Sens": ">"},
    "max": {"TBE_BE": 2500, "BE_EMO": 3000, "EMO_EME": 3500, "EME_ME": 4000, "Sens": "<"},
}

plt.rcParams.update({
    "font.family":       "DejaVu Sans",
    "font.size":         9,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.25,
    "figure.dpi":        120,
    "savefig.dpi":       200,
    "savefig.bbox":      "tight",
})

# ---------------------------------------------------------------------------
# Utilitaires internes
# ---------------------------------------------------------------------------

def _couleur_station(i: int) -> str:
    return PALETTE_STATIONS[i % len(PALETTE_STATIONS)]


def _nom_court_station(lb: str, max_len: int = 26) -> str:
    lb = lb.strip()
    return lb if len(lb) <= max_len else lb[:max_len - 1] + "\u2026"


def _ajouter_watermark(fig, ax=None, texte="@CDEau",
                       alpha=0.60, fontsize=8, couleur="#999999"):
    """Watermark discret en bas à droite de la zone de tracé."""
    cible = ax if ax is not None else (fig.axes[-1] if fig.axes else None)
    if cible is None:
        return
    cible.text(
        1.0, 0.0, texte,
        transform=cible.transAxes,
        fontsize=fontsize, color=couleur, alpha=alpha,
        ha="right", va="bottom",
        fontfamily="DejaVu Sans",
    )


def _ordonner_par_famille(codes: list) -> list:
    """Trie les codes selon l'ordre des familles M03."""
    ordre = {}
    for rang_fam, (_, codes_fam) in enumerate(FAMILLES_ORDRE[:-1]):
        for rang_param, c in enumerate(codes_fam):
            ordre[c] = (rang_fam, rang_param)
    return sorted(codes, key=lambda c: ordre.get(c, (len(FAMILLES_ORDRE) - 1, c)))


def _construire_unite_map(df_clean: pd.DataFrame) -> dict:
    """Construit {CdParametre: unité} depuis df_clean."""
    col_u = next((c for c in ["SymUniteMesure", "CdUniteMesure"] if c in df_clean.columns), None)
    if col_u is None:
        return {}
    tmp = (df_clean[["CdParametre", col_u]].dropna()
           .drop_duplicates("CdParametre")
           .set_index("CdParametre")[col_u].to_dict())
    return {int(k): str(v) for k, v in tmp.items()}


def _titre_param(code: int, lb_map: dict, unite_map: dict, max_len: int = 38) -> str:
    """
    'Libellé (unité)' + ' *' si SEQ-Eau.
    Conductivité 20°C affichée comme 'Conductivité (µS/cm)'.
    """
    lb = lb_map.get(code, str(code))
    # Fusion conductivité : label commun
    if code == 1304 and 1304 not in lb_map:
        lb = lb_map.get(1303, lb)
    unite = unite_map.get(code, unite_map.get(1303, "") if code == 1304 else "")
    suffix = " *" if code in CODES_SEQ_EAU else ""
    titre_base = f"{lb} ({unite})" if unite else lb
    if len(titre_base) > max_len:
        titre_base = titre_base[:max_len - 1] + "\u2026"
    return titre_base + suffix


def _preparer_df_long(df_clean: pd.DataFrame,
                      params_selectionnes: Optional[list] = None,
                      stations_selectionnees: Optional[list] = None,
                      ) -> tuple[pd.DataFrame, list]:
    """Prépare un DataFrame long (CdStation, DatePrel, CdParametre, Valeur)."""
    alertes = []
    df = df_clean.copy()

    col_station = "CdStationMesureEauxSurface"
    col_date    = "DatePrel"
    col_param   = "CdParametre"
    col_valeur  = "Valeur" if "Valeur" in df.columns else "RsAna_val"

    for col in [col_station, col_date, col_param, col_valeur]:
        if col not in df.columns:
            alertes.append(f"❌ M05 : colonne manquante '{col}' dans df_clean.")
            return pd.DataFrame(), alertes

    df = df[df[col_param] != CD_DEBIT]
    if params_selectionnes:
        df = df[df[col_param].isin(params_selectionnes)]
    if stations_selectionnees:
        df = df[df[col_station].isin(stations_selectionnees)]

    if df.empty:
        alertes.append("⚠️ M05 : aucune donnée après filtrage.")
        return pd.DataFrame(), alertes

    df = df.copy()
    df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors="coerce")
    n_inv = df[col_date].isna().sum()
    if n_inv > 0:
        alertes.append(f"⚠️ M05 : {n_inv} date(s) non parsée(s) — lignes ignorées.")
        df = df.dropna(subset=[col_date])

    cols = [col_station, col_date, col_param, col_valeur]
    for extra in ["LbStationMesureEauxSurface", "SymUniteMesure", "CdUniteMesure"]:
        if extra in df.columns:
            cols.append(extra)
    df = df[[c for c in cols if c in df.columns]].copy()
    df = df.rename(columns={
        col_station: "CdStation",
        col_date:    "DatePrel",
        col_param:   "CdParametre",
        col_valeur:  "Valeur",
        "LbStationMesureEauxSurface": "LbStation",
    })
    if "LbStation" not in df.columns:
        df["LbStation"] = df["CdStation"].astype(str)

    df["Valeur"] = pd.to_numeric(df["Valeur"], errors="coerce")
    df = df.dropna(subset=["Valeur"])
    return df, alertes


# ---------------------------------------------------------------------------
# Seuils : extraction et tracé
# ---------------------------------------------------------------------------

def _seuils_pour_code(code: int, df_seuils: Optional[pd.DataFrame]) -> list:
    """
    Retourne une liste de dicts de seuils pour le code.
    pH → 2 dicts (min + max). Conductivité → 2 dicts. Autres → 1 dict.
    Chaque dict : {label, TBE_BE, BE_EMO, EMO_EME, EME_ME, Sens}
    """
    if code == CD_PH:
        return [
            {"label": "pH min", **_PH_DCE["min"]},
            {"label": "pH max", **_PH_DCE["max"]},
        ]
    if code in CD_COND:
        return [
            {"label": "Cond. min", **_COND_SEQ["min"]},
            {"label": "Cond. max", **_COND_SEQ["max"]},
        ]
    if df_seuils is None or df_seuils.empty:
        return []
    rows = df_seuils[df_seuils["CdParametre"] == code]
    if rows.empty:
        return []
    row = rows.iloc[0]
    return [{
        "label":   str(row.get("LbParametre", code)),
        "TBE_BE":  row.get("TBE_BE"),
        "BE_EMO":  row.get("BE_EMO"),
        "EMO_EME": row.get("EMO_EME"),
        "EME_ME":  row.get("EME_ME"),
        "Sens":    row.get("Sens", "<"),
    }]


def _tracer_seuils(ax, code: int, df_seuils: Optional[pd.DataFrame]) -> list:
    """
    Trace les lignes de seuil en pointillés sur ax.
    Retourne la liste des valeurs TBE_BE trouvées (pour ajuster ylim).
    """
    seuils_list = _seuils_pour_code(code, df_seuils)
    vals_tbe_be = []

    for seuil in seuils_list:
        for cle, lw in EPAISSEUR_SEUILS.items():
            val = seuil.get(cle)
            if val is None:
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(val):
                continue
            ax.axhline(val, color=COULEUR_SEUIL[cle], lw=lw,
                       linestyle="--", alpha=0.82, zorder=2)
            if cle == "TBE_BE":
                vals_tbe_be.append(val)

    return vals_tbe_be


def _ajuster_ylim(ax, vals_data: pd.Series, vals_tbe_be: list,
                  sens: str = "<", marge: float = 0.12,
                  contrainte_tbe_be: bool = True):
    """
    Ajuste ylim pour que le seuil TBE/BE soit toujours visible.
    Si contrainte_tbe_be=False, adapte simplement aux données + marge.
    """
    if vals_data.empty:
        return
    ylo = vals_data.min()
    yhi = vals_data.max()
    plage = max(yhi - ylo, abs(yhi) * 0.05, 1e-9)

    if not vals_tbe_be or not contrainte_tbe_be:
        ax.set_ylim(max(0, ylo - marge * plage), yhi + marge * plage)
        return

    if sens == ">":
        y_max = max(yhi, max(vals_tbe_be)) + marge * plage
        y_min = ylo - marge * plage
    elif sens == "<":
        y_max = max(yhi, max(vals_tbe_be)) + marge * plage
        y_min = max(0, ylo - marge * plage)
    else:
        y_min = min(ylo, min(vals_tbe_be)) - marge * plage
        y_max = max(yhi, max(vals_tbe_be)) + marge * plage

    ax.set_ylim(y_min, y_max)


def _legende_seuils() -> list:
    """Retourne les handles Line2D pour la légende des seuils."""
    return [
        Line2D([0], [0], color=COULEUR_SEUIL[k], lw=EPAISSEUR_SEUILS[k],
               linestyle="--", alpha=0.85, label=lb)
        for k, lb in [
            ("TBE_BE",  "Seuil TBE/BE  (vert)"),
            ("BE_EMO",  "Seuil BE/EMO  (jaune)"),
            ("EMO_EME", "Seuil EMO/EME (orange)"),
            ("EME_ME",  "Seuil EME/ME  (rouge)"),
        ]
    ]


def _legende_commune(fig, stations: list, lb_stations: Optional[dict],
                     avec_seuils: bool = False):
    """Trace la légende commune stations (+ seuils si demandé) en bas de figure."""
    patches_st = [
        mpatches.Patch(
            color=_couleur_station(k),
            label=_nom_court_station(lb_stations.get(s, s)) if lb_stations else str(s),
        )
        for k, s in enumerate(stations)
    ]
    handles = patches_st + (_legende_seuils() if avec_seuils else [])
    ncol = min(len(handles), 8)
    titre_leg = "Stations & seuils de qualité" if avec_seuils else "Stations"
    fig.legend(
        handles=handles, fontsize=7, loc="lower center",
        ncol=ncol, framealpha=0.85,
        bbox_to_anchor=(0.5, -0.04),
        title=titre_leg, title_fontsize=7,
    )


# ---------------------------------------------------------------------------
# 1. Boxplots — un graphique par paramètre
# ---------------------------------------------------------------------------

def boxplots_stations(
    df_clean: pd.DataFrame,
    lb_map: dict,
    *,
    df_seuils: Optional[pd.DataFrame] = None,
    params_selectionnes: Optional[list] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    n_params_max: int = 30,
    n_colonnes: int = 4,
    titre: str = "Distribution des concentrations par station",
    figsize: Optional[tuple] = None,
    dpi: int = 150,
) -> tuple[plt.Figure, list]:
    """
    Un graphique par paramètre : distributions en boîtes à moustaches,
    une boîte colorée par station. Seuils en pointillés colorés.

    Returns (fig, alertes)
    """
    alertes = []
    df, msgs = _preparer_df_long(df_clean, params_selectionnes=params_selectionnes)
    alertes.extend(msgs)
    if df.empty:
        return plt.figure(), alertes

    unite_map = _construire_unite_map(df_clean)
    codes_ordonnes = _ordonner_par_famille(sorted(df["CdParametre"].unique()))

    if len(codes_ordonnes) > n_params_max:
        alertes.append(f"⚠️ M05 : affichage limité à {n_params_max} paramètres.")
        codes_ordonnes = codes_ordonnes[:n_params_max]
        df = df[df["CdParametre"].isin(codes_ordonnes)]

    stations = list(df["CdStation"].unique())
    if ordre_stations:
        stations = [s for s in ordre_stations if s in stations] + \
                   [s for s in stations if s not in ordre_stations]

    n_st  = len(stations)
    n_p   = len(codes_ordonnes)
    n_col = min(n_colonnes, n_p)
    n_row = int(np.ceil(n_p / n_col))

    if figsize is None:
        figsize = (n_col * 3.6, n_row * 3.6)

    fig, axes = plt.subplots(n_row, n_col, figsize=figsize, dpi=dpi, squeeze=False)

    width  = 0.70 / max(n_st, 1)
    offset = np.linspace(-0.35 + width / 2, 0.35 - width / 2, n_st)

    for idx, code in enumerate(codes_ordonnes):
        row_i, col_i = divmod(idx, n_col)
        ax = axes[row_i][col_i]
        df_p = df[df["CdParametre"] == code]
        vals_tous = df_p["Valeur"].dropna()

        for k, station in enumerate(stations):
            vals = df_p[df_p["CdStation"] == station]["Valeur"].dropna()
            if vals.empty:
                continue
            ax.boxplot(
                vals,
                positions=[offset[k]],
                widths=width * 0.85,
                patch_artist=True,
                showfliers=True,
                flierprops=dict(marker="o", markerfacecolor=_couleur_station(k),
                                markersize=3, alpha=0.5, linestyle="none",
                                markeredgecolor="none"),
                medianprops=dict(color="white", lw=1.8),
                boxprops=dict(facecolor=_couleur_station(k), alpha=0.75, linewidth=0.5),
                whiskerprops=dict(color=_couleur_station(k), lw=0.9),
                capprops=dict(color=_couleur_station(k), lw=0.9),
            )

        # Seuils
        vals_tbe_be = _tracer_seuils(ax, code, df_seuils)

        ax.set_title(_titre_param(code, lb_map, unite_map), fontsize=8,
                     fontweight="bold", pad=4)
        ax.set_xticks([])
        ax.set_xlim(-0.5, 0.5)
        ax.tick_params(axis="y", labelsize=7)

        if not vals_tous.empty:
            seuils_info = _seuils_pour_code(code, df_seuils)
            sens = seuils_info[0].get("Sens", "<") if seuils_info else "<"
            _ajuster_ylim(ax, vals_tous, vals_tbe_be, sens=sens,
                          contrainte_tbe_be=(code not in CODES_SANS_CONTRAINTE_YLIM))

        _ajouter_watermark(fig, ax=ax)

    for idx in range(n_p, n_row * n_col):
        row_i, col_i = divmod(idx, n_col)
        axes[row_i][col_i].set_visible(False)

    _legende_commune(fig, stations, lb_stations, avec_seuils=(df_seuils is not None))
    fig.suptitle(titre, fontsize=10, fontweight="bold", y=1.01)
    fig.tight_layout()

    alertes.append(f"ℹ️ Boxplots : {n_p} paramètre(s) × {n_st} station(s).")
    return fig, alertes


# ---------------------------------------------------------------------------
# 2. Séries temporelles
# ---------------------------------------------------------------------------

def series_temporelles(
    df_clean: pd.DataFrame,
    lb_map: dict,
    *,
    df_seuils: Optional[pd.DataFrame] = None,
    params_selectionnes: Optional[list] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    n_colonnes: int = 3,
    n_params_max: int = 18,
    afficher_points: bool = True,
    afficher_lissage: bool = True,
    titre: str = "Évolution temporelle des concentrations",
    figsize: Optional[tuple] = None,
    dpi: int = 150,
) -> tuple[plt.Figure, list]:
    """
    Séries chronologiques : un sous-graphe par paramètre, une ligne par station.
    Seuils en pointillés colorés. Axe Y toujours étendu au seuil TBE/BE.

    Returns (fig, alertes)
    """
    alertes = []
    df, msgs = _preparer_df_long(df_clean, params_selectionnes=params_selectionnes)
    alertes.extend(msgs)
    if df.empty:
        return plt.figure(), alertes

    unite_map = _construire_unite_map(df_clean)
    codes_ordonnes = _ordonner_par_famille(sorted(df["CdParametre"].unique()))

    if len(codes_ordonnes) > n_params_max:
        alertes.append(f"⚠️ M05 : affichage limité à {n_params_max} paramètres.")
        codes_ordonnes = codes_ordonnes[:n_params_max]
        df = df[df["CdParametre"].isin(codes_ordonnes)]

    stations = list(df["CdStation"].unique())
    if ordre_stations:
        stations = [s for s in ordre_stations if s in stations] + \
                   [s for s in stations if s not in ordre_stations]

    n_p   = len(codes_ordonnes)
    n_col = min(n_colonnes, n_p)
    n_row = int(np.ceil(n_p / n_col))

    if figsize is None:
        figsize = (n_col * 5.5, n_row * 3.4)

    fig, axes = plt.subplots(n_row, n_col, figsize=figsize, dpi=dpi, squeeze=False)

    for idx, code in enumerate(codes_ordonnes):
        row_i, col_i = divmod(idx, n_col)
        ax = axes[row_i][col_i]
        df_p = df[df["CdParametre"] == code].sort_values("DatePrel")
        vals_tous = df_p["Valeur"].dropna()

        for k, station in enumerate(stations):
            df_st = df_p[df_p["CdStation"] == station].sort_values("DatePrel")
            if df_st.empty:
                continue
            dates = df_st["DatePrel"]
            vals  = df_st["Valeur"]
            color = _couleur_station(k)
            lb_st = _nom_court_station(lb_stations.get(station, station)) \
                    if lb_stations else str(station)

            ax.plot(dates, vals, color=color, lw=1.2, alpha=0.65, zorder=3, label=lb_st)
            if afficher_points:
                ax.scatter(dates, vals, color=color, s=18, zorder=4,
                           edgecolors="white", linewidths=0.3)
            if afficher_lissage and len(vals) >= 3:
                ax.plot(dates, vals.rolling(3, center=True, min_periods=2).mean(),
                        color=color, lw=2.0, alpha=0.95, zorder=5)

        vals_tbe_be = _tracer_seuils(ax, code, df_seuils)

        ax.set_title(_titre_param(code, lb_map, unite_map), fontsize=8,
                     fontweight="bold", pad=4)
        ax.tick_params(labelsize=7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=6))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

        if not vals_tous.empty:
            seuils_info = _seuils_pour_code(code, df_seuils)
            sens = seuils_info[0].get("Sens", "<") if seuils_info else "<"
            _ajuster_ylim(ax, vals_tous, vals_tbe_be, sens=sens,
                          contrainte_tbe_be=(code not in CODES_SANS_CONTRAINTE_YLIM))

        _ajouter_watermark(fig, ax=ax)

    for idx in range(n_p, n_row * n_col):
        row_i, col_i = divmod(idx, n_col)
        axes[row_i][col_i].set_visible(False)

    _legende_commune(fig, stations, lb_stations, avec_seuils=(df_seuils is not None))
    fig.suptitle(titre, fontsize=10, fontweight="bold", y=1.01)
    fig.tight_layout()

    alertes.append(f"ℹ️ Séries temporelles : {n_p} paramètre(s) × {len(stations)} station(s).")
    return fig, alertes


# ---------------------------------------------------------------------------
# 3. Saisonnalité
# ---------------------------------------------------------------------------

def saisonnalite_stations(
    df_clean: pd.DataFrame,
    lb_map: dict,
    *,
    df_seuils: Optional[pd.DataFrame] = None,
    params_selectionnes: Optional[list] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    statistique: str = "mediane",
    n_colonnes: int = 3,
    n_params_max: int = 18,
    afficher_ic: bool = True,
    titre: str = "Profils saisonniers mensuels",
    figsize: Optional[tuple] = None,
    dpi: int = 150,
) -> tuple[plt.Figure, list]:
    """
    Profils mensuels médians/moyens : un sous-graphe par paramètre.
    Seuils en pointillés colorés. Axe Y toujours étendu au seuil TBE/BE.

    Returns (fig, alertes)
    """
    alertes = []
    if statistique not in ("mediane", "moyenne"):
        alertes.append(f"⚠️ statistique='{statistique}' inconnue — 'mediane' utilisée.")
        statistique = "mediane"

    df, msgs = _preparer_df_long(df_clean, params_selectionnes=params_selectionnes)
    alertes.extend(msgs)
    if df.empty:
        return plt.figure(), alertes

    unite_map = _construire_unite_map(df_clean)
    df = df.copy()
    df["Mois"] = df["DatePrel"].dt.month

    codes_ordonnes = _ordonner_par_famille(sorted(df["CdParametre"].unique()))

    if len(codes_ordonnes) > n_params_max:
        alertes.append(f"⚠️ M05 : affichage limité à {n_params_max} paramètres.")
        codes_ordonnes = codes_ordonnes[:n_params_max]
        df = df[df["CdParametre"].isin(codes_ordonnes)]

    stations = list(df["CdStation"].unique())
    if ordre_stations:
        stations = [s for s in ordre_stations if s in stations] + \
                   [s for s in stations if s not in ordre_stations]

    n_p   = len(codes_ordonnes)
    n_col = min(n_colonnes, n_p)
    n_row = int(np.ceil(n_p / n_col))

    if figsize is None:
        figsize = (n_col * 5.0, n_row * 3.2)

    fig, axes = plt.subplots(n_row, n_col, figsize=figsize, dpi=dpi, squeeze=False)
    mois_labels = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]

    for idx, code in enumerate(codes_ordonnes):
        row_i, col_i = divmod(idx, n_col)
        ax = axes[row_i][col_i]
        df_p = df[df["CdParametre"] == code]
        vals_tous = df_p["Valeur"].dropna()

        for k, station in enumerate(stations):
            df_st = df_p[df_p["CdStation"] == station]
            if df_st.empty:
                continue
            grp = df_st.groupby("Mois")["Valeur"]
            if statistique == "mediane":
                centre = grp.median()
                bas    = grp.quantile(0.25) if afficher_ic else None
                haut   = grp.quantile(0.75) if afficher_ic else None
            else:
                centre = grp.mean()
                std    = grp.std()
                bas    = (centre - std) if afficher_ic else None
                haut   = (centre + std) if afficher_ic else None

            color = _couleur_station(k)
            lb_st = _nom_court_station(lb_stations.get(station, station)) \
                    if lb_stations else str(station)

            ax.plot(centre.index, centre.values, color=color, lw=1.8,
                    marker="o", ms=4, zorder=4, label=lb_st)
            if afficher_ic and bas is not None and haut is not None:
                ax.fill_between(centre.index, bas.values, haut.values,
                                color=color, alpha=0.13, zorder=2)

        vals_tbe_be = _tracer_seuils(ax, code, df_seuils)

        ax.set_xticks(range(1, 13))
        ax.set_xticklabels(mois_labels, fontsize=8)
        ax.set_xlim(0.5, 12.5)
        ax.set_title(_titre_param(code, lb_map, unite_map), fontsize=8,
                     fontweight="bold", pad=4)
        ax.tick_params(axis="y", labelsize=7)

        if not vals_tous.empty:
            seuils_info = _seuils_pour_code(code, df_seuils)
            sens = seuils_info[0].get("Sens", "<") if seuils_info else "<"
            _ajuster_ylim(ax, vals_tous, vals_tbe_be, sens=sens,
                          contrainte_tbe_be=(code not in CODES_SANS_CONTRAINTE_YLIM))

        _ajouter_watermark(fig, ax=ax)

    for idx in range(n_p, n_row * n_col):
        row_i, col_i = divmod(idx, n_col)
        axes[row_i][col_i].set_visible(False)

    note_ic = (
        " (P25-P75)" if statistique == "mediane" and afficher_ic
        else " (\u00b11\u03c3)" if statistique == "moyenne" and afficher_ic
        else ""
    )
    alertes.append(
        f"ℹ️ Saisonnalité : {statistique}{note_ic} — "
        f"{n_p} paramètre(s) × {len(stations)} station(s)."
    )

    _legende_commune(fig, stations, lb_stations, avec_seuils=(df_seuils is not None))
    fig.suptitle(f"{titre}  ({statistique}{note_ic})",
                 fontsize=10, fontweight="bold", y=1.01)
    fig.tight_layout()

    return fig, alertes


# ---------------------------------------------------------------------------
# 4. Appel groupé — Streamlit ready
# ---------------------------------------------------------------------------

def figure_variabilite_complete(
    df_clean: pd.DataFrame,
    lb_map: dict,
    *,
    df_seuils: Optional[pd.DataFrame] = None,
    params_selectionnes: Optional[list] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    statistique_saison: str = "mediane",
    n_colonnes: int = 3,
    n_params_max: int = 18,
    afficher_lissage: bool = True,
    afficher_ic: bool = True,
    titre_global: str = "Variabilité temporelle — Chimie globale",
    dpi: int = 150,
) -> tuple[dict[str, plt.Figure], list]:
    """
    Génère boxplots, séries temporelles et saisonnalité en un seul appel.

    Parameters
    ----------
    df_seuils : DataFrame issu de m07.selectionner_seuil_reference()
                Si None, les seuils ne sont pas tracés.

    Returns
    -------
    dict : {"boxplots", "series", "saison"}
    alertes : liste de messages
    """
    alertes = []
    figures = {}

    fig, msgs = boxplots_stations(
        df_clean, lb_map, df_seuils=df_seuils,
        params_selectionnes=params_selectionnes,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        n_params_max=n_params_max, n_colonnes=n_colonnes,
        titre=f"{titre_global} — Distributions", dpi=dpi,
    )
    figures["boxplots"] = fig
    alertes.extend(msgs)

    fig, msgs = series_temporelles(
        df_clean, lb_map, df_seuils=df_seuils,
        params_selectionnes=params_selectionnes,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        n_colonnes=n_colonnes, n_params_max=n_params_max,
        afficher_lissage=afficher_lissage,
        titre=f"{titre_global} — Séries temporelles", dpi=dpi,
    )
    figures["series"] = fig
    alertes.extend(msgs)

    fig, msgs = saisonnalite_stations(
        df_clean, lb_map, df_seuils=df_seuils,
        params_selectionnes=params_selectionnes,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        statistique=statistique_saison,
        n_colonnes=n_colonnes, n_params_max=n_params_max,
        afficher_ic=afficher_ic,
        titre=f"{titre_global} — Saisonnalité", dpi=dpi,
    )
    figures["saison"] = fig
    alertes.extend(msgs)

    return figures, alertes


# ---------------------------------------------------------------------------
# Bloc de test autonome
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    print("Test M05 v2 — données synthétiques avec seuils")
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2020-01-01", periods=n, freq="14D")
    stations = ["ST_A", "ST_B", "ST_C"]
    params = [1311, 1340, 1433, 1301, 1302, 1303]
    rows = []
    for st in stations:
        for d in dates:
            for p in params:
                rows.append({
                    "CdStationMesureEauxSurface": st,
                    "LbStationMesureEauxSurface": f"Station {st[-1]}",
                    "DatePrel": d.strftime("%d/%m/%Y"),
                    "CdParametre": p,
                    "Valeur": max(0.01, np.random.lognormal(0, 0.8) +
                                  2 * np.sin(2 * np.pi * d.month / 12)),
                    "SymUniteMesure": {
                        1311: "mg/l O2", 1340: "mg/l NO3",
                        1433: "mg/l PO4", 1301: "\u00b0C",
                        1302: "upH", 1303: "\u00b5S/cm",
                    }.get(p, ""),
                })
    df_test = pd.DataFrame(rows)

    df_seuils_test = pd.DataFrame([
        {"CdParametre": 1311, "TBE_BE": 8.0,  "BE_EMO": 6.0,  "EMO_EME": 4.0,  "EME_ME": 3.0,  "Sens": ">"},
        {"CdParametre": 1340, "TBE_BE": 2.0,  "BE_EMO": 10.0, "EMO_EME": 25.0, "EME_ME": 50.0, "Sens": "<"},
        {"CdParametre": 1433, "TBE_BE": 0.1,  "BE_EMO": 0.5,  "EMO_EME": 1.0,  "EME_ME": 2.0,  "Sens": "<"},
        {"CdParametre": 1301, "TBE_BE": 20.0, "BE_EMO": 21.5, "EMO_EME": 25.0, "EME_ME": 28.0, "Sens": "<"},
    ])

    lb_map_t = {1311: "Oxygène dissous", 1340: "Nitrates",
                1433: "Orthophosphates", 1301: "Température de l'Eau",
                1302: "pH", 1303: "Conductivité à 25°C"}
    lb_st_t  = {"ST_A": "Amont", "ST_B": "Milieu", "ST_C": "Aval"}

    figs, alertes = figure_variabilite_complete(
        df_test, lb_map_t, df_seuils=df_seuils_test,
        lb_stations=lb_st_t, n_colonnes=3,
    )
    for a in alertes:
        print(a)
    os.makedirs("test_outputs", exist_ok=True)
    for nom, fig in figs.items():
        p = f"test_outputs/m05v2_{nom}.png"
        fig.savefig(p, dpi=130, bbox_inches="tight")
        print(f"  ✅ {p}")
