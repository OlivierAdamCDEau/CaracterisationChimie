"""
Module 04 — Analyses multivariées (v1)
========================================
ACP, biplot, clustering hiérarchique et matrice de corrélation
pour la comparaison inter-stations de profils chimiques.

Entrées attendues (issues de m02_nettoyage.nettoyer_et_pivoter()) :
  - pivot_norm     : DataFrame stations × paramètres (log-zscore), index = codes station
  - pivot_fam_norm : DataFrame stations × familles SANDRE normalisé (peut être vide)
  - lb_map         : dict {CdParametre: LbLongParamètre}
  - lb_stations    : dict {CdStation: libellé court} (optionnel)
  - ordre_stations : liste de codes station pour l'ordre d'affichage (optionnel)

Conventions respectées (identiques à M03) :
  - Watermark @CDEau : bas à droite de la zone de tracé, #999999, alpha 0.60, 8pt
  - Police minimum 8pt
  - Palette stations : PALETTE_STATIONS (cyclique)
  - Paramètres ordonnés par famille SANDRE (via ordonner_par_famille de M03)
  - * en fin de libellé = SEQ-Eau ; sans * = DCE
  - Débit (1420) exclu — géré en amont par M02
  - Conductivité fusionnée en amont par M03 si besoin
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from scipy.cluster.hierarchy import dendrogram, linkage, fcluster
from scipy.spatial.distance import squareform
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from typing import Optional

# ---------------------------------------------------------------------------
# Constantes partagées (alignées avec M03)
# ---------------------------------------------------------------------------

PALETTE_STATIONS = [
    "#2563eb", "#16a34a", "#dc2626", "#d97706",
    "#7c3aed", "#0891b2", "#be185d", "#4d7c0f",
]

# Palette familles chimiques : 14 couleurs distinctes, lisibles sur fond blanc
# Conçue pour rester lisible même avec 10-12 familles affichées simultanément
PALETTE_FAMILLES = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231",
    "#911eb4", "#42d4f4", "#f032e6", "#bfef45",
    "#fabed4", "#469990", "#9a6324", "#808000",
    "#aaffc3", "#000075",
]

# Dictionnaire de repli : codes PCH généraux absents du fichier SANDRE
# → famille logique pour la coloration du biplot
FAMILLES_REPLI_PCH = {
    1295: "PCH généraux",   # Turbidité
    1296: "PCH généraux",   # Turbidité (variante)
    1297: "PCH généraux",   # Turbidité (variante)
    1301: "PCH généraux",   # Température
    1302: "PCH généraux",   # pH
    1303: "PCH généraux",   # Conductivité 25°C
    1304: "PCH généraux",   # Conductivité 20°C
    1305: "PCH généraux",   # MES
    1306: "PCH généraux",   # Turbidité (autre)
    1314: "PCH généraux",   # DCO
    1319: "PCH généraux",   # NKJ
    1340: "PCH généraux",   # Nitrates
    1342: "PCH généraux",   # TAC
    1420: "PCH généraux",   # Débit
    6484: "PCH généraux",   # T° mesure pH
}

CODES_SEQ_EAU = {
    1303, 1304,   # Conductivité
    1305,         # MES
    1306,         # Turbidité
    1314,         # DCO
    1319,         # NKJ
    1340,         # Nitrates (forcé SEQ-Eau)
    1342,         # TAC
    1367,         # Potassium (sans seuil mais source SEQ)
    1374,         # Magnésium
    1375,         # Calcium
    1376,         # Sodium
    1436,         # Chlorophylle a
    1439,         # Phéopigments
    1551,         # NGL
}

# ---------------------------------------------------------------------------
# Utilitaires graphiques internes (copie allégée depuis M03)
# ---------------------------------------------------------------------------

def _construire_palette_familles(
    codes_params: list,
    fam_map: Optional[dict] = None,
) -> tuple[dict, dict]:
    """
    Construit deux dicts à partir d'une liste de codes paramètres :
      - famille_par_code : {code: nom_famille}
      - couleur_par_famille : {nom_famille: couleur_hex}

    Si fam_map est None ou ne couvre pas un code, le repli PCH est appliqué,
    puis "Divers" si rien ne correspond.

    Returns
    -------
    (famille_par_code, couleur_par_famille)
    """
    if fam_map is None:
        fam_map = {}

    # Résolution famille pour chaque code
    famille_par_code = {}
    for code in codes_params:
        fam = fam_map.get(code)
        if pd.isna(fam) if isinstance(fam, float) else (fam is None or fam == ""):
            fam = FAMILLES_REPLI_PCH.get(code, "Divers")
        famille_par_code[code] = fam

    # Attribution couleurs aux familles (ordre alphabétique pour stabilité)
    familles_uniques = sorted(set(famille_par_code.values()))
    couleur_par_famille = {
        fam: PALETTE_FAMILLES[i % len(PALETTE_FAMILLES)]
        for i, fam in enumerate(familles_uniques)
    }
    return famille_par_code, couleur_par_famille


def _legende_familles(ax, couleur_par_famille: dict,
                      fontsize: int = 7, loc: str = "upper right"):
    """Ajoute une légende compacte des familles chimiques."""
    patches = [
        mpatches.Patch(color=c, label=fam)
        for fam, c in couleur_par_famille.items()
    ]
    n = len(patches)
    ncol = 1 if n <= 8 else 2
    ax.legend(
        handles=patches, fontsize=fontsize, loc=loc,
        framealpha=0.85, ncol=ncol,
        title="Familles", title_fontsize=fontsize,
        handlelength=1.0, handleheight=0.8,
    )


def _ajouter_watermark(fig, ax=None, texte="@CDEau",
                       alpha=0.60, fontsize=8, couleur="#999999"):
    """Watermark discret en bas à droite de la zone de tracé."""
    target = ax if ax is not None else (fig.axes[-1] if fig.axes else None)
    if target is not None:
        target.annotate(
            texte,
            xy=(1.0, -0.02),
            xycoords="axes fraction",
            ha="right", va="top",
            fontsize=fontsize, color=couleur, alpha=alpha,
            annotation_clip=False,
        )


def _couleur_station(i: int) -> str:
    return PALETTE_STATIONS[i % len(PALETTE_STATIONS)]


def _nom_court_station(lb: str, max_len: int = 26) -> str:
    return lb if len(lb) <= max_len else lb[:max_len - 1] + "…"


def _lb_court(code, lb_map: dict, max_len: int = 18) -> str:
    lb = lb_map.get(code, str(code))
    return lb if len(lb) <= max_len else lb[:max_len - 1] + "…"


def _lb_court_avec_ref(code, lb_map: dict,
                       codes_seq: set = CODES_SEQ_EAU,
                       max_len: int = 18) -> str:
    lb = lb_map.get(code, str(code))
    suffix = "*" if code in codes_seq else ""
    label = lb if len(lb) <= max_len else lb[:max_len - 1] + "…"
    return label + suffix


def _ordonner_stations(df: pd.DataFrame,
                       ordre: Optional[list] = None,
                       lb_stations: Optional[dict] = None) -> pd.DataFrame:
    if ordre is None or len(ordre) == 0:
        return df
    ordre_valide = [s for s in ordre if s in df.index]
    reste = [s for s in df.index if s not in ordre_valide]
    return df.loc[ordre_valide + reste]


def _prepare_pivot(pivot_norm: pd.DataFrame,
                   ordre_stations: Optional[list] = None,
                   lb_stations: Optional[dict] = None,
                   min_stations: int = 2,
                   min_params: int = 2,
                   corpus_commun: bool = False,
                   seuil_imputation: float = 0.20,
                   ) -> tuple[pd.DataFrame, list, dict]:
    """
    Nettoie un pivot normalisé : supprime colonnes tout-NaN,
    remplace NaN restants par 0 (zscore neutre), ordonne les stations.

    Parameters
    ----------
    corpus_commun      : si True, restreint l'ACP aux paramètres analysés dans
                         TOUTES les stations (aucun NaN avant imputation).
    seuil_imputation   : taux NaN au-delà duquel une station est signalée
                         (ex. 0.20 = 20 %).

    Retourne (df_propre, alertes, taux_imputation).
    taux_imputation : dict {code_station: float} — calculé sur le pivot retenu,
                      avant imputation. Vaut 0.0 si corpus_commun=True.
    """
    alertes = []
    df = pivot_norm.copy()

    # Supprimer colonnes entièrement NaN
    cols_nan = df.columns[df.isna().all()].tolist()
    if cols_nan:
        alertes.append(f"⚠️ ACP : {len(cols_nan)} colonne(s) entièrement NaN supprimée(s) : {cols_nan}")
        df = df.drop(columns=cols_nan)

    if df.shape[0] < min_stations or df.shape[1] < min_params:
        alertes.append(
            f"❌ ACP : pivot trop petit ({df.shape[0]} stations × {df.shape[1]} paramètres). "
            f"Minimum requis : {min_stations} × {min_params}."
        )
        return pd.DataFrame(), alertes, {}

    # --- Mode corpus commun : restreindre aux paramètres sans aucun NaN ---
    if corpus_commun:
        cols_ok = df.columns[df.notna().all()].tolist()
        n_retires = df.shape[1] - len(cols_ok)
        if n_retires > 0:
            alertes.append(
                f"ℹ️ ACP corpus commun : {n_retires} paramètre(s) écarté(s) "
                f"(non analysé(s) dans toutes les stations). "
                f"{len(cols_ok)} paramètre(s) conservé(s)."
            )
        df = df[cols_ok]
        if df.shape[1] < min_params:
            alertes.append(
                f"❌ ACP corpus commun : seulement {df.shape[1]} paramètre(s) commun(s) "
                f"— minimum requis : {min_params}. Désactivez corpus_commun."
            )
            return pd.DataFrame(), alertes, {}
        # En mode corpus commun : aucune imputation, taux = 0 pour toutes
        taux_imputation = {st: 0.0 for st in df.index}
    else:
        # Calculer le taux d'imputation par station AVANT fillna
        n_params = df.shape[1]
        taux_imputation = (df.isna().sum(axis=1) / n_params).to_dict()

        # Alertes stations fortement imputées
        stations_high = [
            st for st, t in taux_imputation.items() if t > seuil_imputation
        ]
        if stations_high:
            noms = [
                lb_stations.get(st, str(st)) if lb_stations else str(st)
                for st in stations_high
            ]
            alertes.append(
                f"⚠️ ACP : {len(stations_high)} station(s) avec taux d'imputation "
                f"> {seuil_imputation:.0%} (zscore neutre forcé sur ces paramètres) : "
                + ", ".join(
                    f"{n} ({taux_imputation[st]:.0%})"
                    for n, st in zip(noms, stations_high)
                )
            )

        # Imputer NaN résiduels par 0 (neutre pour zscore)
        n_nan = df.isna().sum().sum()
        if n_nan > 0:
            alertes.append(f"ℹ️ ACP : {n_nan} valeur(s) NaN imputée(s) à 0 (zscore neutre).")
            df = df.fillna(0.0)

    df = _ordonner_stations(df, ordre_stations, lb_stations)
    # Réindexer taux_imputation selon l'ordre final du df
    taux_imputation = {st: taux_imputation.get(st, 0.0) for st in df.index}
    return df, alertes, taux_imputation


# ---------------------------------------------------------------------------
# Fonction principale ACP
# ---------------------------------------------------------------------------

def _calculer_acp(df: pd.DataFrame, n_composantes: int = 5
                  ) -> tuple[PCA, np.ndarray, list]:
    """Ajuste une ACP sur df (stations × params), retourne (pca, scores, alertes)."""
    alertes = []
    n_comp = min(n_composantes, df.shape[0] - 1, df.shape[1])
    pca = PCA(n_components=n_comp)
    scores = pca.fit_transform(df.values)
    var_exp = pca.explained_variance_ratio_ * 100
    alertes.append(
        f"ℹ️ ACP : {df.shape[0]} stations × {df.shape[1]} paramètres — "
        f"PC1={var_exp[0]:.1f}% / PC2={var_exp[1]:.1f}% / "
        f"cumulé {sum(var_exp[:min(3, len(var_exp))]):.1f}%"
    )
    return pca, scores, alertes


# ---------------------------------------------------------------------------
# Utilitaire : déplacement itératif des labels pour éviter les chevauchements
# ---------------------------------------------------------------------------

def _placer_labels_biplot(
    ax: plt.Axes,
    positions_vecteurs: list[tuple[float, float]],
    labels: list[str],
    couleurs: list[str],
    positions_points: list[tuple[float, float]] | None = None,
    fontsize: int = 8,
    n_iter: int = 20,
) -> None:
    """
    Pose les labels des vecteurs avec un léger décalage en cas de chevauchement.

    Stratégie : répulsion à courte portée uniquement (s'active seulement quand
    deux labels se recouvrent), avec une ancre forte qui maintient chaque label
    près de sa position naturelle au bout du vecteur. Le déplacement maximal
    est plafonné à la demi-largeur d'un label.

    Si un label a été déplacé de façon significative, un filet pointillé fin
    relie la pointe du vecteur au label pour conserver le lien visuel.
    """
    if not labels:
        return

    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    rx = xlim[1] - xlim[0]
    ry = ylim[1] - ylim[0]

    # Emprise approximative d'un label en unités data
    # (calibrée pour des labels de ~15 caractères à 8pt)
    lw = fontsize * 0.006 * rx   # largeur  ≈ 6‰ de rx par pt de police
    lh = fontsize * 0.013 * ry   # hauteur  ≈ 13‰ de ry par pt de police

    # Position initiale : décalage depuis la pointe selon le quadrant
    marge = 0.04   # fraction de la plage d'axe
    pos = []
    for vx, vy in positions_vecteurs:
        dx = marge * rx * (1.0 if vx >= 0 else -1.0)
        dy = marge * ry * (1.0 if vy >= 0 else -1.0)
        pos.append([vx + dx, vy + dy])
    pos = np.array(pos, dtype=float)
    pos0 = pos.copy()  # ancre forte

    # Déplacement maximal autorisé : 1.5× la largeur d'un label
    max_depl_x = 1.5 * lw
    max_depl_y = 1.5 * lh

    # Intensité de la répulsion : très faible, juste pour écarter les labels
    # qui se chevauchent — la force s'annule dès qu'il n'y a plus de recouvrement
    k_rep = 0.0015   # fraction de rx² / ry²
    k_anc = 0.35     # ancre forte : ramène rapidement vers pos0

    for _ in range(n_iter):
        forces = np.zeros_like(pos)

        # Répulsion label↔label — active seulement si les boîtes se chevauchent
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                dx = pos[i, 0] - pos[j, 0]
                dy = pos[i, 1] - pos[j, 1]
                # Recouvrement sur chaque axe (positif = chevauchement)
                ov_x = lw - abs(dx)
                ov_y = lh - abs(dy)
                if ov_x > 0 and ov_y > 0:
                    # Pousser selon l'axe de moindre recouvrement
                    if ov_x < ov_y:
                        fx = k_rep * ov_x * rx * np.sign(dx)
                        fy = 0.0
                    else:
                        fx = 0.0
                        fy = k_rep * ov_y * ry * np.sign(dy)
                    forces[i] += [fx, fy]
                    forces[j] -= [fx, fy]

        # Ancre forte vers position initiale
        forces += k_anc * (pos0 - pos)

        pos += forces

    # Clip : ne pas sortir de la zone de tracé
    pos[:, 0] = np.clip(pos[:, 0], xlim[0] + 0.01 * rx, xlim[1] - 0.01 * rx)
    pos[:, 1] = np.clip(pos[:, 1], ylim[0] + 0.01 * ry, ylim[1] - 0.01 * ry)

    # Clip : déplacement max par rapport à la position initiale
    depl = pos - pos0
    depl[:, 0] = np.clip(depl[:, 0], -max_depl_x, max_depl_x)
    depl[:, 1] = np.clip(depl[:, 1], -max_depl_y, max_depl_y)
    pos = pos0 + depl

    # Tracé
    seuil_filet = 0.025  # fraction de plage → filet si déplacement > seuil
    for i, (label, couleur) in enumerate(zip(labels, couleurs)):
        lx, ly = pos[i]
        vx, vy = positions_vecteurs[i]

        dist_depl = np.sqrt(((lx - vx) / rx) ** 2 + ((ly - vy) / ry) ** 2)
        if dist_depl > seuil_filet:
            ax.plot([vx, lx], [vy, ly], color=couleur, lw=0.5,
                    alpha=0.45, zorder=6, ls=":")

        ha = "left" if lx >= vx else "right"
        ax.text(
            lx, ly, label,
            fontsize=fontsize, color=couleur,
            ha=ha, va="center", zorder=8,
            bbox=dict(boxstyle="round,pad=0.08", fc="white", ec="none", alpha=0.55),
        )


# ---------------------------------------------------------------------------
# 1. Biplot ACP (stations + vecteurs paramètres)
# ---------------------------------------------------------------------------

def biplot_acp(
    pivot_norm: pd.DataFrame,
    lb_map: dict,
    *,
    fam_map: Optional[dict] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    axe_x: int = 0,
    axe_y: int = 1,
    n_vecteurs: int = 10,
    echelle_vecteur: float = 1.0,
    corpus_commun: bool = False,
    seuil_imputation: float = 0.20,
    titre: str = "ACP — Biplot stations / paramètres",
    figsize: tuple = (11, 8),
    dpi: int = 150,
) -> tuple[plt.Figure, list]:
    """
    Biplot ACP : projection des stations (points) et des paramètres (vecteurs).

    Parameters
    ----------
    pivot_norm        : DataFrame normalisé (stations × paramètres)
    lb_map            : dict {code: libellé}
    fam_map           : dict {code: nom_famille} — si fourni, les vecteurs sont
                        colorés par famille chimique avec légende dédiée.
                        Les codes absents reçoivent le repli PCH ou "Divers".
    ordre_stations    : liste codes station pour l'ordre d'affichage
    lb_stations       : dict {code: libellé court} pour l'étiquetage
    axe_x, axe_y      : indices des composantes à afficher (0-indexé)
    n_vecteurs        : nombre de vecteurs (loadings) à afficher (les plus contributeurs)
    echelle_vecteur   : facteur d'échelle des vecteurs (ajuster si chevauchement)
    corpus_commun     : si True, restreint l'ACP aux paramètres présents dans
                        TOUTES les stations (élimine l'imputation par 0).
    seuil_imputation  : taux NaN par station au-delà duquel le point est affiché
                        en cercle creux (défaut 20 %).
    titre             : titre de la figure
    figsize, dpi      : dimensions et résolution

    Returns
    -------
    (fig, alertes)
    """
    alertes = []

    df, msgs, taux_imputation = _prepare_pivot(
        pivot_norm, ordre_stations, lb_stations,
        corpus_commun=corpus_commun, seuil_imputation=seuil_imputation,
    )
    alertes.extend(msgs)
    if df.empty:
        return plt.figure(), alertes

    pca, scores, msgs = _calculer_acp(df, n_composantes=max(axe_x, axe_y) + 2)
    alertes.extend(msgs)

    var_exp = pca.explained_variance_ratio_ * 100
    loadings = pca.components_  # shape (n_comp, n_features)
    codes_params = list(df.columns)
    stations = list(df.index)

    # Sélection des n_vecteurs paramètres les plus discriminants sur les 2 axes
    contrib = np.sqrt(loadings[axe_x] ** 2 + loadings[axe_y] ** 2)
    idx_top = np.argsort(contrib)[::-1][:n_vecteurs]

    # Mise à l'échelle des scores et vecteurs pour comparabilité visuelle
    s_x, s_y = scores[:, axe_x], scores[:, axe_y]
    l_x = loadings[axe_x, idx_top]
    l_y = loadings[axe_y, idx_top]
    scale = (np.max(np.abs(s_x)) + np.max(np.abs(s_y))) / 2 * echelle_vecteur

    # Palette familles (si fam_map fourni)
    use_familles = fam_map is not None
    if use_familles:
        codes_affichés = [codes_params[i] for i in idx_top]
        famille_par_code, couleur_par_famille = _construire_palette_familles(
            codes_affichés, fam_map
        )
    else:
        famille_par_code, couleur_par_famille = {}, {}

    # --- Mise en page : zone plot + légendes séparées ---
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    # --- Points stations ---
    pts_stations = []
    for i, station in enumerate(stations):
        taux_st = taux_imputation.get(station, 0.0)
        est_impute = taux_st > seuil_imputation
        # Point creux si taux d'imputation élevé, plein sinon
        ax.scatter(
            s_x[i], s_y[i],
            color=_couleur_station(i) if not est_impute else "none",
            edgecolors=_couleur_station(i),
            s=90, zorder=5,
            linewidths=1.8 if est_impute else 0.6,
            marker="o",
        )
        lb_st = _nom_court_station(lb_stations.get(station, station)) if lb_stations else str(station)
        # Suffixe taux si imputation notable
        label_st = f"{lb_st} ({taux_st:.0%}*)" if est_impute else lb_st
        ax.annotate(
            label_st, (s_x[i], s_y[i]),
            textcoords="offset points", xytext=(6, 5),
            fontsize=8, color=_couleur_station(i), fontweight="bold", zorder=6,
        )
        pts_stations.append((s_x[i], s_y[i]))

    # --- Vecteurs paramètres (loadings) : flèches d'abord ---
    vecteurs_xy = []
    labels_vecteurs = []
    couleurs_vecteurs = []

    for j, idx in enumerate(idx_top):
        code = codes_params[idx]
        vx, vy = l_x[j] * scale, l_y[j] * scale
        vecteurs_xy.append((vx, vy))

        couleur_vecteur = (
            couleur_par_famille.get(famille_par_code.get(code, "Divers"), "#555555")
            if use_familles else "#555555"
        )
        couleurs_vecteurs.append(couleur_vecteur)
        labels_vecteurs.append(_lb_court_avec_ref(code, lb_map))

        ax.annotate(
            "", xy=(vx, vy), xytext=(0, 0),
            arrowprops=dict(
                arrowstyle="-|>",
                color=couleur_vecteur,
                lw=1.5,
                mutation_scale=10,
            ),
            zorder=4,
        )

    # --- Axes centraux ---
    ax.axhline(0, color="#d0d0d0", lw=0.8, zorder=1)
    ax.axvline(0, color="#d0d0d0", lw=0.8, zorder=1)

    ax.set_xlabel(f"PC{axe_x + 1} ({var_exp[axe_x]:.1f}%)", fontsize=9)
    ax.set_ylabel(f"PC{axe_y + 1} ({var_exp[axe_y]:.1f}%)", fontsize=9)
    ax.set_title(titre, fontsize=10, fontweight="bold", pad=10)
    ax.tick_params(labelsize=8)
    ax.set_aspect("equal", adjustable="datalim")

    # Forcer le rendu pour que get_xlim/ylim soient stables avant la répulsion
    fig.canvas.draw()

    # --- Labels avec répulsion itérative ---
    _placer_labels_biplot(
        ax, vecteurs_xy, labels_vecteurs, couleurs_vecteurs,
        fontsize=8,
    )

    # --- Légende stations (en haut à gauche, toujours) ---
    import matplotlib.lines as mlines
    patches_st = []
    for i, s in enumerate(stations):
        taux_st = taux_imputation.get(s, 0.0)
        est_impute = taux_st > seuil_imputation
        lb_leg = _nom_court_station(lb_stations.get(s, s)) if lb_stations else str(s)
        if est_impute:
            lb_leg = f"{lb_leg} ({taux_st:.0%}*)"
        handle = mlines.Line2D(
            [], [],
            marker="o", linestyle="None",
            markerfacecolor="none" if est_impute else _couleur_station(i),
            markeredgecolor=_couleur_station(i),
            markeredgewidth=1.6 if est_impute else 0.6,
            markersize=7,
            label=lb_leg,
        )
        patches_st.append(handle)
    leg_st = ax.legend(
        handles=patches_st, fontsize=7, loc="upper left",
        framealpha=0.85, ncol=max(1, len(stations) // 6),
        title="Stations  (* = imputation > seuil)" if any(
            taux_imputation.get(s, 0.0) > seuil_imputation for s in stations
        ) else "Stations",
        title_fontsize=7,
    )
    ax.add_artist(leg_st)  # permet d'ajouter une 2ᵉ légende

    # --- Légende familles (en bas à droite, si activée) ---
    if use_familles and couleur_par_famille:
        n_fam = len(couleur_par_famille)
        patches_fam = [
            mpatches.Patch(color=c, label=fam)
            for fam, c in couleur_par_famille.items()
        ]
        ax.legend(
            handles=patches_fam,
            fontsize=7, loc="lower right",
            framealpha=0.85, ncol=1 if n_fam <= 9 else 2,
            title="Familles (vecteurs)", title_fontsize=7,
            handlelength=1.0,
        )
        alertes.append(
            f"ℹ️ Biplot : {n_fam} famille(s) colorée(s) sur {len(idx_top)} vecteurs affichés."
        )

    _ajouter_watermark(fig, ax=ax)
    fig.tight_layout()
    return fig, alertes


# ---------------------------------------------------------------------------
# 2. Double projection ACP : individuel + familles SANDRE
# ---------------------------------------------------------------------------

def biplot_double_projection(
    pivot_norm: pd.DataFrame,
    pivot_fam_norm: pd.DataFrame,
    lb_map: dict,
    *,
    fam_map: Optional[dict] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    n_vecteurs: int = 10,
    echelle_vecteur: float = 1.0,
    corpus_commun: bool = False,
    seuil_imputation: float = 0.20,
    titre: str = "ACP — Double projection (paramètres & familles SANDRE)",
    figsize: tuple = (16, 7),
    dpi: int = 150,
) -> tuple[plt.Figure, list]:
    """
    Figure côte-à-côte : biplot individuel (gauche) + biplot familles (droite).
    Si pivot_fam_norm est vide, produit uniquement le biplot individuel.

    corpus_commun    : restreint l'ACP aux paramètres présents dans toutes les stations.
    seuil_imputation : taux NaN au-delà duquel le point station est affiché en creux.

    Returns (fig, alertes)
    """
    alertes = []

    has_fam = pivot_fam_norm is not None and not pivot_fam_norm.empty

    if not has_fam:
        alertes.append("ℹ️ Double projection : pas de pivot familles — biplot individuel uniquement.")
        return biplot_acp(
            pivot_norm, lb_map,
            fam_map=fam_map,
            ordre_stations=ordre_stations, lb_stations=lb_stations,
            n_vecteurs=n_vecteurs, echelle_vecteur=echelle_vecteur,
            corpus_commun=corpus_commun, seuil_imputation=seuil_imputation,
            titre=titre + " (paramètres individuels)",
            figsize=(figsize[0] // 2, figsize[1]), dpi=dpi,
        )

    fig, axes = plt.subplots(1, 2, figsize=figsize, dpi=dpi)

    # Palette familles communes (calculée sur tous les paramètres individuels)
    use_familles = fam_map is not None
    couleur_par_famille_glob = {}
    if use_familles:
        df_tmp, _, _ = _prepare_pivot(pivot_norm, ordre_stations, lb_stations,
                                      corpus_commun=corpus_commun,
                                      seuil_imputation=seuil_imputation)
        if not df_tmp.empty:
            _, couleur_par_famille_glob = _construire_palette_familles(
                list(df_tmp.columns), fam_map
            )

    def _tracer_biplot(ax, df_prep, pca, scores, params_codes, lb_map_local,
                       idx_top, loadings, axe_x, axe_y, var_exp,
                       stations_list, scale, avec_ref=True, avec_familles=False,
                       taux_imputation=None, seuil_imputation=0.20):
        if taux_imputation is None:
            taux_imputation = {}
        s_x, s_y = scores[:, axe_x], scores[:, axe_y]
        pts_st = []
        for i, station in enumerate(stations_list):
            taux_st = taux_imputation.get(station, 0.0)
            est_impute = taux_st > seuil_imputation
            ax.scatter(
                s_x[i], s_y[i],
                color=_couleur_station(i) if not est_impute else "none",
                edgecolors=_couleur_station(i),
                s=70, zorder=5,
                linewidths=1.6 if est_impute else 0.4,
                marker="o",
            )
            lb_st = _nom_court_station(lb_stations.get(station, station)) if lb_stations else str(station)
            label_st = f"{lb_st} ({taux_st:.0%}*)" if est_impute else lb_st
            ax.annotate(label_st, (s_x[i], s_y[i]),
                        textcoords="offset points", xytext=(4, 4),
                        fontsize=8, color=_couleur_station(i), fontweight="bold", zorder=6)
            pts_st.append((s_x[i], s_y[i]))

        vecteurs_xy, labels_v, couleurs_v = [], [], []
        for j, idx in enumerate(idx_top):
            code = params_codes[idx]
            vx = loadings[axe_x, idx] * scale
            vy = loadings[axe_y, idx] * scale
            if avec_familles and fam_map is not None:
                fam_code = fam_map.get(code) or FAMILLES_REPLI_PCH.get(code, "Divers")
                if isinstance(fam_code, float) and pd.isna(fam_code):
                    fam_code = FAMILLES_REPLI_PCH.get(code, "Divers")
                couleur_v = couleur_par_famille_glob.get(fam_code, "#555555")
            else:
                couleur_v = "#555555"
            ax.annotate("", xy=(vx, vy), xytext=(0, 0),
                        arrowprops=dict(arrowstyle="-|>", color=couleur_v,
                                        lw=1.4, mutation_scale=9), zorder=4)
            lb_p = (_lb_court_avec_ref(code, lb_map_local) if avec_ref
                    else _lb_court(code, lb_map_local))
            vecteurs_xy.append((vx, vy))
            labels_v.append(lb_p)
            couleurs_v.append(couleur_v)

        ax.axhline(0, color="#d0d0d0", lw=0.7, zorder=1)
        ax.axvline(0, color="#d0d0d0", lw=0.7, zorder=1)
        ax.set_xlabel(f"PC{axe_x + 1} ({var_exp[axe_x]:.1f}%)", fontsize=9)
        ax.set_ylabel(f"PC{axe_y + 1} ({var_exp[axe_y]:.1f}%)", fontsize=9)
        ax.tick_params(labelsize=8)
        ax.set_aspect("equal", adjustable="datalim")
        fig.canvas.draw()
        _placer_labels_biplot(ax, vecteurs_xy, labels_v, couleurs_v, fontsize=8)

    # --- Panneau gauche : paramètres individuels ---
    df_ind, msgs, taux_imp_ind = _prepare_pivot(
        pivot_norm, ordre_stations, lb_stations,
        corpus_commun=corpus_commun, seuil_imputation=seuil_imputation,
    )
    alertes.extend(msgs)
    if not df_ind.empty:
        pca_ind, scores_ind, msgs = _calculer_acp(df_ind)
        alertes.extend(msgs)
        var_ind = pca_ind.explained_variance_ratio_ * 100
        load_ind = pca_ind.components_
        contrib_ind = np.sqrt(load_ind[0] ** 2 + load_ind[1] ** 2)
        idx_top_ind = np.argsort(contrib_ind)[::-1][:n_vecteurs]
        scale_ind = ((np.max(np.abs(scores_ind[:, 0])) +
                      np.max(np.abs(scores_ind[:, 1]))) / 2 * echelle_vecteur)
        _tracer_biplot(axes[0], df_ind, pca_ind, scores_ind,
                       list(df_ind.columns), lb_map, idx_top_ind, load_ind,
                       0, 1, var_ind, list(df_ind.index), scale_ind,
                       avec_ref=True, avec_familles=use_familles,
                       taux_imputation=taux_imp_ind, seuil_imputation=seuil_imputation)
        axes[0].set_title("Paramètres individuels", fontsize=9, fontweight="bold")

    # --- Panneau droit : familles SANDRE ---
    df_fam, msgs, _ = _prepare_pivot(pivot_fam_norm, ordre_stations, lb_stations)
    alertes.extend(msgs)
    if not df_fam.empty:
        pca_fam, scores_fam, msgs = _calculer_acp(df_fam)
        alertes.extend(msgs)
        var_fam = pca_fam.explained_variance_ratio_ * 100
        load_fam = pca_fam.components_
        contrib_fam = np.sqrt(load_fam[0] ** 2 + load_fam[1] ** 2)
        idx_top_fam = np.argsort(contrib_fam)[::-1][:n_vecteurs]
        scale_fam = ((np.max(np.abs(scores_fam[:, 0])) +
                      np.max(np.abs(scores_fam[:, 1]))) / 2 * echelle_vecteur)
        # lb_map familles = identité (noms de familles directement en colonnes)
        lb_fam = {c: c for c in df_fam.columns}
        _tracer_biplot(axes[1], df_fam, pca_fam, scores_fam,
                       list(df_fam.columns), lb_fam, idx_top_fam, load_fam,
                       0, 1, var_fam, list(df_fam.index), scale_fam,
                       avec_ref=False, avec_familles=False,
                       taux_imputation={}, seuil_imputation=seuil_imputation)
        axes[1].set_title("Familles SANDRE", fontsize=9, fontweight="bold")

    # Légende stations commune (en bas) — avec distinction creux/plein
    import matplotlib.lines as mlines
    stations_ref = list(df_ind.index) if not df_ind.empty else list(df_fam.index)
    taux_ref = taux_imp_ind if not df_ind.empty else {}
    has_imputed = any(taux_ref.get(s, 0.0) > seuil_imputation for s in stations_ref)
    patches = []
    for i, s in enumerate(stations_ref):
        taux_st = taux_ref.get(s, 0.0)
        est_impute = taux_st > seuil_imputation
        lb_leg = _nom_court_station(lb_stations.get(s, s)) if lb_stations else str(s)
        if est_impute:
            lb_leg = f"{lb_leg} ({taux_st:.0%}*)"
        handle = mlines.Line2D(
            [], [],
            marker="o", linestyle="None",
            markerfacecolor="none" if est_impute else _couleur_station(i),
            markeredgecolor=_couleur_station(i),
            markeredgewidth=1.6 if est_impute else 0.6,
            markersize=7, label=lb_leg,
        )
        patches.append(handle)
    fig.legend(
        handles=patches, fontsize=7, loc="lower center",
        ncol=min(len(patches), 6), framealpha=0.85,
        bbox_to_anchor=(0.5, -0.03),
        title="Stations  (* = imputation > seuil)" if has_imputed else "Stations",
        title_fontsize=7,
    )

    # Légende familles sur le panneau gauche (si activée)
    if use_familles and couleur_par_famille_glob:
        n_fam = len(couleur_par_famille_glob)
        patches_fam = [
            mpatches.Patch(color=c, label=fam)
            for fam, c in couleur_par_famille_glob.items()
        ]
        axes[0].legend(
            handles=patches_fam, fontsize=7, loc="lower right",
            framealpha=0.85, ncol=1 if n_fam <= 9 else 2,
            title="Familles (vecteurs)", title_fontsize=7,
            handlelength=1.0,
        )

    fig.suptitle(titre, fontsize=11, fontweight="bold", y=1.01)
    _ajouter_watermark(fig, ax=axes[-1])
    fig.tight_layout()
    return fig, alertes


# ---------------------------------------------------------------------------
# 3. Dendrogramme — clustering hiérarchique des stations
# ---------------------------------------------------------------------------

def dendrogramme_stations(
    pivot_norm: pd.DataFrame,
    *,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    methode_linkage: str = "ward",
    metric: str = "euclidean",
    n_clusters: int = 0,
    titre: str = "Clustering hiérarchique des stations",
    figsize: tuple = (10, 6),
    dpi: int = 150,
) -> tuple[plt.Figure, list, Optional[dict]]:
    """
    Dendrogramme de clustering hiérarchique sur les stations.

    Parameters
    ----------
    pivot_norm      : DataFrame normalisé (stations × paramètres)
    methode_linkage : méthode de liaison ('ward', 'complete', 'average', 'single')
    metric          : distance ('euclidean', 'cosine', …)
                      Note : 'ward' impose 'euclidean'.
    n_clusters      : si > 0, coupe l'arbre et colorie les groupes
    titre, figsize, dpi : mise en page

    Returns
    -------
    (fig, alertes, dict_clusters | None)
    dict_clusters : {code_station: numéro_cluster} si n_clusters > 0, sinon None
    """
    alertes = []
    dict_clusters = None

    df, msgs, _ = _prepare_pivot(pivot_norm, ordre_stations, lb_stations, min_stations=3)
    alertes.extend(msgs)
    if df.empty:
        return plt.figure(), alertes, None

    if methode_linkage == "ward" and metric != "euclidean":
        alertes.append("⚠️ La méthode 'ward' impose la distance euclidienne — metric forcé.")
        metric = "euclidean"

    stations = list(df.index)
    labels_st = [
        _nom_court_station(lb_stations.get(s, s)) if lb_stations else str(s)
        for s in stations
    ]

    # Matrice de liaison
    Z = linkage(df.values, method=methode_linkage, metric=metric)

    # Couleur de coupure si n_clusters demandé
    color_threshold = 0.0
    if n_clusters > 1:
        # Seuil = hauteur de la (n-n_clusters+1)-ème fusion
        idx_cut = len(Z) - n_clusters + 1
        color_threshold = Z[idx_cut, 2] if idx_cut < len(Z) else Z[-1, 2]
        cluster_ids = fcluster(Z, t=n_clusters, criterion="maxclust")
        dict_clusters = {s: int(c) for s, c in zip(stations, cluster_ids)}

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    dendrogram(
        Z,
        labels=labels_st,
        ax=ax,
        color_threshold=color_threshold if n_clusters > 1 else -1,
        above_threshold_color="#aaaaaa",
        leaf_font_size=8,
        leaf_rotation=45,
    )

    ax.set_title(titre, fontsize=10, fontweight="bold", pad=10)
    ax.set_ylabel(
        f"Distance ({methode_linkage} / {metric})",
        fontsize=9
    )
    ax.tick_params(axis="x", labelsize=8)
    ax.tick_params(axis="y", labelsize=8)

    # Ligne de coupure
    if n_clusters > 1 and color_threshold > 0:
        ax.axhline(color_threshold, color="#cc3333", lw=1.2, ls="--", alpha=0.7)
        ax.annotate(
            f"{n_clusters} groupes",
            xy=(0, color_threshold),
            xycoords=("axes fraction", "data"),
            xytext=(2, 4), textcoords="offset points",
            fontsize=8, color="#cc3333",
        )
        alertes.append(
            f"ℹ️ Clustering : {n_clusters} groupes — "
            + ", ".join(f"{s}→G{c}" for s, c in dict_clusters.items())
        )

    _ajouter_watermark(fig, ax=ax)
    fig.tight_layout()
    return fig, alertes, dict_clusters


# ---------------------------------------------------------------------------
# 4. Matrice de corrélation entre paramètres
# ---------------------------------------------------------------------------

def matrice_correlations(
    pivot_norm: pd.DataFrame,
    lb_map: dict,
    *,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    methode: str = "pearson",
    annot: bool = True,
    seuil_affichage: float = 0.0,
    titre: str = "Corrélations entre paramètres",
    figsize: tuple = (12, 10),
    dpi: int = 150,
) -> tuple[plt.Figure, list]:
    """
    Heatmap de la matrice de corrélation entre paramètres chimiques.

    Parameters
    ----------
    pivot_norm      : DataFrame normalisé (stations × paramètres)
    lb_map          : dict {code: libellé}
    methode         : 'pearson' ou 'spearman'
    annot           : afficher les valeurs de corrélation dans les cellules
    seuil_affichage : n'affiche les annotations que si |r| >= seuil (0 = toutes)
    titre, figsize, dpi : mise en page

    Returns
    -------
    (fig, alertes)
    """
    alertes = []

    df, msgs, _ = _prepare_pivot(pivot_norm, ordre_stations, lb_stations, min_params=3)
    alertes.extend(msgs)
    if df.empty:
        return plt.figure(), alertes

    # Calcul de la matrice de corrélation
    if methode == "spearman":
        corr = df.corr(method="spearman")
    else:
        corr = df.corr(method="pearson")

    n = len(corr)
    codes = list(corr.columns)
    labels = [_lb_court_avec_ref(c, lb_map) for c in codes]

    # Palette divergente bleu–blanc–rouge
    cmap = plt.cm.RdBu_r

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    im = ax.imshow(corr.values, cmap=cmap, vmin=-1, vmax=1, aspect="auto")

    # Annotations
    if annot:
        for i in range(n):
            for j in range(n):
                val = corr.values[i, j]
                if abs(val) >= seuil_affichage:
                    # Couleur du texte selon fond
                    text_color = "white" if abs(val) > 0.65 else "black"
                    ax.text(
                        j, i, f"{val:.2f}",
                        ha="center", va="center",
                        fontsize=max(6, min(9, 72 // n)),
                        color=text_color,
                    )

    # Axes
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=max(7, min(9, 80 // n)))
    ax.set_yticklabels(labels, fontsize=max(7, min(9, 80 // n)))

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(f"Corrélation ({methode})", fontsize=8)
    cbar.ax.tick_params(labelsize=8)

    ax.set_title(titre, fontsize=10, fontweight="bold", pad=10)

    # Séparateurs familles (triangle inférieur seulement)
    ax.set_facecolor("#f8f8f8")

    _ajouter_watermark(fig, ax=ax)
    fig.tight_layout()
    alertes.append(
        f"ℹ️ Corrélations {methode} : {n} paramètres × {df.shape[0]} stations."
    )
    return fig, alertes


# ---------------------------------------------------------------------------
# 5. Variance expliquée — Scree plot
# ---------------------------------------------------------------------------

def scree_plot(
    pivot_norm: pd.DataFrame,
    *,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    n_composantes: int = 10,
    titre: str = "Éboulis des valeurs propres (Scree plot)",
    figsize: tuple = (8, 5),
    dpi: int = 150,
) -> tuple[plt.Figure, list]:
    """
    Scree plot (éboulis) avec variance expliquée cumulée.

    Returns (fig, alertes)
    """
    alertes = []

    df, msgs, _ = _prepare_pivot(pivot_norm, ordre_stations, lb_stations)
    alertes.extend(msgs)
    if df.empty:
        return plt.figure(), alertes

    n_comp = min(n_composantes, df.shape[0] - 1, df.shape[1])
    pca = PCA(n_components=n_comp)
    pca.fit(df.values)

    var = pca.explained_variance_ratio_ * 100
    cum_var = np.cumsum(var)
    comp_labels = [f"PC{i + 1}" for i in range(n_comp)]

    fig, ax1 = plt.subplots(figsize=figsize, dpi=dpi)
    ax2 = ax1.twinx()

    ax1.bar(comp_labels, var, color="#2563eb", alpha=0.75, zorder=3, label="Variance expliquée (%)")
    ax2.plot(comp_labels, cum_var, color="#dc2626", marker="o", ms=5,
             lw=1.8, zorder=4, label="Cumulé (%)")
    ax2.axhline(80, color="#999999", lw=0.9, ls="--", alpha=0.7)
    ax2.text(n_comp - 0.5, 81, "80 %", fontsize=8, color="#777777", ha="right")

    ax1.set_xlabel("Composantes principales", fontsize=9)
    ax1.set_ylabel("Variance expliquée (%)", fontsize=9)
    ax2.set_ylabel("Cumulé (%)", fontsize=9)
    ax1.tick_params(labelsize=8)
    ax2.tick_params(labelsize=8)
    ax2.set_ylim(0, 105)

    # Légende combinée
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=8, loc="center right")

    ax1.set_title(titre, fontsize=10, fontweight="bold", pad=10)

    _ajouter_watermark(fig, ax=ax1)
    fig.tight_layout()
    alertes.append(
        f"ℹ️ Scree plot : PC1={var[0]:.1f}% / PC2={var[1]:.1f}% / "
        f"80% cumulé atteint à PC{int(np.searchsorted(cum_var, 80)) + 1}."
    )
    return fig, alertes


# ---------------------------------------------------------------------------
# 6. Figure multivariée complète
# ---------------------------------------------------------------------------

def figure_multivar_complete(
    pivot_norm: pd.DataFrame,
    lb_map: dict,
    *,
    pivot_fam_norm: Optional[pd.DataFrame] = None,
    fam_map: Optional[dict] = None,
    ordre_stations: Optional[list] = None,
    lb_stations: Optional[dict] = None,
    n_vecteurs: int = 10,
    echelle_vecteur: float = 1.0,
    corpus_commun: bool = False,
    seuil_imputation: float = 0.20,
    n_clusters: int = 0,
    methode_linkage: str = "ward",
    methode_corr: str = "pearson",
    titre_global: str = "Analyses multivariées — Chimie globale",
    dpi: int = 150,
) -> tuple[dict[str, plt.Figure], list]:
    """
    Génère l'ensemble des figures multivariées en un seul appel.

    Parameters
    ----------
    corpus_commun    : si True, restreint les biplots ACP aux seuls paramètres
                       analysés dans toutes les stations (pas d'imputation).
    seuil_imputation : taux NaN par station au-delà duquel le point est affiché
                       en cercle creux dans le biplot (défaut 20 %).

    Returns
    -------
    dict de figures : {
        "biplot"      : Figure biplot ACP individuel,
        "biplot_fam"  : Figure double projection (si pivot_fam_norm fourni),
        "dendro"      : Figure dendrogramme,
        "corr"        : Figure matrice corrélation,
        "scree"       : Figure scree plot,
    }
    alertes : liste de messages
    """
    alertes = []
    figures = {}

    # Biplot individuel
    fig, msgs = biplot_acp(
        pivot_norm, lb_map,
        fam_map=fam_map,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        n_vecteurs=n_vecteurs, echelle_vecteur=echelle_vecteur,
        corpus_commun=corpus_commun, seuil_imputation=seuil_imputation,
        titre=f"{titre_global} — Biplot", dpi=dpi,
    )
    figures["biplot"] = fig
    alertes.extend(msgs)

    # Double projection si familles disponibles
    if pivot_fam_norm is not None and not pivot_fam_norm.empty:
        fig, msgs = biplot_double_projection(
            pivot_norm, pivot_fam_norm, lb_map,
            fam_map=fam_map,
            ordre_stations=ordre_stations, lb_stations=lb_stations,
            n_vecteurs=n_vecteurs, echelle_vecteur=echelle_vecteur,
            corpus_commun=corpus_commun, seuil_imputation=seuil_imputation,
            titre=f"{titre_global} — Double projection", dpi=dpi,
        )
        figures["biplot_fam"] = fig
        alertes.extend(msgs)

    # Dendrogramme
    fig, msgs, clusters = dendrogramme_stations(
        pivot_norm,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        methode_linkage=methode_linkage, n_clusters=n_clusters,
        titre=f"{titre_global} — Clustering", dpi=dpi,
    )
    figures["dendro"] = fig
    alertes.extend(msgs)

    # Matrice de corrélation
    fig, msgs = matrice_correlations(
        pivot_norm, lb_map,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        methode=methode_corr,
        titre=f"{titre_global} — Corrélations ({methode_corr})", dpi=dpi,
    )
    figures["corr"] = fig
    alertes.extend(msgs)

    # Scree plot
    fig, msgs = scree_plot(
        pivot_norm,
        ordre_stations=ordre_stations, lb_stations=lb_stations,
        titre=f"{titre_global} — Éboulis des valeurs propres", dpi=dpi,
    )
    figures["scree"] = fig
    alertes.extend(msgs)

    return figures, alertes


# ---------------------------------------------------------------------------
# Bloc de test autonome
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    print("=== Test M04 — Analyses multivariées ===\n")

    rng = np.random.default_rng(42)

    # Données synthétiques : 6 stations, 12 paramètres
    stations = ["ST001", "ST002", "ST003", "ST004", "ST005", "ST006"]
    params = [1311, 1312, 1313, 1335, 1340, 1433, 1350, 1303, 1301, 1314, 1319, 1436]
    lb_map = {
        1311: "O₂ dissous", 1312: "Sat. O₂", 1313: "DBO5", 1335: "NH4+",
        1340: "Nitrates", 1433: "PO4", 1350: "P total", 1303: "Conductivité",
        1301: "Température", 1314: "DCO", 1319: "NKJ", 1436: "Chlorophylle a",
    }
    lb_stations = {
        "ST001": "Amont source", "ST002": "Confluence A",
        "ST003": "Station urbaine", "ST004": "Aval rejet",
        "ST005": "Bras mort", "ST006": "Exutoire",
    }

    # Deux groupes de stations avec profils différenciés
    data = rng.standard_normal((6, 12))
    data[:2, :3] -= 1.5   # Amont : O2 bon
    data[3:5, 3:6] += 2.0  # Aval rejet : azote/phosphore élevés

    pivot_norm = pd.DataFrame(data, index=stations, columns=params)

    # Familles synthétiques
    fam_data = rng.standard_normal((6, 4))
    pivot_fam_norm = pd.DataFrame(
        fam_data, index=stations,
        columns=["Bilan O₂", "Azote", "Phosphore", "Minéralisation"]
    )

    os.makedirs("test_output_m04", exist_ok=True)

    # --- Scree plot ---
    fig, alertes = scree_plot(pivot_norm, lb_stations=lb_stations)
    print("Scree :", alertes)
    fig.savefig("test_output_m04/scree.png", bbox_inches="tight")
    plt.close(fig)

    # --- Biplot ---
    fig, alertes = biplot_acp(pivot_norm, lb_map, lb_stations=lb_stations, n_vecteurs=8)
    print("Biplot :", alertes)
    fig.savefig("test_output_m04/biplot.png", bbox_inches="tight")
    plt.close(fig)

    # --- Double projection ---
    fig, alertes = biplot_double_projection(
        pivot_norm, pivot_fam_norm, lb_map, lb_stations=lb_stations
    )
    print("Double proj :", alertes)
    fig.savefig("test_output_m04/biplot_double.png", bbox_inches="tight")
    plt.close(fig)

    # --- Dendrogramme ---
    fig, alertes, clusters = dendrogramme_stations(
        pivot_norm, lb_stations=lb_stations, n_clusters=3
    )
    print("Dendro :", alertes)
    print("Clusters :", clusters)
    fig.savefig("test_output_m04/dendro.png", bbox_inches="tight")
    plt.close(fig)

    # --- Corrélations ---
    fig, alertes = matrice_correlations(pivot_norm, lb_map, lb_stations=lb_stations)
    print("Corrélations :", alertes)
    fig.savefig("test_output_m04/correlations.png", bbox_inches="tight")
    plt.close(fig)

    # --- Figure complète ---
    figures, alertes = figure_multivar_complete(
        pivot_norm, lb_map,
        pivot_fam_norm=pivot_fam_norm,
        lb_stations=lb_stations,
        n_clusters=3,
    )
    print("Figure complète :", alertes)
    for nom, fig in figures.items():
        fig.savefig(f"test_output_m04/{nom}.png", bbox_inches="tight")
        plt.close(fig)

    print(f"\n✅ Figures générées dans test_output_m04/ : {list(figures.keys())}")
