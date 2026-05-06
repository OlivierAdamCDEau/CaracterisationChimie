"""
Module 06 — Relation Concentration-Débit (C-Q) (v1)
=====================================================
Analyse de la relation chimio-dynamique entre concentrations et débits
pour la comparaison inter-stations de profils chimiques en eaux de surface.

Fonctions disponibles :
  - lire_hydroportail()        : importe un export Hydroportail (CSV journalier)
  - appariement_cq()           : fusionne chimie + débit (mode co-localisé ou hydro externe)
  - regression_cq()            : régression log-log C = a × Q^b par station × paramètre
  - classifier_comportement()  : classe chaque paire (station, paramètre) selon b
  - figure_cq_param()          : nuage C-Q + droite de régression, un graphe par paramètre
  - figure_cq_comportements()  : heatmap station × paramètre colorée par comportement
  - figure_cq_complete()       : appel groupé → dict de figures pour Streamlit

Deux modes d'apport de débit — EXCLUSIFS
─────────────────────────────────────────
Le mode est choisi explicitement via source= dans appariement_cq() et
figure_cq_complete(). Les deux modes ne peuvent pas être mélangés sur un
même graphique afin de garantir la comparabilité inter-stations.

Mode A — "colocal" — Débit co-localisé (issu de M01) :
  Seules les stations chimiques ayant leurs propres mesures de débit SANDRE
  (code 1420) participent à l'analyse. Les autres sont exclues avec alerte.
  Jointure : CdStation + date (tolérance ±1 jour).

Mode B — "hydro" — Station hydrométrique externe :
  Un fichier Hydroportail (chronique journalière) rattaché à un groupe de
  stations via rattachement {CdStation_chimie: id_hydro}.
  Toutes les stations rattachées partagent la même source → traitement homogène.
  Jointure : date uniquement (tolérance ±1 jour).

Pourquoi pas de mode mixte ?
  Mélanger débit co-localisé (8-10 points) et chronique hydro (centaines de
  points) crée un biais de traitement inter-stations non comparable.

Structure df_debit (M01, mode A) :
  CdStationMesureEauxSurface | DatePrel | Debit_m3s

Structure df_debit_hydro (Hydroportail, mode B) :
  DatePrel | Debit_m3s  [+ CdStation optionnel si multi-stations hydro]

Classification des comportements chimio-dynamiques
────────────────────────────────────────────────────
  b > +SEUIL_B  → Enrichissement  (concentration augmente avec le débit)
  b < -SEUIL_B  → Dilution        (concentration diminue avec le débit)
  |b| ≤ SEUIL_B → Constant/Mixte  (peu sensible au débit)
  Défaut SEUIL_B = 0.2 (ajustable)

Conventions graphiques (identiques M03/M04/M05) :
  - Watermark @CDEau, #999999, alpha 0.60, 8pt
  - Police minimum 8pt
  - Palette stations PALETTE_STATIONS (cyclique)
  - * en fin de libellé = SEQ-Eau ; sans * = DCE
  - Débit (1420) exclu des analyses chimiques
"""

import io
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from scipy import stats
from typing import Optional

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

PALETTE_STATIONS = [
    "#2563eb", "#16a34a", "#dc2626", "#d97706",
    "#7c3aed", "#0891b2", "#be185d", "#4d7c0f",
]

PALETTE_COMPORTEMENTS = {
    "Enrichissement": "#e07b39",   # orange
    "Dilution":       "#2563eb",   # bleu
    "Constant":       "#74b74a",   # vert
    "ND":             "#cccccc",   # gris (insuffisant)
}

CODES_SEQ_EAU = {
    1340, 1303, 1304, 1337, 1338, 1305, 1295, 1347,
    1372, 1374, 1375, 1323, 1314, 1319, 1436, 1439,
}

CD_DEBIT = 1420

# Seuil sur l'exposant b pour la classification
SEUIL_B = 0.2

# Nombre minimal de paires C-Q valides pour calculer une régression
N_MIN_PAIRES = 5

# Tolérance de jointure date (en jours)
TOLERANCE_JOURS = 1

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


def _lb_court(code: int, lb_map: dict, max_len: int = 24) -> str:
    lb = lb_map.get(code, str(code))
    suffix = " *" if code in CODES_SEQ_EAU else ""
    lb_base = lb[:max_len - len(suffix)] if len(lb) > max_len else lb
    return lb_base + suffix


def _ajouter_watermark(fig, ax=None, texte="@CDEau",
                       alpha=0.60, fontsize=8, couleur="#999999"):
    cible = ax if ax is not None else (fig.axes[-1] if fig.axes else None)
    if cible is None:
        return
    cible.text(
        1.0, 0.0, texte,
        transform=cible.transAxes,
        fontsize=fontsize, color=couleur, alpha=alpha,
        ha="right", va="bottom", fontfamily="DejaVu Sans",
    )


def _ordonner_par_famille(codes: list) -> list:
    ordre = {}
    for rang_fam, (_, codes_fam) in enumerate(FAMILLES_ORDRE[:-1]):
        for rang_param, c in enumerate(codes_fam):
            ordre[c] = (rang_fam, rang_param)
    return sorted(codes, key=lambda c: ordre.get(c, (len(FAMILLES_ORDRE) - 1, c)))


# ---------------------------------------------------------------------------
# 0. Import fichier Hydroportail
# ---------------------------------------------------------------------------

def lire_hydroportail(
    chemin: str,
    cd_station: Optional[str] = None,
    lb_station: Optional[str] = None,
    filtre_statut: Optional[list] = None,
) -> tuple[pd.DataFrame, list]:
    """
    Lit un export CSV Hydroportail (débits journaliers en m³/s).

    Le format Hydroportail est un CSV particulier : chaque ligne est encapsulée
    dans des guillemets externes, les guillemets internes sont doublés.
    En-tête : Date (TU), Valeur (en m³/s), Statut, Qualification, Méthode, Continuité
    Format date : ISO 8601 — 1990-01-01T00:00:00.000Z

    Parameters
    ----------
    chemin         : chemin du fichier CSV Hydroportail
    cd_station     : code station hydrométrique (pour traçabilité, optionnel)
    lb_station     : libellé station hydrométrique (pour traçabilité, optionnel)
    filtre_statut  : liste de codes Statut à conserver (ex. [16] = données validées).
                     None = conserver tout.

    Returns
    -------
    df_hydro : DataFrame [DatePrel, Debit_m3s, CdStation*, LbStation*]
               DatePrel normalisé en date (sans heure), Debit_m3s en m³/s
    alertes  : liste de messages
    """
    alertes = []

    try:
        with open(chemin, "r", encoding="utf-8") as f:
            raw_lines = f.readlines()
    except UnicodeDecodeError:
        with open(chemin, "r", encoding="latin-1") as f:
            raw_lines = f.readlines()

    # Dépliage du format Hydroportail : guillemets externes + doubles internes
    clean_lines = []
    for line in raw_lines:
        line = line.strip()
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1]
        line = line.replace('""', '"')
        clean_lines.append(line)

    try:
        df = pd.read_csv(io.StringIO("\n".join(clean_lines)))
    except Exception as e:
        alertes.append(f"❌ M06 lire_hydroportail : erreur lecture — {e}")
        return pd.DataFrame(), alertes

    # Renommage colonnes robuste (Hydroportail peut varier légèrement)
    rename_map = {}
    for col in df.columns:
        col_lower = col.lower()
        if "date" in col_lower:
            rename_map[col] = "DatePrel"
        elif "valeur" in col_lower or "m3" in col_lower or "m³" in col_lower:
            rename_map[col] = "Debit_m3s"
        elif "statut" in col_lower:
            rename_map[col] = "Statut"
    df = df.rename(columns=rename_map)

    if "DatePrel" not in df.columns or "Debit_m3s" not in df.columns:
        alertes.append(
            f"❌ M06 lire_hydroportail : colonnes Date/Valeur non trouvées. "
            f"Colonnes disponibles : {df.columns.tolist()}"
        )
        return pd.DataFrame(), alertes

    # Conversion date ISO 8601 → date (sans heure)
    df["DatePrel"] = pd.to_datetime(df["DatePrel"], utc=True, errors="coerce").dt.normalize().dt.tz_localize(None)
    n_inv = df["DatePrel"].isna().sum()
    if n_inv > 0:
        alertes.append(f"⚠️ M06 : {n_inv} date(s) Hydroportail non parsée(s) — ignorées.")
        df = df.dropna(subset=["DatePrel"])

    df["Debit_m3s"] = pd.to_numeric(df["Debit_m3s"], errors="coerce")

    # Filtre statut (ex. garder uniquement statut=16 = données validées)
    if filtre_statut and "Statut" in df.columns:
        n_avant = len(df)
        df = df[df["Statut"].isin(filtre_statut)]
        alertes.append(
            f"ℹ️ Hydroportail : filtre statut {filtre_statut} → "
            f"{len(df)}/{n_avant} lignes conservées."
        )

    df = df.dropna(subset=["Debit_m3s"])
    df = df[["DatePrel", "Debit_m3s"]].copy()

    # Traçabilité station
    if cd_station:
        df["CdStation"] = cd_station
    if lb_station:
        df["LbStation"] = lb_station

    alertes.append(
        f"ℹ️ Hydroportail : {len(df)} jours | "
        f"{df['DatePrel'].min().date()} → {df['DatePrel'].max().date()} | "
        f"Q moy={df['Debit_m3s'].mean():.3f} m³/s | "
        f"Q max={df['Debit_m3s'].max():.3f} m³/s"
    )

    return df, alertes


# ---------------------------------------------------------------------------
# 1. Appariement C-Q
# ---------------------------------------------------------------------------

def appariement_cq(
    df_clean: pd.DataFrame,
    lb_map: dict,
    *,
    source: str = "colocal",
    df_debit: Optional[pd.DataFrame] = None,
    df_debit_hydro: Optional[pd.DataFrame] = None,
    rattachement: Optional[dict] = None,
    tolerance_jours: int = TOLERANCE_JOURS,
    params_selectionnes: Optional[list] = None,
    stations_selectionnees: Optional[list] = None,
) -> tuple[pd.DataFrame, list]:
    """
    Fusionne les données chimiques et les données de débit.

    DEUX MODES EXCLUSIFS — choisir via source= :
    ──────────────────────────────────────────────
    source="colocal" (Mode A) :
      Seules les stations ayant leurs propres mesures de débit SANDRE (code 1420,
      issu de M01 via df_debit) participent. Les stations sans débit co-localisé
      sont exclues avec alerte explicite.
      Jointure : CdStation + date (±tolerance_jours).
      Minimum : N_MIN_PAIRES paires valides par station×paramètre.

    source="hydro" (Mode B) :
      Toutes les stations chimiques rattachées à une station hydrométrique externe
      (df_debit_hydro, issu de lire_hydroportail()) reçoivent le même débit.
      Traitement homogène → comparaison inter-stations non biaisée.
      rattachement : dict {CdStation_chimie: id_hydro} pour multi-hydro,
                     ou None si df_debit_hydro s'applique à toutes les stations.
      Jointure : date uniquement (±tolerance_jours).

    ⚠️  Pas de mode mixte : mélanger débits co-localisés (quelques points) et
    chronique hydro (centaines de points) rendrait les nuages C-Q et les R²
    incomparables entre stations d'un même graphique.

    Parameters
    ----------
    df_clean        : DataFrame brut nettoyé issu de M02
    lb_map          : dict {CdParametre: libellé}
    source          : "colocal" ou "hydro" (défaut "colocal")
    df_debit        : DataFrame débit co-localisé M01 [CdStationMesureEauxSurface,
                      DatePrel, Debit_m3s] — requis si source="colocal"
    df_debit_hydro  : DataFrame Hydroportail [DatePrel, Debit_m3s]
                      issu de lire_hydroportail() — requis si source="hydro"
    rattachement    : dict {CdStation_chimie: id_hydro} (source="hydro" uniquement)
                      None = toutes les stations partagent df_debit_hydro
    tolerance_jours : tolérance jointure date en jours (défaut 1)
    params_selectionnes    : liste codes paramètres (None = tous sauf débit)
    stations_selectionnees : liste codes stations  (None = toutes)

    Returns
    -------
    df_cq   : DataFrame [CdStation, LbStation, DatePrel, CdParametre,
                         Concentration, Debit_m3s, Source_debit]
              Source_debit : "colocal" | "hydro"
    alertes : liste de messages
    """
    alertes = []

    if source not in ("colocal", "hydro"):
        alertes.append(f"❌ M06 : source='{source}' invalide. Choisir 'colocal' ou 'hydro'.")
        return pd.DataFrame(), alertes

    if source == "colocal" and (df_debit is None or df_debit.empty):
        alertes.append("❌ M06 (mode colocal) : df_debit absent ou vide. "
                       "Fournir les débits co-localisés issus de M01.")
        return pd.DataFrame(), alertes

    if source == "hydro" and (df_debit_hydro is None or df_debit_hydro.empty):
        alertes.append("❌ M06 (mode hydro) : df_debit_hydro absent ou vide. "
                       "Charger un fichier Hydroportail via lire_hydroportail().")
        return pd.DataFrame(), alertes

    alertes.append(f"ℹ️ M06 : mode débit = '{source}'.")

    # --- Préparer df_chimie ---
    col_station = "CdStationMesureEauxSurface"
    col_date    = "DatePrel"
    col_param   = "CdParametre"
    col_valeur  = "Valeur" if "Valeur" in df_clean.columns else "RsAna_val"

    for col in [col_station, col_date, col_param, col_valeur]:
        if col not in df_clean.columns:
            alertes.append(f"❌ M06 : colonne '{col}' manquante dans df_clean.")
            return pd.DataFrame(), alertes

    df_chim = df_clean[df_clean[col_param] != CD_DEBIT].copy()
    if params_selectionnes:
        df_chim = df_chim[df_chim[col_param].isin(params_selectionnes)]
    if stations_selectionnees:
        df_chim = df_chim[df_chim[col_station].isin(stations_selectionnees)]

    cols_chim = [col_station, col_date, col_param, col_valeur]
    if "LbStationMesureEauxSurface" in df_clean.columns:
        df_chim = df_chim.copy()
        df_chim["LbStation"] = df_clean.loc[df_chim.index, "LbStationMesureEauxSurface"]
        cols_chim.append("LbStation")

    df_chim = df_chim[[c for c in cols_chim if c in df_chim.columns]].copy()
    df_chim = df_chim.rename(columns={
        col_station: "CdStation",
        col_date:    "DatePrel",
        col_param:   "CdParametre",
        col_valeur:  "Concentration",
    })
    if "LbStation" not in df_chim.columns:
        df_chim["LbStation"] = df_chim["CdStation"].astype(str)

    df_chim["DatePrel"] = pd.to_datetime(df_chim["DatePrel"], dayfirst=True, errors="coerce")
    df_chim["Concentration"] = pd.to_numeric(df_chim["Concentration"], errors="coerce")
    df_chim = df_chim.dropna(subset=["DatePrel", "Concentration"])
    df_chim["DatePrel"] = df_chim["DatePrel"].dt.normalize()

    # --- Jointure avec tolérance (commune aux deux modes) ---
    def _jointure_proche(df_g: pd.DataFrame, df_q: pd.DataFrame) -> pd.DataFrame:
        if df_g.empty or df_q.empty:
            return pd.DataFrame()
        g = df_g.sort_values("DatePrel").copy()
        q = df_q.sort_values("DatePrel")[["DatePrel", "Debit_m3s", "Source_debit"]].copy()
        merged = pd.merge_asof(
            g, q, on="DatePrel",
            direction="nearest",
            tolerance=pd.Timedelta(days=tolerance_jours),
        )
        return merged.dropna(subset=["Debit_m3s"])

    resultats = []
    stations_traitees = df_chim["CdStation"].unique()

    # ── Mode A : co-localisé ──
    if source == "colocal":
        df_q = df_debit.copy()
        col_st_q = "CdStationMesureEauxSurface" if "CdStationMesureEauxSurface" in df_q.columns \
                   else "CdStation"
        df_q = df_q.rename(columns={col_st_q: "CdStation"})
        df_q["DatePrel"] = pd.to_datetime(df_q["DatePrel"], dayfirst=True, errors="coerce").dt.normalize()
        df_q["Debit_m3s"] = pd.to_numeric(df_q["Debit_m3s"], errors="coerce")
        df_q = df_q.dropna(subset=["Debit_m3s"])
        df_q["Source_debit"] = "colocal"
        stations_avec_debit = set(df_q["CdStation"].unique())

        for station in stations_traitees:
            if station not in stations_avec_debit:
                lb = df_chim.loc[df_chim["CdStation"] == station, "LbStation"].iloc[0] \
                     if not df_chim[df_chim["CdStation"] == station].empty else station
                alertes.append(
                    f"⚠️ Mode colocal : station '{lb}' ({station}) sans débit co-localisé "
                    f"→ exclue de l'analyse C-Q."
                )
                continue
            df_st = df_chim[df_chim["CdStation"] == station].copy()
            q_st  = df_q[df_q["CdStation"] == station]
            merged = _jointure_proche(df_st, q_st)
            if not merged.empty:
                resultats.append(merged)
            else:
                alertes.append(
                    f"⚠️ Mode colocal : aucune paire appariée pour station {station} "
                    f"(écart date > {tolerance_jours} j ?)."
                )

    # ── Mode B : hydro externe ──
    elif source == "hydro":
        df_q_hydro = df_debit_hydro.copy()
        df_q_hydro["DatePrel"] = pd.to_datetime(df_q_hydro["DatePrel"], errors="coerce").dt.normalize()
        df_q_hydro["Debit_m3s"] = pd.to_numeric(df_q_hydro["Debit_m3s"], errors="coerce")
        df_q_hydro = df_q_hydro.dropna(subset=["Debit_m3s"])
        df_q_hydro["Source_debit"] = "hydro"

        for station in stations_traitees:
            df_st = df_chim[df_chim["CdStation"] == station].copy()

            # Sélection de la chronique hydro selon le rattachement
            if rattachement is not None:
                hydro_id = rattachement.get(station)
                if hydro_id is None:
                    lb = df_st["LbStation"].iloc[0] if not df_st.empty else station
                    alertes.append(
                        f"⚠️ Mode hydro : station '{lb}' ({station}) absente du dict "
                        f"rattachement → exclue."
                    )
                    continue
                # Si df_debit_hydro a une colonne CdStation (multi-hydro)
                if "CdStation" in df_q_hydro.columns:
                    q_hydro_st = df_q_hydro[df_q_hydro["CdStation"] == hydro_id]
                    if q_hydro_st.empty:
                        alertes.append(
                            f"⚠️ Mode hydro : id_hydro='{hydro_id}' introuvable dans "
                            f"df_debit_hydro pour station {station}."
                        )
                        continue
                else:
                    q_hydro_st = df_q_hydro
            else:
                q_hydro_st = df_q_hydro

            merged = _jointure_proche(df_st, q_hydro_st)
            if not merged.empty:
                resultats.append(merged)
            else:
                alertes.append(
                    f"⚠️ Mode hydro : aucune paire appariée pour station {station}."
                )

    if not resultats:
        alertes.append("❌ M06 : aucune paire C-Q construite — vérifier les dates et le mode.")
        return pd.DataFrame(), alertes

    df_cq = pd.concat(resultats, ignore_index=True)
    n_st = df_cq["CdStation"].nunique()
    n_p  = df_cq["CdParametre"].nunique()
    alertes.append(
        f"ℹ️ M06 appariement ({source}) : {len(df_cq)} paires C-Q | "
        f"{n_st} station(s) | {n_p} paramètre(s)."
    )
    return df_cq, alertes


# ---------------------------------------------------------------------------
# 2. Régression log-log C = a × Q^b
# ---------------------------------------------------------------------------

def regression_cq(
    df_cq: pd.DataFrame,
    *,
    n_min: int = N_MIN_PAIRES,
    seuil_b: float = SEUIL_B,
) -> tuple[pd.DataFrame, list]:
    """
    Régression log-log C = a × Q^b par (CdStation × CdParametre).
    Modèle : log(C) = log(a) + b × log(Q)  → régression linéaire sur log-log.

    Valeurs nulles ou négatives de C ou Q exclues avant régression.

    Parameters
    ----------
    df_cq  : DataFrame issu de appariement_cq()
    n_min  : nombre minimal de paires valides pour calculer la régression
    seuil_b: seuil |b| pour la classification comportementale

    Returns
    -------
    df_reg : DataFrame [CdStation, LbStation, CdParametre, n_paires,
                        a, b, r2, p_value, Comportement]
    alertes
    """
    alertes = []
    resultats = []

    if df_cq.empty:
        alertes.append("❌ M06 regression_cq : df_cq vide.")
        return pd.DataFrame(), alertes

    groupes = df_cq.groupby(["CdStation", "CdParametre"])

    for (station, code), grp in groupes:
        # Valeurs strictement positives uniquement
        masque = (grp["Concentration"] > 0) & (grp["Debit_m3s"] > 0)
        data = grp[masque].dropna(subset=["Concentration", "Debit_m3s"])

        n = len(data)
        lb_station = data["LbStation"].iloc[0] if "LbStation" in data.columns else str(station)

        if n < n_min:
            resultats.append({
                "CdStation": station, "LbStation": lb_station,
                "CdParametre": code, "n_paires": n,
                "a": np.nan, "b": np.nan, "r2": np.nan,
                "p_value": np.nan, "Comportement": "ND",
                "Source_debit": data["Source_debit"].iloc[0] if not data.empty else "?",
            })
            continue

        log_q = np.log(data["Debit_m3s"].values)
        log_c = np.log(data["Concentration"].values)

        slope, intercept, r_value, p_value, _ = stats.linregress(log_q, log_c)

        b = slope
        a = np.exp(intercept)
        r2 = r_value ** 2

        comportement = classifier_comportement(b, seuil_b=seuil_b)

        resultats.append({
            "CdStation":    station,
            "LbStation":    lb_station,
            "CdParametre":  code,
            "n_paires":     n,
            "a":            round(a, 6),
            "b":            round(b, 4),
            "r2":           round(r2, 4),
            "p_value":      round(p_value, 6),
            "Comportement": comportement,
            "Source_debit": data["Source_debit"].iloc[0],
        })

    df_reg = pd.DataFrame(resultats)

    # Résumé comportements
    if not df_reg.empty:
        compt = df_reg["Comportement"].value_counts().to_dict()
        alertes.append(
            f"ℹ️ Régression C-Q : {len(df_reg)} couples station×paramètre — "
            + ", ".join(f"{k}: {v}" for k, v in compt.items())
        )
        n_nd = (df_reg["Comportement"] == "ND").sum()
        if n_nd > 0:
            alertes.append(
                f"⚠️ {n_nd} couple(s) avec < {n_min} paires valides → classés ND."
            )

    return df_reg, alertes


def classifier_comportement(b: float, seuil_b: float = SEUIL_B) -> str:
    """
    Classe l'exposant b de la relation C-Q.

    b > +seuil_b  → Enrichissement  (lessivage, apports avec la crue)
    b < -seuil_b  → Dilution        (paramètre dilué par l'eau supplémentaire)
    |b| ≤ seuil_b → Constant        (tamponné, peu sensible au débit)
    """
    if np.isnan(b):
        return "ND"
    if b > seuil_b:
        return "Enrichissement"
    if b < -seuil_b:
        return "Dilution"
    return "Constant"


# ---------------------------------------------------------------------------
# 3. Figure C-Q par paramètre — nuages de points + droites de régression
# ---------------------------------------------------------------------------

def figure_cq_param(
    df_cq: pd.DataFrame,
    df_reg: pd.DataFrame,
    lb_map: dict,
    *,
    params_selectionnes: Optional[list] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    n_colonnes: int = 3,
    n_params_max: int = 18,
    afficher_droite: bool = True,
    afficher_ic: bool = True,
    titre: str = "Relation Concentration-Débit (C-Q)",
    figsize: Optional[tuple] = None,
    dpi: int = 150,
) -> tuple[plt.Figure, list]:
    """
    Un sous-graphe par paramètre : nuage de points C vs Q (axes log-log),
    une couleur par station. Droite de régression + IC 95 % optionnels.
    Annotation b et R² dans chaque sous-graphe.

    Returns (fig, alertes)
    """
    alertes = []

    if df_cq.empty:
        alertes.append("❌ M06 figure_cq_param : df_cq vide.")
        return plt.figure(), alertes

    codes_presents = sorted(df_cq["CdParametre"].unique())
    if params_selectionnes:
        codes_presents = [c for c in codes_presents if c in params_selectionnes]
    codes_ordonnes = _ordonner_par_famille(codes_presents)

    if len(codes_ordonnes) > n_params_max:
        alertes.append(f"⚠️ M06 : affichage limité à {n_params_max} paramètres.")
        codes_ordonnes = codes_ordonnes[:n_params_max]

    stations = list(df_cq["CdStation"].unique())
    if ordre_stations:
        stations = [s for s in ordre_stations if s in stations] + \
                   [s for s in stations if s not in ordre_stations]

    n_p   = len(codes_ordonnes)
    n_col = min(n_colonnes, n_p)
    n_row = int(np.ceil(n_p / n_col))

    if figsize is None:
        figsize = (n_col * 5.2, n_row * 4.0)

    fig, axes = plt.subplots(n_row, n_col, figsize=figsize, dpi=dpi, squeeze=False)

    for idx, code in enumerate(codes_ordonnes):
        row_i, col_i = divmod(idx, n_col)
        ax = axes[row_i][col_i]

        df_p = df_cq[df_cq["CdParametre"] == code].copy()
        df_p = df_p[(df_p["Concentration"] > 0) & (df_p["Debit_m3s"] > 0)]

        annots = []  # annotations b / R²

        for k, station in enumerate(stations):
            df_st = df_p[df_p["CdStation"] == station]
            if df_st.empty:
                continue

            color = _couleur_station(k)
            lb_st = _nom_court_station(lb_stations.get(station, station)) \
                    if lb_stations else str(station)

            ax.scatter(
                df_st["Debit_m3s"], df_st["Concentration"],
                color=color, s=22, alpha=0.75, zorder=4,
                edgecolors="white", linewidths=0.3,
                label=lb_st,
            )

            # Droite de régression
            if afficher_droite and df_reg is not None and not df_reg.empty:
                reg_row = df_reg[
                    (df_reg["CdStation"] == station) &
                    (df_reg["CdParametre"] == code)
                ]
                if not reg_row.empty:
                    r = reg_row.iloc[0]
                    if not np.isnan(r["a"]) and not np.isnan(r["b"]):
                        q_range = np.logspace(
                            np.log10(df_st["Debit_m3s"].min()),
                            np.log10(df_st["Debit_m3s"].max()),
                            50,
                        )
                        c_pred = r["a"] * q_range ** r["b"]
                        ax.plot(q_range, c_pred, color=color, lw=1.5,
                                alpha=0.85, zorder=5)

                        comp = r["Comportement"]
                        annots.append(
                            f"{lb_st[:12]} : b={r['b']:+.2f} R²={r['r2']:.2f}"
                            f" [{comp[0]}]"  # E/D/C/N
                        )

        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Débit (m³/s)", fontsize=8)
        ax.set_ylabel(_lb_court(code, lb_map), fontsize=8)
        ax.set_title(_lb_court(code, lb_map, max_len=30), fontsize=8,
                     fontweight="bold", pad=4)
        ax.tick_params(labelsize=7)

        # Annotations b/R² (coins supérieur gauche)
        if annots:
            txt = "\n".join(annots)
            ax.text(0.03, 0.97, txt, transform=ax.transAxes,
                    fontsize=7, va="top", ha="left",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="#cccccc", alpha=0.85))

        _ajouter_watermark(fig, ax=ax)

    for idx in range(n_p, n_row * n_col):
        row_i, col_i = divmod(idx, n_col)
        axes[row_i][col_i].set_visible(False)

    # Légende comportements
    leg_comp = [
        mpatches.Patch(color=PALETTE_COMPORTEMENTS[c], label=f"{c} (b)")
        for c in ["Enrichissement", "Dilution", "Constant", "ND"]
    ]
    # Légende stations
    patches_st = [
        mpatches.Patch(
            color=_couleur_station(k),
            label=_nom_court_station(lb_stations.get(s, s)) if lb_stations else str(s),
        )
        for k, s in enumerate(stations)
    ]
    fig.legend(
        handles=patches_st,
        fontsize=7, loc="lower center",
        ncol=min(len(patches_st), 6), framealpha=0.85,
        bbox_to_anchor=(0.5, -0.04),
        title="Stations  (annotation : E=Enrichissement D=Dilution C=Constant N=ND)",
        title_fontsize=7,
    )

    fig.suptitle(titre, fontsize=10, fontweight="bold", y=1.01)
    fig.tight_layout()

    alertes.append(f"ℹ️ Figure C-Q : {n_p} paramètre(s) × {len(stations)} station(s).")
    return fig, alertes


# ---------------------------------------------------------------------------
# 4. Heatmap des comportements chimio-dynamiques
# ---------------------------------------------------------------------------

def figure_cq_comportements(
    df_reg: pd.DataFrame,
    lb_map: dict,
    *,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    titre: str = "Comportements chimio-dynamiques (C-Q)",
    figsize: Optional[tuple] = None,
    dpi: int = 150,
    r2_min: float = 0.20,
) -> tuple[plt.Figure, list]:
    """
    Heatmap station (lignes) × paramètre (colonnes) colorée par comportement C-Q.
    Paramètres ordonnés par famille. Annotations b et R² dans chaque cellule.
    Cellules grisées si R² < r2_min (régression peu fiable).

    Parameters
    ----------
    df_reg  : DataFrame issu de regression_cq()
    lb_map  : dict {CdParametre: libellé}
    r2_min  : R² minimum pour afficher la couleur de comportement
              (en dessous → affiché en gris clair avec annotation italique)

    Returns (fig, alertes)
    """
    alertes = []

    if df_reg.empty:
        alertes.append("❌ M06 figure_cq_comportements : df_reg vide.")
        return plt.figure(), alertes

    # Ordres
    codes = _ordonner_par_famille(sorted(df_reg["CdParametre"].unique()))
    stations = sorted(df_reg["CdStation"].unique())
    if ordre_stations:
        stations = [s for s in ordre_stations if s in stations] + \
                   [s for s in stations if s not in ordre_stations]

    n_st = len(stations)
    n_p  = len(codes)

    if figsize is None:
        # Hauteur augmentée pour laisser de la place à la légende sous les labels X
        figsize = (max(8, n_p * 1.1), max(3, n_st * 0.85 + 2.5))

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    for j, code in enumerate(codes):
        for i, station in enumerate(stations):
            row = df_reg[
                (df_reg["CdStation"] == station) &
                (df_reg["CdParametre"] == code)
            ]
            if row.empty:
                # Cellule vide (pas de données)
                rect = plt.Rectangle([j - 0.5, i - 0.5], 1, 1,
                                     facecolor="#eeeeee", edgecolor="white", lw=0.5)
                ax.add_patch(rect)
                ax.text(j, i, "–", ha="center", va="center",
                        fontsize=7, color="#aaaaaa")
                continue

            r = row.iloc[0]
            comp = r["Comportement"]
            r2   = r["r2"] if not np.isnan(r.get("r2", np.nan)) else np.nan
            b    = r["b"]  if not np.isnan(r.get("b", np.nan))  else np.nan

            # Couleur : gris si ND ou R² faible
            if comp == "ND" or (not np.isnan(r2) and r2 < r2_min):
                couleur = "#dddddd"
                style_txt = "italic"
            else:
                couleur = PALETTE_COMPORTEMENTS.get(comp, "#cccccc")
                style_txt = "normal"

            rect = plt.Rectangle([j - 0.5, i - 0.5], 1, 1,
                                  facecolor=couleur, edgecolor="white", lw=0.8,
                                  alpha=0.85)
            ax.add_patch(rect)

            # Annotation b / R²
            txt_b  = f"b={b:+.2f}"  if not np.isnan(b)  else ""
            txt_r2 = f"R²={r2:.2f}" if not np.isnan(r2) else ""
            txt = f"{txt_b}\n{txt_r2}" if txt_b and txt_r2 else txt_b or txt_r2 or "ND"
            ax.text(j, i, txt, ha="center", va="center",
                    fontsize=6.5, fontstyle=style_txt,
                    color="white" if comp in ("Enrichissement", "Dilution") else "#333333")

    ax.set_xlim(-0.5, n_p - 0.5)
    ax.set_ylim(-0.5, n_st - 0.5)
    ax.set_xticks(range(n_p))
    ax.set_xticklabels(
        [_lb_court(c, lb_map, max_len=18) for c in codes],
        rotation=45, ha="right", fontsize=8,
    )
    ax.set_yticks(range(n_st))
    ax.set_yticklabels(
        [_nom_court_station(lb_stations.get(s, s)) if lb_stations else str(s)
         for s in stations],
        fontsize=8,
    )
    ax.set_title(titre, fontsize=10, fontweight="bold", pad=10)
    ax.tick_params(length=0)
    ax.set_aspect("equal", adjustable="box")

    # Légende comportements — en dessous de la figure, après les labels X inclinés
    leg = [
        mpatches.Patch(color=PALETTE_COMPORTEMENTS["Enrichissement"], label="Enrichissement (b > 0)"),
        mpatches.Patch(color=PALETTE_COMPORTEMENTS["Dilution"],       label="Dilution (b < 0)"),
        mpatches.Patch(color=PALETTE_COMPORTEMENTS["Constant"],       label="Constant (|b| faible)"),
        mpatches.Patch(color="#dddddd", label=f"ND ou R² < {r2_min:.2f}"),
    ]
    fig.legend(
        handles=leg, fontsize=7,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.02),
        ncol=4, framealpha=0.85,
        title="Comportement chimio-dynamique", title_fontsize=7,
    )

    _ajouter_watermark(fig, ax=ax)
    fig.tight_layout()

    alertes.append(
        f"ℹ️ Heatmap C-Q : {n_p} paramètre(s) × {n_st} station(s) | "
        f"seuil R² affiché : {r2_min:.2f}."
    )
    return fig, alertes


# ---------------------------------------------------------------------------
# 5. Appel groupé — Streamlit ready
# ---------------------------------------------------------------------------

def figure_cq_complete(
    df_clean: pd.DataFrame,
    lb_map: dict,
    *,
    source: str = "colocal",
    df_debit: Optional[pd.DataFrame] = None,
    df_debit_hydro: Optional[pd.DataFrame] = None,
    rattachement: Optional[dict] = None,
    params_selectionnes: Optional[list] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    n_colonnes: int = 3,
    n_params_max: int = 18,
    seuil_b: float = SEUIL_B,
    r2_min: float = 0.20,
    titre_global: str = "Relation C-Q — Chimie globale",
    dpi: int = 150,
) -> tuple[dict[str, plt.Figure], pd.DataFrame, list]:
    """
    Pipeline complet C-Q en un seul appel.

    Parameters
    ----------
    source : "colocal" (débits co-localisés M01) ou "hydro" (Hydroportail externe).
             Les deux modes sont exclusifs — voir appariement_cq() pour le détail.

    Returns
    -------
    figures : {"cq_params", "cq_comportements"}
    df_reg  : DataFrame des régressions (pour export M08 ou affichage Streamlit)
    alertes : liste de messages
    """
    alertes = []
    figures = {}

    df_cq, msgs = appariement_cq(
        df_clean, lb_map,
        source=source,
        df_debit=df_debit,
        df_debit_hydro=df_debit_hydro,
        rattachement=rattachement,
        params_selectionnes=params_selectionnes,
    )
    alertes.extend(msgs)
    if df_cq.empty:
        return figures, pd.DataFrame(), alertes

    # Régression
    df_reg, msgs = regression_cq(df_cq, seuil_b=seuil_b)
    alertes.extend(msgs)

    # Figures
    fig, msgs = figure_cq_param(
        df_cq, df_reg, lb_map,
        params_selectionnes=params_selectionnes,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        n_colonnes=n_colonnes, n_params_max=n_params_max,
        titre=f"{titre_global} — Nuages C-Q",
        dpi=dpi,
    )
    figures["cq_params"] = fig
    alertes.extend(msgs)

    fig, msgs = figure_cq_comportements(
        df_reg, lb_map,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        r2_min=r2_min,
        titre=f"{titre_global} — Comportements chimio-dynamiques",
        dpi=dpi,
    )
    figures["cq_comportements"] = fig
    alertes.extend(msgs)

    return figures, df_reg, alertes


# ---------------------------------------------------------------------------
# Bloc de test autonome
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, "/tmp/chimie_modules")
    sys.path.insert(0, "/home/claude")

    print("Test M06 — données Bienne/Lison")

    import m01_import, m02_nettoyage
    import pandas as pd

    res = m01_import.importer_bdd(
        "/mnt/user-data/uploads/Analyses_InterStations_apprentissage.csv",
        cd_support=3, cd_fractions=[23],
    )
    df_filtre = res["df"]
    df_debit  = res["df_debit"]
    inv = res["inventaire_stations"]
    lb_stations = dict(zip(
        inv["CdStationMesureEauxSurface"],
        inv["LbStationMesureEauxSurface"],
    ))

    def corriger(s):
        if not isinstance(s, str): return s
        try: return s.encode("latin-1").decode("utf-8")
        except: return s

    df_fam = pd.read_csv(
        "/mnt/user-data/uploads/Substances_Familles.csv",
        sep=None, engine="python", encoding="latin-1",
    )
    df_fam["CdParametre"] = pd.to_numeric(df_fam["CdParametre"], errors="coerce")
    for col in df_fam.columns:
        if df_fam[col].dtype == object:
            df_fam[col] = df_fam[col].apply(corriger)

    pivots  = m02_nettoyage.nettoyer_et_pivoter(df_filtre, df_familles=df_fam)
    df_clean = pivots["df_clean"]
    lb_map   = pivots["lb_map"]

    print(f"df_debit : {len(df_debit)} lignes, stations : {df_debit['CdStationMesureEauxSurface'].unique().tolist()}")

    # Test lire_hydroportail
    df_hydro, msgs_h = lire_hydroportail(
        "/mnt/user-data/uploads/Hydroportail_structure.csv",
        cd_station="HYDRO_TEST",
        lb_station="Station hydro test",
    )
    print("\n".join(msgs_h))
    print(f"Hydroportail : {len(df_hydro)} jours")

    # Test pipeline complet — mode A (co-localisé)
    params_test = [1311, 1302, 1340, 1335, 1433, 1303, 1301]
    figs, df_reg, alertes = figure_cq_complete(
        df_clean, lb_map,
        source="colocal",
        df_debit=df_debit,
        params_selectionnes=params_test,
        lb_stations=lb_stations,
        n_colonnes=3,
    )
    print()
    for a in alertes:
        print(a)

    print("\nRégressions :")
    if not df_reg.empty:
        print(df_reg[["CdStation", "CdParametre", "n_paires", "b", "r2",
                       "Comportement"]].to_string(index=False))

    os.makedirs("/mnt/user-data/outputs", exist_ok=True)
    for nom, fig in figs.items():
        p = f"/mnt/user-data/outputs/m06_{nom}.png"
        fig.savefig(p, dpi=150, bbox_inches="tight")
        print(f"  ✅ {p}")
