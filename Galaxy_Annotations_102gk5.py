# (c) Steffen Schreiber, Patrick Wagner 2025
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This script is a customized version of the original Galaxy Annotations script
# created by Steffen Schreiber and Patrick Wagner.
#
# Original repository:
# https://gitlab.com/schreiberste/siril-scripts
# Based on official version: v1.0.2
#
# Customized by: gonkane, 2025 — version 1.0.2-gk.5
# See version history below for details.
#
# License: GPL v3 or later (see LICENSE file for details)

"""
Siril 用銀河アノテーションスクリプト（カスタム版 1.0.2-gk.5 by gonkane）

このスクリプトは、Steffen Schreiber 氏と Patrick Wagner 氏による
Galaxy Annotations Script (v1.0.2) を拡張・調整したものです。

本カスタム版の主なポイント：
- 内蔵カタログ（Messier / NGC / IC / Star）対応
- 内蔵カタログから読み取った天体は、銀河に限定せず“すべて”表示対象
- Simbad＋ローカル注釈の統合
- 天体ごとの表示（ON/OFF）、色、表示名、座標、半径の個別制御
- Object ウィンドウと C/O/T/N 画像切替を備えた拡張 GUI
- 中心座標が同一の天体は注釈円/枠を外側へ拡張して重なりを回避
- M/NGC/IC の重複抑制：座標と半径が同一でカタログが異なる場合、
  最初の1件のみ表示ON、以降はリスト表示（OFF）
- Apply：Simbad 取得天体をカタログ順で並べ替え。
  非選択カタログの天体は名前と TYPE をコンソールに出力
- Replace / Reapply：CSV を“そのまま”読み込み（並べ替え・カタログ絞り込みなし）
- Defaults ボタン：
  * Apply直後 → Objectウィンドウ作成時の ON/OFF 状態に復元
  * Replace直後 → CSV 読み込み直後の ON/OFF 状態に復元

gk.5 での主な更新：
- Objectウィンドウ：表示のON/−切替ではNoを即時更新せず、ReApply/天体標本作成時に再採番
- ラベル配置：8方向×2半径＝16候補からコスト最小配置（衝突・画面外・楕円交差を考慮）
- Simbadの楕円パラメータ（galdim_majaxis/minaxis/angle）対応（ellipses描画）
- Stars/M/IC/NGCのCSV行順を保持し、表示順・番号へ反映
- Export CSV：列名の日本語化（Name/TYPE含む）、表示名列は末尾へ移動
- Replace CSV：長径・短径・回転角度も含め“そのまま”反映（並べ替え無し）
- Table画像：dpi=200固定。結合画像作成時のサイズ不一致にも対応
- 進捗表示：結合画像/テーブル生成の進行をSirilコンソールに逐次表示
- WCSガード：プレートソルブ未実施時に一度だけ警告し安全終了
- 表示正規化：ロバスト百分位により白飛びを抑制したオーバーレイ描画
- UI：C/O/T/Nボタン位置の整理・11行表示レイアウト調整

詳しくはこのフォークの「Version History / Releases」を参照してください。
"""

import os
import sys
import time
import math
import argparse
import tkinter as tk

# ---- Debug Log Flags (default: OFF) ----
GA_DEBUG_STARS_CSV_LOG = False      # [Stars] CSV行順 先頭20件
GA_DEBUG_OBJECT_ORDER_LOG = False   # [Object順チェック] 系（Objectウィンドウ並び確認）
# ----------------------------------------

from tkinter import ttk, filedialog, messagebox, colorchooser

def _ask_okcancel_front(title, message, parent_win=None):
    from tkinter import messagebox
    win = parent_win
    if win is None:
        return messagebox.askokcancel(title, message)
    try:
        prev_top = bool(win.attributes('-topmost'))
    except Exception:
        prev_top = False
    try:
        try:
            win.attributes('-topmost', True)
        except Exception:
            pass
        try:
            win.update_idletasks()
        except Exception:
            pass
        return messagebox.askokcancel(title, message, parent=win)
    finally:
        try:
            win.attributes('-topmost', prev_top)
        except Exception:
            pass
        try:
            win.lift()
            win.focus_force()
            win.after(10, win.lift)
        except Exception:
            pass

_SHUTTING_DOWN = False

def _load_custom_csv_paths_from_lines(lines):
    """Load custom CSV paths (NEW format only).

    NEW format: lines[4]=Stars, [5]=M, [6]=IC, [7]=NGC.
    Settings start at line 8 (0-based).
    Returns (paths_dict, has_stars_line=True).
    """
    def _pick(i: int) -> str:
        try:
            return (lines[i] if len(lines) > i else '').strip()
        except Exception:
            return ''

    stars = _pick(4)
    m     = _pick(5)
    ic    = _pick(6)
    ngc   = _pick(7)
    has_stars_line = True
    return {'Stars': stars, 'M': m, 'IC': ic, 'NGC': ngc}, has_stars_line

def _robust_rescale01(arr, low=0.1, high=99.9):
    import numpy as _np
    a = _np.asarray(arr)
    if a.size == 0:
        return _np.zeros_like(a, dtype=_np.float32)
    # ensure float
    if not _np.issubdtype(a.dtype, _np.floating):
        a = a.astype(_np.float32, copy=False)
    # mask non-finite
    m = _np.isfinite(a)
    if not _np.any(m):
        return _np.zeros_like(a, dtype=_np.float32)
    vals = a[m]
    try:
        lo, hi = _np.nanpercentile(vals, [low, high])
    except Exception:
        lo, hi = float(_np.nanmin(vals)), float(_np.nanmax(vals))
    if not _np.isfinite(lo) or not _np.isfinite(hi) or lo >= hi:
        lo, hi = float(_np.nanmin(vals)), float(_np.nanmax(vals))
        if lo == hi:
            return _np.zeros_like(a, dtype=_np.float32)
    out = (a - lo) / max(1e-12, (hi - lo))
    _np.clip(out, 0.0, 1.0, out=out)
    return out.astype(_np.float32, copy=False)
# ----------------------------------------------------------------------

import sirilpy as s
# Check the module version is enough to provide get_image_fits_header(return_as = 'dict')
if not s.check_module_version('>=0.6.37'):
    print("Error: requires sirilpy module >=0.6.37 (Siril 1.4.0 Beta 2)")
    sys.exit(1)

from sirilpy import tksiril, SirilError
s.ensure_installed("ttkthemes")
s.ensure_installed("astropy", "astroquery", "matplotlib", "numpy", "pandas", "Pillow", "scikit-image")

from ttkthemes import ThemedTk
import numpy as np  # top-level import for annotate_fit and image ops


# Add any additional imports here
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Ellipse

# ---- WCS / Plate-solve guard (gk.13c) ----------------------------------------
_GA_WCS_WARNED = False

def _ga_has_wcs(hdr: dict) -> bool:
    if not isinstance(hdr, dict):
        return False
    ctype1 = str(hdr.get("CTYPE1", "")).upper()
    ctype2 = str(hdr.get("CTYPE2", "")).upper()
    has_axes = ("CRVAL1" in hdr and "CRVAL2" in hdr)
    has_matrix = any(k in hdr for k in ("CD1_1","PC1_1","CDELT1"))
    is_sky = (("RA" in ctype1 or "GLON" in ctype1) and ("DEC" in ctype2 or "GLAT" in ctype2))
    return has_axes and has_matrix and is_sky

def _ga_ensure_platesolved_or_exit():
    """Return True if OK; if not plate-solved, show a single warning and return False."""
    global _GA_WCS_WARNED
    try:
        import sirilpy as _s
        hdr = _s.get_image_fits_header(return_as='dict')
    except Exception:
        hdr = None
    ok = _ga_has_wcs(hdr)
    if not ok and not _GA_WCS_WARNED:
        _GA_WCS_WARNED = True
        msg = ("現在開いている画像には星の位置情報が不足しています。\n"
               "このスクリプトはWCS情報（CRVAL/CD/PC/CTYPE）が必要です。\n"
               "・Sirilの『アストロメトリー』でPlate Solveを実行し保存してください。\n"
               "・保存後にもう一度スクリプトを起動してください。")
        try:
            # GUI環境ならダイアログ、無ければprintのみ
            from tkinter import messagebox, Tk
            try:
                # avoid creating a visible root if none
                root = Tk(); root.withdraw()
            except Exception:
                root = None
            messagebox.showwarning("Plate-solve required", msg)
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass
        except Exception:
            pass
        print("[GalaxyAnnotations] WCS not found. Abort.")
    return ok
# ---- Warn-once helper for missing plate-solve (gk.13d) -----------------------
_GA_WCS_WARNED_ONCE = False
def _ga_warn_once_wcs_not_solved():
    global _GA_WCS_WARNED_ONCE
    if _GA_WCS_WARNED_ONCE:
        return
    _GA_WCS_WARNED_ONCE = True
    msg = ("開いている画像はプレートソルブされていません。\n"
           "Sirilの『アストロメトリー』でPlate Solveを実行し、\n"
           "ソルブ後に画像を保存してから再実行してください。")
    try:
        # Try Siril console log first if available
        import sirilpy as _s
        try:
            _s.log(msg, color=_s.LogColor.RED)
            return
        except Exception:
            pass
    except Exception:
        pass
    try:
        from tkinter import messagebox, Tk
        try:
            root = Tk(); root.withdraw()
        except Exception:
            root = None
        messagebox.showerror("Plate Solving Required", msg)
        if root is not None:
            try: root.destroy()
            except Exception: pass
    except Exception:
        # Fallback to stdout
        print("[GalaxyAnnotations] " + msg)
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
from skimage.transform import resize
from PIL import Image
# Image.MAX_IMAGE_PIXELS = None  # 大きい画像読込時の安全装置を解除（上限を自前で管理するため）
from astropy.io import fits
from astropy.coordinates import SkyCoord
from astropy import coordinates as coord
from astropy.wcs.utils import skycoord_to_pixel
from astropy.table import Table
import astropy.units as u
from astropy.wcs import WCS
from astroquery.simbad import Simbad
import pandas as pd

# Optional: enable Feather cache if pyarrow is available
try:
    import pyarrow  # noqa: F401
    _GA_HAS_ARROW = True
except Exception:
    _GA_HAS_ARROW = False


# Control: write cache (CSV/Feather) on Apply. Set False to avoid creating files on Apply.
GA_AUTO_WRITE_APPLY_CACHE = False
from pathlib import Path
from matplotlib.lines import Line2D

VERSION = "1.0.2-gk.13a-...-storder+csv4-prep1-prep"


# === PREP TODO ============================================================
# - Combined image generation: print progress to Siril console per image
# - Keep Apply/ReApply = Overlay only (Table/Combined via Object window)
# - Maintain CSV order (csv_order/_csv_order) and disable re-sorting
# - Defaults snapshot updates only on Apply, not on ReApply
# - Export CSV JP header order; display_name placed at the rightmost column
# - Replace CSV: full refresh and Object re-open path
# - Stars/M/IC/NGC CSV path order in Advanced settings
# - Single WCS-guard check and safe early exit when unsolved
# - 11 visible rows layout; after: C/O/T/N buttons
# =========================================================================
CONFIG_FILENAME = "Galaxy_Annotations.conf"


def load_builtin_catalog(filepath, catalog_type):
    if not os.path.exists(filepath):
        print(f"Catalog file not found: {filepath}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(filepath)
        # Preserve CSV row order for later Object-window sorting
        try:
            df['_csv_order'] = np.arange(len(df), dtype=int)
        except Exception:
            try:
                import numpy as _np
                df['_csv_order'] = _np.arange(len(df), dtype=int)
            except Exception:
                df['_csv_order'] = list(range(len(df)))
    except Exception as e:
        print(f"Error loading catalog {filepath}: {e}")
        return pd.DataFrame()

    required_columns = {'name', 'ra', 'dec'}
    if not required_columns.issubset(df.columns):
        print(f"Missing required columns in: {filepath}")
        return pd.DataFrame()

    df = df.dropna(subset=['ra', 'dec'])
    # Transfer preserved order after NA-drop
    try:
        df['csv_order'] = df['_csv_order'].astype('Int64')
        df = df.drop(columns=['_csv_order'])
    except Exception:
        pass
    df['main_id'] = df['name'].astype(str)
    df['TYPE'] = catalog_type
    df['ra'] = pd.to_numeric(df['ra'], errors='coerce')
    df['dec'] = pd.to_numeric(df['dec'], errors='coerce')
    df['galdim_majaxis'] = pd.to_numeric(df.get('diameter', np.nan), errors='coerce')

    def make_display_name(row):
        main_id = str(row['main_id'])
        alias = row.get('alias')
        if pd.notna(alias):
            alias_str = str(alias).strip()
            if alias_str and not alias_str.startswith(main_id):
                return f"{main_id}/{alias_str}"
        return main_id

    df['display_name'] = df.apply(make_display_name, axis=1)
    df['original_display_name'] = df['display_name']
    return df


def load_custom_star_catalog(filepath, catalog_type="Stars"):
    if not os.path.exists(filepath):
        print(f"Star catalog not found: {filepath}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(filepath)
        # Preserve CSV row order for later Object-window sorting
        try:
            df['_csv_order'] = np.arange(len(df), dtype=int)
        except Exception:
            try:
                import numpy as _np
                df['_csv_order'] = _np.arange(len(df), dtype=int)
            except Exception:
                df['_csv_order'] = list(range(len(df)))
    except Exception as e:
        print(f"Failed to load star catalog: {e}")
        return pd.DataFrame()

    required_columns = {'name', 'ra', 'dec'}
    if not required_columns.issubset(df.columns):
        print("Missing required columns in star catalog.")
        return pd.DataFrame()

    df = df.dropna(subset=['ra', 'dec'])
    # Transfer preserved order after NA-drop
    try:
        df['csv_order'] = df['_csv_order'].astype('Int64')
        df = df.drop(columns=['_csv_order'])
    except Exception:
        pass
    df['main_id'] = df['name'].astype(str)
    df['ra'] = pd.to_numeric(df['ra'], errors='coerce')
    df['dec'] = pd.to_numeric(df['dec'], errors='coerce')
    df['TYPE'] = catalog_type

    def estimate_angular_size_from_mag(row):
        try:
            mag = float(row.get('mag', np.nan))
            if np.isnan(mag):
                return 3.0
            return max(1.5, 12.0 - 1.5 * mag)
        except Exception:
            return 3.0

    df['galdim_majaxis'] = df.apply(estimate_angular_size_from_mag, axis=1)

    def make_display_name(row):
        main_id = str(row['main_id'])
        alias = row.get('alias')
        if pd.notna(alias) and str(alias).strip():
            return f"{main_id}/{str(alias).strip()}"
        return main_id

    df['display_name'] = df.apply(make_display_name, axis=1)
    df['original_display_name'] = df['display_name']
    # --- Stars CSV行順のログ出力（先頭20件） ---
    try:
        if 'csv_order' in df.columns:
            try:
                names = df['name'] if 'name' in df.columns else df['main_id']
            except Exception:
                names = df.get('main_id')
            try:
                orders = df['csv_order'].astype('Int64').astype(str).tolist()[:20]
            except Exception:
                orders = [str(x) for x in list(df['csv_order'])[:20]]
            head = list(zip(orders, list(map(str, list(names)[:20]))))
            msg = "[Stars] CSV行順 先頭20件: " + ", ".join([f"{o}:{n}" for o, n in head])
            print(msg) if GA_DEBUG_STARS_CSV_LOG else None
            try:
                s.log(msg, color=s.LogColor.CYAN) if GA_DEBUG_STARS_CSV_LOG else None
            except Exception:
                pass
    except Exception:
        pass

    return df


def find_catalogue_dir(siril=None):
    # 1) Siril.app の標準位置（macOS）
    mac_app = Path("/Applications/Siril.app/Contents/Resources/share/siril/catalogue")
    # 2) Siril 内蔵 Python を想定
    exe = Path(sys.executable).resolve()
    mac_rel = exe.parents[1] / "Resources" / "share" / "siril" / "catalogue"

    # 3) Linux
    linux1 = Path("/usr/share/siril/catalogue")
    linux2 = Path("/usr/local/share/siril/catalogue")

    # 4) Windows
    win = Path(r"C:\Program Files\Siril\share\siril\catalogue")

    # 5) ユーザ設定ディレクトリ
    try:
        cfg = Path(siril.get_siril_configdir()) / "catalogue" if siril else None
    except Exception:
        cfg = None

    for p in [mac_rel, mac_app, linux1, linux2, win, cfg]:
        if p and p.is_dir():
            return str(p)
    return None


def annotate_fit(siril, fit, catalogs, output, title, logo_path, overlay_alpha, overlay_type,
                 custom_object_colors, visible_object_names=None, preloaded_df=None,
                 reapply=False, display_name_vars=None, custom_catalog_files=None,
                 # サイズ未取得時のフォールバック表示
                 fallback_mode="default", fallback_radius_px=60,
                 fallback_line_len_px=60, fallback_center_gap_px=40,
                 # 通常の番号表示（全体）
                 label_number_mode="default", label_threshold_px=200,
                 # サイズ未取得天体のラベル形式 override
                 size_missing_label_mode="num",  # "num" or "num_name" or "name_only"
                 # 各天体ごとの個別表示モード（"No" / "No+DN" / "DN"）
                 per_object_label_overrides=None,
                 # テーブル出力のページング/横並び上限
                 table_max_per_page=25, table_max_cols=5,
                 generate_table=False, generate_combined=False
                 , square_layout=False):
    unselected_log = []  # 未選択カタログをログ出力

    print(f"Title: {title}")
    print(f"Logo: {logo_path}")

    main_object = title
    output_fname = get_combined_filename(output)
    output_overlay_fname = get_overlay_filename(output)
    output_table_fname = get_table_filename(output)
    import os, time
    base = os.path.join(os.path.dirname(output) or ".", "__ga_tmp_input")
    tmp_png = base + ".png"
    # Prefer high-bit-depth image directly from Siril first; fallback to temporary PNG if needed.
    # Prefer high-bit FITS data first; set a flag to unify orientation logic
    try:
        _fit = siril.get_image()
        raw = np.array(_fit.data, copy=True)
        _src_is_fits = True
        NEED_Y_FLIP = False
    except Exception as _e:
        try:
            try:
                siril.cmd("savepng", base)
            except Exception:
                siril.cmd("savepng", tmp_png)
            for _ in range(50):
                if os.path.isfile(tmp_png) or os.path.isfile(base + ".png") or os.path.isfile(tmp_png + ".png"):
                    break
                time.sleep(0.1)
            png_path = (tmp_png if os.path.isfile(tmp_png) else
                        (base + ".png" if os.path.isfile(base + ".png") else
                         (tmp_png + ".png" if os.path.isfile(tmp_png + ".png") else None)))
            if not png_path:
                raise RuntimeError("Temporary PNG was not created by Siril")
            from PIL import Image
            raw = np.array(Image.open(png_path))
            _src_is_fits = False
            NEED_Y_FLIP = True
        except Exception as _e2:
            raise RuntimeError(f"Could not retrieve image: {_e} / {_e2}")
    if raw.ndim == 2:
        img = raw
        H, W = img.shape
        C = 1
    elif raw.ndim == 3 and raw.shape[0] in (1,3) and raw.shape[1] != raw.shape[0]:
        img = np.transpose(raw, (1,2,0))
        H, W, C = img.shape
    else:
        img = raw
        H, W, C = img.shape
    print(f"Input dimensions: {W} x {H}")
    minsize_pixels = 5
    min_patch_size = int(round(max(W, H) / 100))
    # Keep native dtype; normalize to 0..1 float only where required (e.g., before resizing patches).
    (center_ra, center_dec) = siril.pix2radec(W / 2, H / 2)
    print(f"Center: {center_ra, center_dec}")

    header = siril.get_image_fits_header(return_as='dict')
    wcs = WCS(header, naxis=[1, 2])

    # --- Step 1: データ取得 ---
    simbad_ellipse_map = {}  # main_id -> (a_arcmin, b_arcmin, pa_deg)

    if preloaded_df is not None:
        df = preloaded_df.copy()
        print(f"Using preloaded DataFrame: {df.shape[0]} rows")
    else:
        CATALOG_DIR = find_catalogue_dir(siril)
        df_list = []
        catalog_files = {}
        if CATALOG_DIR:
            catalog_files = {
                "Stars": os.path.join(CATALOG_DIR, "stars.csv"),
                "M":     os.path.join(CATALOG_DIR, "messier.csv"),
                "NGC":   os.path.join(CATALOG_DIR, "ngc.csv"),
                "IC":    os.path.join(CATALOG_DIR, "ic.csv"),
            }
        else:
            print("Could not locate Siril catalogue directory; built-in CSVs will be skipped.")

        # ユーザー指定があれば優先
        if custom_catalog_files:
            for k in ('Stars', 'M', 'IC', 'NGC'):
                p = (custom_catalog_files.get(k) or "").strip()
                if p:
                    catalog_files[k] = p

        # 内蔵CSV（選択されているものだけ読み込み）
        for key, filename in catalog_files.items():
            if catalogs.get(key) and catalogs[key].get_selected():
                if key == "Stars":
                    df_cat = load_custom_star_catalog(filename, key)
                else:
                    df_cat = load_builtin_catalog(filename, key)
                if not df_cat.empty:
                    df_list.append(df_cat)

        # Simbad クエリ（銀河全体・楕円情報取得目的）
        EXCLUDED_SOURCES = ['Stars', 'M', 'IC', 'NGC']

        need_simbad_galaxies = True
        if need_simbad_galaxies:
            simbad = Simbad()
            simbad.TIMEOUT = 120
            simbad.add_votable_fields("otype", "galdim_majaxis", "galdim_minaxis", "galdim_angle", "ra", "dec")

            target_coord = SkyCoord(ra=center_ra * u.deg, dec=center_dec * u.deg, frame='icrs')

            # 画像四隅から検索半径を推定
            corners = [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]
            corner_coords = [
                SkyCoord(*siril.pix2radec(x, y), unit=(u.deg, u.deg), frame='icrs')
                for (x, y) in corners
            ]
            radius_deg = max(target_coord.separation(cc).deg for cc in corner_coords)

            # ピクセルスケール（1pxの角分）
            p0 = target_coord
            p1 = SkyCoord(*siril.pix2radec(W / 2 + 1, H / 2), unit=(u.deg, u.deg), frame='icrs')
            pixscale_arcmin = p0.separation(p1).arcmin
            minsize_arcmin = max(0.0, float(minsize_pixels) * float(pixscale_arcmin))

            radius = radius_deg * u.deg
            criteria_opt = (
                "otype='Galaxy..' AND "
                f"(galdim_majaxis>{minsize_arcmin:.6f} OR galdim_majaxis IS NULL)"
            )

            print(f"Query radius: {radius_deg:.6f} deg")
            print(f"      minimum size: {minsize_pixels} pixels ~ {minsize_arcmin:.3f}分")
            print(f"      criteria: {criteria_opt}")

            result_table = None
            try:
                result_table = simbad.query_region(target_coord, radius=radius, criteria=criteria_opt)
            except TypeError:
                try:
                    result_table = simbad.query_region(target_coord, radius=radius)
                except Exception as e:
                    print(f"Simbad query failed (no-criteria fallback): {e}")
            except Exception as e:
                print(f"Simbad query failed: {e}")

            if result_table is None or len(result_table) == 0:
                print("Simbad query returned no results.")
            else:
                try:
                    result_table.sort("galdim_majaxis", reverse=True)
                except Exception:
                    pass

                # --- Simbad 結果を DataFrame に ---
                df_simbad = result_table.to_pandas()
                df_simbad = df_simbad[(df_simbad['galdim_majaxis'].isna()) | (df_simbad['galdim_majaxis'] >= minsize_arcmin)]

                # main_id整形
                df_simbad['main_id'] = df_simbad['main_id'].astype(str) \
                    .str.replace(r'\s+', ' ', regex=True).str.strip()

                # M/NGC/IC は中間空白を削除
                mask_mni = df_simbad['main_id'].str.match(r'^(M|NGC|IC)\s+', na=False)
                df_simbad.loc[mask_mni, 'main_id'] = df_simbad.loc[mask_mni, 'main_id'].str.replace(' ', '', regex=False)

                print(f"Simbad query results: {df_simbad.shape[0]} entries")

                # 数値化
                for col in ("ra", "dec", "galdim_majaxis", "galdim_minaxis", "galdim_angle"):
                    if col in df_simbad.columns:
                        df_simbad[col] = pd.to_numeric(df_simbad[col], errors="coerce")

                # RA/DEC のフォールバック
                if df_simbad['ra'].isna().any() or df_simbad['dec'].isna().any():
                    try:
                        ra_col = 'RA' if 'RA' in df_simbad.columns else 'ra'
                        dec_col = 'DEC' if 'DEC' in df_simbad.columns else 'dec'
                        sc = SkyCoord(df_simbad[ra_col].astype(str), df_simbad[dec_col].astype(str),
                                      unit=(u.hourangle, u.deg), frame='icrs')
                        df_simbad['ra'] = sc.ra.deg
                        df_simbad['dec'] = sc.dec.deg
                    except Exception as e:
                        print(f"Failed to normalize RA/DEC to degrees: {e}")

                df_simbad.dropna(subset=["ra", "dec"], inplace=True)

                # 表示名
                df_simbad['display_name'] = df_simbad['main_id']
                df_simbad['original_display_name'] = df_simbad['main_id']

                import re

                def detect_type(name: str) -> str:
                    raw = str(name).strip()
                    m = re.match(r'^\[([A-Za-z0-9]+)\]', raw)
                    if m:
                        return m.group(1).upper()

                    n = re.sub(r'\s+', ' ', raw).upper().strip()

                    if re.match(r'^M\d+', n):   return 'M'
                    if re.match(r'^NGC\d+', n): return 'NGC'
                    if re.match(r'^IC\d+', n):  return 'IC'

                    if re.match(r'^2MASX([ \-_]|[A-Z0-9])', n): return '2MASX'
                    if re.match(r'^2MASS([ \-_]|[A-Z0-9])', n): return '2MASS'
                    if re.match(r'^(?<!\d)MASS([ \-_]|[A-Z0-9])', n): return 'MASS'

                    known_prefixes = [k.upper() for k in catalogs.keys()]
                    known_prefixes.sort(key=len, reverse=True)
                    for key in known_prefixes:
                        if n.startswith(key + ' ') or n.startswith(key + '-') or n.startswith(key + '_') or n == key:
                            return key
                        if re.match(r'^' + re.escape(key) + r'[A-Z0-9]', n):
                            return key

                    m2 = re.match(r'^([A-Z0-9]+)', n)
                    return m2.group(1) if m2 else 'Unknown'

                df_simbad['TYPE'] = df_simbad['main_id'].apply(detect_type)

                # ---- 楕円パラメータを全件キャッシュ ----
                for r in df_simbad[['main_id', 'galdim_majaxis', 'galdim_minaxis', 'galdim_angle']].itertuples(index=False):
                    name = str(r.main_id).upper()
                    a = float(r.galdim_majaxis) if pd.notna(r.galdim_majaxis) else np.nan
                    b = float(r.galdim_minaxis) if pd.notna(r.galdim_minaxis) else np.nan
                    pa = float(r.galdim_angle) if pd.notna(r.galdim_angle) else np.nan
                    simbad_ellipse_map[name] = (a, b, pa)

                # 描画順調整
                if not reapply and not df_simbad.empty:
                    order_map = {k: i for i, k in enumerate(catalogs.keys())}
                    df_simbad['_ord'] = df_simbad['TYPE'].map(order_map).fillna(999)
                    df_simbad = df_simbad.sort_values(['_ord', 'main_id'], kind='stable').drop(columns=['_ord'])

                # 選択外カタログをログに
                selected_types = {k for k, v in catalogs.items() if v.get_selected()}
                unselected_preview = df_simbad[~df_simbad['TYPE'].isin(selected_types)]
                if not unselected_preview.empty:
                    unselected_log.extend(unselected_preview[['main_id', 'TYPE']].astype(str).to_dict('records'))

                simbad_others = df_simbad[~df_simbad['TYPE'].isin({'M', 'NGC', 'IC'})]
                simbad_others = simbad_others[simbad_others['TYPE'].isin(selected_types)]
                if not simbad_others.empty:
                    df_list.append(simbad_others)

        if not df_list:
            print("No catalog data loaded.")
            return pd.DataFrame(), 0, pd.DataFrame(), {"table_pages": 1, "combined_pages": 1}

        # Simbad 楕円値を CSV 側にもマージ（楕円モード時のみ）
        df = pd.concat(df_list, ignore_index=True)

        if simbad_ellipse_map and overlay_type == "ellipses":
            def apply_simbad_ellipse(row):
                key = str(row['main_id']).upper()
                a, b, pa = simbad_ellipse_map.get(key, (np.nan, np.nan, np.nan))
                if pd.notna(a):  row['galdim_majaxis'] = a
                if pd.notna(b):  row['galdim_minaxis'] = b
                if pd.notna(pa): row['galdim_angle']   = pa
                return row

            df = df.apply(apply_simbad_ellipse, axis=1)

    # --- Step 2: ピクセル座標変換 ---
    import warnings
    from astropy.utils.exceptions import AstropyWarning
    warnings.filterwarnings("ignore", category=UserWarning, message=".*all_world2pix.*")
    warnings.filterwarnings("ignore", category=AstropyWarning)

    wcs_error_entries = []

    def safe_radec2pix(row):
        try:
            x, y = siril.radec2pix(row['ra'], row['dec'])
            if not (np.isfinite(x) and np.isfinite(y)):
                raise ValueError("radec2pix returned non-finite values")
            return (x, y)
        except Exception as e:
            wcs_error_entries.append((row.get('main_id', 'Unknown'), row['ra'], row['dec'], str(e)))
            return (np.nan, np.nan)

    # 各行をWCSでpx/pyへ変換
    df['Pixel_Position'] = df.apply(safe_radec2pix, axis=1)

    # 有効な座標だけ残す
    df = df[df['Pixel_Position'].apply(lambda x: np.isfinite(x[0]) and np.isfinite(x[1]))].copy()

    # px/py 付与
    df['px'] = df['Pixel_Position'].apply(lambda x: int(round(x[0])))
    df['py'] = df['Pixel_Position'].apply(lambda x: int(round(x[1])))

    # WCS変換失敗のサマリ
    if wcs_error_entries:
        print(f"WCS conversion failed for {len(wcs_error_entries)} entries (showing first 5):")
        for rec in wcs_error_entries[:5]:
            print("  main_id=", rec[0], " ra=", rec[1], " dec=", rec[2], " err=", rec[3])

    # 画像範囲内のみ
    df = df[(df.px > min_patch_size) & (df.py > min_patch_size)
            & (df.px < W - min_patch_size) & (df.py < H - min_patch_size)].copy()

    print(f"Filtered query result by image coordinates: {df.shape[0]} entries")

    if df.empty:
        print("No valid objects remain after WCS projection and image-boundary filtering.")
        return pd.DataFrame(), 0, pd.DataFrame(), {"table_pages": 1, "combined_pages": 1}

    if not reapply and unselected_log:
        from collections import defaultdict
        type_to_names = defaultdict(list)
        seen = defaultdict(set)
        for rec in unselected_log:
            t = str(rec.get('TYPE', 'Unknown')) if rec.get('TYPE', None) is not None else 'Unknown'
            name = str(rec.get('main_id', 'Unknown')) if rec.get('main_id', None) is not None else 'Unknown'
            if name not in seen[t]:
                type_to_names[t].append(name)
                seen[t].add(name)

        order_map = {k: i for i, k in enumerate(catalogs.keys())}
        ordered_types = sorted(type_to_names.keys(),
                               key=lambda t: (order_map.get(t, 10**6), t))

        print("=== Unselected catalog objects (name\tTYPE) ===")
        for t in ordered_types:
            names = type_to_names[t]
            first = names[0]
            extra = len(names) - 1
            if extra > 0:
                print(f"  {first}\t{t} (+{extra} more)")
            else:
                print(f"  {first}\t{t}")
        print("=== End of unselected list ===")

    # --- Step 3: カタログフィルタ ---
    if not reapply:
        filter_types = [key for key, value in catalogs.items() if value.get_selected()]
        filtered_result = Table.from_pandas(df[df['TYPE'].isin(filter_types)])
        dfi = filtered_result.to_pandas()
        print(f"Filtered by catalog: {dfi.shape[0]} entries")
    else:
        dfi = df.copy()
        print(f"Skipped catalog filter (ReApply): {dfi.shape[0]} entries")

    # --- Step 4: M/NGC/IC 重複間引き ---
    if not reapply:
        primary_types = [t for t in ['Stars', 'M', 'IC', 'NGC']
                         if (t in catalogs and catalogs[t].get_selected())]
        if len(primary_types) >= 2 and not dfi.empty:
            dedup_priority = {'M': 0, 'IC': 1, 'NGC': 2}
            cand = dfi[dfi['TYPE'].isin(primary_types)].copy()
            cand = cand.sort_values(
                by='TYPE',
                key=lambda s: s.map(lambda t: dedup_priority.get(t, 999))
            )
            to_drop = set()

            def alias_set_val(v):
                if pd.isna(v) or v is None:
                    return set()
                return set([p.strip() for p in str(v).split('/') if p.strip()])

            def same_object(a, b):
                same_pos = (abs(int(a.px) - int(b.px)) <= 1) and (abs(int(a.py) - int(b.py)) <= 1)
                da = float(a.galdim_majaxis) if pd.notna(a.galdim_majaxis) else float('nan')
                db = float(b.galdim_majaxis) if pd.notna(b.galdim_majaxis) else float('nan')
                if not (np.isfinite(da) and np.isfinite(db)):
                    same_rad = True
                else:
                    tol = min(0.5, 0.1 * max(da, db))
                    same_rad = abs(da - db) <= tol
                alias_hit = (str(a.main_id) in alias_set_val(getattr(b, 'alias', None))) or \
                            (str(b.main_id) in alias_set_val(getattr(a, 'alias', None)))
                return (same_pos and same_rad) or alias_hit

            rows = list(cand.iterrows())
            for i, a in rows:
                if i in to_drop:
                    continue
                for j, b in rows:
                    if j <= i or j in to_drop:
                        continue
                    if same_object(a, b):
                        to_drop.add(j)

            if to_drop:
                dfi = dfi.drop(index=list(to_drop))

    # --- Step 4: 同一座標の重複除去（種類ごとに1つ残す） ---
    if not reapply:
        dfi = dfi.drop_duplicates(subset=['px', 'py', 'TYPE'])

    # --- Step 4.5: visible_object_names 補完 ---
    if not reapply and visible_object_names is not None:
        missing_names = dfi[~dfi['main_id'].isin(visible_object_names)]['main_id'].tolist()
        if missing_names:
            print(f"Adding {len(missing_names)} newly detected objects to visible list")
            visible_object_names.extend(missing_names)

    # --- Step 5: ReApply の表示チェック ---
    if reapply and visible_object_names is not None:
        dfi = dfi[dfi['main_id'].isin(visible_object_names)]
        print(f"Filtered by visibility (ReApply): {dfi.shape[0]} entries")
    else:
        print(f"No visibility filter applied (Apply): {dfi.shape[0]} entries")

    # --- Step 6: 重複数・インデックス ---
    dfi['duplicate_count'] = dfi.groupby(['px', 'py'])['main_id'].transform('count')
    dfi['duplicate_index'] = dfi.groupby(['px', 'py']).cumcount()

    print(f"Filtered after removing duplicates: {dfi.shape[0]} entries")

    if dfi.shape[0] == 0:
        print("No objects found in image boundary.")
        return pd.DataFrame(), 0, pd.DataFrame(), {"table_pages": 1, "combined_pages": 1}

    # --- Step 8: 表示順 ---
    sub = 1
    dpi_overlay = 200  # オーバーレイ用のdpi（従来通り）

    # Stars/M/IC/NGC は CSV 読み順で番号付け＆表示順にする（Apply/ReApply 共通）
    rep_dic = {key: f"{i:02d}" for i, key in enumerate(catalogs.keys())}
    dfi['sorting'] = dfi.TYPE.replace(rep_dic)
    try:
        dfi = dfi.sort_values(['sorting'], kind='stable')
        def _within_sort(g):
            t = g['TYPE'].iloc[0] if not g.empty else ''
            if t in ['Stars','M','IC','NGC'] and ('csv_order' in g.columns):
                return g.sort_values(['csv_order'], kind='stable')
            else:
                return g.sort_values(['main_id'], kind='stable')
        _groups = [ _within_sort(g) for _, g in dfi.groupby('TYPE', sort=False) ]
        if _groups:
            dfi = pd.concat(_groups, ignore_index=True)
        else:
            dfi = dfi.reset_index(drop=True)
    except Exception:
        dfi = dfi.sort_values(['sorting', 'main_id'], kind='stable').reset_index(drop=True)

    dfi['anno_num'] = dfi.index + 1

    # --- Step 9: 描画準備 ---
    def _setup_japanese_font():
        import matplotlib
        from matplotlib import font_manager
        cand = ['Yu Gothic', 'Meiryo', 'MS Gothic', 'Yu Mincho',
                'Hiragino Sans', 'Hiragino Kaku Gothic ProN', 'Hiragino Mincho ProN',
                'Noto Sans CJK JP', 'Noto Serif CJK JP', 'IPAGothic', 'IPAMincho']
        available = {f.name for f in font_manager.fontManager.ttflist}
        for name in cand:
            if name in available:
                matplotlib.rcParams['font.family'] = name
                matplotlib.rcParams['axes.unicode_minus'] = False
                print(f"Matplotlib font set to: {name}")
                return
        print("Japanese font not found; warnings may appear.")

    _setup_japanese_font()
    plt.style.use('dark_background')
    extra_axis_label_size_inches = 1.15
    fig = plt.figure(
        figsize=(W / dpi_overlay + extra_axis_label_size_inches, H / dpi_overlay + extra_axis_label_size_inches)
    )
    ax1 = plt.subplot(projection=wcs, label='overlays')
    disp = img[::sub, ::sub]
    if NEED_Y_FLIP:
        disp = np.flipud(disp)
    # Display normalization using robust percentiles to avoid white-out
    if np.issubdtype(disp.dtype, np.floating):
        disp = _robust_rescale01(disp, 0.1, 99.9)
    elif disp.dtype == np.uint16:
        disp = (disp.astype(np.float32) / 65535.0)
    elif disp.dtype == np.uint8:
        disp = (disp.astype(np.float32) / 255.0)
    else:
        disp = _robust_rescale01(disp, 0.1, 99.9)
    ax1.imshow(disp, origin="lower", cmap="gray", vmin=0.0, vmax=1.0)
    ax1.coords.grid(True, color='white', ls=':', alpha=overlay_alpha)
    ax1.coords[0].set_axislabel('Right Ascension (J2000)')
    ax1.coords[1].set_axislabel('Declination (J2000)', minpad=-1)
    ax1.set_title(title, fontsize=24)

    def _draw_four_pointer_lines(ax, cx, cy, line_len, gap, color, alpha, lw=1):
        half_gap = max(1, float(gap) / 2.0)
        ll = max(1, float(line_len))

        x_left1, x_left2 = cx - half_gap - ll, cx - half_gap
        x_right1, x_right2 = cx + half_gap,     cx + half_gap + ll
        y_h = cy

        y_down1, y_down2 = cy - half_gap - ll, cy - half_gap
        y_up1,   y_up2   = cy + half_gap,      cy + half_gap + ll
        x_v = cx

        def _clip_segment(x1, y1, x2, y2, W, H):
            x1 = max(0, min(W-1, x1)); x2 = max(0, min(W-1, x2))
            y1 = max(0, min(H-1, y1)); y2 = max(0, min(H-1, y2))
            return x1, y1, x2, y2

        for (x1, y1, x2, y2) in [
            _clip_segment(x_left1,  y_h, x_left2,  y_h, W, H),
            _clip_segment(x_right1, y_h, x_right2, y_h, W, H),
            _clip_segment(x_v, y_down1, x_v, y_down2, W, H),
            _clip_segment(x_v, y_up1,   x_v, y_up2,   W, H),
        ]:
            ln = Line2D([x1, x2], [y1, y2], lw=lw, color=color, alpha=alpha)
            ax.add_line(ln)
    # GPT PATCH: init patches only when needed
    if generate_table or generate_combined:
        all_patches = []
        filter_idxs = []
    else:
        all_patches = None
        filter_idxs = None

    # --- Step 10: 各天体のアノテーションを描画 ---
    diag = math.hypot(W, H)
    inc_px = max(12.0, diag * 0.01)

    # しきい値（指定時は設定値、デフォルトは 200）
    try:
        label_threshold_px = max(1, int(label_threshold_px))
    except Exception:
        label_threshold_px = 200

    for i, row in dfi.iterrows():
        def _valid_arcmin(v):
            try:
                v = float(v)
                return np.isfinite(v) and v > 0
            except Exception:
                return False

        has_arcmin = _valid_arcmin(row.get('galdim_majaxis', np.nan))

        siril.update_progress(f"Creating patches", i / (10 * dfi.shape[0]))

        fontsize = 12
        base_color = catalogs[row.TYPE].color if row.TYPE in catalogs else "#ff0000"
        color = custom_object_colors.get(row.main_id, base_color)

        angular_size = row.get("galdim_majaxis", np.nan)
        size_factor = 2

        if not has_arcmin:
            known_arcmin = {"M8": 90, "M40": 0.86, "M43": 20, "M78": 8, "M82": 11.2}
            angular_size = known_arcmin.get(str(row.main_id), np.nan)
            has_arcmin = _valid_arcmin(angular_size)

        # パッチサイズ（px）
        if has_arcmin:
            try:
                half_diam_deg = (float(angular_size) / 2.0) / 60.0
                coord_top    = SkyCoord(ra=row.ra * u.deg, dec=(row.dec + half_diam_deg) * u.deg)
                coord_bottom = SkyCoord(ra=row.ra * u.deg, dec=(row.dec - half_diam_deg) * u.deg)
                coord_left   = SkyCoord(ra=(row.ra - half_diam_deg) * u.deg, dec=row.dec * u.deg)
                coord_right  = SkyCoord(ra=(row.ra + half_diam_deg) * u.deg, dec=row.dec * u.deg)

                px_top,    py_top    = siril.radec2pix(coord_top.ra.deg,    coord_top.dec.deg)
                px_bottom, py_bottom = siril.radec2pix(coord_bottom.ra.deg, coord_bottom.dec.deg)
                px_left,   py_left   = siril.radec2pix(coord_left.ra.deg,   coord_left.dec.deg)
                px_right,  py_right  = siril.radec2pix(coord_right.ra.deg,  coord_right.dec.deg)

                d_dec = math.hypot(px_top - px_bottom, py_top - py_bottom)
                d_ra  = math.hypot(px_right - px_left, py_right - py_left)
                patch_diameter_pix = (d_dec + d_ra) / 2.0

                patch_size = int(round(patch_diameter_pix * size_factor))
                patch_size = max(min_patch_size, patch_size)

            except Exception as e:
                siril.log(f"{row.main_id}: WCS radius estimation failed: {e}", color=s.LogColor.RED)
                if fallback_mode == "fixed":
                    patch_diameter_pix = 2.0 * float(fallback_radius_px)
                    patch_size = int(round(patch_diameter_pix * size_factor))
                    patch_size = max(min_patch_size, patch_size)
                else:
                    patch_size = patch_diameter_pix = min_patch_size
        else:
            if fallback_mode == "fixed":
                patch_diameter_pix = 2.0 * float(fallback_radius_px)
                patch_size = int(round(patch_diameter_pix * size_factor))
                patch_size = max(min_patch_size, patch_size)
            else:
                patch_size = patch_diameter_pix = min_patch_size

        # 文字サイズ
        if row.main_id == title:
            fontsize = 20
            color = 'white'
        elif row.TYPE in ['M', 'NGC']:
            fontsize = 18
        elif row.TYPE in ['SAI', 'UGC', 'MCG', 'IC']:
            fontsize = 16

        # 表示名（ReApply 時に編集反映）
        if reapply and display_name_vars:
            var = display_name_vars.get(row.main_id)
            display_name = var.get() if var else row.display_name
        else:
            display_name = row.display_name

        # 個別オーバーライドがあれば最優先適用
        try:
            patch_size_for_label = float(patch_size)  # patch_size(px) を使う
        except Exception:
            patch_size_for_label = float(min_patch_size)

        annotation_text = None
        if per_object_label_overrides and str(row.main_id) in per_object_label_overrides:
            ov = (per_object_label_overrides.get(str(row.main_id), "") or "").strip()
            if ov == "No":
                annotation_text = f"{i + 1}"
            elif ov == "No+DN":
                annotation_text = f"{i + 1}: {display_name}"
            elif ov == "DN":
                annotation_text = f"{display_name}"

        # 個別指定がない場合は全体設定に従う
        if annotation_text is None:
            if not has_arcmin:
                # サイズ情報無し天体
                if size_missing_label_mode == "num_name":
                    annotation_text = f"{i + 1}: {display_name}"
                elif size_missing_label_mode == "name_only":
                    annotation_text = f"{display_name}"
                else:
                    annotation_text = f"{i + 1}"
            else:
                # サイズ情報有り天体
                if label_number_mode == "name_only":
                    annotation_text = f"{display_name}"
                elif label_number_mode == "all":
                    annotation_text = f"{i + 1}: {display_name}"
                elif label_number_mode == "custom":
                    th = label_threshold_px  # patch_size(px) のしきい値
                    annotation_text = f"{i + 1}" if patch_size_for_label <= th else f"{i + 1}: {display_name}"
                else:
                    # default: patch_size≦200px（＝直径100px相当）
                    annotation_text = f"{i + 1}" if patch_size_for_label <= 200 else f"{i + 1}: {display_name}"

        # 描画領域のクリップ
        clipped = min(patch_size, (W - row.px) * 2, row.px * 2, (H - row.py) * 2, row.py * 2)
        x1 = row.px - clipped // 2
        x2 = row.px + clipped // 2
        y1 = H - row.py - clipped // 2
        y2 = H - row.py + clipped // 2

        # Unflipped image coordinates for Table cutouts
        x1_u = row.px - clipped // 2
        x2_u = row.px + clipped // 2
        y1_u = row.py - clipped // 2
        y2_u = row.py + clipped // 2


        # 囲みの描画
        if overlay_type == "boxes":
            size_increment = int(inc_px)
            expansion = (int(row.duplicate_index) if hasattr(row, 'duplicate_index') else 0) * size_increment
            x1_exp, x2_exp = x1 - expansion, x2 + expansion
            y1_exp, y2_exp = y1 - expansion, y2 + expansion

            rect = Rectangle((x1_exp, y1_exp), x2_exp - x1_exp, y2_exp - y1_exp,
                             alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
            ax1.add_patch(rect)

            text_y = y1_exp - 6
            if text_y < 0:
                text_y = min(y2_exp + 6, H - (3 * fontsize))

        elif overlay_type == "ellipses":
            def _to_float(x):
                try:
                    x = float(x)
                    return x if np.isfinite(x) else float("nan")
                except Exception:
                    return float("nan")

            a_arcmin = _to_float(row.get("galdim_majaxis", np.nan))
            b_arcmin = _to_float(row.get("galdim_minaxis", np.nan))
            pa_deg   = _to_float(row.get("galdim_angle",   np.nan))

            if np.isfinite(a_arcmin) and a_arcmin > 0 and np.isfinite(pa_deg):
                if not (np.isfinite(b_arcmin) and b_arcmin > 0):
                    b_arcmin = a_arcmin * 0.6

                ra0, dec0 = float(row.ra), float(row.dec)
                pa = math.radians(pa_deg)
                dec0_rad = math.radians(dec0)
                cosd = max(1e-9, math.cos(dec0_rad))

                a_deg = (a_arcmin / 2.0) / 60.0
                b_deg = (b_arcmin / 2.0) / 60.0

                dra_a  = (a_deg * math.sin(pa)) / cosd
                ddec_a =  a_deg * math.cos(pa)
                dra_b  = (b_deg * math.sin(pa + math.pi/2.0)) / cosd
                ddec_b =  b_deg * math.cos(pa + math.pi/2.0)

                x1a, y1a = siril.radec2pix(ra0 - dra_a, dec0 - ddec_a)
                x2a, y2a = siril.radec2pix(ra0 + dra_a, dec0 + ddec_a)
                x1b, y1b = siril.radec2pix(ra0 - dra_b, dec0 - ddec_b)
                x2b, y2b = siril.radec2pix(ra0 + dra_b, dec0 + ddec_b)

                if not all(np.isfinite(v) for v in [x1a,y1a,x2a,y2a,x1b,y1b,x2b,y2b]):
                    radius_increment = inc_px
                    annot_radius = max(min_patch_size, 1.2 * patch_diameter_pix / 2.0)
                    if hasattr(row, 'duplicate_index'):
                        annot_radius += float(row.duplicate_index) * radius_increment
                    circ = Circle((row.px, H - row.py), radius=annot_radius,
                                  alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
                    ax1.add_patch(circ)
                    text_y = H - row.py - 6 - annot_radius
                    if text_y < 0:
                        text_y = min(H - row.py + 6 + annot_radius, H - (3 * fontsize))
                else:
                    ya1, ya2 = H - y1a, H - y2a
                    yb1, yb2 = H - y1b, H - y2b

                    width_px  = math.hypot(x2a - x1a, y2a - y1a)
                    height_px = math.hypot(x2b - x1b, y2b - y1b)

                    if hasattr(row, 'duplicate_index'):
                        d = float(row.duplicate_index) * inc_px
                        width_px  += 2.0 * d
                        height_px += 2.0 * d

                    angle_deg = math.degrees(math.atan2(ya2 - ya1, x2a - x1a))

                    ell = Ellipse((row.px, H - row.py), width=width_px, height=height_px, angle=angle_deg,
                                  alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
                    ax1.add_patch(ell)

                    text_y = H - row.py - 6 - (height_px / 2.0)
                    if text_y < 0:
                        text_y = min(H - row.py + 6 + (height_px / 2.0), H - (3 * fontsize))

            else:
                if (not has_arcmin) and (fallback_mode == "fourlines"):
                    _draw_four_pointer_lines(
                        ax1, row.px, H - row.py,
                        fallback_line_len_px, fallback_center_gap_px,
                        color, overlay_alpha, lw=1
                    )
                    span = (fallback_center_gap_px / 2.0) + float(fallback_line_len_px)
                    text_y = H - row.py - 6 - span
                    if text_y < 0:
                        text_y = min(H - row.py + 6 + span, H - (3 * fontsize))
                else:
                    radius_increment = inc_px
                    if (not has_arcmin) and (fallback_mode == "fixed"):
                        annot_radius = float(fallback_radius_px)
                        if hasattr(row, 'duplicate_index'):
                            annot_radius += float(row.duplicate_index) * (radius_increment * 0.5)
                    else:
                        annot_radius = max(min_patch_size, 1.2 * patch_diameter_pix / 2.0)
                        if hasattr(row, 'duplicate_index'):
                            annot_radius += float(row.duplicate_index) * radius_increment
                    circ = Circle((row.px, H - row.py), radius=annot_radius,
                                  alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
                    ax1.add_patch(circ)
                    text_y = H - row.py - 6 - annot_radius
                    if text_y < 0:
                        text_y = min(H - row.py + 6 + annot_radius, H - (3 * fontsize))

        else:  # "circles"
            radius_increment = inc_px

            if (not has_arcmin) and (fallback_mode == "fourlines"):
                _draw_four_pointer_lines(
                    ax1, row.px, H - row.py,
                    fallback_line_len_px, fallback_center_gap_px,
                    color, overlay_alpha, lw=1
                )
                span = (fallback_center_gap_px / 2.0) + float(fallback_line_len_px)
                text_y = H - row.py - 6 - span
                if text_y < 0:
                    text_y = min(H - row.py + 6 + span, H - (3 * fontsize))

            else:
                if (not has_arcmin) and (fallback_mode == "fixed"):
                    annot_radius = float(fallback_radius_px)
                    if hasattr(row, 'duplicate_index'):
                        annot_radius += float(row.duplicate_index) * (radius_increment * 0.5)
                else:
                    annot_radius = max(min_patch_size, 1.2 * patch_diameter_pix / 2.0)
                    if hasattr(row, 'duplicate_index'):
                        annot_radius += float(row.duplicate_index) * radius_increment

                circ = Circle((row.px, H - row.py), radius=annot_radius,
                              alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
                ax1.add_patch(circ)

                text_y = H - row.py - 6 - annot_radius
                if text_y < 0:
                    text_y = min(H - row.py + 6 + annot_radius, H - (3 * fontsize))

        text_y = max(0, min(text_y, H - (3 * fontsize)))
        ax1.text(row.px, text_y, annotation_text,
                 ha='center', va='top' if text_y < (H - row.py) else 'bottom',
                 color=color, alpha=overlay_alpha, fontsize=fontsize)

        # パッチ保存用
        # GPT PATCH: flip-before-crop & guard
        if generate_table or generate_combined:
            y1c, y2c = y1, y2
            patch = img[y1c:y2c, x1:x2]
            all_patches.append(patch)
            filter_idxs.append(i)

    plt.tight_layout()
    siril.update_progress("Saving overlay image...", 0.2)
    plt.savefig(output_overlay_fname, bbox_inches='tight', pad_inches=0.1, dpi=dpi_overlay)
    siril.update_progress("Finished overlay image.", 0.3)
    plt.close(fig)

    # If only overlay is requested, skip table/combined generation and return early
    if not generate_table and not generate_combined:
        page_info = {"table_pages": 1, "combined_pages": 1}
        return dfi, dfi.shape[0], df, page_info


    
    # === DIAG (pre-table) ===
    try:
        if generate_table:
            gmaj = pd.to_numeric(dfi.get('galdim_majaxis'), errors='coerce')
            size_info_count = int((gmaj.fillna(-1) > 0).sum())
            if reapply and (visible_object_names is not None):
                visible_on_count = int(dfi['main_id'].isin(visible_object_names).sum())
            else:
                visible_on_count = int(dfi.shape[0])
            deduped_count = int(dfi.drop_duplicates(subset=['px','py','TYPE']).shape[0])
            print("=== Specimen diagnostics (pre-table) ===")
            print(f"dfi総数: {dfi.shape[0]}")
            print(f"サイズ情報あり数: {size_info_count}")
            print(f"可視ON数: {visible_on_count}")
            print(f"重複除去後数: {deduped_count}")
    except Exception as _diag_e:
        print(f"Diagnostics error: {_diag_e}")
# --- Step 11: パッチ画像をリサイズ（既定 512×512、必要時のみ自動縮小） ---
    # 環境変数で調整可：
    #   GA_PATCH_SIZE     ... 既定サイズ（既定=512）
    #   GA_PATCH_MEM_MB   ... パッチ群に許す概算上限メモリ[MB]（既定=512）
    DEFAULT_PATCH_SIZE  = int(os.environ.get("GA_PATCH_SIZE", "512"))
    PATCH_MEM_BUDGET_MB = int(os.environ.get("GA_PATCH_MEM_MB", "512"))

    # uint8 RGB 前提の概算（1pxあたり3バイト）
    bytes_per_px = 3
    n_patches = len(all_patches)
    max_pixels_total = (PATCH_MEM_BUDGET_MB * 1024 * 1024) // bytes_per_px

    # まずは通常サイズ（512）
    new_patch_size = DEFAULT_PATCH_SIZE

    # 総ピクセル数が予算を超えそうなときだけ、必要最小限に縮小
    if n_patches * (new_patch_size ** 2) > max_pixels_total:
        new_patch_size = int(math.floor(math.sqrt(max_pixels_total / max(1, n_patches))))
        # レイアウトしやすいよう 16 の倍数に丸め、下限は 128px
        new_patch_size = max(128, (new_patch_size // 16) * 16)

    print(f"Patch size: {new_patch_size}x{new_patch_size} (n={n_patches})")

    siril.update_progress("Resizing patch images...", 0.4)
    all_patches_resized = []
    for patch in all_patches:
        # Normalize to 0..1 float just-in-time for resizing (avoid global float32 to save memory)
        pf = patch
        if pf.dtype == np.uint8:
            pf = pf.astype(np.float32) / 255.0
        elif pf.dtype == np.uint16:
            pf = pf.astype(np.float32) / 65535.0
        elif not np.issubdtype(pf.dtype, np.floating):
            pf = pf.astype(np.float32)
            maxv = float(np.max(pf)) if np.size(pf) else 1.0
            if maxv > 0:
                pf = pf / maxv
        else:
            maxv = float(np.max(pf)) if np.size(pf) else 1.0
            if maxv > 1.0 and maxv > 0:
                pf = pf / maxv
        pf = np.clip(pf, 0, 1)

        # skimage.resize returns float; we'll convert back to uint8 afterward
        r = resize(pf, (new_patch_size, new_patch_size),
                   preserve_range=True, anti_aliasing=True)
        r = np.clip(r, 0, 1)
        r = (r * 255.0).astype(np.uint8)  # HxW or HxWxC, uint8
        all_patches_resized.append(r)
# ★ 巨大な連結配列を作らない：リストのまま保持
    all_patches = all_patches_resized
    siril.update_progress("Patch images resized.", 0.5)


    # --- Step 12: サムネイル表の作成（安全なdpiに自動調整 & ページ分割） ---
    scale = 3
    n = len(all_patches)

    # ページング設定
    # デフォルト（正方形レイアウト）時は、ページの行数も正方形に近づけるため
    # 全体件数 n から列数を決め、1ページの収容数を ncols*ncols に自動設定する
    if square_layout:
        try:
            ncols_global = max(1, int(math.ceil(math.sqrt(max(1, n)))))
        except Exception:
            ncols_global = 1
        nrows_global = ncols_global
        # ★ ここで max_per_page を上書きするため、一時的なフラグで後続を分岐
        _ga_square_override = ncols_global * nrows_global
    else:
        _ga_square_override = None

    max_per_page = (_ga_square_override if (_ga_square_override is not None) else max(1, int(table_max_per_page)))
    max_cols_cap = max(1, int(table_max_cols))
    total_pages = max(1, (n + max_per_page - 1) // max_per_page)
    table_files = []

    dft_all = dfi.iloc[filter_idxs].reset_index()

    for page_idx in range(1, total_pages + 1):
        start = (page_idx - 1) * max_per_page
        end   = min(start + max_per_page, n)
        if start >= end:
            break

        page_patches = all_patches[start:end]
        n_page = len(page_patches)

        # 横並び上限を尊重して列数を決める
        if square_layout:
            # 列数はページ内ではなく全体件数 n を基準に決定して、正方形に近い形に
            ncols = max(1, int(math.ceil(math.sqrt(max(1, n)))))
        else:
            ncols = max(1, int(max_cols_cap))
        nrows = int(np.ceil(n_page / float(ncols)))
        print(f"Grid size (p{page_idx}): nrows={nrows}, ncols={ncols}")

        # 総ピクセル数上限（既定1.6億px）に合わせてdpiをcap
        dpi_table = 200

        out_w = int(ncols * scale * dpi_table)
        out_h = int(nrows * scale * dpi_table)
        print(f"Table dpi (p{page_idx}) fixed to {dpi_table} → {out_w}×{out_h} px")
        try:
            siril.log(f"Table dpi fixed to {dpi_table}.", color=s.LogColor.CYAN)
        except Exception:
            pass
        fig, axarr = plt.subplots(nrows, ncols, figsize=(ncols * scale, nrows * scale))
        dft = dft_all.iloc[start:end].reset_index(drop=True)

        for i, row in dft.iterrows():
            ax = axarr if (nrows == 1 and ncols == 1) else (axarr[i] if (nrows == 1 or ncols == 1) else axarr[i // ncols, i % ncols])
            if row.main_id in custom_object_colors:
                color = custom_object_colors[row.main_id]
            elif row.TYPE in catalogs:
                color = catalogs[row.TYPE].color
            else:
                color = "#ff0000"
            ax.imshow(page_patches[i], origin="lower")
            display_name = row.display_name
            ax.set_title(display_name, fontsize=12, color=color)

            ax.set_xticks([]); ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_edgecolor(color)
            ax.text(0.02, 0.98, str(start + i + 1), transform=ax.transAxes,
                ha='left', va='top', color='white', fontsize=18)

        for i in range(n_page, nrows * ncols):
            ax = axarr if (nrows == 1 and ncols == 1) else (axarr[i] if (nrows == 1 or ncols == 1) else axarr[i // ncols, i % ncols])
            ax.axis('off')

        if (logo_path != "") and (nrows * ncols > n_page):
            try:
                logo_img = plt.imread(logo_path)
                ax_logo = (
    axarr if (nrows == 1 and ncols == 1)
    else (axarr[-1] if (nrows == 1 or ncols == 1)
          else axarr[nrows - 1, ncols - 1])
)
                ax_logo.imshow(logo_img)
            except Exception:
                pass

        siril.update_progress(f"Creating thumbnail table p{page_idx}/{total_pages}...", 0.6)
        plt.tight_layout()
        # 出力ファイル名（ページ数が1なら従来名、複数なら _table_p{idx}）
        if total_pages == 1:
            out_table = output_table_fname
        else:
            out_table = get_table_filename_page(output, page_idx)
        plt.savefig(out_table, bbox_inches='tight', pad_inches=.1, dpi=dpi_table)
        siril.update_progress(f"Saved thumbnail table image p{page_idx}.", 0.7)
        plt.close(fig)

        table_files.append(out_table)
    # If combined image is not requested, finalize after table generation
    if not generate_combined:
        siril.update_progress("Finalizing outputs...", 0.97)
        siril.update_progress("Completed combined image(s).", 1.0)
        page_info = {"table_pages": max(1, len(table_files) or 1), "combined_pages": 1}
        return dfi, dfi.shape[0], df, page_info

    # --- Step 13: 縦結合（NumPyではなくPILで省メモリ結合） ---
    siril.update_progress("Creating combined output image...", 0.8)

    overlay_img = Image.open(output_overlay_fname).convert("RGB")
    ow, oh = overlay_img.size

    combined_files = []

    for idx, tf in enumerate(table_files or [output_table_fname], start=1):

        total_pages_lp = len(table_files) if table_files else 1

        progress_start, progress_end = 0.80, 0.97

        frac = progress_start + (progress_end - progress_start) * (idx - 1) / max(1, total_pages_lp)

        siril.update_progress(f"Combining overlay and table ({idx}/{total_pages_lp})...", frac)
        total_pages = len(table_files) if table_files else 1
        table_img = Image.open(tf).convert("RGB")
        tw, th = table_img.size
        if tw != ow:
            new_h = max(1, int(round(th * (ow / float(tw)))))
            table_img = table_img.resize((ow, new_h), Image.LANCZOS)
            th = new_h

        combined = Image.new("RGB", (ow, oh + th))
        combined.paste(overlay_img, (0, 0))
        combined.paste(table_img, (0, oh))

        if len(table_files) <= 1:
            out_comb = output_fname
        else:
            out_comb = get_combined_filename_page(output, idx)

        siril.update_progress(f"Creating combined image p{idx}/{total_pages}...", 0.85 + 0.1 * (idx/total_pages))
        try:
            siril.log(f"結合画像作成中 p{idx}/{total_pages} ...", color=s.LogColor.CYAN)
        except Exception:
            pass
        siril.update_progress("Saving combined output image...", 0.9)
        combined.save(out_comb)
        frac2 = progress_start + (progress_end - progress_start) * (idx) / max(1, total_pages_lp)
        siril.update_progress(f"Saved combined image ({idx}/{total_pages_lp})", frac2)
        try:
            siril.log(f"結合画像 p{idx}/{total_pages} を保存: {out_comb}", color=s.LogColor.GREEN)
        except Exception:
            pass
        combined_files.append(out_comb)

    print("output image files:")
    print("  overlay:  ", output_overlay_fname)
    if len(table_files) <= 1:
        print("  table:    ", output_table_fname)
    else:
        for i, tf in enumerate(table_files, 1):
            print(f"  table[{i}]: {tf}")
    if len(combined_files) <= 1:
        print("  combined: ", output_fname)
    else:
        for i, cf in enumerate(combined_files, 1):
            print(f"  combined[{i}]: {cf}")

    siril.update_progress("Finalizing outputs...", 0.97)
    siril.update_progress("Completed combined image(s).", 1.0)

    # ページ情報を返却（UIのC/Tボタン用）
    page_info = {"table_pages": max(1, len(table_files) or 1),
                 "combined_pages": max(1, len(combined_files) or 1)}
    return dfi, dfi.shape[0], df, page_info


def get_output_filename(output_basename, suffix=''):
    filename, extension = os.path.splitext(output_basename)
    if extension == '':
        extension = '.png'
    else:
        if not extension.lower() in (".eps", ".jpeg", ".jpg", ".pdf", ".pgf",
                                     ".png", ".ps", ".raw", ".rgba", ".svg",
                                     ".svgz", ".tif", ".tiff", ".webp"):
            extension = '.png'
            filename = output_basename
    return f"{filename}{suffix}{extension}"


def get_overlay_filename(output_basename):
    return get_output_filename(output_basename, '_overlay')


def get_table_filename(output_basename):
    return get_output_filename(output_basename, '_table')


def get_combined_filename(output_basename):
    return get_output_filename(output_basename, '')

def get_table_filename_page(output_basename, page_index:int):
    """Return numbered table filename when multiple pages exist."""
    if page_index <= 1:
        return get_table_filename(output_basename)
    filename, extension = os.path.splitext(output_basename)
    if extension == '':
        extension = '.png'
    return f"{filename}_table_p{page_index}{extension}"


def get_combined_filename_page(output_basename, page_index:int):
    """Return numbered combined filename when multiple pages exist."""
    if page_index <= 1:
        return get_combined_filename(output_basename)
    filename, extension = os.path.splitext(output_basename)
    if extension == '':
        extension = '.png'
    return f"{filename}_p{page_index}{extension}"

class CatalogEntry:
    def __init__(self, description, color='#ffffff', selection_default=True):
        self._replaced_csv_path = None
        self._replaced_csv_name = None
        self.description = description
        self.color = color
        self.selection_default = selection_default
        self.checkbox_var = None
        self.color_var = None

    def get_selected(self):
        if self.checkbox_var is None:
            return self.selection_default
        else:
            return self.checkbox_var.get()


class AnnotationsScriptInterface:
    def __init__(self, root=None, cli_args=None):
        if cli_args is None:
            parser = argparse.ArgumentParser()
            parser.add_argument("-output", type=str, default=None)
            parser.add_argument("-title", type=str, default=None)
            parser.add_argument("-logo_path", type=str, default="")
            parser.add_argument("-overlay_alpha", type=float, default=0.6)
            parser.add_argument("-overlay_type", type=str, default="circles")
            cli_args = parser.parse_args([])

        self.cli_args = cli_args
        self.root = root

        self.custom_object_colors = {}
        self.visible_object_flags = {}
        self.anno_numbers = {}
        self.pending_object_renumber = False  # 次回Object再描画時にのみNoを振り直す
        self._object_defaults_snapshot = None  # Defaults用スナップショット
        self._label_defaults_snapshot = None  # Label Defaults用スナップショット
        self._view_mode = "normal"            # "normal" | "csv"

        
        # 並び替えはしない（Noに基づく再配置を無効化）
        self.no_reorder_for_object_table = True# 各天体の画像上の表示モード（"No" / "No+DN" / "DN"）
        self.object_label_mode_overrides = {}
        self.label_mode_vars = {}

        # 詳細設定のカスタムCSVパス
        self.custom_catalog_files = {'Stars': '', 'M': '', 'IC': '', 'NGC': ''}

        # サイズ未取得時のフォールバック設定
        self.size_fallback_mode = "default"  # "default" | "fixed" | "fourlines"
        self.size_fallback_radius_px = 15    # fixed半径（px）
        self.size_fallback_line_len_px = 10  # 4線の各線分長（px）
        self.size_fallback_center_gap_px = 20  # 中央の空き（px）

        # 通常の番号表示
        self.label_number_mode = "default"   # "default" | "custom" | "all" | "name_only"
        self.label_threshold_px = 200        # custom のときのしきい値(px)

        # 新規：サイズ未取得天体のラベル表示
        self.size_missing_label_mode = "num"  # "num" | "num_name" | "name_only"

        # --- 天体標本設定（テーブル出力のページング/横並び上限） ---
        self.specimen_use_defaults = True     # True: 25/5 を使用, False: 指定値を使用
        self.specimen_max_per_page = 25       # 1ページあたりの最大天体数
        self.specimen_max_per_row  = 5        # 横に並べる最大天体数

        # 出力ページ数と現在のページ（C/T のリサイクル表示用）
        self.combined_pages = 1
        self.table_pages = 1
        self.combined_page_idx = 1
        self.table_page_idx = 1

        self.label_threshold_arcmin_ui = None  # 直径[分]のUI入力値を保持
        self.saved_arcmin_per_px = None  # 最後にApplyしたときのスケール(arcmin/px)を保存

        from collections import OrderedDict
        self.catalogs = OrderedDict([
            ('Stars', CatalogEntry('Star Catalog', '#ffd700', False)),
            ('M', CatalogEntry('Messier Catalog', '#80ff80', True)),
            ('IC', CatalogEntry('Index Catalogue', '#80ffff', True)),
            ('NGC', CatalogEntry('New General Catalogue', '#ffffff', True)),
            ('MCG', CatalogEntry('Morphological Catalogue of Galaxies', '#955ec2', False)),
            ('UGC', CatalogEntry('Uppsala General Catalogue', '#3abed1', False)),
            ('MGC', CatalogEntry('Millennium Galaxy Catalogue', '#30a500', False)),
            ('Mrk', CatalogEntry('Markarian galaxies', '#fbbd70', False)),
            ('LEDA', CatalogEntry('Lyon-Meudon Extragalactic Database', '#c29d94', False)),
            ('Z', CatalogEntry('Zwicky Catalogue of galaxies and of clusters of galaxies', '#fb9795', False)),
            ('Gaia', CatalogEntry('Gaia catalogues', '#c6aed8', False)),
            ('2MASX', CatalogEntry('Two Micron All Sky Survey, Extended source catalogue', '#895447', False)),
            ('SDSS', CatalogEntry('Sloan Digital Sky Survey', '#b2c5eb', False)),
            ('SDSSCGB', CatalogEntry('SDSS DR6 Compact Group Catalogue B', '#b2c5eb', False)),
            ('UGCA', CatalogEntry('Uppsala Selected non-UGC Galaxies', '#f5b3d3', False)),
            ('MASS', CatalogEntry(None, '#c8c8c8', False)),
            ('MFGC', CatalogEntry(None, '#b9c200', False)),
            ('2MFGC', CatalogEntry('2MASS Flat Galaxy Catalog', '#d9df85', False)),
            ('FIRST', CatalogEntry('FIRST Survey Catalogs', '#a3dae7', False)),
            ('2MASS', CatalogEntry('Two Micron All Sky Survey', '#895447', False))
        ])

        if root:
            self.root.title(f"Galaxy Annotations Script - v{VERSION}")
            self.root.resizable(True, False)
            self.style = tksiril.standard_style()

        self.siril = s.SirilInterface()

        try:
            self.siril.connect()
        except s.SirilConnectionError:
            if globals().get("_SHUTTING_DOWN", False):
                return
            if root:
                self.siril.error_messagebox("Failed to connect to Siril")
            else:
                print("Failed to connect to Siril")
            return

        if not self.siril.is_image_loaded():
            if root:
                self.siril.error_messagebox("No image is loaded")
            else:
                print("No image is loaded")
            return

        try:
            self.siril.cmd("requires", "1.4.0-beta2")
        except s.CommandError:
            return

        if self.cli_args.output is None:
            basename = os.path.basename(self.siril.get_image_filename())
            filename, extension = os.path.splitext(basename)
            self.cli_args.output = "annotated_" + filename

        if not self.cli_args.title:
            basename = os.path.basename(self.siril.get_image_filename())
            filename, extension = os.path.splitext(basename)
            self.cli_args.title = filename

        if root:
            logo_path, overlay_alpha, overlay_type, selected_catalogs = self.load_config_file()
            self.cli_args.logo_path = logo_path if logo_path is not None else ""
            self.cli_args.overlay_alpha = overlay_alpha
            self.cli_args.overlay_type = overlay_type
            self.create_widgets()
            tksiril.match_theme_to_siril(self.root, self.siril)

            self._original_image = self.siril.get_image_filename()
            self.siril.log(f"Original image at GUI startup: {self._original_image}", color=s.LogColor.GREEN)

        # CLI から上書き（指定があれば）
        if self.cli_args:
            if getattr(self.cli_args, "fallback_mode", None):
                self.size_fallback_mode = self.cli_args.fallback_mode
            if getattr(self.cli_args, "fallback_radius_px", None) is not None:
                self.size_fallback_radius_px = int(self.cli_args.fallback_radius_px)
            if getattr(self.cli_args, "fallback_line_len_px", None) is not None:
                self.size_fallback_line_len_px = int(self.cli_args.fallback_line_len_px)
            if getattr(self.cli_args, "fallback_center_gap_px", None) is not None:
                self.size_fallback_center_gap_px = int(self.cli_args.fallback_center_gap_px)

        if self.siril.is_cli():
            print("Apply changes from CLI")
            self.apply_changes(from_cli=True)

    # 画像中心のピクセルスケール（分/px）
    def _arcmin_per_pixel(self):
        fit = self.siril.get_image()
        if fit.data.ndim == 2:
            H, W = fit.data.shape
        else:
            H, W = fit.data.shape[1], fit.data.shape[2]
        ra0, dec0 = self.siril.pix2radec(W / 2,     H / 2)
        ra1, dec1 = self.siril.pix2radec(W / 2 + 1, H / 2)
        c0 = SkyCoord(ra0 * u.deg, dec0 * u.deg, frame='icrs')
        c1 = SkyCoord(ra1 * u.deg, dec1 * u.deg, frame='icrs')
        return c0.separation(c1).arcmin  # 分/px

    # ★ 追加：詳細設定から Object ウィンドウの初期 Label を計算
    def _compute_default_label_mode_for_row(self, row):
        """詳細設定を用いて、行ごとのデフォルトLabel（No / No+DN / DN）を決める"""
        import numpy as np
        try:
            maj = float(getattr(row, 'galdim_majaxis', np.nan))
            has_arcmin = np.isfinite(maj) and maj > 0
        except Exception:
            has_arcmin = False

        # 直径情報が無い天体は「サイズ情報無し」の設定に従う
        if not has_arcmin:
            m = getattr(self, 'size_missing_label_mode', 'num')
            if m == 'num':
                return 'No'           # 番号のみ
            elif m in ('num_name', 'num+name', 'num+dn'):
                return 'No+DN'        # 番号＋表示名
            elif m == 'name_only':
                return 'DN'           # 表示名のみ
            return 'No'

        # 直径情報がある天体は「サイズ情報有り」の設定に従う
        mode = getattr(self, 'label_number_mode', 'default')
        if mode == 'name_only':
            return 'DN'
        if mode == 'all':
            return 'No+DN'

                # default/custom は「基準値側（px）→角分」に一度だけ変換し、天体側は長径[分]のみと比較
        try:
            arcmin_per_px = getattr(self, 'saved_arcmin_per_px', None)
            if not (arcmin_per_px and arcmin_per_px > 0 and math.isfinite(arcmin_per_px)):
                # フォールバック：一度だけ測定して保存
                arcmin_per_px = float(self._arcmin_per_pixel())
                if arcmin_per_px > 0 and math.isfinite(arcmin_per_px):
                    self.saved_arcmin_per_px = arcmin_per_px
                else:
                    raise ValueError
            th_px = int(self.label_threshold_px) if mode == 'custom' else 200  # 既定は patch_size≦200px
            # patch_size(px) = 直径px × 2 → 直径しきい[分] = (th_px/2) × (分/px)
            threshold_arcmin = (float(th_px) / 2.0) * float(arcmin_per_px)
        except Exception:
            # スケールが取得できない場合は安全側（No+DN）へ
            return 'No+DN'
        # 長径[分]としきい[分]の比較（4点座標変換は行わない）
        return 'No' if float(maj) <= float(threshold_arcmin) else 'No+DN'

    def _browse_logo_file(self):
        filename = filedialog.askopenfilename(
            title="Select a Logo Image File",
            initialdir=os.path.expanduser("~"),
            filetypes=[("Image file", ".png .jpg .jpeg .ico .bmp .gif")]
        )
        if filename:
            self.logo_path.set(filename)
            self.save_config_file(filename, self.overlay_alpha_var.get(), self.overlay_type_var.get(), None)

    def create_widgets(self):
        """メインウィンドウ（GUI）レイアウト"""
        PADX, PADY = 8, 6

        # --- ルート土台 ---
        main = ttk.Frame(self.root, padding=(10, 8))
        main.grid(row=0, column=0, sticky="nsew")
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=0)
        main.grid_rowconfigure(2, weight=0)

        # === 上段：出力設定 ===
        top = ttk.Frame(main)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top.grid_columnconfigure(0, weight=1)

        left = ttk.Frame(top)
        left.grid(row=0, column=0, sticky="ew")
        left.grid_columnconfigure(1, weight=1)

        out_grp = ttk.LabelFrame(left, text="Output", padding=(10, 8))
        out_grp.grid(row=0, column=0, columnspan=2, sticky="ew")
        out_grp.grid_columnconfigure(1, weight=1)

        r = 0
        ttk.Label(out_grp, text="Title:").grid(row=r, column=0, sticky="e", padx=(0, PADX), pady=(0, PADY))
        self.title = tk.StringVar(self.root, value=self.cli_args.title)
        ttk.Entry(out_grp, textvariable=self.title).grid(row=r, column=1, sticky="ew", pady=(0, PADY))

        r += 1
        ttk.Label(out_grp, text="Logo:").grid(row=r, column=0, sticky="e", padx=(0, PADX), pady=(0, PADY))
        self.logo_path = tk.StringVar(self.root, value=self.cli_args.logo_path)
        ttk.Entry(out_grp, textvariable=self.logo_path).grid(row=r, column=1, sticky="ew", pady=(0, PADY))
        btn_browse = ttk.Button(out_grp, text="Browse", command=self._browse_logo_file)
        btn_browse.grid(row=r, column=2, sticky="w", padx=(PADX // 2, 0))
        tksiril.create_tooltip(btn_browse, "Select a logo image file")

        r += 1
        ttk.Label(out_grp, text="Output file:").grid(row=r, column=0, sticky="e", padx=(0, PADX), pady=(0, PADY))
        self.output = tk.StringVar(self.root, value=self.cli_args.output)
        e_out = ttk.Entry(out_grp, textvariable=self.output)
        e_out.grid(row=r, column=1, sticky="ew", pady=(0, PADY))
        tksiril.create_tooltip(e_out, "Base filename (extension decided automatically)")

        r += 1
        ttk.Label(out_grp, text="Overlay:").grid(row=r, column=0, sticky="ne", padx=(0, PADX))
        overlay_row = ttk.Frame(out_grp)
        overlay_row.grid(row=r, column=1, columnspan=2, sticky="ew")
        overlay_row.grid_columnconfigure(6, weight=1)

        ttk.Label(overlay_row, text="Alpha:").grid(row=0, column=0, sticky="w")
        self.overlay_alpha_var = tk.DoubleVar(value=self.cli_args.overlay_alpha)
        sld = ttk.Scale(overlay_row, from_=0.0, to=1.0, orient=tk.HORIZONTAL,
                        variable=self.overlay_alpha_var, length=140)
        sld.grid(row=0, column=1, sticky="w", padx=(PADX // 2, PADX))
        self.overlay_alpha_label = ttk.Label(overlay_row, text=f"{self.cli_args.overlay_alpha:.2f}")
        self.overlay_alpha_label.grid(row=0, column=2, sticky="w")
        self.overlay_alpha_var.trace_add("write", self._update_alpha_label)
        tksiril.create_tooltip(sld, "Adjust the visibility of the annotation overlays")

        ttk.Label(overlay_row, text="Type:").grid(row=0, column=3, sticky="w", padx=(PADX, 0))
        self.overlay_type_var = tk.StringVar(self.root, value=self.cli_args.overlay_type)
        cb = ttk.Combobox(overlay_row, textvariable=self.overlay_type_var,
                          values=('circles', 'boxes', 'ellipses'),
                          state="readonly", justify='center', width=10)
        cb.grid(row=0, column=4, sticky="w")
        tksiril.create_tooltip(cb, "The type of annotations to draw around galaxies")

        ttk.Button(overlay_row, text='詳細設定...', command=self.open_advanced_settings).grid(row=0, column=6, sticky='e', padx=(PADX, 0))
        # === Catalogs ===
        right = ttk.LabelFrame(main, text="Catalogs", padding=(10, 8))
        right.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        sel_row = ttk.Frame(right)
        sel_row.grid(row=0, column=0, sticky="ew", pady=(0, PADY))
        ttk.Label(sel_row, text="Select:").pack(side="left")
        ttk.Button(sel_row, text="All", command=self.select_all).pack(side="left", padx=(6, 2))
        ttk.Button(sel_row, text="None", command=self.select_none).pack(side="left", padx=(2, 2))
        ttk.Button(sel_row, text="Defaults", command=self.select_defaults).pack(side="left", padx=(2, 2))
        style = ttk.Style()
        bg = (style.lookup("TFrame", "background") or self.root.cget("background") or "#2e2e2e")
        canvas = tk.Canvas(right, highlightthickness=0, bg=bg)
        canvas.grid(row=1, column=0, sticky="nsew")
        vscroll = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
        vscroll.grid(row=1, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vscroll.set)

        catalogs_inner = ttk.Frame(canvas)
        inner_window = canvas.create_window((0, 0), window=catalogs_inner, anchor="nw")

        def _on_canvas_resize(e):
            canvas.itemconfigure(inner_window, width=e.width)
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", _on_canvas_resize)
        catalogs_inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        catalogs_inner.grid_columnconfigure(0, minsize=80)
        catalogs_inner.grid_columnconfigure(1, minsize=72)
        catalogs_inner.grid_columnconfigure(2, minsize=100)
        catalogs_inner.grid_columnconfigure(3, weight=1, minsize=180)

        for i, (key, value) in enumerate(self.catalogs.items()):
            value.checkbox_var = tk.BooleanVar(self.root, value=value.selection_default)
            value.color_var = tk.StringVar(value=self.catalogs[key].color)

            width_chars = max(6, min(10, len(str(key)) + 1))
            chk = ttk.Checkbutton(catalogs_inner, text=key, variable=value.checkbox_var, width=width_chars)
            chk.grid(row=i, column=0, sticky="w", padx=(0, PADX // 3), pady=(0, 2))

            # Hex と Color の列を入れ替え：先に Hex（chip）、次に Color ボタン
            chip = tk.Label(catalogs_inner, textvariable=value.color_var,
                            bg=value.color, width=10, relief="groove")
            chip.grid(row=i, column=1, sticky="w", pady=(0, 2))
            value.color_label = chip

            btn = ttk.Button(catalogs_inner, text="Color", command=lambda k=key: self.choose_color(k))
            btn.grid(row=i, column=2, sticky="w", padx=(PADX, 4), pady=(0, 2))

            desc = value.description or key
            desc_lbl = ttk.Label(catalogs_inner, text=desc, anchor="w", justify="left")
            desc_lbl.grid(row=i, column=3, sticky="we", padx=(PADX, 0), pady=(0, 2))
            desc_lbl.bind("<Configure>", lambda e, lbl=desc_lbl: lbl.config(
                wraplength=max(10, e.width - 6)
            ))

        # === アクションバー ===
        action = ttk.Frame(main)
        action.grid(row=2, column=0, sticky="ew")
        action.grid_columnconfigure(0, weight=1)
        action.grid_columnconfigure(1, weight=0)

        leftbar  = ttk.Frame(action); leftbar.grid(row=0, column=0, sticky="w")
        rightbar = ttk.Frame(action); rightbar.grid(row=0, column=1, sticky="e")

        btn_close = ttk.Button(leftbar, text="Close", style="Obj.TButton", command=self.close_dialog)
        btn_apply = ttk.Button(leftbar, text="Apply", command=self.apply_changes)
        btn_close.pack(side="left", padx=(0, PADX))
        btn_apply.pack(side="left", padx=(0, PADX))
        tksiril.create_tooltip(btn_apply, "Create the annotated output image")

        ttk.Label(rightbar, text="after :", style="Obj.TLabel").pack(side="left", padx=(0, 3))
        # O/T はページ数に応じて（T1/T2...）。Cは同様に（C1/C2...）。
        ttk.Button(rightbar, text="O", width=2, style="Obj.TButton", command=lambda: self.switch_image("overlay")).pack(side="left", padx=2)
        self.main_btn_t = ttk.Button(rightbar, text="T", width=3, style="Obj.TButton", command=self._on_click_cycled_table)
        self.main_btn_t.pack(side="left", padx=2)
        self.main_btn_c = ttk.Button(rightbar, text="C", width=3, style="Obj.TButton", command=self._on_click_cycled_combined)
        self.main_btn_c.pack(side="left", padx=2)
        ttk.Button(rightbar, text="N", width=2, style="Obj.TButton", command=lambda: self.switch_image("original")).pack(side="left", padx=2)
        btn_obj = ttk.Button(rightbar, text="Object", command=self.show_or_focus_object_window)
        btn_obj.pack(side="left", padx=(PADX, 0))
        try:
            self._update_ct_labels()
        except Exception:
            pass
        
        tksiril.create_tooltip(btn_obj, "Open or focus the Object Control window")
    def open_advanced_settings(self):
        # 既に開いていれば前面へ
        if hasattr(self, 'advanced_window') and self.advanced_window.winfo_exists():
            self.advanced_window.lift()
            self.advanced_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self.advanced_window = win
        win.title("詳細設定")
        win.resizable(True, False)    # 縦は固定、横のみリサイズ可
        win.geometry("640x460")
        PADX, PADY = 12, 10


        # ===== タブ =====
        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=PADX, pady=(PADY, 0))

        # ---------- Tab 0: 天体標本設定（カタログ/CSV の左） ----------
        tab_spec = ttk.Frame(nb)
        nb.add(tab_spec, text="天体標本設定")

        # ラジオボタン：デフォルト or 指定する
        specimen_mode_var = tk.StringVar(value=("default" if self.specimen_use_defaults else "custom"))

        rb_def = ttk.Radiobutton(tab_spec, text="デフォルト（正方形に近い形に並べる）",
                                 variable=specimen_mode_var, value="default")
        rb_def.grid(row=0, column=0, sticky="w", padx=PADX, pady=(PADY, 4))

        rb_custom = ttk.Radiobutton(tab_spec, text="それぞれ指定する",
                                    variable=specimen_mode_var, value="custom")
        rb_custom.grid(row=1, column=0, sticky="w", padx=PADX, pady=(0, 8))

        lbl_pp = ttk.Label(tab_spec, text="テーブル1ページあたりの最大天体数：")
        lbl_pp.grid(row=2, column=0, sticky="w", padx=(PADX+20, 4))
        sp_pp  = ttk.Spinbox(tab_spec, from_=5, to=500, increment=1, width=6)
        sp_pp.grid(row=2, column=1, sticky="w", padx=(0, PADX))
        sp_pp.delete(0, "end"); sp_pp.insert(0, str(self.specimen_max_per_page))

        lbl_pr = ttk.Label(tab_spec, text="横に並べる最大天体数（1行の上限）：")
        lbl_pr.grid(row=3, column=0, sticky="w", padx=(PADX+20, 4), pady=(4, 0))
        sp_pr  = ttk.Spinbox(tab_spec, from_=2, to=20, increment=1, width=6)
        sp_pr.grid(row=3, column=1, sticky="w", padx=(0, PADX), pady=(4, 0))
        sp_pr.delete(0, "end"); sp_pr.insert(0, str(self.specimen_max_per_row))

        def _apply_specimen_state(*_):
            use_def = (specimen_mode_var.get() == "default")
            self.specimen_use_defaults = use_def
            # 有効無効切替
            state = ("disabled" if use_def else "normal")
            for w in (lbl_pp, sp_pp, lbl_pr, sp_pr):
                try:
                    w.configure(state=state)
                except Exception:
                    pass

            # 値の同期
            try:
                v1 = int(sp_pp.get())
                v2 = int(sp_pr.get())
            except Exception:
                v1, v2 = 25, 5
            self.specimen_max_per_page = max(1, int(v1))
            self.specimen_max_per_row  = max(1, int(v2))

        def _on_spin_change(*_):
            specimen_mode_var.set("custom")
            _apply_specimen_state()

        specimen_mode_var.trace_add("write", _apply_specimen_state)
        for w in (sp_pp, sp_pr):
            w.configure(command=_on_spin_change)
            try:
                w.bind("<Return>", _on_spin_change)
                w.bind("<FocusOut>", _on_spin_change)
            except Exception:
                pass

        # 初期適用
        _apply_specimen_state()

        # ---------- Tab 1: カタログ / CSV ----------
        tab_csv = ttk.Frame(nb)
        nb.add(tab_csv, text="カタログ / CSV")

        ttk.Label(tab_csv, text="Stars / Messier / IC / NGC のCSVを指定できます（空欄なら組み込みを使用）")\
            .grid(row=0, column=0, columnspan=3, sticky="w", padx=PADX, pady=(PADY, 6))

        vars_map = {
    'Stars': tk.StringVar(value=self.custom_catalog_files.get('Stars', '')),
    'M':     tk.StringVar(value=self.custom_catalog_files.get('M', '')),
    'IC':    tk.StringVar(value=self.custom_catalog_files.get('IC', '')),
    'NGC':   tk.StringVar(value=self.custom_catalog_files.get('NGC', '')),
}

        def row_ui(r, key, label):
            ttk.Label(tab_csv, text=label, width=10).grid(row=r, column=0, sticky="e", padx=(PADX, 6), pady=(0, 6))
            ent = ttk.Entry(tab_csv, textvariable=vars_map[key])
            ent.grid(row=r, column=1, sticky="ew", pady=(0, 6))
            def browse():
                path = filedialog.askopenfilename(
                    title=f"{label} のCSVを選択",
                    filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
                )
                if path:
                    vars_map[key].set(path)
            ttk.Button(tab_csv, text="参照", command=browse)\
                .grid(row=r, column=2, sticky="w", padx=(6, PADX), pady=(0, 6))
        row_ui(1, 'Stars', "Stars")
        row_ui(2, 'M',     "Messier")
        row_ui(3, 'IC',    "IC")
        row_ui(4, 'NGC',   "NGC")
        tab_csv.grid_columnconfigure(1, weight=1)

        def _safe_float_var(var):
            try:
                return float(var.get())
            except Exception:
                return None

        # ---------- Tab 2: サイズ情報無し天体 ----------
        tab_fb = ttk.Frame(nb)
        nb.add(tab_fb, text="サイズ情報無し天体")

        # 各天体の示し方（3カードをまとめる外枠）
        grp_methods = ttk.LabelFrame(tab_fb, text="各天体の示し方")
        grp_methods.grid(row=0, column=0, columnspan=3, sticky="ew", padx=PADX, pady=(PADY, 8))

        cards = ttk.Frame(grp_methods)
        cards.pack(fill="x", expand=True, padx=10, pady=8)
        for c in range(3):
            cards.grid_columnconfigure(c, weight=1)

        # 既存内部状態をUIにバインド
        fb_mode_var       = tk.StringVar(value=self.size_fallback_mode)
        fb_radius_var     = tk.IntVar(value=int(self.size_fallback_radius_px))
        fb_line_len_var   = tk.IntVar(value=int(self.size_fallback_line_len_px))
        fb_gap_var        = tk.IntVar(value=int(self.size_fallback_center_gap_px))

        # A) デフォルト
        card_default = ttk.LabelFrame(cards, text="デフォルト")
        card_default.grid(row=0, column=0, sticky="nsew", padx=(0,6), pady=0)
        ttk.Radiobutton(card_default, value="default", variable=fb_mode_var,
                        text="画像の長辺の約1%で円表示")\
            .pack(anchor="w", padx=10, pady=10)

        # B) 半径指定（px）
        card_fixed = ttk.LabelFrame(cards, text="半径指定（px）")
        card_fixed.grid(row=0, column=1, sticky="nsew", padx=6, pady=0)
        frm_fix = ttk.Frame(card_fixed)
        frm_fix.pack(fill="x", padx=10, pady=10)
        ttk.Radiobutton(frm_fix, value="fixed", variable=fb_mode_var,
                        text="固定半径を使う").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,6))
        ttk.Label(frm_fix, text="半径(px)").grid(row=1, column=0, sticky="e", padx=(0,6))
        ent_radius = ttk.Entry(frm_fix, textvariable=fb_radius_var, width=8)
        ent_radius.grid(row=1, column=1, sticky="w")

        # C) 4本のガイドライン
        card_four = ttk.LabelFrame(cards, text="4本のガイドライン")
        card_four.grid(row=0, column=2, sticky="nsew", padx=(6,0), pady=0)
        frm_four = ttk.Frame(card_four)
        frm_four.pack(fill="x", padx=10, pady=10)
        ttk.Radiobutton(frm_four, value="fourlines", variable=fb_mode_var,
                        text="上下左右の4線で示す").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,6))
        ttk.Label(frm_four, text="線分長(px)").grid(row=1, column=0, sticky="e", padx=(0,6))
        ent_len = ttk.Entry(frm_four, textvariable=fb_line_len_var, width=8)
        ent_len.grid(row=1, column=1, sticky="w", pady=(0,6))
        ttk.Label(frm_four, text="中央の空き(px)").grid(row=2, column=0, sticky="e", padx=(0,6))
        ent_gap = ttk.Entry(frm_four, textvariable=fb_gap_var, width=8)
        ent_gap.grid(row=2, column=1, sticky="w")

        # 入力有効/無効の切替
        def _toggle_state(*_):
            m = fb_mode_var.get()
            ent_radius.configure(state=("normal" if m == "fixed" else "disabled"))
            ent_len.configure(state=("normal" if m == "fourlines" else "disabled"))
            ent_gap.configure(state=("normal" if m == "fourlines" else "disabled"))
        fb_mode_var.trace_add("write", lambda *_: _toggle_state())
        _toggle_state()

        # サイズ情報無し天体の画像上の表示名（番号のみ / 番号＋表示名 / 表示名のみ）
        if not hasattr(self, "size_missing_label_mode"):
            self.size_missing_label_mode = "num"  # 既定値

        lbl_grp = ttk.LabelFrame(tab_fb, text="各天体の画像上の表示名")
        lbl_grp.grid(row=1, column=0, columnspan=3, sticky="ew", padx=PADX, pady=(0, PADY))
        m = getattr(self, "size_missing_label_mode", "num")
        m = m if m in ("num","num_name","name_only") else "num"
        self.fb_label_var = tk.StringVar(value=m)
        ttk.Radiobutton(lbl_grp, text="番号のみ", value="num", variable=self.fb_label_var)\
            .grid(row=0, column=0, sticky="w", padx=10, pady=6)
        ttk.Radiobutton(lbl_grp, text="番号＋表示名", value="num_name", variable=self.fb_label_var)\
            .grid(row=1, column=0, sticky="w", padx=10, pady=6)
        ttk.Radiobutton(lbl_grp, text="表示名のみ", value="name_only", variable=self.fb_label_var)\
            .grid(row=2, column=0, sticky="w", padx=10, pady=6)
        # 初期表示で押下状態が見えない場合があるため、現在値を再適用して視覚状態を安定化
        try:
            _val = self.fb_label_var.get()
            self.fb_label_var.set("")  # 一旦クリア
            self.fb_label_var.set(_val)
            try:
                lbl_grp.update_idletasks()
            except Exception:
                pass
        except Exception:
            pass


        
# ---------- Tab 3: サイズ情報有り天体 ----------
        tab_norm = ttk.Frame(nb)
        nb.add(tab_norm, text="サイズ情報有り天体")

        # 既存の内部状態をUIにバインド（※しきい値は“直径[分]”で表示）
        num_mode_var = tk.StringVar(value=self.label_number_mode)  # "default" | "custom" | "all" | "name_only"

        # 1) ピクセルスケールを決定：現在→保存値→フォールバック  # ★ 変更点
        pixscale_arcmin = None
        used_saved = False
        try:
            pixscale_arcmin = float(self._arcmin_per_pixel())  # 分/px（中心）
        except Exception:
            pixscale_arcmin = None

        if not pixscale_arcmin or not math.isfinite(pixscale_arcmin) or pixscale_arcmin <= 0:
            if getattr(self, "saved_arcmin_per_px", None):
                pixscale_arcmin = float(self.saved_arcmin_per_px)
                used_saved = True
            else:
                pixscale_arcmin = 1.0  # 最後の手段
                used_saved = False

        # 2) init_arcmin を必ず決める（custom保存値があれば優先）
        saved_arcmin = getattr(self, "label_threshold_arcmin_ui", None)
        if self.label_number_mode == "custom" and saved_arcmin is not None:
            init_arcmin = float(saved_arcmin)
        else:
            # ★ 内部px(=patch_size)→直径[分]に戻すときは /2 を挟む
            init_arcmin = round((float(self.label_threshold_px) / 2.0) * float(pixscale_arcmin), 2)

        # デフォルト相当の直径[分]（内部は patch_size<=200px ⇒ 直径100px 相当）
        default_cut_arcmin = round(100.0 * float(pixscale_arcmin), 2)

        # 入力バインド
        num_th_arcmin_var = tk.DoubleVar(value=init_arcmin)

        # グループ（縦並び）
        grp_norm = ttk.LabelFrame(tab_norm, text="各天体の画像上の表示名", padding=(10, 8))
        grp_norm.grid(row=0, column=0, columnspan=3, sticky="ew", padx=PADX, pady=(PADY, 8))
        grp_norm.grid_columnconfigure(0, weight=1)

        # A) デフォルト（直径100px 基準を明記）
        rb_def = ttk.Radiobutton(
            grp_norm, value="default", variable=num_mode_var,
            text=f"直径100px（≒ {default_cut_arcmin}分）以下の天体は番号のみ / それ以外は「番号＋表示名」"
        )
        rb_def.grid(row=0, column=0, sticky="w", padx=10, pady=6)

        # B) しきい値を指定（直径[分]）
        frm_n_custom = ttk.Frame(grp_norm)
        frm_n_custom.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))
        ttk.Radiobutton(frm_n_custom, value="custom", variable=num_mode_var,
                        text="直径[分]の指定値以下を番号のみ").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(frm_n_custom, text="指定値（直径[分]）").grid(row=1, column=0, sticky="e", padx=(0, 6))
        ent_n_th = ttk.Entry(frm_n_custom, textvariable=num_th_arcmin_var, width=8)
        ent_n_th.grid(row=1, column=1, sticky="w")

        # C) すべて番号＋表示名
        rb_all = ttk.Radiobutton(grp_norm, value="all", variable=num_mode_var,
                                 text="すべて「番号＋表示名」")
        rb_all.grid(row=2, column=0, sticky="w", padx=10, pady=6)

        # D) 表示名のみ
        rb_nameonly = ttk.Radiobutton(grp_norm, value="name_only", variable=num_mode_var,
                                      text="すべて「表示名のみ」")
        rb_nameonly.grid(row=3, column=0, sticky="w", padx=10, pady=6)

        # 下部補足：スケールと px換算のプレビュー（保存スケール使用時は注記）  # ★ 変更点
        scale_txt = (f"現在のピクセルスケール：約 {pixscale_arcmin:.3f} 分/px"
                     + ("（前回Apply時の値）" if used_saved else ""))
        ttk.Label(tab_norm, text=scale_txt)\
            .grid(row=1, column=0, sticky="w", padx=PADX, pady=(0, 4))

        lbl_px = ttk.Label(tab_norm, text="現在のpx換算値（= ― px）")
        lbl_px.grid(row=2, column=0, sticky="w", padx=PADX, pady=(0, 4))

        # 説明行
        lbl_rule = ttk.Label(tab_norm, foreground="#9cdcfe")
        lbl_rule.grid(row=3, column=0, sticky="w", padx=PADX, pady=(0, PADY))

        def _to_float(s):
            try:
                return float(str(s).strip())
            except Exception:
                return None

        def _refresh_px_preview(*_):
            mode = num_mode_var.get()
            arcmin_per_px = float(pixscale_arcmin) if pixscale_arcmin and pixscale_arcmin > 0 else 0.0  # 分/px  # ★ 変更点
            px_per_arcmin = (1.0 / arcmin_per_px) if arcmin_per_px > 0 else 0.0                           # px/分

            if mode == "custom":
                ent_n_th.configure(state="normal")
                th_arcmin = _safe_float_var(num_th_arcmin_var)   # 入力の安全取得
                if th_arcmin is not None and px_per_arcmin > 0:
                    px = max(1, int(round(th_arcmin * px_per_arcmin * 2.0)))  # patch_size(px)
                    lbl_px.configure(text=f"現在のpx換算値（patch_size ≒ {px} px）")
                    lbl_rule.configure(
                        text=(f"この画像のスケール: {arcmin_per_px:.4f}分/px  →  "
                              f"{th_arcmin:.2f}分 × (px/分) × 2 ≒ {px} px（内部判定のpatch_size）\n"
                              f"よって、天体データ（CSV）の直径[分]が {th_arcmin:.2f}分（≒直径px={int(round(th_arcmin*px_per_arcmin))}px）"
                              f"に対応し、patch_size≦{px}px の天体は「番号のみ」です。")
                    )
                else:
                    lbl_px.configure(text="現在のpx換算値（= ― px）")
                    lbl_rule.configure(text="")

            elif mode == "default":
                ent_n_th.configure(state="disabled")
                # デフォルトは patch_size≦200px ⇒ 直径100px ⇒ 100×分/px
                minutes_threshold = 100.0 * arcmin_per_px
                lbl_px.configure(text="デフォルト基準（内部判定=patch_size≦200px）")
                lbl_rule.configure(
                    text=(
                        f"内部は patch_size≦200px 判定（= 直径100px 相当）\n"
                        f"直径100px × {arcmin_per_px:.4f}分/px ＝ {minutes_threshold:.2f}分"
                    )
                )
            else:
                ent_n_th.configure(state="disabled")
                lbl_px.configure(text="現在のpx換算値（= ― px）")
                lbl_rule.configure(text="")

        num_mode_var.trace_add("write", _refresh_px_preview)
        num_th_arcmin_var.trace_add("write", _refresh_px_preview)
        _refresh_px_preview()


        # ===== ボタン行 =====
        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=PADX, pady=(8, PADY))

        def _validate_csv(path):
            if not path:
                return True
            if not os.path.isfile(path):
                return False
            try:
                df = pd.read_csv(path, nrows=1)
                return {'name', 'ra', 'dec'}.issubset(df.columns)
            except Exception:
                return False

        def save_and_close():
            # CSV 検証
            for k in ('Stars', 'M', 'IC', 'NGC'):
                p = vars_map[k].get().strip()
                if p and not _validate_csv(p):
                    messagebox.showerror("エラー", f"{k} のCSVが不正です。\n'name','ra','dec' 列を含むCSVを指定してください。")
                    return

            # 反映
            self.custom_catalog_files = {k: vars_map[k].get().strip() for k in vars_map}
            self.size_fallback_mode = fb_mode_var.get()
            self.size_fallback_radius_px = max(1, int(fb_radius_var.get()))
            self.size_fallback_line_len_px = max(1, int(fb_line_len_var.get()))
            self.size_fallback_center_gap_px = max(1, int(fb_gap_var.get()))
            self.size_missing_label_mode = self.fb_label_var.get()  # "num" | "num_name" | "name_only"

            # 通常天体の番号表示（モードはそのまま）
            self.label_number_mode = num_mode_var.get()  # "default" | "custom" | "all" | "name_only"

            # 直径[分] → 内部px(patch_size)へ換算し、UIの生値も保存
            if self.label_number_mode == "custom":
                th_arcmin = _safe_float_var(num_th_arcmin_var)   # ← 安全取得
                if th_arcmin is None:
                    messagebox.showerror("エラー", "直径[分]の指定値が空、または不正です。")
                    return
                th_arcmin = max(0.001, th_arcmin)  # 最小値ガード
                self.label_threshold_arcmin_ui = th_arcmin
                pix = float(pixscale_arcmin) if pixscale_arcmin > 0 else 0.0
                px_per_arcmin = (1.0 / pix) if pix > 0 else 0.0
                if px_per_arcmin > 0:
                    # 直径[分] → 直径px → patch_size(px)（×2）
                    self.label_threshold_px = max(1, int(round(th_arcmin * px_per_arcmin * 2.0)))
            else:
                self.label_threshold_arcmin_ui = None

            # ファイル保存
            self.save_config_file(self.cli_args.logo_path,
                                  float(self.cli_args.overlay_alpha),
                                  self.cli_args.overlay_type)

            win.destroy()

        ttk.Button(btns, text="保存", command=save_and_close).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="閉じる", command=win.destroy).pack(side=tk.RIGHT)

    def show_or_focus_object_window(self):
        if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
            self.object_control_window.lift()
            self.object_control_window.focus_force()
        elif hasattr(self, 'df_all') and self.df_all is not None:
            if self._view_mode == "csv":
                df_for_object = self.df_all.copy()
            else:
                types_selected = [k for k, v in self.catalogs.items() if v.get_selected()]
                df_for_object = self.df_all[self.df_all['TYPE'].isin(types_selected)].copy()
            self.show_object_selection_dialog(df_for_object)
        else:
            messagebox.showinfo("注意", "先に「Apply」ボタンを押してください。")

    def choose_color(self, catalog_key):
        current_color = self.catalogs[catalog_key].color_var.get()
        color_code = colorchooser.askcolor(title=f"Choose color for {catalog_key}", color=current_color)
        if color_code[1] is not None:
            self.catalogs[catalog_key].color_var.set(color_code[1])
            self.catalogs[catalog_key].color = color_code[1]
            if hasattr(self.catalogs[catalog_key], "color_label"):
                self.catalogs[catalog_key].color_label.config(bg=color_code[1])

    def apply_changes(self, from_cli=False, is_reapply=False):
        if is_reapply:
            self.pending_object_renumber = True  # Reapply時はNo振り直し
        _t0 = time.perf_counter()  # Start timing

        try:
            if not from_cli and not is_reapply and hasattr(self, 'df_all') and self.df_all is not None:
                result = messagebox.askokcancel(
                    "注意",
                    "新たに実行すると個別の天体設定は初期化されます。\n続行してよろしいですか？"
                )
                if not result:
                    return
                if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
                    self.object_control_window.destroy()

            if hasattr(self, "_original_image") and self._original_image:
                try:
                    self.siril.cmd("load", f"\"{self._original_image}\"")
                    self.siril.log(f"Reloaded original image: {self._original_image}", color=s.LogColor.GREEN)
                except Exception as e:
                    if not from_cli:
                        messagebox.showerror("Error", f"Failed to load original image:\n{str(e)}")
                    else:
                        print(f"Failed to load original image: {str(e)}")
                    return

            with self.siril.image_lock():
                if from_cli and self.cli_args:
                    output = self.cli_args.output
                    title = self.cli_args.title
                    logo_path = self.cli_args.logo_path
                    overlay_alpha = self.cli_args.overlay_alpha
                    overlay_type = self.cli_args.overlay_type
                else:
                    output = self.output.get()
                    title = self.title.get()
                    logo_path = self.logo_path.get()
                    overlay_alpha = float(self.overlay_alpha_var.get())
                    overlay_type = self.overlay_type_var.get()
                    self.save_config_file(logo_path, overlay_alpha, overlay_type, None)
                    try:
                        self.siril.pix2radec(0, 0)
                    except ValueError:
                        self.siril.log("The image is not plate solved", color=s.LogColor.RED)
                        if not from_cli:
                            self.siril.error_messagebox("The image is not plate solved")
                        return
                try:
                    arcmin_per_px_now = float(self._arcmin_per_pixel())  # 分/px
                    if arcmin_per_px_now > 0 and math.isfinite(arcmin_per_px_now):
                        self.saved_arcmin_per_px = arcmin_per_px_now
                        self.siril.log(f"Saved pixel scale: {arcmin_per_px_now:.4f}分/px", color=s.LogColor.GREEN)
                        # 直後に設定ファイルへ反映（既に一度 save_config_file 済みでも上書きでOK）
                        self.save_config_file(
                            self.cli_args.logo_path if from_cli else self.logo_path.get(),
                            float(self.cli_args.overlay_alpha) if from_cli else float(self.overlay_alpha_var.get()),
                            self.cli_args.overlay_type if from_cli else self.overlay_type_var.get(),
                            None
                        )
                except Exception as e:
                    self.siril.log(f"Warning: cannot save pixel scale: {e}", color=s.LogColor.RED)
                # --- 挿入ここまで ---

                if not is_reapply:
                    self.df_all = None
                    self.custom_object_colors.clear()
                    self.visible_object_flags.clear()
                    self.display_name_vars = {}
                    self._object_defaults_snapshot = None
                    self._view_mode = "normal"
                    self.object_label_mode_overrides = {}
                    self.label_mode_vars = {}
                    if hasattr(self, 'visible_object_names'):
                        del self.visible_object_names

                self.siril.log(
                    f"Label mode={self.label_number_mode}, "
                    f"threshold_px={int(self.label_threshold_px)}"
                    + (f" (~{self.label_threshold_arcmin_ui:.2f} arcmin UI)" 
                       if self.label_threshold_arcmin_ui is not None else ""),
                    color=s.LogColor.GREEN
                )

                try:
                    arcmin_per_px = self._arcmin_per_pixel()
                    self.siril.log(f"Current scale ~ {arcmin_per_px:.4f} arcmin/px", color=s.LogColor.GREEN)
                except Exception:
                    self.siril.log("Scale lookup failed; using threshold_px only.", color=s.LogColor.RED)

                result = annotate_fit(
                self.siril, None, self.catalogs, output, title, logo_path, overlay_alpha, overlay_type,
                self.custom_object_colors,
                visible_object_names=(self.visible_object_names if (is_reapply and hasattr(self, 'visible_object_names')) else None),
                preloaded_df=(self.df_all if (((is_reapply) or (getattr(self, "_view_mode", "normal")=="csv")) and hasattr(self, "df_all")) else None),
                reapply=is_reapply,
                display_name_vars=(self.display_name_vars if (is_reapply or (getattr(self, "_view_mode","normal")=="csv")) else None),
                custom_catalog_files=self.custom_catalog_files,
                # フォールバック設定
                fallback_mode=self.size_fallback_mode,
                fallback_radius_px=int(self.size_fallback_radius_px),
                fallback_line_len_px=int(self.size_fallback_line_len_px),
                fallback_center_gap_px=int(self.size_fallback_center_gap_px),
                # ラベル/番号設定
                label_number_mode=self.label_number_mode,
                label_threshold_px=int(self.label_threshold_px),
                size_missing_label_mode=self.size_missing_label_mode,
                per_object_label_overrides=self.object_label_mode_overrides,
                # 標本設定
                table_max_per_page=(25 if self.specimen_use_defaults else int(self.specimen_max_per_page)),
                table_max_cols=(5 if self.specimen_use_defaults else int(self.specimen_max_per_row)),
                # ★ Apply/ReApply は Overlay のみ
                generate_table=False,
                generate_combined=False, square_layout=bool(self.specimen_use_defaults))

                                # Normalize annotate_fit(square_layout=False) result → (dfi, found, df_all, page_info)
                res = result

                try:
                    if isinstance(res, tuple):
                        if len(res) == 4:
                            dfi, found, df_all, page_info = res
                        elif len(res) == 3:
                            dfi, found, df_all = res
                            page_info = {"table_pages": 1, "combined_pages": 1}
                        else:
                            raise ValueError(f"tuple length {len(res)} not supported")
                    elif isinstance(res, pd.DataFrame):
                        dfi = res
                        found = int(dfi.shape[0])
                        df_all = dfi
                        page_info = {"table_pages": 1, "combined_pages": 1}
                    else:
                        raise TypeError(f"{type(res).__name__}")
                except Exception as e:
                    if not from_cli:
                        messagebox.showerror("Error", f"Unexpected result from annotate_fit(square_layout=False): {type(res).__name__} {e}")
                    else:
                        print(f"Error: Unexpected result from annotate_fit(square_layout=False): {type(res).__name__} {e}")
                    return

                # ページ情報を保存し、C/Tボタンを初期化
                try:
                    self.table_pages = int(page_info.get("table_pages", 1))
                    self.combined_pages = int(page_info.get("combined_pages", 1))
                except Exception:
                    self.table_pages = 1; self.combined_pages = 1
                self.table_page_idx = 1
                self.combined_page_idx = 1
                try:
                    self._update_ct_labels()
                except Exception:
                    pass
                self.df_all = df_all

# === Apply Cache Patch (gk.13) ===
                if GA_AUTO_WRITE_APPLY_CACHE:
                    try:
                        _df_to_cache = self.df_all.copy()
                        # ensure obj_id
                        if "obj_id" not in _df_to_cache.columns:
                            try:
                                _df_to_cache.insert(0, "obj_id", range(1, len(_df_to_cache)+1))
                            except Exception:
                                _df_to_cache["obj_id"] = list(range(1, len(_df_to_cache)+1))
                        # keep minimal columns if available
                        _keep_cols = [c for c in [
                            "obj_id","main_id","display_name","TYPE",
                            "RAJ2000","DEJ2000","ra","dec","X","Y",
                            "galdim_majaxis","galdim_minaxis","galdim_angle",
                            "maj_arcmin","min_arcmin","PA","pix_diam",
                            "color_hex","color","visible","label_mode"
                        ] if c in _df_to_cache.columns]
                        if _keep_cols:
                            _df_to_cache = _df_to_cache[_keep_cols].copy()

                        # cache directory
                        _cache_dir = getattr(self, "cache_base_dir", None)
                        if not _cache_dir:
                            _cache_dir = os.path.join(os.getcwd(), "ga_cache")
                        os.makedirs(_cache_dir, exist_ok=True)
                        import datetime as _dt
                        _stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                        _base = f"apply_{_stamp}"
                        _obj_path = os.path.join(_cache_dir, _base + (".feather" if _GA_HAS_ARROW else ".csv.gz"))

                        # write cache
                        try:
                            if _GA_HAS_ARROW:
                                _df_to_cache.reset_index(drop=True).to_feather(_obj_path)
                            else:
                                _df_to_cache.to_csv(_obj_path, index=False, encoding="utf-8", compression="gzip")
                        except Exception as _e:
                            try:
                                self.siril.log(f"Cache write failed, fallback to CSV: {str(_e)}", color=s.LogColor.RED)
                            except Exception:
                                pass
                            try:
                                _obj_path = os.path.join(_cache_dir, _base + ".csv.gz")
                                _df_to_cache.to_csv(_obj_path, index=False, encoding="utf-8", compression="gzip")
                            except Exception:
                                _obj_path = ""

                        # write latest link
                        try:
                            if _obj_path:
                                with open(os.path.join(_cache_dir, "latest_apply.link"), "w", encoding="utf-8") as _f:
                                    _f.write(_obj_path+"\n")
                        except Exception:
                            pass

                        # reload from cache to lower RAM & switch to CSV view
                        if _obj_path:
                            try:
                                if _obj_path.endswith(".feather") and _GA_HAS_ARROW:
                                    _re_df = pd.read_feather(_obj_path)
                                else:
                                    _re_df = pd.read_csv(_obj_path, dtype=None, encoding="utf-8", compression="gzip", low_memory=False)
                                self.df_all = _re_df
                                self._view_mode = "csv"
                            except Exception as _e:
                                try:
                                    self.siril.log(f"Cache reload failed: {str(_e)}", color=s.LogColor.RED)
                                except Exception:
                                    pass

                    except Exception as _e:
                        try:
                            self.siril.log(f"Cache patch skipped: {str(_e)}", color=s.LogColor.RED)
                        except Exception:
                            print("Cache patch skipped:", _e)
                    # === /Apply Cache Patch ===


                    self.anno_numbers = {}
                    if 'anno_num' in dfi.columns:
                        for r in dfi[['main_id','anno_num']].itertuples(index=False):
                            try:
                                self.anno_numbers[str(r.main_id)] = int(r.anno_num)
                            except Exception:
                                pass
                # After normalization above, dfi should be a DataFrame.
                if not isinstance(dfi, pd.DataFrame):
                    if not from_cli:
                        messagebox.showerror("Error", f"Unexpected result from annotate_fit(square_layout=False) after normalization: type(dfi)={type(dfi).__name__}")
                    else:
                        print(f"Error: Unexpected result from annotate_fit(square_layout=False) after normalization: type(dfi)={type(dfi).__name__}")
                    return

                # Populate annotation numbers for Object window ("No." column)
                try:
                    self.anno_numbers = {}
                    if isinstance(dfi, pd.DataFrame) and ('main_id' in dfi.columns):
                        if 'anno_num' in dfi.columns:
                            for r in dfi[['main_id','anno_num']].itertuples(index=False):
                                try:
                                    self.anno_numbers[str(r.main_id)] = int(r.anno_num)
                                except Exception:
                                    pass
                        else:
                            # Fallback: assign sequential numbers in current dfi order
                            i = 1
                            for r in dfi[['main_id']].itertuples(index=False):
                                self.anno_numbers[str(r.main_id)] = i
                                i += 1
                except Exception:
                    pass
                # Build display order map aligned with numbering (No.)
                try:
                    self._object_order_map = {}
                    if isinstance(dfi, pd.DataFrame) and ('main_id' in dfi.columns):
                        if 'anno_num' in dfi.columns:
                            _sorted = dfi[['main_id','anno_num']].sort_values('anno_num', kind='stable')
                            for i, r in enumerate(_sorted.itertuples(index=False)):
                                self._object_order_map[str(r.main_id)] = i
                        else:
                            # Use current dfi order
                            for i, r in enumerate(dfi[['main_id']].itertuples(index=False)):
                                self._object_order_map[str(r.main_id)] = i
                except Exception:
                    try:
                        self._object_order_map = {}
                    except Exception:
                        pass


                if not from_cli and not is_reapply:
                    if 'original_display_name' in self.df_all.columns:
                        self.df_all['display_name'] = self.df_all['original_display_name']

                    if not is_reapply:
                        selected_types = {k for k, v in self.catalogs.items() if v.get_selected()}
                        # dfi は annotate_fit(square_layout=bool(self.specimen_use_defaults)) の描画最終リスト（重複間引き済み）。
                        # Objectウィンドウの初期表示を描画結果に厳密一致させるため、
                        # kept_set に残った main_id のみ ON、それ以外（描画で落ちたもの）は OFF にする。
                        try:
                            kept_set = set(dfi['main_id'].astype(str).tolist())
                        except Exception:
                            kept_set = set()


                        self.visible_object_flags.clear()
                        self.custom_object_colors.clear()
                        for row in self.df_all.itertuples(index=False):
                            ctype = row.TYPE
                            if ctype not in selected_types:
                                continue
                            name = row.main_id
                            self.visible_object_flags[name] = tk.BooleanVar(value=(str(name) in kept_set))
                            self.custom_object_colors[name] = self.catalogs[ctype].color
                            # ★ ここでは Label 既定値は設定しない（Objectウィンドウで詳細設定から計算）

                        primary = [t for t in ['Stars', 'M', 'IC', 'NGC'] if t in selected_types]
                        if len(primary) >= 2 and isinstance(self.df_all, pd.DataFrame):
                            df_mni = self.df_all[self.df_all['TYPE'].isin(primary)].copy()
                            if not df_mni.empty and {'px', 'py'}.issubset(df_mni.columns):
                                dedup_priority = {'M': 0, 'IC': 1, 'NGC': 2}

                                def alias_set(v):
                                    if pd.isna(v) or v is None:
                                        return set()
                                    return set([p.strip() for p in str(v).split('/') if p.strip()])

                                rows = list(
                                    df_mni.sort_values(
                                        by='TYPE',
                                        key=lambda s: s.map(lambda t: dedup_priority.get(t, 999))
                                    ).iterrows()
                                )
                                used = set()
                                for i, a in rows:
                                    if i in used:
                                        continue
                                    group = [i]
                                    for j, b in rows:
                                        if j <= i or j in used:
                                            continue
                                        same_pos = (abs(int(a.px) - int(b.px)) <= 1) and (abs(int(a.py) - int(b.py)) <= 1)
                                        da = float(a.galdim_majaxis) if pd.notna(a.galdim_majaxis) else float('nan')
                                        db = float(b.galdim_majaxis) if pd.notna(b.galdim_majaxis) else float('nan')
                                        if not (np.isfinite(da) and np.isfinite(db)):
                                            same_rad = True
                                        else:
                                            tol = min(0.5, 0.1 * max(da, db))
                                            same_rad = abs(da - db) <= tol
                                        alias_hit = (str(a.main_id) in alias_set(getattr(b, 'alias', None))) or \
                                                    (str(b.main_id) in alias_set(getattr(a, 'alias', None)))
                                        if (same_pos and same_rad) or alias_hit:
                                            group.append(j)
                                            used.add(j)
                                    if len(group) > 1:
                                        for j in group[1:]:
                                            nm = df_mni.loc[j, 'main_id']
                                            if nm in self.visible_object_flags:
                                                self.visible_object_flags[nm].set(False)
                    if not is_reapply:
                        self.visible_object_names = [name for name, var in self.visible_object_flags.items() if var.get()]


                # Save Defaults snapshot after **Apply only**
                if not is_reapply:
                    try:
                        self._object_defaults_snapshot = {name: var.get() for name, var in self.visible_object_flags.items()}
                    except Exception:
                        pass

                # Save Label Defaults snapshot after **Apply only**
                if not is_reapply:
                    try:
                        names_for_label = []
                        try:
                            if hasattr(self, 'df_all') and self.df_all is not None and 'main_id' in self.df_all.columns:
                                names_for_label = [str(x) for x in self.df_all['main_id'].astype(str).tolist()]
                        except Exception:
                            pass
                        if not names_for_label:
                            names_for_label = [str(n) for n in (self.visible_object_flags.keys() if hasattr(self, 'visible_object_flags') else [])]
                        self._label_defaults_snapshot = {
                            nm: (self.label_mode_vars[nm].get() if (hasattr(self, 'label_mode_vars') and nm in self.label_mode_vars and self.label_mode_vars[nm]) else None)
                            for nm in names_for_label
                        }
                    except Exception:
                        pass


                if found and found > 0:
                    if is_reapply or self._view_mode == "csv":
                        df_for_object = self.df_all.copy()
                    else:
                        types_selected = [k for k, v in self.catalogs.items() if v.get_selected()]
                        df_for_object = self.df_all[self.df_all['TYPE'].isin(types_selected)].copy()

                    self.siril.update_progress("Opening Object window...", 0.98)
                    if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
                        self.object_control_window.lift()
                        self.object_control_window.focus_force()
                    else:
                        self.show_object_selection_dialog(df_for_object, is_reapply=is_reapply)
                    self.siril.update_progress("Finished.", 1.0)
                    elapsed = time.perf_counter() - _t0
                    try:
                        mode = "Reapply" if is_reapply else "Apply"
                        self.siril.log(f"{mode} finished in {elapsed:.1f}s", color=s.LogColor.GREEN)
                    except Exception:
                        pass

                    self.siril.log("Annotations image created successfully.", color=s.LogColor.GREEN)
                    self.siril.cmd("load", "\""+ get_overlay_filename(output) +"\"")

        except SirilError as e:
            if from_cli:
                print(f"Error: {str(e)}")
            else:
                messagebox.showerror("Error", str(e))
    
    def _update_ct_labels(self):
        """ページ数に応じて C/T ボタンの表記を更新（メイン/Obj 両対応）"""
        def _set(btn, base, idx, pages):
            if not btn:
                return
            try:
                if pages > 1:
                    btn.configure(text=f"{base}{idx}")
                else:
                    btn.configure(text=base)
            except Exception:
                pass

        # main window buttons (if exist)
        _set(getattr(self, 'main_btn_c', None), 'C', getattr(self, 'combined_page_idx', 1), getattr(self, 'combined_pages', 1))
        _set(getattr(self, 'main_btn_t', None), 'T', getattr(self, 'table_page_idx', 1), getattr(self, 'table_pages', 1))
        # object window buttons (if exist)
        _set(getattr(self, 'obj_btn_c', None), 'C', getattr(self, 'combined_page_idx', 1), getattr(self, 'combined_pages', 1))
        _set(getattr(self, 'obj_btn_t', None), 'T', getattr(self, 'table_page_idx', 1), getattr(self, 'table_pages', 1))

    def _on_click_cycled_combined(self):
        """Cボタンクリック：ページを循環して表示"""
        p = getattr(self, "combined_pages", 1)
        if p > 1:
            i = getattr(self, "combined_page_idx", 1)
            i = (i % p) + 1
            self.combined_page_idx = i
        self.switch_image("combined")
        self._update_ct_labels()

    def _on_click_specimen(self):
        """天体標本作成: Objectウィンドウの変更を反映して Overlay を作り直し、Table を生成。Overlay をロードし、Siril に枚数を通知。"""
        self.pending_object_renumber = True  # Specimen時はNoを振り直す

        # Show original (N) first
        try:
            self.switch_image("original")
        except Exception:
            pass

        try:
            self.object_label_mode_overrides = {n: v.get() for n, v in getattr(self, 'label_mode_vars', {}).items() if (v.get() or '').strip()}
            self.visible_object_names = [name for name, var in getattr(self, 'visible_object_flags', {}).items() if var.get()]
        except Exception:
            pass
        from tkinter import messagebox
        with self.siril.image_lock():
            try:
# Silent WCS check using FITS header (avoid console logs)
                try:
                    hdr = self.siril.get_image_fits_header(return_as='dict')
                except Exception:
                    try:
                        hdr = s.get_image_fits_header(return_as='dict')
                    except Exception:
                        hdr = {}
                if not isinstance(hdr, dict) or ('CRVAL1' not in hdr) or ('CRVAL2' not in hdr):
                    raise RuntimeError('No WCS')
            except Exception:
                messagebox.showerror("Error", "The image is not plate solved")
                return
            output = self.output.get()
            title = self.title.get()
            logo_path = self.logo_path.get()
            overlay_alpha = float(self.overlay_alpha_var.get())
            overlay_type = self.overlay_type_var.get()

            result = annotate_fit(

            self.siril,
            None,
            self.catalogs,
            output,
            title,
            logo_path,
            overlay_alpha,
            overlay_type,
            self.custom_object_colors,
            visible_object_names=getattr(self, 'visible_object_names', None),
            preloaded_df=getattr(self, 'df_all', None),
            reapply=True,
            display_name_vars=self.display_name_vars,
            custom_catalog_files=self.custom_catalog_files,
            fallback_mode=self.size_fallback_mode,
            fallback_radius_px=int(self.size_fallback_radius_px),
            fallback_line_len_px=int(self.size_fallback_line_len_px),
            fallback_center_gap_px=int(self.size_fallback_center_gap_px),
            label_number_mode=self.label_number_mode,
            label_threshold_px=int(self.label_threshold_px),
            size_missing_label_mode=self.size_missing_label_mode,
            per_object_label_overrides=self.object_label_mode_overrides,
            table_max_per_page=(25 if self.specimen_use_defaults else int(self.specimen_max_per_page)),
            table_max_cols=(5 if self.specimen_use_defaults else int(self.specimen_max_per_row)),            generate_table=True,
            generate_combined=False, square_layout=bool(self.specimen_use_defaults))


            if isinstance(result, tuple):
                if len(result) == 4:
                    dfi, found, df_all, page_info = result
                else:
                    dfi, found, df_all = result
                    page_info = {"table_pages": 1, "combined_pages": 1}
                try:
                    self.table_pages = int(page_info.get("table_pages", 1))
                except Exception:
                    self.table_pages = 1
                self.combined_pages = 1
                self.table_page_idx = 1
                self.combined_page_idx = 1
                self.df_all = df_all
                try:
                    self._update_ct_labels()
                except Exception:
                    pass

            try:
                pass
            except Exception:
                pass

            try:
                if hasattr(self, 'obj_btn_make_combined'):
                    self.obj_btn_make_combined.configure(state="normal")
            except Exception:
                pass

            try:
                pages = getattr(self, 'table_pages', 1)
                self.siril.log(f"{pages}枚の天体標本画像を作成しました。画像はTボタンで確認できます。1枚あたりの天体数は詳細設定から変更できます。", color=s.LogColor.GREEN)
            except Exception:
                pass

        self.table_page_idx = 1

        self.switch_image("table")

        self._update_ct_labels()
    def _on_click_make_combined(self):
        ok = _ask_okcancel_front("確認", "変更を反映したい場合には、先に「天体標本作成」ボタンを押してください。続行しますか？", getattr(self, "root", None))
        if not ok:
            return
        try:
            pages = max(1, int(getattr(self, 'table_pages', 1)))
        except Exception:
            pages = 1

        made = self._build_combined_only(self.output.get(), pages)
        self.combined_pages = max(1, int(made))
        self.combined_page_idx = 1
        try:
            self._update_ct_labels()
        except Exception:
            pass
        try:
            self.siril.log(f"{made}枚の「結合画像作成」画像を作成しました。画像はCボタンで確認できます。", color=s.LogColor.GREEN)
        except Exception:
            pass

        self.combined_page_idx = 1

        self.switch_image("combined")

        self._update_ct_labels()
        try:
            self.root.lift(); self.root.focus_force(); self.root.after(10, self.root.lift)
        except Exception:
            pass

    def _build_combined_only(self, output_basename: str, table_pages: int) -> int:
        try:
            overlay_path = get_overlay_filename(output_basename)
            overlay_img = Image.open(overlay_path).convert("RGB")
            ow, oh = overlay_img.size
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Error", f"Overlay not found or unreadable:\n{e}")
            return
        made = 0
        try:
            total_pages_lp = max(1, int(table_pages))
        except Exception:
            total_pages_lp = 1
        progress_start, progress_end = 0.80, 0.97
        self.siril.update_progress("Creating combined output image...", progress_start)
        for idx in range(1, max(1, int(table_pages)) + 1):
            tf = get_table_filename_page(output_basename, idx)
            if not os.path.isfile(tf):
                if idx == 1:
                    tf = get_table_filename(output_basename)
                    if not os.path.isfile(tf):
                        break
                else:
                    break
            try:
                table_img = Image.open(tf).convert("RGB")
            except Exception:
                break
            tw, th = table_img.size
            if tw != ow:
                new_h = max(1, int(round(th * (ow / float(tw)))))
                table_img = table_img.resize((ow, new_h), Image.LANCZOS)
                th = new_h
            combined = Image.new("RGB", (ow, oh + th))
            combined.paste(overlay_img, (0, 0))
            combined.paste(table_img, (0, oh))
            out_comb = get_combined_filename_page(output_basename, idx) if table_pages > 1 else get_combined_filename(output_basename)
            combined.save(out_comb)
            frac2 = progress_start + (progress_end - progress_start) * (idx) / max(1, total_pages_lp)
            self.siril.update_progress(f"Saved combined image ({idx}/{total_pages_lp})", frac2)
            made += 1
            try:
                self.siril.log(f"結合画像を保存: {out_comb}", color=s.LogColor.GREEN)
            except Exception:
                pass

        self.siril.update_progress("Finalizing outputs...", 0.97)
        self.siril.update_progress("Completed combined image(s).", 1.0)
        return made

    def _on_click_cycled_table(self):
        """Tボタンクリック：ページを循環して表示"""
        p = getattr(self, "table_pages", 1)
        if p > 1:
            i = getattr(self, "table_page_idx", 1)
            i = (i % p) + 1
            self.table_page_idx = i
        self.switch_image("table")
        self._update_ct_labels()

    def switch_image(self, kind):
        try:
                if kind == "combined":
                    if getattr(self, "combined_pages", 1) > 1:
                        filepath = get_combined_filename_page(self.output.get(), getattr(self, "combined_page_idx", 1))
                    else:
                        filepath = get_combined_filename(self.output.get())
                elif kind == "overlay":
                    filepath = get_overlay_filename(self.output.get())
                elif kind == "table":
                    if getattr(self, "table_pages", 1) > 1:
                        filepath = get_table_filename_page(self.output.get(), getattr(self, "table_page_idx", 1))
                    else:
                        filepath = get_table_filename(self.output.get())
                elif kind == "original":
                    if not hasattr(self, "_original_image") or not self._original_image:
                        messagebox.showwarning("Warning", "Original image not available.")
                        return
                    filepath = self._original_image
                else:
                    return
    
                if not os.path.isfile(filepath):
                    messagebox.showwarning("Warning", f"Image not found:\n{filepath}")
                    return
    
                self.siril.cmd("load", f"\"{filepath}\"")
                self.siril.log(f"Switched to: {os.path.basename(filepath)}", color=s.LogColor.GREEN)

                # Refresh Object window numbers immediately for Specimen (use internal refresh hook if available)
                try:
                    if hasattr(self, "object_control_window") and self.object_control_window.winfo_exists():
                        self.pending_object_renumber = True
                        if hasattr(self, "_object_window_refresh"):
                            self._object_window_refresh()
                        else:
                            self.show_object_selection_dialog(self.df_all.copy(), is_reapply=True)
                except Exception:
                    pass
        except Exception as e:
                messagebox.showerror("Error", f"Failed to load image:\n{str(e)}")
    
    def close_dialog(self):
        global _SHUTTING_DOWN
        _SHUTTING_DOWN = True
        if hasattr(self, 'root'):
            self.root.quit()
            self.root.destroy()
    
    def select_all(self):
        for key, value in self.catalogs.items():
                value.checkbox_var.set(True)
    
    def select_none(self):
        for key, value in self.catalogs.items():
                value.checkbox_var.set(False)
    
    def select_defaults(self):
        """Reset catalog checkboxes to their built-in defaults (selection_default)."""
        try:
            for key, value in self.catalogs.items():
                # Some entries may not be displayed; still set their vars if present
                if hasattr(value, "checkbox_var"):
                    value.checkbox_var.set(bool(getattr(value, "selection_default", False)))
        except Exception:
            # Fallback: do nothing if catalogs not initialized yet
            pass


    def show_object_selection_dialog(self, dataframe, is_reapply=False):
        """
        Objectウィンドウ（軽量Canvas版）
        - ヘッダーに Filter / Catalog / items 表記 / Export CSV / Replace CSV
        - 2段目に 対象トグル（表示天体のみ/全ページ天体） + 「表示：All/None/Defaults」 + 「ラベル：No+DN/DN/No/Defaults」 と Page size / Page ナビ（< 1/3 >）
        - 本体は Canvas に自前描画（軽量）。
        - 列:
            [#0 色スウォッチ] [#1 Hex] [#2 表示(ON/-)] [#3 No.] [#4 main_id] [#5 TYPE]
            [#6 Label(クリックで No→No+DN→DN)] [#7 Display Name(ダブルクリック編集)]
        - Hex/スウォッチ ダブルクリックでカラーピッカー
        - Display Name ダブルクリックでインプレース編集
        - vis 列クリックで ON / - トグル
        """
        import tkinter as tk
        from tkinter import ttk, filedialog, colorchooser, messagebox
        from tkinter import font as tkfont
        # === Rightmost column display mode ('name' or 'axes') ===
        try:
            _ = self.rightcol_mode
        except Exception:
            pass
        if (not hasattr(self, 'rightcol_mode')) or (not isinstance(getattr(self, 'rightcol_mode', None), tk.StringVar)):
            self.rightcol_mode = tk.StringVar(value='name')  # default: show 表示名

        import pandas as pd
        renumber_enabled = bool(is_reapply)
        import gc, os

        # --- 事前掃除（メモリ圧迫を避ける） ---
        try:
            import matplotlib.pyplot as _plt
            _plt.close('all')
        except Exception:
            pass
        try:
            gc.collect()
        except Exception:
            pass

        df = dataframe.dropna(subset=['main_id', 'TYPE']).copy()
        # === JP-named convenience columns for the rightmost column toggle ===
        try:
            if 'display_name' in df.columns and '表示名' not in df.columns:
                df['表示名'] = df['display_name'].astype(str)
            if 'galdim_majaxis' in df.columns and '長径' not in df.columns:
                df['長径'] = df['galdim_majaxis']
            if 'galdim_minaxis' in df.columns and '短径' not in df.columns:
                df['短径'] = df['galdim_minaxis']
        except Exception:
            pass

        try:
            if 'galdim_angle' in df.columns and '回転角度' not in df.columns:
                df['回転角度'] = df['galdim_angle']
        except Exception:
            pass


        # --- Enforce stable CSV order for Stars/M/IC/NGC (including display='-') ---
        # Keep original relative order as baseline for types without csv_order
        try:
            import numpy as _np
        except Exception:
            _np = None
        try:
            if 'TYPE' in df.columns:
                # Baseline index to preserve input order for non-target types
                try:
                    base_idx = _np.arange(len(df), dtype=int) if _np is not None else list(range(len(df)))
                except Exception:
                    base_idx = list(range(len(df)))
                df['_base_idx'] = base_idx

                # Map TYPE to group order (as in catalogs order)
                try:
                    _type_order_map = {k: i for i, k in enumerate(self.catalogs.keys())}
                except Exception:
                    _type_order_map = {}
                df['_type_ord'] = df['TYPE'].map(_type_order_map).fillna(999)

                # Within-type order: use csv_order for Stars/M/IC/NGC if present, otherwise baseline index
                _targets = set(['Stars','M','IC','NGC'])
                if 'csv_order' in df.columns:
                    try:
                        df['_within_ord'] = df.apply(
                            lambda r: int(r['csv_order']) if (str(r['TYPE']) in _targets and pd.notna(r.get('csv_order'))) else int(r['_base_idx']),
                            axis=1
                        )
                    except Exception:
                        df['_within_ord'] = df['_base_idx']
                else:
                    df['_within_ord'] = df['_base_idx']

                # Final stable sort: by TYPE block then within-type order
                df = df.sort_values(['_type_ord', '_within_ord'], kind='stable').drop(columns=['_type_ord','_within_ord','_base_idx'])
        except Exception:
            # If anything goes wrong, keep original order
            pass

        # 表示順：番号(No.)の付与順に「番号が付いている行だけ」並べ替え、
        # 番号がない行（ord_mapに無い main_id）は元の位置のまま動かさない
        
        # 表示順：番号(No.)の付与順に「番号が付いている行だけ」並べ替え、
        # 番号がない行（ord_mapに無い main_id）は元の位置のまま動かさない
        _is_csv_mode = (getattr(self, "_view_mode", "normal") == "csv")
        _has_csv_order = ('csv_order' in df.columns)
        # When in CSV mode or csv_order is present, we must preserve the CSV-defined order exactly.
        # Therefore, skip No.-based reordering in those cases.
        if (not _is_csv_mode) and (not _has_csv_order):
            ord_map = getattr(self, '_object_order_map', {}) or {}
            if ord_map:
                pass  # kept for reference
            # ※無効化: 並び替えはしない（Noベース再配置をスキップ）
            if False and ord_map and not getattr(self, "no_reorder_for_object_table", True):
                try:
                    names = df['main_id'].astype(str).tolist()
                    mapped_pos = [i for i, nm in enumerate(names) if nm in ord_map]
                    if mapped_pos:
                        mapped = df.iloc[mapped_pos].copy()
                        mapped['_ord'] = mapped['main_id'].astype(str).map(ord_map)
                        mapped = mapped.sort_values(['_ord'], kind='stable').drop(columns=['_ord'])
                        # 再配置：番号が付いている行だけを、元の位置スロットに順に詰め直す
                        df = df.copy()
                        df.iloc[mapped_pos] = mapped.values
                except Exception:
                    pass

        pass


        # --- per-object 状態の初期化 ---
        self.label_mode_vars = getattr(self, 'label_mode_vars', {}) or {}
        self.display_name_vars = getattr(self, 'display_name_vars', {}) or {}
        self.visible_object_flags = getattr(self, 'visible_object_flags', {}) or {}
        self.object_label_mode_overrides = getattr(self, 'object_label_mode_overrides', {}) or {}
        self.custom_object_colors = getattr(self, 'custom_object_colors', {}) or {}
        # Objectウィンドウ全体のDataFrame参照を保持（スコープ判定用）
        # === LOG: Object window order vs CSV order (per TYPE) ===
        try:
            _dbg_msg = f"[Object順チェック] _is_csv_mode={_is_csv_mode}, _has_csv_order={_has_csv_order}"
            print(_dbg_msg) if GA_DEBUG_OBJECT_ORDER_LOG else None
            try:
                self.siril.log(_dbg_msg, color=s.LogColor.CYAN) if GA_DEBUG_OBJECT_ORDER_LOG else None
            except Exception:
                pass
        except Exception:
            pass

        try:
            import pandas as pd  # ensure alias
            _targets = ['Stars','M','IC','NGC']
            if 'TYPE' in df.columns:
                # prefer display_name/Name/name/main_id in this order
                def _pick_name_frame(_df):
                    for k in ['display_name', 'Name', 'name', 'main_id']:
                        if k in _df.columns:
                            return _df[k].astype(str).tolist()
                    # fallback
                    return _df.index.astype(str).tolist()
                if 'csv_order' in df.columns:
                    for _ty in _targets:
                        _sub = df[df['TYPE'] == _ty].copy()
                        if _sub.empty:
                            continue
                        _names = _pick_name_frame(_sub)
                        _csvs = pd.to_numeric(_sub['csv_order'], errors='coerce').fillna(-1).astype(int).tolist()
                        _pairs = list(zip(range(1, len(_sub)+1), _csvs, _names))
                        _head = ", ".join([f"{i}:{co}:{nm}" for i,co,nm in _pairs[:20]])
                        _msg = f"[Object順チェック][{_ty}] 先頭20件 (disp#:csv_order:name) => {_head}"
                        print(_msg) if GA_DEBUG_OBJECT_ORDER_LOG else None if GA_DEBUG_OBJECT_ORDER_LOG else None
                        try:
                            self.siril.log(_msg, color=s.LogColor.CYAN) if GA_DEBUG_OBJECT_ORDER_LOG else None
                        except Exception:
                            pass
                        # monotonic nondecreasing check on csv_order >= 0
                        _csv_list = [co for _,co,_ in _pairs if co >= 0]
                        if _csv_list:
                            _is_sorted = all(_csv_list[i] <= _csv_list[i+1] for i in range(len(_csv_list)-1))
                            _chk = "OK" if _is_sorted else "NG"
                            _msg2 = f"[Object順チェック][{_ty}] csv_order非減少性: {_chk} (len={len(_csv_list)})"
                            print(_msg2) if GA_DEBUG_OBJECT_ORDER_LOG else None
                            try:
                                self.siril.log(_msg2, color=s.LogColor.CYAN if _is_sorted else s.LogColor.YELLOW) if GA_DEBUG_OBJECT_ORDER_LOG else None
                            except Exception:
                                pass
                else:
                    _msg = "[Object順チェック] このDataFrameには csv_order 列がありません（CSV順検証をスキップ）"
                    print(_msg) if GA_DEBUG_OBJECT_ORDER_LOG else None if GA_DEBUG_OBJECT_ORDER_LOG else None
                    try:
                        self.siril.log(_msg, color=s.LogColor.YELLOW) if GA_DEBUG_OBJECT_ORDER_LOG else None
                    except Exception:
                        pass
        except Exception as __e_log__:
            try:
                print(f"[Object順チェック] ログ出力で例外: {__e_log__}") if GA_DEBUG_OBJECT_ORDER_LOG else None
            except Exception:
                pass
        # === END LOG ===

        self._object_window_df = df.copy()

        def _compute_default_label_mode_for_row(row):
            try:
                return self._compute_default_label_mode_for_row(row)
            except Exception:
                return "No"

        for row in df.itertuples(index=False):
            name = row.main_id
            ctype = row.TYPE
            if name not in self.visible_object_flags:
                self.visible_object_flags[name] = tk.BooleanVar(value=True)
            if name not in self.custom_object_colors:
                try:
                    self.custom_object_colors[name] = self.catalogs[ctype].color
                except Exception:
                    self.custom_object_colors[name] = "#FFFFFF"
            if name not in self.display_name_vars:
                disp = ""
                if hasattr(row, 'display_name') and row.display_name is not None:
                    disp = str(row.display_name)
                self.display_name_vars[name] = tk.StringVar(value=disp)
            if name not in self.label_mode_vars:
                try:
                    default_mode = self.object_label_mode_overrides.get(name) or _compute_default_label_mode_for_row(row)
                except Exception:
                    default_mode = "No"
                self.label_mode_vars[name] = tk.StringVar(value=default_mode)

        # --- 初回オープン時：ラベル既定スナップショットを保存（is_reapplyでは上書きしない） ---
        try:
            if not is_reapply:
                # df 内の順番で確定した per-object デフォルトを丸ごと保存
                self._label_defaults_snapshot = {str(nm): self.label_mode_vars[str(nm)].get() for nm in df['main_id'].astype(str).tolist() if str(nm) in self.label_mode_vars}
        except Exception:
            # フォールバック：少なくとも辞書は存在させる
            if getattr(self, "_label_defaults_snapshot", None) is None:
                self._label_defaults_snapshot = {}

        # 初回オープン時だけDefaultsスナップショット作成
        if not getattr(self, "_object_defaults_snapshot", None):
            try:
                self._object_defaults_snapshot = {name: var.get() for name, var in self.visible_object_flags.items()}
            except Exception:
                self._object_defaults_snapshot = {}

        # 既存ウィンドウがあればフォーカス
        if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
            try:
                self.object_control_window.lift()
                self.object_control_window.focus_force()
                return
            except Exception:
                try:
                    self.object_control_window.destroy()
                except Exception:
                    pass

        # === Window ===
        window = tk.Toplevel(self.root); self.object_control_window = window
        window.withdraw()
        window.title("Customize Objects (Canvas)")
        window.geometry("700x450")
        window.minsize(700, 420)

        PADX, PADY = 10, 8

        # === スタイル ===
        style = ttk.Style(window)
        try:
            base_family = tkfont.nametofont("TkDefaultFont").cget("family")
        except Exception:
            base_family = "Segoe UI"
        OBJ_FONT_SIZE = 10
        obj_font   = tkfont.Font(family=base_family, size=OBJ_FONT_SIZE)
        obj_font_b = tkfont.Font(family=base_family, size=OBJ_FONT_SIZE, weight="bold")

        style.configure("Obj.TButton",      padding=(0, 4), font=obj_font)
        style.configure("Obj.Tool.TButton", padding=(0, 2), font=obj_font)
        style.configure("Obj.TLabel",       font=obj_font)
        style.configure("Obj.TEntry",       font=obj_font)
        style.configure("Obj.TCombobox",    font=obj_font)

        # === Toolbar ===
        top = ttk.Frame(window)
        top.pack(side="top", fill="x", padx=PADX, pady=PADY)

        # 1行目: Filter / Catalog / items / CSV
        top_row1 = ttk.Frame(top); top_row1.pack(side="top", fill="x")
        ttk.Label(top_row1, text="Filter:", style="Obj.TLabel").pack(side="left")
        filter_var = tk.StringVar(value="")
        ttk.Entry(top_row1, textvariable=filter_var, width=24, style="Obj.TEntry").pack(side="left", padx=(6, 10))

        ttk.Label(top_row1, text="Catalog:", style="Obj.TLabel").pack(side="left", padx=(4, 0))
        cat_var = tk.StringVar(value="All")
        cat_opts = ["All"] + list(self.catalogs.keys())
        cat_box = ttk.Combobox(top_row1, state="readonly", values=cat_opts, textvariable=cat_var, style="Obj.TCombobox", width=10)
        cat_box.pack(side="left", padx=(6, 10))
        # Objectウィンドウのスコープ計算用に参照を保持
        self._object_window_cat_var = cat_var

        count_var = tk.StringVar(value="")
        ttk.Label(top_row1, textvariable=count_var, style="Obj.TLabel").pack(side="left", padx=(6, 10))
        
        # 中間行: PageSize / {start}-{end} / filtered_total / Page <cp/total_pages>
        top_rowPg = ttk.Frame(top); top_rowPg.pack(side="top", fill="x", pady=(2, 0))

        # Page size control
        ttk.Label(top_rowPg, text="Page size:", style="Obj.TLabel").pack(side="left", padx=(2, 4))
        current_page_var = tk.IntVar(value=1)
        ps_combo = ttk.Combobox(top_rowPg, state="readonly", values=(10, 20, 30), width=4, style="Obj.TCombobox")
        ps_combo.set("10"); ps_combo.pack(side="left", padx=(0, 10))

        # Range label: {start}-{end} / filtered_total
        page_range_var = tk.StringVar(value="0-0 / 0")
        ttk.Label(top_rowPg, textvariable=page_range_var, style="Obj.TLabel").pack(side="left", padx=(0, 14))

        # Page navigation
        ttk.Label(top_rowPg, text="Page:", style="Obj.TLabel").pack(side="left", padx=(4, 4))
        prev_btn = ttk.Button(top_rowPg, text="<", width=3, style="Obj.Tool.TButton")
        prev_btn.pack(side="left", padx=(0, 4))
        page_label = ttk.Label(top_rowPg, text="1 / 1", width=8, anchor="center", style="Obj.TLabel")
        page_label.pack(side="left", padx=(0, 4))
        next_btn = ttk.Button(top_rowPg, text=">", width=3, style="Obj.Tool.TButton")
        next_btn.pack(side="left", padx=(0, 4))

        # Rightmost-column toggle buttons moved next to Page controls
        btn_right_name = ttk.Button(top_rowPg, text="表示名", style="Obj.TButton",
                                    command=lambda: set_rightcol_mode('name'))
        btn_right_axes = ttk.Button(top_rowPg, text="長径短径回転角度", style="Obj.TButton",
                                    command=lambda: set_rightcol_mode('axes'))
        btn_right_name.pack(side="left", padx=(12, 4))
        btn_right_axes.pack(side="left", padx=(0, 8))


        ttk.Button(top_row1, text="Replace CSV", padding=(1, 4), style="Obj.TButton",
                   command=lambda: do_import_csv()
        ).pack(side="right", padx=(0, 0))
        ttk.Button(top_row1, text="Export CSV", padding=(1, 4), style="Obj.TButton",
                   command=lambda: do_export_csv()
        ).pack(side="right", padx=(0, 8))

        # 2行目: Select / Page size / Page
        top_row2 = ttk.Frame(top); top_row2.pack(side="top", fill="x", pady=(4, 0))
                # 対象トグル（Selectの左）：クリックで「表示天体のみ」↔「全ページ天体」
        ttk.Label(top_row2, text="対象：", style="Obj.TLabel").pack(side="left")
        self.object_select_scope_var = getattr(self, "object_select_scope_var", None) or tk.BooleanVar(value=False)
        scope_btn = ttk.Button(top_row2, text="", width=12, style="Obj.Tool.TButton")
        def _update_scope_btn_text():
            try:
                scope_btn.config(text=("表示天体のみ" if not self.object_select_scope_var.get() else "全ページ天体"))
            except Exception:
                pass
        def _toggle_scope():
            try:
                self.object_select_scope_var.set(not self.object_select_scope_var.get())
            finally:
                _update_scope_btn_text()
        scope_btn.config(command=_toggle_scope)
        scope_btn.pack(side="left", padx=(2, 10))
        _update_scope_btn_text()

        # 「表示」：all / non / default
        ttk.Label(top_row2, text="表示：", style="Obj.TLabel").pack(side="left")
        ttk.Button(top_row2, text="All", width=6, style="Obj.Tool.TButton",
                   command=lambda: (self._select_objects(True), refresh_view())
        ).pack(side="left", padx=2)
        ttk.Button(top_row2, text="None", width=6, style="Obj.Tool.TButton",
                   command=lambda: (self._select_objects(False), refresh_view())
        ).pack(side="left", padx=2)
        ttk.Button(top_row2, text="Defaults", width=8, style="Obj.Tool.TButton",
                   command=lambda: (self._reset_object_defaults(), refresh_view())
        ).pack(side="left", padx=2)

        # 「ラベル」：No+DN / DN / No / default（スコープは対象トグルに従う）
        ttk.Label(top_row2, text="  ラベル：", style="Obj.TLabel").pack(side="left", padx=(8, 4))
        ttk.Button(top_row2, text="No+DN", width=7, style="Obj.Tool.TButton",
                   command=lambda: (self._mass_set_label_mode("No+DN"), refresh_view())
        ).pack(side="left", padx=2)
        ttk.Button(top_row2, text="DN", width=4, style="Obj.Tool.TButton",
                   command=lambda: (self._mass_set_label_mode("DN"), refresh_view())
        ).pack(side="left", padx=2)
        ttk.Button(top_row2, text="No", width=4, style="Obj.Tool.TButton",
                   command=lambda: (self._mass_set_label_mode("No"), refresh_view())
        ).pack(side="left", padx=2)
        ttk.Button(top_row2, text="Defaults", width=8, style="Obj.Tool.TButton",
                   command=lambda: (self._mass_set_label_mode(None), refresh_view())
        ).pack(side="left", padx=2)

#         ttk.Label(top_row2, text="  Page size:", style="Obj.TLabel").pack(side="left", padx=(10, 4))
#         current_page_var = tk.IntVar(value=1)
#         ps_combo = ttk.Combobox(top_row2, state="readonly", values=(10, 20, 30), width=4, style="Obj.TCombobox")
#         ps_combo.set("10"); ps_combo.pack(side="left", padx=(0, 8))
# 
#         ttk.Label(top_row2, text="Page:", style="Obj.TLabel").pack(side="left", padx=(8, 4))
#         prev_btn = ttk.Button(top_row2, text="<", width=3, style="Obj.Tool.TButton")
#         prev_btn.pack(side="left", padx=(0, 4))
#         page_label = ttk.Label(top_row2, text="1 / 1", width=8, anchor="center", style="Obj.TLabel")
#         page_label.pack(side="left", padx=(0, 4))
#         next_btn = ttk.Button(top_row2, text=">", width=3, style="Obj.Tool.TButton")
#         next_btn.pack(side="left", padx=(0, 4))

        def _update_page_widgets(total_pages, cp):
            page_label.configure(text=f"{cp} / {total_pages}")
            try:
                prev_btn.state(["disabled"] if cp <= 1 else ["!disabled"])
                next_btn.state(["disabled"] if cp >= total_pages else ["!disabled"])
            except Exception:
                prev_btn.config(state=("disabled" if cp <= 1 else "normal"))
                next_btn.config(state=("disabled" if cp >= total_pages else "normal"))

        # === Canvas table ===
        center = ttk.Frame(window); center.pack(side="top", fill="x", expand=False, padx=PADX, pady=(0, PADY))
        try:
            # center.pack_propagate(False)  # disabled to allow canvas height to be honored
            pass
        except Exception:
            pass
        canvas = tk.Canvas(center, background="#fafafa", highlightthickness=1, relief="solid")
        vbar = ttk.Scrollbar(center, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        vbar.pack(side="right", fill="y")

        # Header/row metrics
        ROW_H = max(24, obj_font.metrics("linespace")+8)
        HDR_H = ROW_H

        # Column widths for the object table
        COL_W = {"#0": 30, "hex": 57, "vis": 40, "num": 52, "name": 140, "type": 70, "label": 55, "display": 240}

        # --- Ensure exactly 11 visible rows in the viewport ---
        VISIBLE_ROWS = 10
        def _apply_fixed_table_height():
            try:
                window.update_idletasks()
            except Exception:
                pass
            # Slight negative fudge to avoid an extra partial row (theme/metrics variance)
            _fudge = max(3, int(0.12 * ROW_H))
            ch = int(HDR_H + VISIBLE_ROWS * ROW_H - _fudge)
            # Apply canvas height and ensure parent frame also has height so it's not collapsed
            try:
                canvas.configure(height=ch)
                try:
                    center.configure(height=ch)
                except Exception:
                    pass
            except Exception:
                # Fallback if fonts/metrics aren't ready yet
                ch = int(HDR_H + VISIBLE_ROWS * 28 + 2)
                try:
                    canvas.configure(height=ch)
                except Exception:
                    pass
            # Optionally tighten overall window height so bottom buttons remain visible
            try:
                parts_h = 0
                for w in (top_row1,):
                    try:
                        parts_h += int(w.winfo_reqheight())
                    except Exception:
                        pass
                try:
                    parts_h += int(top_row2.winfo_reqheight())
                except Exception:
                    pass
                try:
                    parts_h += int(top_rowPg.winfo_reqheight())
                except Exception:
                    pass
                try:
                    parts_h += int(bottom.winfo_reqheight())
                except Exception:
                    pass
                total_h = int(parts_h + ch + PADY*2)
                cur_w = max(700, window.winfo_width())
                window.minsize(700, total_h)
                try:
                    window.geometry(f"{cur_w}x{total_h}")
                except Exception:
                    pass
            except Exception:
                pass
        def _apply_canvas_min_height():
            """Ensure the canvas height fits exactly header + 11 rows,
            and the window height accommodates toolbars and bottom buttons."""
            try:
                window.update_idletasks()
            except Exception:
                pass
            try:
                ch = int(HDR_H + VISIBLE_ROWS * ROW_H + 2)
                canvas.configure(height=ch)
            except Exception:
                ch = int(HDR_H + VISIBLE_ROWS * 28 + 2)  # fallback

            # Estimate non-canvas vertical size (toolbars + bottom)
            try:
                # Use requested heights to avoid 0 before being mapped
                parts = []
                try: parts.append(top_row1.winfo_reqheight())
                except Exception: pass
                try: parts.append(top_rowPg.winfo_reqheight())
                except Exception: pass
                try: parts.append(top_row2.winfo_reqheight())
                except Exception: pass
                try: parts.append(bottom.winfo_reqheight())
                except Exception: pass
                non_canvas_h = sum([h for h in parts if isinstance(h, int)]) + (PADY * 2) + 16
            except Exception:
                non_canvas_h = 160  # safe default

            try:
                total_h = int(ch + non_canvas_h)
                # keep current width (or default width)
                try:
                    cur_w = max(window.winfo_width(), 725)
                except Exception:
                    cur_w = 725
                window.minsize(700, total_h)
                window.geometry(f"{cur_w}x{total_h}")
            except Exception:
                pass


        # Keep anno numbers (may be computed elsewhere)
        self.anno_numbers = getattr(self, "anno_numbers", {}) or {}

        # row map for hit testing
        draw_rows = []   # list of dicts: {"name":..., "bbox":(y0,y1), "cells": {"hex":(x0,y0,x1,y1), ...}}
        edit_entry = None

        def filtered_df():
            q = filter_var.get().strip()
            cat = cat_var.get()
            sub = df
            if cat and cat != "All":
                sub = sub[sub["TYPE"] == cat]
            if q:
                dn_series = sub["display_name"] if "display_name" in sub.columns else pd.Series([""]*len(sub), index=sub.index)
                sub = sub[sub["main_id"].astype(str).str.contains(q, case=False, na=False) |
                          dn_series.astype(str).str.contains(q, case=False, na=False)]
            return sub

        def _paged(df_sub):
            try:
                ps = int(ps_combo.get())
            except Exception:
                ps = 10; ps_combo.set("10")
            ps = max(1, ps)
            total = len(df_sub)
            total_pages = max(1, (total + ps - 1) // ps)
            try:
                cp = int(current_page_var.get())
            except Exception:
                cp = 1
            if cp < 1: cp = 1
            if cp > total_pages: cp = total_pages
            current_page_var.set(cp)
            start = (cp - 1) * ps
            end = min(start + ps, total)
            _update_page_widgets(total_pages, cp)
            return df_sub.iloc[start:end] if total > 0 else df_sub.iloc[0:0], (start, end, total, ps, cp, total_pages)

        def _next_label(cur):
            seq = ("No", "No+DN", "DN")
            try:
                i = seq.index(cur)
                return seq[(i+1)%3]
            except Exception:
                return "No"

        def _fmt_axes_arcmin(maj, minn):
            """Format 長径/短径 in arcmin.
            >=10 → integer; else → 1 decimal. Missing → '—'."""
            def _fmt(x):
                try:
                    if x is None:
                        return None
                    x = float(x)
                    if not (x == x):  # NaN
                        return None
                    return f"{int(round(x))}" if x >= 10 else f"{x:.1f}"
                except Exception:
                    return None
            a = _fmt(maj); b = _fmt(minn)
            if a is None and b is None:
                return "—"
            if a is None:
                a = "—"
            if b is None:
                b = "—"
            return f"{a}、{b}"

        def _update_rightmode_buttons():
            # Disable the active-mode button for clarity
            try:
                mode = self.rightcol_mode.get()
                if mode == 'name':
                    try:
                        btn_right_name.state(['disabled'])
                        btn_right_axes.state(['!disabled'])
                    except Exception:
                        pass
                else:
                    try:
                        btn_right_axes.state(['disabled'])
                        btn_right_name.state(['!disabled'])
                    except Exception:
                        pass
            except Exception:
                pass

        def set_rightcol_mode(mode: str):
            if mode not in ('name', 'axes'):
                return
            try:
                if self.rightcol_mode.get() == mode:
                    return
            except Exception:
                pass
            try:
                self.rightcol_mode.set(mode)
            except Exception:
                pass
            _update_rightmode_buttons()
            try:
                refresh_view()
            except Exception:
                pass


        def _clear_canvas():
            canvas.delete("all")
            draw_rows.clear()

        def _text(x, y, s, anchor="w", font=obj_font, fill="#111"):
            return canvas.create_text(x, y, text=str(s), anchor=anchor, font=font, fill=fill)

        def _rect(x0, y0, x1, y1, **kw):
            return canvas.create_rectangle(x0, y0, x1, y1, **kw)

        def _draw_header(x, y):
            x0 = x
            right_label = "表示名" if self.rightcol_mode.get() == 'name' else "長径、短径（分）、回転角度（度）"
            for key, label in (("#0",""), ("hex","色"), ("vis","表示"), ("num","No."),
                               ("name","Name"), ("type","TYPE"), ("label","ラベル"), ("display", right_label)):
                w = COL_W[key]
                _rect(x0, y, x0+w, y+HDR_H, fill="#f0f0f0", outline="#ddd")
                _text(x0+6, y+HDR_H//2, label, anchor="w", font=obj_font_b, fill="#333")
                x0 += w

        def _get_col_x():
            # compute left x of each column
            x = 2
            xs = {}
            for k in ("#0","hex","vis","num","name","type","label","display"):
                xs[k] = x
                x += COL_W[k]
            return xs

        def refresh_view():
            self._object_window_refresh = refresh_view
            nonlocal edit_entry
            if edit_entry and edit_entry.winfo_exists():
                try:
                    edit_entry.destroy()
                except Exception:
                    pass
            _clear_canvas()

            xs = _get_col_x()
            y = 2
            _draw_header(2, y)
            y += HDR_H

            sub_all = filtered_df()

            # --- Recompute No.: visible(ON) only, sequential, without changing row order ---
            if (renumber_enabled or getattr(self, 'pending_object_renumber', False) or not getattr(self, 'anno_numbers', {})):
                try:
                    new_no_map = {}
                    _cnt = 0
                    # Assign numbers in the order of filtered (pre-pagination) rows
                    for _r in sub_all.itertuples(index=False):
                        _mid = str(_r.main_id)
                        _var = self.visible_object_flags.get(_mid)
                        _on = _var.get() if _var is not None else True
                        if _on:
                            _cnt += 1
                            new_no_map[_mid] = _cnt
                        else:
                            new_no_map[_mid] = ""
                    self.anno_numbers = new_no_map
                    self.pending_object_renumber = False
                except Exception as _e:
                    # keep previous numbers if anything goes wrong
                    pass
            # フィルター適用後の全件（ページ分割前）のmain_id一覧を保持（「まとめて」時に使用）
            try:
                self._object_window_filtered_all_names = [r.main_id for r in sub_all.itertuples(index=False)]
            except Exception:
                self._object_window_filtered_all_names = []
            sub, pageinfo = _paged(sub_all)
            # 現在ページのmain_id一覧を保持（Selectスコープ用）
            try:
                self._object_window_current_names = [r.main_id for r in sub.itertuples(index=False)]
            except Exception:
                self._object_window_current_names = []
            start, end, total, ps, cp, total_pages = pageinfo

            # update count label (start-end / total items)
            start_disp = 0 if total == 0 else start + 1
            end_disp   = 0 if total == 0 else end
            try:
                count_var.set(f"{start_disp}-{end_disp} / {total} items")
            except Exception:
                count_var.set(f"{len(sub)} / {len(df)} items")

            # rows
            for i, r in enumerate(sub.itertuples(index=False)):
                nm = r.main_id
                vis = "ON" if self.visible_object_flags[nm].get() else "-"
                num = self.anno_numbers.get(str(nm), "")
                label_mode = self.label_mode_vars[nm].get()
                disp = self.display_name_vars[nm].get()
                hx = self.custom_object_colors.get(nm, "#FFFFFF")

                # background band
                _rect(0, y, max(sum(COL_W.values())+8, canvas.winfo_width()), y+ROW_H, fill="#ffffff", outline="#eee")

                # swatch
                swx0, swy0 = xs["#0"], y+6
                swx1, swy1 = swx0 + COL_W["#0"]-8, y+ROW_H-6
                _rect(swx0+10, swy0, swx0+26, swy1, fill=hx if str(hx).startswith("#") else f"#{hx}", outline="#aaa")

                # texts
                _text(xs["hex"]+6, y+ROW_H//2, hx)
                _text(xs["vis"]+6, y+ROW_H//2, vis)
                _text(xs["num"]+6, y+ROW_H//2, "" if num is None else num)
                _text(xs["name"]+6, y+ROW_H//2, nm)
                _text(xs["type"]+6, y+ROW_H//2, r.TYPE)
                _text(xs["label"]+6, y+ROW_H//2, label_mode)
                
                # Rightmost column value (表示名 or 長径、短径)
                _mode = None
                try:
                    _mode = self.rightcol_mode.get()
                except Exception:
                    _mode = 'name'
                if _mode == 'name':
                    right_val = disp  # current editable display name
                else:
                    # Prefer JP-named columns if present; fallback to galdim_* fields
                    try:
                        maj = sub.iloc[i]['長径'] if ('長径' in sub.columns) else getattr(r, 'galdim_majaxis', None)
                    except Exception:
                        maj = getattr(r, 'galdim_majaxis', None)
                    try:
                        minn = sub.iloc[i]['短径'] if ('短径' in sub.columns) else getattr(r, 'galdim_minaxis', None)
                    except Exception:
                        minn = getattr(r, 'galdim_minaxis', None)
                    # 角度（度）
                    try:
                        ang = sub.iloc[i]['回転角度'] if ('回転角度' in sub.columns) else getattr(r, 'galdim_angle', None)
                    except Exception:
                        ang = getattr(r, 'galdim_angle', None)
                    # 表示用フォーマット
                    def __fmt_arc(v):
                        try:
                            if v is None: return None
                            v = float(v)
                            if not (v == v): return None
                            return f"{int(round(v))}" if v >= 10 else f"{v:.1f}"
                        except Exception:
                            return None
                    def __fmt_deg(v):
                        try:
                            if v is None: return None
                            v = float(v)
                            if not (v == v): return None
                            return f"{int(round(v))}" if v >= 10 else f"{v:.1f}"
                        except Exception:
                            return None
                    a = __fmt_arc(maj); b = __fmt_arc(minn); d = __fmt_deg(ang)
                    if a is None: a = "—"
                    if b is None: b = "—"
                    if d is None: d = "—"
                    right_val = f"{a}、{b}、{d}"  # arcmin, arcmin, deg

                _text(xs["display"]+6, y+ROW_H//2, right_val)


                cells = {
                    "swatch": (xs["#0"], y, xs["#0"]+COL_W["#0"], y+ROW_H),
                    "hex":    (xs["hex"], y, xs["hex"]+COL_W["hex"], y+ROW_H),
                    "vis":    (xs["vis"], y, xs["vis"]+COL_W["vis"], y+ROW_H),
                    "label":  (xs["label"], y, xs["label"]+COL_W["label"], y+ROW_H),
                    "display":(xs["display"], y, xs["display"]+COL_W["display"], y+ROW_H),
                }
                draw_rows.append({"name": nm, "rowkey": sub.index[i], "bbox": (y, y+ROW_H), "cells": cells})
                y += ROW_H

            # scrollregion
            canvas.configure(scrollregion=(0, 0, sum(COL_W.values())+8, y+2))

        def _hit_test(ev_x, ev_y):
            # return (index, cellkey)
            for i, row in enumerate(draw_rows):
                y0,y1 = row["bbox"]
                if y0 <= ev_y <= y1:
                    for key, (x0,y0c,x1,y1c) in row["cells"].items():
                        if x0 <= ev_x <= x1 and y0c <= ev_y <= y1c:
                            return i, key
                    return i, None
            return None, None

        def _open_color_for(name):
            try:
                initial = self.custom_object_colors.get(name, "#FFFFFF")
                rgb, hx = colorchooser.askcolor(initialcolor=initial, parent=window, title=f"Color for {name}")
                if hx:
                    self.custom_object_colors[name] = hx
                    refresh_view()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to pick color:\\n{e}")

        def _begin_edit_display(name, cell):
            nonlocal edit_entry
            # place Entry over the display cell rect
            for row in draw_rows:
                if row["name"] == name:
                    x0,y0,x1,y1 = row["cells"]["display"]
                    if edit_entry and edit_entry.winfo_exists():
                        try: edit_entry.destroy()
                        except Exception: pass
                    edit_entry = ttk.Entry(canvas, style="Obj.TEntry")
                    edit_entry.place(x=x0+2, y=y0+2, width=(x1-x0-4), height=(y1-y0-4))
                    edit_entry.insert(0, self.display_name_vars[name].get())
                    edit_entry.focus_set()
                    def commit(*_):
                        self.display_name_vars[name].set(edit_entry.get())
                        try:
                            edit_entry.destroy()
                        except Exception:
                            pass
                        refresh_view()
                    edit_entry.bind("<Return>", commit)
                    edit_entry.bind("<Escape>", lambda *_: (edit_entry.destroy(), refresh_view()))
                    edit_entry.bind("<FocusOut>", commit)
                    break

        def _begin_edit_dispname(name, rowkey=None):
            """表示名を編集する小ダイアログ（クリックした行のみ更新）。タイトルに天体名を表示。"""
            import tkinter as tk
            from tkinter import ttk, messagebox
            # 既存表示名とタイトル表示名
            try:
                current_disp = self.display_name_vars.get(name).get()
            except Exception:
                current_disp = ""
            title_name = current_disp if (isinstance(current_disp, str) and current_disp.strip()) else str(name)
            tl = tk.Toplevel(window)
            tl.title(f"編集中の天体：{name}")
            tl.transient(window)
            try:
                tl.wm_attributes("-topmost", True)
            except Exception:
                pass
            frm = ttk.Frame(tl, padding=8); frm.pack(fill="both", expand=True)
            ttk.Label(frm, text="現在の表示名：", style="Obj.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(frm, text=current_disp, style="Obj.TLabel").grid(row=0, column=1, sticky="w")
            ttk.Label(frm, text="表示名", style="Obj.TLabel").grid(row=1, column=0, sticky="w", pady=(8,2))
            ent = ttk.Entry(frm, style="Obj.TEntry", width=44)
            ent.grid(row=1, column=1, sticky="ew", padx=(8,0), pady=(8,2))
            frm.grid_columnconfigure(1, weight=1)
            ent.insert(0, current_disp)
            def _commit(*_):
                val = ent.get().strip()
                # 空文字は許可しない（空の場合は main_id を採用）
                if not val:
                    val = str(name)
                # StringVar を更新
                try:
                    self.display_name_vars[name].set(val)
                except Exception:
                    pass
                # df / df_all にも極力反映
                try:
                    nonlocal df
                except Exception:
                    pass
                # df 側
                try:
                    idx2 = None
                    if 'df' in locals():
                        if rowkey is not None and rowkey in df.index:
                            idx2 = rowkey
                        else:
                            idxs = df.index[df['main_id'].astype(str)==str(name)]
                            if len(idxs)>0:
                                idx2 = idxs[0]
                        if idx2 is not None:
                            if 'display_name' not in df.columns:
                                df['display_name'] = None
                            if '表示名' not in df.columns:
                                # 日本語列は存在しない環境もあるため、無理に追加しない方針だが、
                                # 他の箇所と合わせ存在しなければ追加しておく
                                df['表示名'] = None
                            df.at[idx2, 'display_name'] = val
                            if '表示名' in df.columns:
                                df.at[idx2, '表示名'] = val
                except Exception:
                    pass
                # df_all 側
                try:
                    if hasattr(self, 'df_all') and self.df_all is not None:
                        j = None
                        try:
                            if rowkey is not None and rowkey in self.df_all.index:
                                j = rowkey
                        except Exception:
                            j = None
                        if j is None:
                            try:
                                idall = self.df_all.index[self.df_all['main_id'].astype(str)==str(name)]
                                if len(idall)>0:
                                    j = idall[0]
                            except Exception:
                                j = None
                        if j is not None:
                            if 'display_name' not in self.df_all.columns:
                                self.df_all['display_name'] = None
                            if '表示名' not in self.df_all.columns:
                                self.df_all['表示名'] = None
                            self.df_all.at[j, 'display_name'] = val
                            if '表示名' in self.df_all.columns:
                                self.df_all.at[j, '表示名'] = val
                except Exception:
                    pass
                try:
                    tl.destroy()
                except Exception:
                    pass
                refresh_view()
            def _cancel(*_):
                try:
                    tl.destroy()
                except Exception:
                    pass
                refresh_view()
            btns = ttk.Frame(frm); btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10,0))
            ttk.Button(btns, text="OK", style="Obj.TButton", command=_commit).pack(side="right", padx=(6,0))
            ttk.Button(btns, text="キャンセル", style="Obj.TButton", command=_cancel).pack(side="right")
            ent.focus_set()
            try:
                tl.grab_set()
            except Exception:
                pass
            tl.wait_window()

        def _begin_edit_axes(name, cell, rowkey=None):

            """長径・短径（分）を編集する小ダイアログ（クリックした行のみ更新）。"""

            # 既存の display セル座標（ダイアログ位置の参考）

            x0=y0=x1=y1=0

            for row in draw_rows:

                if row.get("name") == name:

                    x0,y0,x1,y1 = row["cells"]["display"]

                    break

        

            # 現在値の取得（rowkey優先。無ければ main_id 一致の先頭）

            try:

                rowdf = None

                if rowkey is not None and rowkey in df.index:

                    rowdf = df.loc[[rowkey]]

                if rowdf is None or rowdf.empty:

                    rowdf = df[df["main_id"].astype(str) == str(name)]

                if not rowdf.empty:

                    row0 = rowdf.iloc[0]

                    cur_maj = row0["長径"] if "長径" in rowdf.columns else row0.get("galdim_majaxis", None)

                    cur_min = row0["短径"] if "短径" in rowdf.columns else row0.get("galdim_minaxis", None)

                    cur_ang = row0["回転角度"] if "回転角度" in rowdf.columns else row0.get("galdim_angle", None)
                else:

                    cur_maj = None; cur_min = None; cur_ang = None

            except Exception:

                cur_maj = None; cur_min = None; cur_ang = None

        

            tl = tk.Toplevel(canvas)

                        # タイトルは表示名があれば表示名、なければ main_id
            try:
                disp_title = self.display_name_vars.get(name).get()
            except Exception:
                disp_title = str(name)
            if not isinstance(disp_title, str) or not disp_title.strip():
                disp_title = str(name)
            tl.title(f"編集中：{str(name)}")

            tl.transient(canvas.winfo_toplevel())

            try:

                tl.resizable(False, False)

            except Exception:

                pass

        

            # 画面内に置く（大きくずれないように）

            try:

                cx = canvas.winfo_rootx() + x0 + 20

                cy = canvas.winfo_rooty() + y0 + 20

                tl.geometry(f"+{max(0,cx)}+{max(0,cy)}")

            except Exception:

                pass

        

            frm = ttk.Frame(tl, padding=8); frm.pack(fill="both", expand=True)

                        # 1行目：現在の数値の提示
            def _fmtv(v):
                try:
                    if v is None:
                        return "—"
                    fv = float(v)
                    return str(int(round(fv))) if fv >= 10 else f"{fv:.1f}"
                except Exception:
                    return "—"
            cur_summary = f"{_fmtv(cur_maj)}、{_fmtv(cur_min)}、{_fmtv(cur_ang)}"
            ttk.Label(frm, text="円の半径は長径を使用しています。", style="Obj.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0,4))
            ttk.Label(frm, text="現在の数値：", style="Obj.TLabel").grid(row=1, column=0, sticky="w", pady=(0,6))
            ttk.Label(frm, text=cur_summary, style="Obj.TLabel").grid(row=1, column=1, sticky="w", pady=(0,6))

        

            ttk.Label(frm, text="長径（分）", style="Obj.TLabel").grid(row=2, column=0, sticky="e", padx=(0,6))

            ent_maj = ttk.Entry(frm, width=12, style="Obj.TEntry"); ent_maj.grid(row=2, column=1, sticky="w")

            ttk.Label(frm, text="短径（分）", style="Obj.TLabel").grid(row=3, column=0, sticky="e", padx=(0,6), pady=(6,0))

            ent_min = ttk.Entry(frm, width=12, style="Obj.TEntry"); ent_min.grid(row=3, column=1, sticky="w", pady=(6,0))

            ttk.Label(frm, text="回転角度（度）", style="Obj.TLabel").grid(row=4, column=0, sticky="e", padx=(0,6), pady=(6,0))
            ent_ang = ttk.Entry(frm, width=12, style="Obj.TEntry"); ent_ang.grid(row=4, column=1, sticky="w", pady=(6,0))

        

            def _prefill(e, v):

                try:

                    if v is None: return

                    fv = float(v)

                    if fv >= 10: e.insert(0, str(int(round(fv))))

                    else: e.insert(0, f"{fv:.1f}")

                except Exception:

                    pass

        

            _prefill(ent_maj, cur_maj)

            _prefill(ent_min, cur_min)
            _prefill(ent_ang, cur_ang)

        

            btns = ttk.Frame(frm); btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(10,0))

            def _commit():

                def _to_float(s):

                    s = s.strip()

                    if s == "":

                        return None

                    try:

                        v = float(s)

                        if v < 0: return None

                        return v

                    except Exception:

                        return None

        

                maj = _to_float(ent_maj.get())

                minn = _to_float(ent_min.get())
                ang = _to_float(ent_ang.get())

        

                # df 更新（クリック行のみ）

                try:

                    idx = None

                    if rowkey is not None and rowkey in df.index:

                        idx = rowkey

                    else:

                        idxs = df.index[df["main_id"].astype(str) == str(name)]

                        if len(idxs) > 0:

                            idx = idxs[0]

                    if idx is not None:

                        if "長径" not in df.columns:

                            df["長径"] = None

                        if "短径" not in df.columns:

                            df["短径"] = None

                        df.at[idx, "長径"] = maj

                        df.at[idx, "短径"] = minn


                        if "galdim_majaxis" in df.columns:

                            df.at[idx, "galdim_majaxis"] = maj


                        if "galdim_minaxis" in df.columns:

                            df.at[idx, "galdim_minaxis"] = minn


                        if "回転角度" not in df.columns:

                            df["回転角度"] = None


                        if "galdim_angle" in df.columns:

                            df.at[idx, "galdim_angle"] = ang


                        if "回転角度" in df.columns:

                            df.at[idx, "回転角度"] = ang

                except Exception:

                    pass

        

                # self.df_all も同じ index があればそれを更新。無ければ main_idで先頭一致を更新

                try:

                    if hasattr(self, "df_all") and self.df_all is not None:

                        j = None

                        try:

                            if rowkey is not None and rowkey in self.df_all.index:

                                j = rowkey

                        except Exception:

                            j = None

                        if j is None:

                            idall = self.df_all.index[self.df_all["main_id"].astype(str) == str(name)]

                            if len(idall) > 0:

                                j = idall[0]

                        if j is not None:

                            if "長径" not in self.df_all.columns:

                                self.df_all["長径"] = None

                            if "短径" not in self.df_all.columns:

                                self.df_all["短径"] = None

                            self.df_all.at[j, "長径"] = maj

                            self.df_all.at[j, "短径"] = minn

                            
                            if "回転角度" not in self.df_all.columns:
                                self.df_all["回転角度"] = None
                            if "galdim_majaxis" in self.df_all.columns:

                                self.df_all.at[j, "galdim_majaxis"] = maj

                            if "galdim_minaxis" in self.df_all.columns:

                                self.df_all.at[j, "galdim_minaxis"] = minn

                
                            if "galdim_angle" in self.df_all.columns:
                                self.df_all.at[j, "galdim_angle"] = ang
                            if "回転角度" in self.df_all.columns:
                                self.df_all.at[j, "回転角度"] = ang
                except Exception:

                    pass

        

                try:

                    tl.destroy()

                except Exception:

                    pass

                try:

                    refresh_view()

                except Exception:

                    pass

        

            def _cancel():

                try: tl.destroy()

                except Exception: pass

        

            ttk.Button(btns, text="OK", style="Obj.TButton", command=_commit).pack(side="right", padx=(6,0))

            ttk.Button(btns, text="キャンセル", style="Obj.TButton", command=_cancel).pack(side="right")

        

            ent_maj.focus_set()

            tl.grab_set()

            tl.wait_window()


        def _on_click(ev):
            nonlocal renumber_enabled
            idx, cell = _hit_test(ev.x, ev.y)
            if idx is None:
                return
            name = draw_rows[idx]["name"]
            if cell == "vis":
                cur = self.visible_object_flags[name].get()
                self.visible_object_flags[name].set(not cur)
                renumber_enabled = False
                refresh_view()
            elif cell == "label":
                cur = self.label_mode_vars[name].get()
                nxt = _next_label(cur)
                self.label_mode_vars[name].set(nxt)
                self.object_label_mode_overrides[name] = nxt
                refresh_view()

        def _on_double(ev):
            idx, cell = _hit_test(ev.x, ev.y)
            if idx is None:
                return
            name = draw_rows[idx]["name"]
            if cell in ("swatch","hex"):
                _open_color_for(name)
            elif cell == "display":
                try:
                    if self.rightcol_mode.get() == 'name':
                        _begin_edit_dispname(name, rowkey=draw_rows[idx].get("rowkey"))
                    else:
                        _begin_edit_axes(name, cell, draw_rows[idx].get("rowkey"))
                except Exception:
                    pass

        canvas.bind("<Button-1>", _on_click)
        canvas.bind("<Double-1>", _on_double)

        # --- CSV Export/Replace ---


        def do_export_csv():
            import csv
            # Save as UTF-8 with BOM for Excel compatibility
            path = filedialog.asksaveasfilename(title="Export CSV", defaultextension=".csv",
                                                    filetypes=[("CSV", "*.csv")])
            if not path:
                return
            # Header: Name/TYPE (EN), others in JP; display_name at the far right
            header = ["Name","TYPE","表示","色","赤経","赤緯","長径（直径）","短径","回転角度","ラベル","表示名"]
            try:
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(header)
                    # df is captured from outer scope; other values come from the current UI state dicts
                    for row in df.itertuples(index=False):
                        name = getattr(row, "main_id")
                        TYPE = getattr(row, "TYPE")
                        ra = getattr(row, "ra")
                        dec = getattr(row, "dec")
                        maj = getattr(row, "galdim_majaxis")
                        minu = getattr(row, "galdim_minaxis")
                        ang = getattr(row, "galdim_angle")
                        # UI-bound fields (with fallbacks)
                        visible_var = self.visible_object_flags.get(name)
                        visible = bool(visible_var.get()) if visible_var is not None else False
                        color = self.custom_object_colors.get(name)
                        if not color:
                            try:
                                color = self.catalogs[TYPE].color
                            except Exception:
                                color = "#FFFFFF"
                        label_var = self.label_mode_vars.get(name)
                        label_mode = label_var.get() if label_var is not None else "Defaults"
                        disp_var = self.display_name_vars.get(name)
                        display_name = disp_var.get() if disp_var is not None else str(name)
                        w.writerow([name, TYPE, visible, color, ra, dec, maj, minu, ang, label_mode, display_name])
                messagebox.showinfo("Export", f"Exported successfully:\n{path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export CSV:\n{e}")

        def do_import_csv():
            import csv
            from tkinter import filedialog, messagebox
            import pandas as pd, numpy as np
            
            def _to_float_axes(s):
                try:
                    if s is None:
                        return float("nan")
                    s = str(s).strip()
                    if s == "":
                        return float("nan")
                    return float(s)
                except Exception:
                    return float("nan")
    

            path = filedialog.askopenfilename(
                title="Replace all object settings from CSV（日本語/英語どちらも可）",
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv")]
            )
            if not path:
                return

            
            KEYS = {
                "main_id": ["main_id", "天体ID", "ID", "名前", "Name"],
                "TYPE":           ["TYPE", "Catalog", "catalog", "カタログ"],
                "visible":        ["visible", "表示"],
                "color":          ["color", "色"],
                "display_name":   ["display_name", "表示名", "DN", "dn"],
                "label_mode":     ["label_mode", "ラベル", "label", "LABEL"],
                "ra": ["ra","RA","赤経"],
                "dec": ["dec","DEC","赤緯"],
                "galdim_majaxis": ["galdim_majaxis", "直径[分]", "直径(分)", "diameter", "直径", "長径", "長径（分）", "長径(分)", "長径（直径）"],
                "galdim_minaxis": ["galdim_minaxis", "短径", "短径（分）", "短径(分)"],
                "galdim_angle":   ["galdim_angle", "PA", "pa", "回転角度", "回転角度（度）", "回転角度(度)"]
            }
            def pick(d, keys, default=None):
                for k in keys:
                    if k in d and str(d[k]).strip() != "":
                        return d[k]
                return default

            def _to_float(x):
                try:
                    v = float(x)
                    if v == float("inf") or v == float("-inf"):
                        return float("nan")
                    return v
                except Exception:
                    return float("nan")

            def _to_bool(s, default=False):
                if s is None:
                    return default
                s = str(s).strip().lower()
                return s in ("true","1","t","yes","y","on","はい")

            try:
                # Reset per-object state
                self.visible_object_flags.clear()
                self.custom_object_colors.clear()
                self.display_name_vars = {}
                self.object_label_mode_overrides = {}
                self.label_mode_vars = {}

                new_rows = []
                with open(path, newline='', encoding='utf-8-sig') as f:
                    r = csv.DictReader(f)
                    for rec in r:
                        main_id = pick(rec, KEYS["main_id"])
                        if not main_id:
                            continue
                        ctype   = pick(rec, KEYS["TYPE"]) or "CSV"
                        visible = _to_bool(pick(rec, KEYS["visible"]), default=True)
                        color   = pick(rec, KEYS["color"]) or "#FFFFFF"
                        disp    = pick(rec, KEYS["display_name"]) or main_id

                        ra  = _to_float(pick(rec, KEYS["ra"]))
                        dec = _to_float(pick(rec, KEYS["dec"]))

                        maj = _to_float_axes(pick(rec, KEYS["galdim_majaxis"]))
                        minr = _to_float_axes(pick(rec, KEYS["galdim_minaxis"]))
                        pa = _to_float_axes(pick(rec, KEYS["galdim_angle"]))

                        label = pick(rec, KEYS["label_mode"]) or "No"

                        self.visible_object_flags[main_id] = tk.BooleanVar(value=visible)
                        self.custom_object_colors[main_id] = color
                        self.display_name_vars[main_id]    = tk.StringVar(value=disp)
                        self.label_mode_vars[main_id]      = tk.StringVar(value=label)
                        self.object_label_mode_overrides[main_id] = label

                        __row_idx = len(new_rows)
                        new_rows.append({
                            "main_id": main_id,
                            "TYPE": ctype,
                            "ra": ra, "dec": dec,
                            "galdim_majaxis": maj, "galdim_minaxis": minr, "galdim_angle": pa,
                            "長径": maj, "短径": minr, "回転角度": pa,
                            "display_name": disp,
                            "visible": visible,
                            "color": color,
                            "label_mode": label,
                            "csv_order": __row_idx
                        })

                # rebuild df (preserve order as CSV)
                df_new = pd.DataFrame(new_rows)
                if not df_new.empty:
                    nonlocal_df = df_new
                else:
                    nonlocal_df = df

                # GPT PATCH: sync df_all & refresh object view
                # GPT PATCH: sync df_all & refresh object view
                try:
                    self.df_all = nonlocal_df.copy()
                    # Ensure CSV view mode so Object window reopens from CSV state
                    try:
                        self._view_mode = "csv"
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    refresh_view()
                except Exception:
                    pass

                # 再オープン（is_reapply=True）
                try:
                    if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
                        self.object_control_window.destroy()
                except Exception:
                    pass
                self.show_object_selection_dialog(self.df_all.copy(), is_reapply=True)

                # 可視一覧とDefaultsスナップショット更新
                try:
                    self.visible_object_names = [name for name, var in self.visible_object_flags.items() if var.get()]
                    self._object_defaults_snapshot = {name: var.get() for name, var in self.visible_object_flags.items()}
                except Exception:
                    pass

                try:
                    window.title(f"Customize Objects (from {os.path.basename(path)})")
                except Exception:
                    pass

            except Exception as e:
                messagebox.showerror("Error", f"Failed to replace from CSV:\\n{e}")

        # 反映系
        def reapply_with_confirmation():
            self.object_label_mode_overrides = {n: v.get() for n, v in self.label_mode_vars.items() if v.get().strip()}
            self.visible_object_names = [name for name, var in self.visible_object_flags.items() if var.get()]
            self.apply_changes(from_cli=False, is_reapply=True)
            refresh_view()

        # Bottom buttons
        # Bottom buttons
        bottom = ttk.Frame(window); bottom.pack(side="bottom", fill="x", padx=8, pady=6)

        try:
            _apply_fixed_table_height()
        except Exception:
            pass
        ttk.Button(bottom, text="Close", style="Obj.TButton", command=window.destroy).pack(side="left", padx=4)
        ttk.Button(bottom, text="ReApply", style="Obj.TButton", command=reapply_with_confirmation).pack(side="left", padx=8)

        # Inserted: specimen & combined
        self.obj_btn_specimen = ttk.Button(bottom, text="天体標本作成", style="Obj.TButton", command=self._on_click_specimen)
        self.obj_btn_specimen.pack(side="left", padx=6)
        self.obj_btn_make_combined = ttk.Button(bottom, text="結合画像作成", style="Obj.TButton", state=tk.DISABLED, command=self._on_click_make_combined)
        self.obj_btn_make_combined.pack(side="left", padx=6)

        # Apply sizing so 11 rows are visible and all buttons remain visible
        try:
            _apply_canvas_min_height()
        except Exception:
            pass

        # after : C O T N
        ttk.Label(bottom, text="after :", style="Obj.TLabel").pack(side="left", padx=(10, 4))
        ttk.Button(bottom, text="O", width=2, style="Obj.TButton", command=lambda: self.switch_image("overlay")).pack(side="left", padx=2)
        self.obj_btn_t = ttk.Button(bottom, text="T", width=3, style="Obj.TButton", command=self._on_click_cycled_table)
        self.obj_btn_t.pack(side="left", padx=2)
        self.obj_btn_c = ttk.Button(bottom, text="C", width=3, style="Obj.TButton", command=self._on_click_cycled_combined)
        self.obj_btn_c.pack(side="left", padx=2)
        try:
            self._update_ct_labels()
        except Exception:
            pass
        ttk.Button(bottom, text="N", width=2, style="Obj.TButton", command=lambda: self.switch_image("original")).pack(side="left", padx=2)

        # ページサイズ変更、前後移動、フィルタ/カタログ変更時
        def _on_page_size_change(_evt=None):
            current_page_var.set(1)
            refresh_view()
        def _go_prev():
            cp = max(1, int(current_page_var.get()) - 1)
            current_page_var.set(cp)
            refresh_view()
        def _go_next():
            current_page_var.set(int(current_page_var.get()) + 1)
            refresh_view()
        def _on_filter_or_cat_change(*_):
            current_page_var.set(1)
            refresh_view()

        ps_combo.bind("<<ComboboxSelected>>", _on_page_size_change)
        prev_btn.configure(command=_go_prev)
        next_btn.configure(command=_go_next)
        try:
            filter_var.trace_add("write", _on_filter_or_cat_change)
        except Exception:
            pass
        try:
            cat_box.bind("<<ComboboxSelected>>", _on_filter_or_cat_change)
        except Exception:
            pass

        # 初期描画
        refresh_view()
        window.update_idletasks()
        try:
            window.minsize(window.winfo_width(), window.winfo_height())
        except Exception:
            pass
        window.deiconify()

    def _select_objects(self, state: bool):
        # スコープ判定：「まとめて」未チェック→現在表示中のみ（現在ページ）／チェック→フィルタ適用後の全件
        names = None
        try:
            bulk = bool(getattr(self, "object_select_scope_var", None) and self.object_select_scope_var.get())
        except Exception:
            bulk = False
        if bulk:
            names = list(getattr(self, "_object_window_filtered_all_names", []) or [])
            if not names:
                dfw = getattr(self, "_object_window_df", None)
                catv = getattr(self, "_object_window_cat_var", None)
                if dfw is not None:
                    try:
                        cat = catv.get() if catv is not None else "All"
                    except Exception:
                        cat = "All"
                    if cat and cat != "All" and "TYPE" in dfw.columns:
                        names = [x for x in dfw.loc[dfw["TYPE"]==cat, "main_id"].astype(str).tolist()]
                    else:
                        names = [x for x in dfw["main_id"].astype(str).tolist()]
        if not names:
            names = list(getattr(self, "_object_window_current_names", []))
            if not names:
                names = list(self.visible_object_flags.keys())
        for name in names:
            if name in self.visible_object_flags:
                self.visible_object_flags[name].set(state)

    def _reset_object_defaults(self):
        # スコープ判定
        try:
            bulk = bool(getattr(self, "object_select_scope_var", None) and self.object_select_scope_var.get())
        except Exception:
            bulk = False
        if bulk:
            names = list(getattr(self, "_object_window_filtered_all_names", []) or [])
            if not names:
                dfw = getattr(self, "_object_window_df", None)
                catv = getattr(self, "_object_window_cat_var", None)
                names = []
                if dfw is not None:
                    try:
                        cat = catv.get() if catv is not None else "All"
                    except Exception:
                        cat = "All"
                    if cat and cat != "All" and "TYPE" in dfw.columns:
                        names = [x for x in dfw.loc[dfw["TYPE"]==cat, "main_id"].astype(str).tolist()]
                    else:
                        names = [x for x in dfw["main_id"].astype(str).tolist()]
        else:
            names = list(getattr(self, "_object_window_current_names", []))
            if not names:
                names = list(self.visible_object_flags.keys())

        if getattr(self, "_object_defaults_snapshot", None):
            for name in names:
                if name in self.visible_object_flags and name in self._object_defaults_snapshot:
                    self.visible_object_flags[name].set(self._object_defaults_snapshot[name])
            return

        for name in names:
            if name not in self.visible_object_flags:
                continue
            default = False
            try:
                if hasattr(self, "df_all") and self.df_all is not None:
                    row = self.df_all[self.df_all["main_id"] == name]
                    if not row.empty:
                        ctype = row.iloc[0]["TYPE"] if "TYPE" in row.columns else None
                        if ctype in self.catalogs:
                            default = self.catalogs[ctype].selection_default
            except Exception:
                pass
            self.visible_object_flags[name].set(default)

    def _mass_set_label_mode(self, mode):
            """スコープに対してラベル(表示名/番号)モードを一括設定。mode=Noneでデフォルトに戻す。"""
            # スコープ（対象トグル）判定
            try:
                bulk = bool(getattr(self, "object_select_scope_var", None) and self.object_select_scope_var.get())
            except Exception:
                bulk = False
            names = []
            if bulk:
                names = list(getattr(self, "_object_window_filtered_all_names", []) or [])
                if not names:
                    dfw = getattr(self, "_object_window_df", None)
                    catv = getattr(self, "_object_window_cat_var", None)
                    if dfw is not None:
                        try:
                            cat = catv.get() if catv is not None else "All"
                        except Exception:
                            cat = "All"
                        if cat and cat != "All" and "TYPE" in dfw.columns:
                            names = [x for x in dfw.loc[dfw["TYPE"]==cat, "main_id"].astype(str).tolist()]
                        else:
                            names = [x for x in dfw["main_id"].astype(str).tolist()]
            else:
                names = list(getattr(self, "_object_window_current_names", []))
                if not names:
                    names = list(self.visible_object_flags.keys())

            # 設定
            valid = {"No+DN","DN","No"}
            for name in names:
                if name not in self.label_mode_vars:
                    continue
                try:
                    if mode in valid:
                        self.label_mode_vars[name].set(mode)
                        self.object_label_mode_overrides[name] = mode
                    else:
                        # デフォルトへ戻す（override解除→デフォルト再計算）
                        if name in self.object_label_mode_overrides:
                            try:
                                del self.object_label_mode_overrides[name]
                            except Exception:
                                pass
                        default_mode = None
                        try:
                            snap = getattr(self, "_label_defaults_snapshot", None)
                            if isinstance(snap, dict) and str(name) in snap:
                                default_mode = snap[str(name)]
                        except Exception:
                            default_mode = None
                        if not default_mode:
                            try:
                                if hasattr(self, "df_all") and self.df_all is not None:
                                    rowdf = self.df_all[self.df_all["main_id"].astype(str) == str(name)]
                                    if not rowdf.empty:
                                        row = next(iter(rowdf.itertuples(index=False)))
                                        default_mode = self._compute_default_label_mode_for_row(row)
                            except Exception:
                                pass
                        if not default_mode:
                            default_mode = "No"
                        self.label_mode_vars[name].set(default_mode)
                except Exception:
                    pass

    def select_default(self):
            for key, value in self.catalogs.items():
                value.checkbox_var.set(value.selection_default)
    
    def _update_alpha_label(self, *args):
            self.overlay_alpha_label.config(text=f"{self.overlay_alpha_var.get():.2f}")
    
    def load_config_file(self):
            config_dir = self.siril.get_siril_configdir()
            config_file_path = os.path.join(config_dir, CONFIG_FILENAME)
            logo_path = None
            overlay_alpha = 0.6
            overlay_type = "circles"
            selected_catalogs = None
            if os.path.isfile(config_file_path):
                with open(config_file_path, 'r') as file:
                    lines = [ln.rstrip("\n") for ln in file.readlines()]
    
                # 0..3: 既存
                if len(lines) > 0:
                    lp = lines[0].strip()
                    logo_path = lp if os.path.isfile(lp) else None
                if len(lines) > 1:
                    try:
                        overlay_alpha = float(lines[1].strip())
                    except Exception:
                        overlay_alpha = 0.6
                if len(lines) > 2:
                    overlay_type = lines[2].strip()
                if len(lines) > 3:
                    selected_catalogs = lines[3].strip()
    
                # 4..6: カスタムCSV
                self.custom_catalog_files, __has_stars_line = _load_custom_csv_paths_from_lines(lines)
                off = 1 if __has_stars_line else 0
                # 7..10: フォールバック設定
                try:
                    if len(lines) > 7:  self.size_fallback_mode = lines[7 + off].strip() or "default"
                    if len(lines) > 8:  self.size_fallback_radius_px = max(1, int(float(lines[8 + off].strip() or "60")))
                    if len(lines) > 9:  self.size_fallback_line_len_px = max(1, int(float(lines[9 + off].strip() or "60")))
                    if len(lines) > 10: self.size_fallback_center_gap_px = max(1, int(float(lines[10 + off].strip() or "40")))
                except Exception:
                    pass
    
                # 11..12: 番号表示設定（pxで保存：互換維持）
                try:
                    if len(lines) > 11: self.label_number_mode = (lines[11 + off].strip() or "default")
                    if len(lines) > 12: self.label_threshold_px = max(1, int(float(lines[12 + off].strip() or "200")))
                except Exception:
                    self.label_number_mode = "default"
                    self.label_threshold_px = 200
    
                # 13: サイズ情報無し天体の表示名モード
                try:
                    if len(lines) > 13: self.size_missing_label_mode = (lines[13 + off].strip() or "num")
                except Exception:
                    self.size_missing_label_mode = "num"
    
                # 14: 直径[分]のUI入力値（新規／任意）
                try:
                    if len(lines) > 14 and lines[14 + off].strip() != "":
                        self.label_threshold_arcmin_ui = float(lines[14 + off].strip())
                    else:
                        self.label_threshold_arcmin_ui = None
                except Exception:
                    self.label_threshold_arcmin_ui = None
    
                # 15: 最後にApplyしたときのピクセルスケール(arcmin/px) - 任意
                try:
                    if len(lines) > 15 and lines[15 + off].strip() != "":
                        self.saved_arcmin_per_px = float(lines[15 + off].strip())
                    else:
                        self.saved_arcmin_per_px = None
                except Exception:
                    self.saved_arcmin_per_px = None
    
            # --- specimen settings load (added) ---
            try:
                def _get_int(name, default):
                    for ln in lines:
                        if ln.startswith(name + "="):
                            try:
                                return int(ln.split("=",1)[1].strip())
                            except Exception:
                                return default
                    return default
                def _get_bool(name, default):
                    v = _get_int(name, 1 if default else 0)
                    return bool(v)
                self.specimen_use_defaults = _get_bool('specimen_use_defaults', getattr(self, 'specimen_use_defaults', True))
                self.specimen_max_per_page = _get_int('specimen_max_per_page', getattr(self, 'specimen_max_per_page', 12))
                self.specimen_max_per_row  = _get_int('specimen_max_per_row', getattr(self, 'specimen_max_per_row', 4))
            except Exception:
                pass
            return logo_path, overlay_alpha, overlay_type, selected_catalogs


    def save_config_file(self, logo_path, overlay_alpha, overlay_type, selected_catalogs=None):
                config_dir = self.siril.get_siril_configdir()
                config_file_path = os.path.join(config_dir, CONFIG_FILENAME)
                try:
                    with open(config_file_path, 'w') as file:
                        # 0..3: 既存
                        file.write((logo_path or "") + "\n")
                        file.write(f"{overlay_alpha:.2f}\n")
                        file.write(overlay_type + "\n")
                        file.write((str(selected_catalogs) if selected_catalogs is not None else "") + "\n")
                        # 4..7: カスタムCSV（新フォーマット: Stars, M, IC, NGC）
                        file.write((self.custom_catalog_files.get('Stars', '') or "") + "\n")
                        file.write((self.custom_catalog_files.get('M', '') or "") + "\n")
                        file.write((self.custom_catalog_files.get('IC', '') or "") + "\n")
                        file.write((self.custom_catalog_files.get('NGC', '') or "") + "\n")
                        # 7..10: フォールバック設定
                        file.write((self.size_fallback_mode or "default") + "\n")
                        file.write(str(int(self.size_fallback_radius_px)) + "\n")
                        file.write(str(int(self.size_fallback_line_len_px)) + "\n")
                        file.write(str(int(self.size_fallback_center_gap_px)) + "\n")
                        # 11..12: 通常の番号表示設定（pxで保存：互換維持）
                        file.write((self.label_number_mode or "default") + "\n")
                        file.write(str(int(self.label_threshold_px)) + "\n")
                        # 13: サイズ情報無し天体の表示名モード
                        file.write((self.size_missing_label_mode or "num") + "\n")
                        # 14: 直径[分]のUI入力値（custom時のみ保存／無指定は空行）
                        file.write((("" if getattr(self, "label_threshold_arcmin_ui", None) is None else f"{float(self.label_threshold_arcmin_ui):.6f}") ) + "\n")
                        # 15: 最後にApplyしたときのピクセルスケール(arcmin/px) - 任意（無ければ空行）
                        file.write((("" if getattr(self, "saved_arcmin_per_px", None) is None else f"{float(self.saved_arcmin_per_px):.6f}") ) + "\n")
    
                        # 14: 直径[分]のUI入力値（custom時のみ保存、その他は空行）
                        if (self.label_number_mode == "custom") and (self.label_threshold_arcmin_ui is not None):
                            file.write(str(self.label_threshold_arcmin_ui) + "\n")
                        else:
                            file.write("\n")
    
                        # 15: 最後にApplyしたときのピクセルスケール(arcmin/px) - 任意
                        file.write((f"{self.saved_arcmin_per_px:.6f}" if getattr(self, "saved_arcmin_per_px", None) else "") + "\n")
                        # --- specimen settings (appended as key=value) ---
                        try:
                            file.write(f"specimen_use_defaults={int(getattr(self, 'specimen_use_defaults', True))}\n")
                            file.write(f"specimen_max_per_page={int(getattr(self, 'specimen_max_per_page', 25))}\n")
                            file.write(f"specimen_max_per_row={int(getattr(self, 'specimen_max_per_row', 5))}\n")
                        except Exception:
                            pass

    
                except Exception as e:
                    print(f"Error saving config file: {str(e)}")
    
def main():
    parser = argparse.ArgumentParser(description="Annotations script")
    # 既存
    parser.add_argument("-output", type=str, default=None, help="Output file name")
    parser.add_argument("-title", type=str, default="", help="Optional image title")
    parser.add_argument("-logo_path", type=str, default="", help="Optional logo image path")
    parser.add_argument("-overlay_alpha", type=float, default=0.6, help="Optional overlay alpha value")
    parser.add_argument("-overlay_type", type=str, default="circles",
                            choices=["circles", "boxes", "ellipses"],
                            help="Type of annotation overlays to draw")

    # フォールバック制御（CLI）
    parser.add_argument("-fallback_mode",
            choices=["default", "fixed", "fourlines"], default=None,
            help="Fallback when no galaxy radius: default | fixed | fourlines")
    parser.add_argument("-fallback_radius_px", type=int, default=None,
            help="Fallback fixed radius in pixels (used when -fallback_mode fixed)")
    parser.add_argument("-fallback_line_len_px", type=int, default=None,
            help="Length of each pointer line in pixels (fourlines)")
    parser.add_argument("-fallback_center_gap_px", type=int, default=None,
            help="Gap at center for fourlines (pixels)")

    args = parser.parse_args()

    try:
            if args.output is not None:
                AnnotationsScriptInterface(cli_args=args)
            else:
                siril = s.SirilInterface()
                try:
                    siril.connect()
                except s.SirilConnectionError:
                    if not globals().get("_SHUTTING_DOWN", False):
                        messagebox.showerror("Error", "Sirilに接続できません。スクリプトを終了します。")
                    return

                if not siril.is_image_loaded():
                    messagebox.showerror("Error", "画像が開かれていません。\nSirilで画像を開いてから再実行してください。")
                    siril.disconnect()
                    return

                try:
                    siril.pix2radec(0, 0)
                except ValueError:
                    _ga_warn_once_wcs_not_solved()
                    siril.disconnect()
                    return

                siril.disconnect()

                root = ThemedTk()
                root.geometry("550x520")
                ui = AnnotationsScriptInterface(root)
                try:
                    root.protocol("WM_DELETE_WINDOW", ui.close_dialog)
                except Exception:
                    pass
                root.mainloop()

    except SirilError as e:
            print(f"Error initializing script: {str(e)}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()

# =========================
# CLI wrapper for generate-all (-A / --generate-all)
# =========================
def _cli_generate_all(argv=None):
    import argparse
    from collections import OrderedDict
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-output", type=str, default="", help="Output file name base")
    parser.add_argument("-title", type=str, default="", help="Optional image title")
    parser.add_argument("-logo_path", type=str, default="", help="Optional logo image path")
    parser.add_argument("-overlay_alpha", type=float, default=0.6, help="Overlay alpha value")
    parser.add_argument("-overlay_type", type=str, default="circles",
                            choices=["circles", "boxes", "ellipses"],
                            help="Type of annotation overlays")
    # simple passthrough of fallback knobs (optional)
    parser.add_argument("-fallback_mode", choices=["default", "fixed", "fourlines"], default=None)
    parser.add_argument("-fallback_radius_px", type=int, default=None)
    parser.add_argument("-fallback_line_len_px", type=int, default=None)
    parser.add_argument("-fallback_center_gap_px", type=int, default=None)

    args, _ = parser.parse_known_args(argv)

    try:
            s.connect()
            if not s.is_image_loaded():
                try:
                    s.log("画像が開かれていません。Sirilで画像を開いてから再実行してください。", color=s.LogColor.RED)
                except Exception:
                    pass
                s.disconnect()
                return

            # Ensure plate-solved
            try:
                s.pix2radec(0, 0)
            except Exception:
                try:
                    s.log("現在開いている画像はプレートソルブされていません。", color=s.LogColor.RED)
                except Exception:
                    pass
                s.disconnect()
                return

            # Minimal default catalogs and settings
            catalogs = OrderedDict([
                ('Stars', CatalogEntry('Star Catalog', '#ffd700', False)),
                ('M',     CatalogEntry('Messier Catalog', '#80ff80', True)),
                ('IC',    CatalogEntry('Index Catalogue', '#80ffff', True)),
                ('NGC',   CatalogEntry('New General Catalogue', '#ffffff', True)),
            ])
            custom_catalog_files = {'M': '', 'NGC': '', 'IC': ''}
            custom_object_colors = {}

            fit = s.get_image()
            # keep native dtype (avoid forcing float32)

            # collect optional fallbacks
            kw = {}
            if args.fallback_mode is not None:
                kw["fallback_mode"] = args.fallback_mode
            if args.fallback_radius_px is not None:
                kw["fallback_radius_px"] = int(args.fallback_radius_px)
            if args.fallback_line_len_px is not None:
                kw["fallback_line_len_px"] = int(args.fallback_line_len_px)
            if args.fallback_center_gap_px is not None:
                kw["fallback_center_gap_px"] = int(args.fallback_center_gap_px)

            annotate_fit(
                s, fit, catalogs, args.output, args.title, args.logo_path, float(args.overlay_alpha), args.overlay_type,
                custom_object_colors,
                visible_object_names=None, preloaded_df=None,
                reapply=False, display_name_vars=None, custom_catalog_files=custom_catalog_files,
                # propagate optional fallbacks
                **kw,
                # ★ CLIは明示的に全生成
                generate_table=True,
                generate_combined=True, square_layout=False)
            try:
                s.log("CLI: Overlay + Table + Combined を生成しました。", color=s.LogColor.GREEN)
            except Exception:
                pass
    except Exception as e:
            try:
                s.log(f"CLI generation failed: {e}", color=s.LogColor.RED)
            except Exception:
                pass
    finally:
            try:
                s.disconnect()
            except Exception:
                pass

# Replace the default entry point to allow -A/--generate-all
if __name__ == "__main__":
    import sys
    if ("-A" in sys.argv) or ("--generate-all" in sys.argv):
        # Pass through args so -output/-title/... also work in headless mode
        _cli_generate_all(sys.argv[1:])
    else:
        main()