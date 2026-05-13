"""
Module 02 — Nettoyage & Pivot (v2)
=====================================
À partir du DataFrame filtré du Module 01 :
  1. Gestion des valeurs censurées (<LQ → LQ/2 ; <LD → LQ/2 ou 0 si LqAna absent)
  2. Calcul du taux de renseignement ET de la fréquence de détection par paramètre × station
  3. Sélection avec seuils différenciés PCH classique / micropolluants
  4. Pivot individuel (codes) + pivot par famille SANDRE (optionnel)
  5. Normalisation log-zscore pour analyses multivariées

NOTE sur les codes CdRqAna SANDRE :
  1  → Valeur quantifiée (> LQ)
  10 → Valeur < LQ  → substitution LQ/2
  3  → Valeur < LD  → substitution LQ/2 si LqAna dispo, sinon 0

Convention retenue : <LD et <LQ reçoivent le même traitement (LQ/2).
La distinction est conservée dans EstCensure / EstSousLD pour les stats.
"""

import pandas as pd
import numpy as np
from typing import Optional

CD_RQ_QUANTIFIE = 1   # Seul code indiquant une vraie valeur quantifiée
# Tous les autres codes → substitution LQ/2 (non quantifié, quelle qu'en soit la raison)
# Code 10 : <LQ | Code 3 : <LD | Code 7 : >LD et <LQ | autres cas rares
CODES_CENSURES = {10, 3, 7}

SEUIL_RENS_PCH_DEFAUT       = 30.0
SEUIL_RENS_MICROPOLLUANTS   = 10.0
NB_STATIONS_MIN_DEFAUT      = 2

FAMILLES_PCH_CLASSIQUE = {
    "Bilan oxygène":     [1311, 1312, 1313, 1314, 1841],
    "Nutriments azotés": [1335, 1339, 1340, 1319],
    "Nutriments P":      [1433, 1350],
    "Minéralisation":    [1303, 1304, 1337, 1338, 1347, 1374, 1372, 1375, 1323],
    "Acidification":     [1302],
    "Température":       [1301],
    "MES/Turbidité":     [1305, 1295, 1297],
    "Carbone org.":      [1841, 1306],
    "Phytoplancton":     [1436, 1439],
}


def appliquer_censure(df, methode_censure="LQ/2"):
    """
    Règle unique : CdRqAna != 1 → valeur non quantifiée → substitution LQ/2.
    Cela couvre : code 10 (<LQ), code 3 (<LD), code 7 (>LD et <LQ), et tout autre cas.
    Seul CdRqAna = 1 est considéré comme une vraie valeur quantifiée.
    """
    alertes = []
    df = df.copy()
    df["Valeur"]     = df["RsAna"].copy()
    df["EstCensure"] = False

    masque_censure = df["CdRqAna"] != CD_RQ_QUANTIFIE
    nb_cens = masque_censure.sum()

    if nb_cens > 0:
        lq_valide = df["LqAna"].notna()
        df.loc[masque_censure & lq_valide,  "Valeur"] = df.loc[masque_censure & lq_valide, "LqAna"] / 2
        nb_sans = (masque_censure & ~lq_valide).sum()
        if nb_sans > 0:
            df.loc[masque_censure & ~lq_valide, "Valeur"] = 0.0
            alertes.append(f"⚠️ {nb_sans} valeur(s) non quantifiée(s) sans LqAna → substituées par 0.")
        df.loc[masque_censure, "EstCensure"] = True

        # Détail par code pour information
        detail = df[masque_censure]["CdRqAna"].value_counts().to_dict()
        detail_str = " | ".join([f"code {k}: {v:,}" for k, v in sorted(detail.items())])
        alertes.append(f"ℹ️ {nb_cens:,} valeur(s) non quantifiée(s) → LQ/2 ({detail_str}).")

    nb_nan = df["Valeur"].isna().sum()
    if nb_nan:
        df = df.dropna(subset=["Valeur"])
        alertes.append(f"ℹ️ {nb_nan:,} ligne(s) sans valeur numérique supprimées.")
    return df, alertes


def calculer_stats_par_station_param(df,
        col_station="CdStationMesureEauxSurface", col_param="CdParametre",
        col_lb_param="LbLongParamètre", col_valeur="Valeur",
        col_censure="EstCensure"):
    def _stats(grp):
        vals    = grp[col_valeur]
        cens    = grp[col_censure] if col_censure in grp.columns else pd.Series(False, index=grp.index)
        n       = len(vals)
        n_quant = int((~cens).sum())
        n_cens  = int(cens.sum())
        moy     = vals.mean()
        std     = vals.std()
        return pd.Series({
            "NbMesures":       n,
            "NbQuantifies":    n_quant,
            "NbCensures":      n_cens,
            "FreqDetect_pct":  round(100 * n_quant / n, 1) if n else 0.0,
            "TauxCensure_pct": round(100 * n_cens  / n, 1) if n else 0.0,
            "Mediane":  vals.median(),
            "Moyenne":  moy,
            "P10":      vals.quantile(0.10),
            "P25":      vals.quantile(0.25),
            "P75":      vals.quantile(0.75),
            "P90":      vals.quantile(0.90),
            "Min":      vals.min(),
            "Max":      vals.max(),
            "CV_pct":   round(100 * std / moy, 1) if moy and moy != 0 else np.nan,
        })

    grp_cols = [col_station, col_param]
    if col_lb_param in df.columns: grp_cols.append(col_lb_param)
    result = df.groupby(grp_cols, dropna=False).apply(_stats).reset_index()

    if "LbStationMesureEauxSurface" in df.columns:
        lb = df[["CdStationMesureEauxSurface","LbStationMesureEauxSurface"]].drop_duplicates()
        result = result.merge(lb, on="CdStationMesureEauxSurface", how="left")
    if "SymUniteMesure" in df.columns:
        u = (df.groupby(col_param)["SymUniteMesure"]
               .agg(lambda x: x.dropna().mode()[0] if not x.dropna().empty else "")
               .reset_index())
        result = result.merge(u, on=col_param, how="left")
    return result


def alerter_coherence_lq(
    df: pd.DataFrame,
    params_retenus: list,
    seuil_ratio: float = 5.0,
    col_station: str = "CdStationMesureEauxSurface",
    col_param:   str = "CdParametre",
    col_lb:      str = "LbLongParamètre",
) -> tuple[pd.DataFrame, list[str]]:
    """
    Détecte les paramètres dont la LQ médiane varie fortement entre stations
    (ratio max/min > seuil_ratio). Un tel écart biaise les comparaisons inter-stations :
    une valeur LQ/2 à 5 µg/l n'est pas comparable à une valeur quantifiée à 0.1 µg/l.

    Returns
    -------
    df_alertes : DataFrame des cas problématiques avec les LQ par station
    alertes    : messages texte pour l'interface
    """
    alertes = []
    rows = []

    df_filt = df[df[col_param].isin(params_retenus) & df["LqAna"].notna()].copy()
    if df_filt.empty:
        return pd.DataFrame(), alertes

    lq_st = (df_filt.groupby([col_param, col_station])["LqAna"]
                     .median().reset_index().rename(columns={"LqAna": "LQ_mediane"}))

    for cd, grp in lq_st.groupby(col_param):
        vals = grp["LQ_mediane"].replace(0, np.nan).dropna()
        if len(vals) < 2: continue
        lq_min, lq_max = vals.min(), vals.max()
        if lq_min <= 0: continue
        ratio = lq_max / lq_min
        if ratio > seuil_ratio:
            lb = (df_filt[df_filt[col_param]==cd][col_lb].dropna().iloc[0]
                  if col_lb in df_filt.columns and not df_filt[df_filt[col_param]==cd].empty
                  else str(cd))
            rows.append({
                "CdParametre": cd,
                "LbParametre": lb,
                "LQ_min_ug":   round(lq_min, 6),
                "LQ_max_ug":   round(lq_max, 6),
                "Ratio":       round(ratio, 1),
                "Nb_stations": len(vals),
            })

    df_out = pd.DataFrame(rows).sort_values("Ratio", ascending=False) if rows else pd.DataFrame()

    if not df_out.empty:
        alertes.append(
            f"⚠️ {len(df_out)} paramètre(s) avec LQ très variable entre stations "
            f"(ratio > {seuil_ratio}x) — comparaisons à interpréter avec précaution :"
        )
        for _, r in df_out.iterrows():
            alertes.append(
                f"   • {r['LbParametre']} : LQ de {r['LQ_min_ug']} à {r['LQ_max_ug']} "
                f"(×{r['Ratio']})"
            )
    else:
        alertes.append(f"ℹ️ LQ cohérentes entre stations (ratio < {seuil_ratio}x pour tous les paramètres retenus).")

    return df_out, alertes


def selectionner_parametres(df_stats,
        seuil_pch_pct=SEUIL_RENS_PCH_DEFAUT,
        seuil_micropolluants_pct=SEUIL_RENS_MICROPOLLUANTS,
        seuil_nb_stations_min=NB_STATIONS_MIN_DEFAUT,
        codes_pch=None, col_param="CdParametre",
        col_station="CdStationMesureEauxSurface",
        params_forcer=None, params_exclure=None):
    alertes = []
    if codes_pch is None:
        codes_pch = [cd for lst in FAMILLES_PCH_CLASSIQUE.values() for cd in lst]

    retenus = []
    for cd in df_stats[col_param].unique():
        sub   = df_stats[df_stats[col_param] == cd]
        seuil = seuil_pch_pct if cd in codes_pch else seuil_micropolluants_pct
        if (sub["FreqDetect_pct"] >= seuil).sum() >= seuil_nb_stations_min:
            retenus.append(cd)

    if params_forcer:
        avant   = len(retenus)
        retenus = list(set(retenus) | set(params_forcer))
        if len(retenus) > avant:
            alertes.append(f"ℹ️ {len(retenus)-avant} paramètre(s) forcé(s) inclus.")
    if params_exclure:
        avant   = len(retenus)
        retenus = [p for p in retenus if p not in params_exclure]
        alertes.append(f"ℹ️ {avant-len(retenus)} paramètre(s) exclus manuellement.")

    alertes.append(
        f"ℹ️ Paramètres retenus : {len(retenus)} / {df_stats[col_param].nunique()} "
        f"(seuil PCH ≥ {seuil_pch_pct}% | micropolluants ≥ {seuil_micropolluants_pct}% "
        f"| ≥ {seuil_nb_stations_min} stations)."
    )
    return retenus, alertes


def pivoter_stations_params(df, params_retenus=None, valeur_pivot="Mediane",
        col_station="CdStationMesureEauxSurface", col_param="CdParametre",
        col_lb_param="LbLongParamètre", col_valeur="Valeur"):
    alertes = []
    df = df.copy()
    if params_retenus is not None:
        df = df[df[col_param].isin(params_retenus)]

    AGG = {"Mediane": "median", "P90": lambda x: x.quantile(.90),
           "Moyenne": "mean",   "P10": lambda x: x.quantile(.10)}
    agg_fn = AGG.get(valeur_pivot, "median")
    if valeur_pivot not in AGG:
        alertes.append(f"⚠️ Statistique '{valeur_pivot}' inconnue → médiane.")

    lb_map = {}
    if col_lb_param in df.columns:
        lb_map = (df[[col_param, col_lb_param]].drop_duplicates()
                    .set_index(col_param)[col_lb_param].to_dict())

    pivot = (df.groupby([col_station, col_param])[col_valeur]
               .agg(agg_fn).reset_index()
               .pivot(index=col_station, columns=col_param, values=col_valeur))
    pivot.index.name = "Station"; pivot.columns.name = None
    pivot_labels = pivot.rename(columns=lb_map)

    nb_na = pivot.isna().sum().sum()
    alertes.append(f"ℹ️ Pivot : {pivot.shape[0]} stations × {pivot.shape[1]} paramètres | {nb_na} cellule(s) vide(s).")
    return pivot, pivot_labels, lb_map, alertes


def pivoter_par_famille(df, df_familles=None, params_retenus=None,
        col_station="CdStationMesureEauxSurface", col_param="CdParametre",
        col_valeur="Valeur", niveau_famille="NomGroupeParametres", agregation="median"):
    alertes = []
    if df_familles is None or df_familles.empty:
        alertes.append("ℹ️ Pas de fichier familles → pivot par famille non disponible.")
        return pd.DataFrame(), alertes
    if niveau_famille not in df_familles.columns:
        alertes.append(f"⚠️ Colonne '{niveau_famille}' absente du fichier familles.")
        return pd.DataFrame(), alertes

    df = df.copy()
    if params_retenus is not None:
        df = df[df[col_param].isin(params_retenus)]

    fam_slim = df_familles[["CdParametre", niveau_famille]].drop_duplicates()
    df_join  = df.merge(fam_slim, left_on=col_param, right_on="CdParametre", how="left")

    sans = df_join[niveau_famille].isna().sum()
    if sans: alertes.append(f"⚠️ {sans} mesure(s) sans famille → exclues du pivot familles.")
    df_join = df_join.dropna(subset=[niveau_famille])
    if df_join.empty:
        alertes.append("⚠️ Aucune mesure avec famille connue.")
        return pd.DataFrame(), alertes

    pivot_fam = (df_join.groupby([col_station, niveau_famille])[col_valeur]
                         .agg(agregation).reset_index()
                         .pivot(index=col_station, columns=niveau_famille, values=col_valeur))
    pivot_fam.index.name = "Station"; pivot_fam.columns.name = None
    alertes.append(f"ℹ️ Pivot familles : {pivot_fam.shape[0]} stations × {pivot_fam.shape[1]} familles.")
    return pivot_fam, alertes


def normaliser(pivot, methode="log_zscore", imputer=True):
    """
    imputer=True  : comportement par défaut — remplace NaN par la médiane.
    imputer=False : conserve les NaN (pour corpus_commun en aval).
    """
    alertes = []
    df = pivot.copy().astype(float)
    nb_nan = df.isna().sum().sum()
    if nb_nan and imputer:
        df = df.fillna(df.median())
        alertes.append(f"ℹ️ {nb_nan} cellule(s) vide(s) imputée(s) par médiane de colonne.")
    elif nb_nan and not imputer:
        alertes.append(f"ℹ️ {nb_nan} cellule(s) vide(s) conservées (mode corpus commun).")

    if methode in ("log_zscore", "zscore"):
        if methode == "log_zscore":
            eps = df[df > 0].min().min() * 0.01 if (df > 0).any().any() else 1e-9
            df  = np.log(df + eps)
        moy, sigma = df.mean(), df.std()
        cols_cst = sigma[sigma == 0].index.tolist()
        if cols_cst:
            df = df.drop(columns=cols_cst)
            moy = moy.drop(cols_cst); sigma = sigma.drop(cols_cst)
            alertes.append(f"⚠️ {len(cols_cst)} colonne(s) constante(s) exclue(s).")
        df = (df - moy) / sigma
    elif methode == "minmax":
        vmin, vmax = df.min(), df.max()
        rng = vmax - vmin
        cols_cst = rng[rng == 0].index.tolist()
        if cols_cst:
            df = df.drop(columns=cols_cst)
            rng = rng.drop(cols_cst)
            alertes.append(f"⚠️ {len(cols_cst)} colonne(s) constante(s) exclue(s).")
        df = (df - vmin) / rng

    alertes.append(f"ℹ️ Normalisation '{methode}' → {df.shape[1]} paramètres conservés.")
    return df, alertes


def nettoyer_et_pivoter(df_filtre, df_familles=None,
        seuil_pch_pct=SEUIL_RENS_PCH_DEFAUT,
        seuil_micropolluants_pct=SEUIL_RENS_MICROPOLLUANTS,
        seuil_nb_stations_min=NB_STATIONS_MIN_DEFAUT,
        methode_censure="LQ/2", valeur_pivot="Mediane",
        normalisation="log_zscore", niveau_famille="NomGroupeParametres",
        params_forcer=None, params_exclure=None):
    alertes = []

    df_clean, msgs = appliquer_censure(df_filtre, methode_censure)
    alertes.extend(msgs)

    df_stats = calculer_stats_par_station_param(df_clean)

    params_retenus, msgs = selectionner_parametres(df_stats,
        seuil_pch_pct=seuil_pch_pct,
        seuil_micropolluants_pct=seuil_micropolluants_pct,
        seuil_nb_stations_min=seuil_nb_stations_min,
        params_forcer=params_forcer, params_exclure=params_exclure)
    alertes.extend(msgs)

    pivot, pivot_labels, lb_map, msgs = pivoter_stations_params(
        df_clean, params_retenus=params_retenus, valeur_pivot=valeur_pivot)
    alertes.extend(msgs)

    pivot_familles, msgs = pivoter_par_famille(df_clean, df_familles=df_familles,
        params_retenus=params_retenus, niveau_famille=niveau_famille)
    alertes.extend(msgs)

    pivot_norm, msgs = normaliser(pivot, methode=normalisation, imputer=True)
    alertes.extend(msgs)
    # Version avec NaN préservés pour corpus_commun (paramètres communs à toutes stations)
    pivot_norm_raw, _ = normaliser(pivot, methode=normalisation, imputer=False)

    pivot_fam_norm = pd.DataFrame()
    if not pivot_familles.empty:
        pivot_fam_norm, msgs = normaliser(pivot_familles, methode=normalisation, imputer=True)
        alertes.extend(msgs)

    return {
        "df_clean": df_clean, "df_stats": df_stats,
        "params_retenus": params_retenus,
        "pivot": pivot, "pivot_labels": pivot_labels, "lb_map": lb_map,
        "pivot_familles": pivot_familles,
        "pivot_norm": pivot_norm, "pivot_norm_raw": pivot_norm_raw,
        "pivot_fam_norm": pivot_fam_norm,
        "alertes": alertes,
    }


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from m01_import import importer_bdd

    chemin          = sys.argv[1] if len(sys.argv) > 1 else None
    chemin_familles = sys.argv[2] if len(sys.argv) > 2 else None
    if chemin:
        df_fam = None
        if chemin_familles:
            df_fam = pd.read_csv(chemin_familles, sep=None, engine="python", encoding="latin-1")
            df_fam["CdParametre"] = pd.to_numeric(df_fam["CdParametre"], errors="coerce")

        res1 = importer_bdd(chemin, cd_support=3)
        res2 = nettoyer_et_pivoter(res1["df"], df_familles=df_fam,
                                    seuil_pch_pct=30, seuil_micropolluants_pct=10)
        for msg in res2["alertes"]: print(msg)
        print(f"\n--- FreqDetect_pct extrait ---")
        cols = ["CdStationMesureEauxSurface","LbLongParamètre",
                "NbMesures","NbQuantifies","FreqDetect_pct","TauxCensure_pct","Mediane"]
        print(res2["df_stats"][cols]
              .sort_values(["CdStationMesureEauxSurface","FreqDetect_pct"], ascending=[True,False])
              .head(20).to_string(index=False))
        print(f"\n--- Pivot individuel {res2['pivot'].shape} ---")
        print(res2["pivot_labels"].round(3).to_string())
        if not res2["pivot_familles"].empty:
            print(f"\n--- Pivot familles {res2['pivot_familles'].shape} ---")
            print(res2["pivot_familles"].round(3).to_string())
