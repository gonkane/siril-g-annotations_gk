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
# Customized by: gonkane, 2025 — version 1.0.2-gk.4
# See version history below for details.
#
# License: GPL v3 or later (see LICENSE file for details)

"""
Siril 用銀河アノテーションスクリプト（カスタム版 1.0.2-gk.4 by gonkane）

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

詳しくはこのフォークの「Version History / Releases」を参照してください。
"""

import os
import sys
import math
import argparse
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import numpy as np

import sirilpy as s

# Check the module version is enough to provide get_image_fits_header(return_as = 'dict')
if not s.check_module_version('>=0.6.37'):
    print("Error: requires sirilpy module >= 0.6.37 (Siril 1.4.0 Beta 2)")
    sys.exit(1)

from sirilpy import tksiril, SirilError
s.ensure_installed("ttkthemes")
s.ensure_installed("astropy", "astroquery", "matplotlib", "numpy", "pandas", "Pillow", "scikit-image")

from ttkthemes import ThemedTk

# Add any additional imports here
import subprocess
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.patches import Circle
from skimage.transform import resize
from PIL import Image
from astropy.io import fits
from astropy.coordinates import SkyCoord
from astropy import coordinates as coord
from astropy.wcs.utils import skycoord_to_pixel
from astropy.table import Table
import astropy.units as u
from astropy.wcs import WCS
from astroquery.simbad import Simbad
import pandas as pd

VERSION = "1.0.2-gk.4"
CONFIG_FILENAME = "Galaxy_Annotations.conf"


def load_builtin_catalog(filepath, catalog_type):
    if not os.path.exists(filepath):
        print(f"Catalog file not found: {filepath}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        print(f"Error loading catalog {filepath}: {e}")
        return pd.DataFrame()

    required_columns = {'name', 'ra', 'dec'}
    if not required_columns.issubset(df.columns):
        print(f"Missing required columns in: {filepath}")
        return pd.DataFrame()

    df = df.dropna(subset=['ra', 'dec'])
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
    except Exception as e:
        print(f"Failed to load star catalog: {e}")
        return pd.DataFrame()

    required_columns = {'name', 'ra', 'dec'}
    if not required_columns.issubset(df.columns):
        print("Missing required columns in star catalog.")
        return pd.DataFrame()

    df = df.dropna(subset=['ra', 'dec'])
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
    return df


def annotate_fit(siril, fit, catalogs, output, title, logo_path, overlay_alpha, overlay_type,
                 custom_object_colors, visible_object_names=None, preloaded_df=None,
                 reapply=False, display_name_vars=None):
    print(f"Title: {title}")
    print(f"Logo: {logo_path}")

    main_object = title
    output_fname = get_combined_filename(output)
    output_overlay_fname = get_overlay_filename(output)
    output_table_fname = get_table_filename(output)

    if fit.data.ndim == 2:
        img = np.expand_dims(fit.data, -1)
        img = np.tile(img, (1, 1, 3))
    else:
        img = np.transpose(fit.data, (1, 2, 0))

    H, W, C = img.shape
    print(f"Input dimensions: {W} x {H}")

    minsize_pixels = 5
    min_patch_size = int(round(max(W, H) / 100))

    if img.dtype == np.uint16:
        img = img.astype(np.float32) / 65535.0
    elif img.dtype == np.uint8:
        img = img.astype(np.float32) / 255.0
    else:
        if img.dtype != np.float32:
            img = img.astype(np.float32)
        maxValue = np.max(img)
        if maxValue <= (255.0 / 65535.0) or maxValue > 1.0:
            img = img / maxValue

    img = np.clip(img, 0, 1)

    (center_ra, center_dec) = siril.pix2radec(W / 2, H / 2)
    print(f"Center: {center_ra, center_dec}")

    header = siril.get_image_fits_header(return_as='dict')
    wcs = WCS(header, naxis=[1, 2])

    # --- Step 1: データ取得 ---
    if preloaded_df is not None:
        df = preloaded_df.copy()
        print(f"Using preloaded DataFrame: {df.shape[0]} rows")
    else:
        CATALOG_DIR = "C:/Program Files/Siril/share/siril/catalogue"
        catalog_files = {
            "Stars": os.path.join(CATALOG_DIR, "stars.csv"),
            "M": os.path.join(CATALOG_DIR, "messier.csv"),
            "NGC": os.path.join(CATALOG_DIR, "ngc.csv"),
            "IC": os.path.join(CATALOG_DIR, "ic.csv")
        }
        df_list = []

        # 内蔵CSV（選択されているものだけ読み込み）
        for key, filename in catalog_files.items():
            if catalogs.get(key) and catalogs[key].get_selected():
                if key == "Stars":
                    df_cat = load_custom_star_catalog(filename, key)
                else:
                    df_cat = load_builtin_catalog(filename, key)
                if not df_cat.empty:
                    df_list.append(df_cat)

        # Simbad（M/NGC/IC 以外で選択されたカタログ）
        EXCLUDED_SOURCES = ['M', 'NGC', 'IC']
        simbad_catalogs = [key for key in catalogs.keys()
                           if key not in EXCLUDED_SOURCES and catalogs[key].get_selected()]

        if simbad_catalogs:
            simbad = Simbad()
            simbad.TIMEOUT = 120
            simbad.add_votable_fields("otype", "galdim_majaxis", "ra", "dec")  # 新しいフィールド名

            target_coord = SkyCoord(ra=center_ra, dec=center_dec, unit=(u.deg, u.deg), frame='icrs')

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

            radius = f"{radius_deg:.6f}d"
            criteria_opt = f"otype='Galaxy..' AND (galdim_majaxis>{minsize_arcmin:.6f} OR (galdim_majaxis IS NULL))"
            print(f"Query radius: {radius}")
            print(f"      minimum size: {minsize_pixels} pixels ~ {minsize_arcmin:.3f}′")
            print(f"      criteria: {criteria_opt}")

            result_table = None
            try:
                result_table = simbad.query_region(target_coord, radius, criteria=criteria_opt)
            except Exception as e:
                print(f"Simbad query failed: {e}")

            if result_table is None or len(result_table) == 0:
                print("Simbad query returned no results.")
            else:
                try:
                    result_table.sort("galdim_majaxis", reverse=True)
                except Exception:
                    pass
                df_simbad = result_table.to_pandas()
                print(f"Simbad query results: {df_simbad.shape[0]} entries")

                # ra/dec を数値化
                if "ra" in df_simbad.columns and "dec" in df_simbad.columns:
                    df_simbad["ra"] = pd.to_numeric(df_simbad["ra"], errors="coerce")
                    df_simbad["dec"] = pd.to_numeric(df_simbad["dec"], errors="coerce")
                    df_simbad.dropna(subset=["ra", "dec"], inplace=True)

                # 表示名列
                df_simbad['display_name'] = df_simbad['main_id']
                df_simbad['original_display_name'] = df_simbad['main_id']

                # TYPE を main_id の先頭語から推定（M/NGC/IC は除外）
                import re
                df_simbad['TYPE'] = df_simbad['main_id'].apply(
                    lambda x: re.match(r'^([A-Za-z0-9]+)', str(x)).group(1) if re.match(r'^([A-Za-z0-9]+)', str(x)) else 'Unknown'
                )
                df_simbad = df_simbad[~df_simbad['TYPE'].isin(EXCLUDED_SOURCES)]

                # ★ ここで「Simbad 由来だけ」をカタログ順→main_id で並び替え（Apply時のみ）
                if not reapply and not df_simbad.empty:
                    order_map = {k: i for i, k in enumerate(catalogs.keys())}
                    df_simbad['_ord'] = df_simbad['TYPE'].map(order_map).fillna(999)
                    df_simbad = (df_simbad
                                 .sort_values(['_ord', 'main_id'], kind='stable')
                                 .drop(columns=['_ord']))

                if not df_simbad.empty:
                    df_list.append(df_simbad)

        if not df_list:
            print("No catalog data loaded.")
            return 0

        df = pd.concat(df_list, ignore_index=True)

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

    df['Pixel_Position'] = df.apply(safe_radec2pix, axis=1)
    df = df[df['Pixel_Position'].apply(lambda x: np.isfinite(x[0]) and np.isfinite(x[1]))]
    df['px'] = df['Pixel_Position'].apply(lambda x: int(round(x[0])))
    df['py'] = df['Pixel_Position'].apply(lambda x: int(round(x[1])))

    # 画像範囲内
    df = df[(df.px > min_patch_size) & (df.py > min_patch_size)
            & (df.px < W - min_patch_size) & (df.py < H - min_patch_size)]

    print(f"Filtered query result by image coordinates: {df.shape[0]} entries")

    # ★ Apply時のみ：未選択カタログの天体（名前とTYPE）を絞り込み前にコンソール出力
    if not reapply and not df.empty:
        selected_types = [key for key, value in catalogs.items() if value.get_selected()]
        unselected_df = df[~df['TYPE'].isin(selected_types)]
        if not unselected_df.empty:
            print("=== Unselected catalog objects (name\tTYPE) ===")
            for name, typ in unselected_df[['main_id', 'TYPE']].astype(str).values:
                print(f"  {name}\t{typ}")
            print("=== End of unselected list ===")

    # --- Step 3: カタログフィルタ ---
    if not reapply:
        filter_types = [key for key, value in catalogs.items() if value.get_selected()]
        filtered_result = Table.from_pandas(df[df['TYPE'].isin(filter_types)])
        dfi = filtered_result.to_pandas()
        print(f"Filtered by catalog: {dfi.shape[0]} entries")
    else:
        # ReApply/CSVモード：フィルタなし
        dfi = df.copy()
        print(f"Skipped catalog filter (ReApply): {dfi.shape[0]} entries")

    # ★ Apply時のみ：M/NGC/IC の「座標＋半径」重複を間引く（先頭だけ残す）
    if not reapply:
        primary_types = [t for t in ['M', 'NGC', 'IC']
                         if (t in catalogs and catalogs[t].get_selected())]
        if len(primary_types) >= 2 and not dfi.empty:
            order_map = {k: i for i, k in enumerate(catalogs.keys())}
            cand = dfi[dfi['TYPE'].isin(primary_types)].copy()
            cand = cand.sort_values(by='TYPE', key=lambda s: s.map(order_map))
            to_drop = set()

            def alias_set_val(v):
                if pd.isna(v) or v is None:
                    return set()
                return set([p.strip() for p in str(v).split('/') if p.strip()])

            def same_object(a, b):
                same_pos = (abs(int(a.px) - int(b.px)) <= 1) and (abs(int(a.py) - int(b.py)) <= 1)
                da = float(a.galdim_majaxis) if pd.notna(a.get('galdim_majaxis', np.nan)) else float('nan')
                db = float(b.galdim_majaxis) if pd.notna(b.get('galdim_majaxis', np.nan)) else float('nan')
                if math.isnan(da) or math.isnan(db):
                    same_rad = True
                else:
                    tol = min(0.5, 0.1 * max(da, db))
                    same_rad = abs(da - db) <= tol
                alias_hit = (str(a.main_id) in alias_set_val(b.get('alias', None))) or \
                            (str(b.main_id) in alias_set_val(a.get('alias', None)))
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

    # --- Step 4.5: visible_object_names 補完（Apply時のみ） ---
    if not reapply and visible_object_names is not None:
        missing_names = dfi[~dfi['main_id'].isin(visible_object_names)]['main_id'].tolist()
        if missing_names:
            print(f"Adding {len(missing_names)} newly detected objects to visible list")
            visible_object_names.extend(missing_names)

    # --- Step 5: 表示チェックONのみ（ReApply時） ---
    if reapply and visible_object_names is not None:
        dfi = dfi[dfi['main_id'].isin(visible_object_names)]
        print(f"Filtered by visibility (ReApply): {dfi.shape[0]} entries")
    else:
        print(f"No visibility filter applied (Apply): {dfi.shape[0]} entries")

    # --- Step 6: 重複数・インデックス ---
    dfi['duplicate_count'] = dfi.groupby(['px', 'py'])['main_id'].transform('count')
    dfi['duplicate_index'] = dfi.groupby(['px', 'py']).cumcount()

    print(f"Filtered after removing duplicates: {dfi.shape[0]} entries")

    # --- Step 7: 該当天体が0なら終了 ---
    if dfi.shape[0] == 0:
        print("No objects found in image boundary.")
        return 0

    # --- Step 8: 表示順のソート（Apply時のみ、描画順用） ---
    sub = 1
    dpi = 200

    if not reapply:
        rep_dic = {key: f"{i:02d}" for i, key in enumerate(catalogs.keys())}
        dfi['sorting'] = dfi.TYPE.replace(rep_dic)
        dfi = dfi.sort_values(['sorting', 'main_id'], ascending=True).reset_index(drop=True)
    else:
        dfi = dfi.reset_index(drop=True)

    # --- Step 9: 描画準備 ---
    # 日本語対応
    def _setup_japanese_font():
        import matplotlib
        from matplotlib import font_manager
        cand = ['Yu Gothic', 'Meiryo', 'MS Gothic', 'Yu Mincho',
                'Noto Sans CJK JP', 'Noto Serif CJK JP', 'IPAGothic', 'IPAMincho']
        available = {f.name for f in font_manager.fontManager.ttflist}
        for name in cand:
            if name in available:
                matplotlib.rcParams['font.family'] = name
                matplotlib.rcParams['axes.unicode_minus'] = False
                print(f"Matplotlib font set to: {name}")
                return
        # 見つからない場合は既定のまま（警告は出ます）
        print("Japanese font not found; warnings may appear.")

    _setup_japanese_font()
    plt.style.use('dark_background')
    extra_axis_label_size_inches = 1.15
    fig = plt.figure(
        figsize=(W / dpi + extra_axis_label_size_inches, H / dpi + extra_axis_label_size_inches)
    )
    ax1 = plt.subplot(projection=wcs, label='overlays')
    ax1.imshow(img[::sub, ::sub])
    ax1.coords.grid(True, color='white', ls=':', alpha=overlay_alpha)
    ax1.coords[0].set_axislabel('Right Ascension (J2000)')
    ax1.coords[1].set_axislabel('Declination (J2000)', minpad=-1)
    ax1.set_title(title, fontsize=24)

    all_patches = []
    filter_idxs = []

    # --- Step 10: 各天体のアノテーションを描画 ---
    for i, row in dfi.iterrows():
        siril.update_progress(f"Creating patches", i / (10 * dfi.shape[0]))

        fontsize = 12
        base_color = catalogs[row.TYPE].color if row.TYPE in catalogs else "#ff0000"
        color = custom_object_colors.get(row.main_id, base_color)

        angular_size = row.get("galdim_majaxis", 0)
        size_factor = 2

        if pd.isna(angular_size) or angular_size == 0:
            angular_size = {
                "M8": 90, "M40": 0.86, "M43": 20, "M78": 8, "M82": 11.2
            }.get(row.main_id, 0)

        if angular_size == 0:
            patch_size = patch_diameter_pix = min_patch_size
        else:
            try:
                half_diam_deg = (angular_size / 2.0) / 60.0
                coord_top = SkyCoord(ra=row.ra * u.deg, dec=(row.dec + half_diam_deg) * u.deg)
                coord_bottom = SkyCoord(ra=row.ra * u.deg, dec=(row.dec - half_diam_deg) * u.deg)
                coord_left = SkyCoord(ra=(row.ra - half_diam_deg) * u.deg, dec=row.dec * u.deg)
                coord_right = SkyCoord(ra=(row.ra + half_diam_deg) * u.deg, dec=row.dec * u.deg)

                px_top, py_top = siril.radec2pix(coord_top.ra.deg, coord_top.dec.deg)
                px_bottom, py_bottom = siril.radec2pix(coord_bottom.ra.deg, coord_bottom.dec.deg)
                px_left, py_left = siril.radec2pix(coord_left.ra.deg, coord_left.dec.deg)
                px_right, py_right = siril.radec2pix(coord_right.ra.deg, coord_right.dec.deg)

                d_dec = math.hypot(px_top - px_bottom, py_top - py_bottom)
                d_ra = math.hypot(px_right - px_left, py_right - py_left)
                patch_diameter_pix = (d_dec + d_ra) / 2.0

                patch_size = int(round(patch_diameter_pix * size_factor))
                patch_size = max(min_patch_size, patch_size)

            except Exception as e:
                siril.log(f"{row.main_id}: WCS radius estimation failed: {e}", color=s.LogColor.RED)
                patch_size = patch_diameter_pix = min_patch_size

        if row.main_id == main_object:
            fontsize = 20
            color = 'white'
        elif row.TYPE in ['M', 'NGC']:
            fontsize = 18
        elif row.TYPE in ['SAI', 'UGC', 'MCG', 'IC']:
            fontsize = 16
        elif row.TYPE == 'LEDA':
            if not math.isnan(row.galdim_majaxis) and row.galdim_majaxis > 1.8:
                patch_size = patch_diameter_pix = min_patch_size

        if reapply and display_name_vars:
            var = display_name_vars.get(row.main_id)
            display_name = var.get() if var else row.display_name
        else:
            display_name = row.display_name

        annotation_text = f"{i + 1}" if patch_size <= 200 else f"{i + 1}: {display_name}"

        clipped = min(patch_size, (W - row.px) * 2, row.px * 2, (H - row.py) * 2, row.py * 2)
        x1 = row.px - clipped // 2
        x2 = row.px + clipped // 2
        y1 = H - row.py - clipped // 2
        y2 = H - row.py + clipped // 2

        if overlay_type == "boxes":
            size_increment = 60
            expansion = row.duplicate_index * size_increment if hasattr(row, 'duplicate_index') else 0
            x1_exp, x2_exp = x1 - expansion, x2 + expansion
            y1_exp, y2_exp = y1 - expansion, y2 + expansion

            rect = Rectangle((x1_exp, y1_exp), x2_exp - x1_exp, y2_exp - y1_exp,
                             alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
            ax1.add_patch(rect)

            text_y = y1_exp - 6
            v_align = 'top'
            if text_y < 0:
                text_y = min(y2_exp + 6, H - (3 * fontsize))
                v_align = 'bottom'

        else:
            radius_increment = 60.0
            annot_radius = max(min_patch_size, 1.2 * patch_diameter_pix / 2.0)
            if hasattr(row, 'duplicate_index'):
                annot_radius += row.duplicate_index * radius_increment

            circ = Circle((row.px, H - row.py), radius=annot_radius,
                          alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
            ax1.add_patch(circ)

            text_y = H - row.py - 6 - annot_radius
            v_align = 'top'
            if text_y < 0:
                text_y = min(H - row.py + 6 + annot_radius, H - (3 * fontsize))
                v_align = 'bottom'

        ax1.text(row.px, text_y, annotation_text,
                 ha='center', va=v_align, color=color, alpha=overlay_alpha, fontsize=fontsize)

        patch = img[y1:y2, x1:x2]
        all_patches.append(patch)
        filter_idxs.append(i)

    plt.tight_layout()
    siril.update_progress("Saving overlay image...", 0.2)
    plt.savefig(output_overlay_fname, bbox_inches='tight', pad_inches=0.1, dpi=dpi)
    siril.update_progress("Finished overlay image.", 0.3)
    plt.close(fig)

    overlay_image = plt.imread(output_overlay_fname)

    # --- Step 11: パッチ画像をリサイズ（正方形 512x512） ---
    new_patch_size = 512
    siril.update_progress("Resizing patch images...", 0.4)
    all_patches_resized = [resize(patch, (new_patch_size, new_patch_size)) for patch in all_patches]
    all_patches = np.array(all_patches_resized)
    siril.update_progress("Patch images resized.", 0.5)

    # --- Step 12: サムネイル表の作成 ---
    scale = 3
    n = len(all_patches)
    mincols = 6 if (logo_path != "") else 5
    ncols = max(mincols, int(np.floor(np.sqrt(n))))
    nrows = int(np.ceil(n / ncols))
    print(f"Grid size: nrows={nrows}, ncols={ncols}")

    fig, axarr = plt.subplots(nrows, ncols, figsize=(ncols * scale, nrows * scale))
    dft = dfi.iloc[filter_idxs].reset_index()

    for i, row in dft.iterrows():
        ax = axarr[i // ncols, i % ncols] if nrows > 1 else axarr[i]

        if row.main_id in custom_object_colors:
            color = custom_object_colors[row.main_id]
        elif row.TYPE in catalogs:
            color = catalogs[row.TYPE].color
        else:
            color = "#ff0000"

        ax.imshow(all_patches[i][::-1])
        display_name = row.display_name
        ax.set_title(display_name, fontsize=12, color=color)

        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor(color)
        ax.text(2, 2, str(i + 1), ha='left', va='top', color='white', fontsize=18)

    for i in range(n, nrows * ncols):
        ax = axarr[i // ncols, i % ncols] if nrows > 1 else axarr[i]
        ax.axis('off')

    if (logo_path != "") and (nrows * ncols > n):
        logo_img = plt.imread(logo_path)
        ax_logo = axarr[nrows - 1, ncols - 1] if nrows > 1 else axarr[ncols - 1]
        ax_logo.imshow(logo_img)

    siril.update_progress("Creating thumbnail table...", 0.6)
    plt.tight_layout()
    plt.savefig(output_table_fname, bbox_inches='tight', pad_inches=.1, dpi=dpi)
    siril.update_progress("Saved thumbnail table image.", 0.7)
    plt.close(fig)

    table_image = plt.imread(output_table_fname)

    # --- Step 13: オーバーレイ画像とテーブル画像を縦に結合 ---
    siril.update_progress("Creating combined output image...", 0.8)
    output_shape = (int(table_image.shape[0] * (overlay_image.shape[1] / table_image.shape[1])), overlay_image.shape[1])
    table_image_scaled = (resize(table_image, output_shape) * 255).astype(np.uint8)
    im = Image.fromarray(np.vstack([(overlay_image * 255).astype(np.uint8), table_image_scaled])[:, :, :3])

    siril.update_progress("Saving combined output image...", 0.9)
    im.save(output_fname)
    print("output image files:")
    print("  overlay:  ", output_overlay_fname)
    print("  table:    ", output_table_fname)
    print("  combined: ", output_fname)

    siril.update_progress("Finished.", 1)

    return dfi, dfi.shape[0], df


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


class CatalogEntry:
    def __init__(self, description, color='#ffffff', selection_default=True):
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
        self._object_defaults_snapshot = None  # Defaults用スナップショット
        self._view_mode = "normal"            # "normal" | "csv"

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
            self.root.resizable(False, False)
            self.style = tksiril.standard_style()

        self.siril = s.SirilInterface()

        try:
            self.siril.connect()
        except s.SirilConnectionError:
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

        if self.siril.is_cli():
            print("Apply changes from CLI")
            self.apply_changes(from_cli=True)

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
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        title_label = ttk.Label(main_frame, text="Galaxy Annotations Script", style="Header.TLabel")
        title_label.pack(pady=(0, 5))
        version_label = ttk.Label(main_frame, text=f"Script version: {VERSION}")
        version_label.pack(pady=(0, 0))

        sep = ttk.Separator(main_frame, orient='horizontal')
        sep.pack(fill=tk.X, pady=5)

        params_frame = ttk.LabelFrame(main_frame, text="Output", padding=10)
        params_frame.pack(fill=tk.BOTH, padx=5, pady=5)
        params_frame.columnconfigure(1, weight=1)

        row = 0
        titlelbl = ttk.Label(params_frame, text="Title: ")
        titlelbl.grid(column=0, row=row, sticky="WENS")
        self.title = tk.StringVar(self.root, value=self.cli_args.title)
        title_entry = ttk.Entry(params_frame, textvariable=self.title)
        title_entry.grid(column=1, row=row, sticky="WENS", padx=2, pady=2)
        ttk.Label(params_frame, text="").grid(column=2, row=row, sticky="WENS")

        row += 1
        logolbl = ttk.Label(params_frame, text="Logo: ")
        logolbl.grid(column=0, row=row, sticky="WENS")
        self.logo_path = tk.StringVar(self.root, value=self.cli_args.logo_path)
        logo_file_entry = ttk.Entry(params_frame, textvariable=self.logo_path)
        logo_file_entry.grid(column=1, row=row, sticky="WENS", padx=2, pady=2)

        browsebtn = ttk.Button(params_frame, text="Browse", command=self._browse_logo_file, style="TButton")
        browsebtn.grid(column=2, row=row, sticky="W")

        row += 1
        output_label = ttk.Label(params_frame, text="Output file: ")
        output_label.grid(column=0, row=row, sticky="WENS")
        self.output = tk.StringVar(self.root, value=self.cli_args.output)
        output_file_entry = ttk.Entry(params_frame, textvariable=self.output)
        output_file_entry.grid(column=1, row=row, sticky="WENS", padx=2, pady=2)

        overlay_settings_label = ttk.Label(params_frame, text="Overlay: ")
        overlay_settings_label.grid(column=0, row=row, sticky="WENS")

        overlay_alpha_frame = ttk.Frame(params_frame)
        overlay_alpha_frame.grid(column=1, row=row, sticky="WENS")
        alpha_label = ttk.Label(overlay_alpha_frame, text="Alpha:")
        alpha_label.pack(side=tk.LEFT, padx=5)

        self.overlay_alpha_var = tk.DoubleVar(value=self.cli_args.overlay_alpha)
        overlay_alpha_slider = ttk.Scale(overlay_alpha_frame, from_=0.0, to=1.0, orient=tk.HORIZONTAL, variable=self.overlay_alpha_var)
        overlay_alpha_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tksiril.create_tooltip(overlay_alpha_slider, "Adjust the visibility of the annotation overlays.")

        self.overlay_alpha_label = ttk.Label(overlay_alpha_frame, text=f"{self.cli_args.overlay_alpha}")
        self.overlay_alpha_label.pack(side=tk.RIGHT, padx=5)
        self.overlay_alpha_var.trace_add("write", self._update_alpha_label)

        self.overlay_type_var = tk.StringVar(self.root, value=self.cli_args.overlay_type)
        overlay_type_cb = ttk.Combobox(params_frame, textvariable=self.overlay_type_var, values=('circles', 'boxes'),
                                       state="readonly", justify='center', width=5)
        overlay_type_cb.grid(column=2, row=row, sticky="WENS")
        tksiril.create_tooltip(overlay_type_cb, "The type of annotations to draw around galaxies.")

        row += 1
        loadlbl = ttk.Label(params_frame, text="Load in Siril: ")
        loadlbl.grid(column=0, row=row, sticky="WENS")
        self.load_in_siril = tk.StringVar(None, 'C')
        load_frame = ttk.Frame(params_frame)
        load_frame.grid(column=1, row=row, columnspan=2, sticky="WENS")
        ttk.Radiobutton(load_frame, text='Combined', value='C', variable=self.load_in_siril).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(load_frame, text='Overlay', value='O', variable=self.load_in_siril).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(load_frame, text='Table', value='T', variable=self.load_in_siril).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(load_frame, text='None', value='', variable=self.load_in_siril).pack(side=tk.LEFT, padx=5)

        catalogs_frame = ttk.LabelFrame(main_frame, text="Catalogs", padding=0)
        catalogs_frame.pack(fill=tk.BOTH, padx=5, pady=0, expand=True)

        canvas = tk.Canvas(catalogs_frame, height=210)
        scrollbar = ttk.Scrollbar(catalogs_frame, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)

        catalogs_inner = ttk.Frame(canvas)
        inner_window = canvas.create_window((0, 0), window=catalogs_inner, anchor="nw")

        i = 0
        for key, value in self.catalogs.items():
            value.checkbox_var = tk.BooleanVar(self.root)
            value.checkbox_var.set(value.selection_default)
            value.color_var = tk.StringVar(value=self.catalogs[key].color)

            checkbox = ttk.Checkbutton(catalogs_inner, text=key, variable=value.checkbox_var)
            checkbox.grid(row=i, column=0, sticky="WENS")

            label = ttk.Label(catalogs_inner, text=value.description or key)
            label.grid(row=i, column=1, sticky="WENS")

            color_btn = ttk.Button(catalogs_inner, text="Color", command=lambda k=key: self.choose_color(k))
            color_btn.grid(row=i, column=2, sticky="WENS", padx=2)

            color_disp = ttk.Label(catalogs_inner, textvariable=value.color_var, background=value.color)
            color_disp.grid(row=i, column=3, sticky="WENS", padx=2)
            value.color_label = color_disp

            i += 1

        catalogs_inner.grid_columnconfigure(1, weight=1)

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        catalogs_inner.bind("<Configure>", _on_frame_configure)

        def _on_canvas_resize(event):
            canvas.itemconfig(inner_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        select_frame = ttk.Frame(main_frame)
        select_frame.pack(fill="x", pady=5)
        ttk.Label(select_frame, text="Select: ").grid(row=0, column=0, padx=5)
        ttk.Button(select_frame, text="All", command=self.select_all).grid(row=0, column=1, padx=2)
        ttk.Button(select_frame, text="None", command=self.select_none).grid(row=0, column=2, padx=2)
        ttk.Button(select_frame, text="Defaults", command=self.select_default).grid(row=0, column=3, padx=2)

        sep2 = ttk.Separator(main_frame, orient='horizontal')
        sep2.pack(fill=tk.X, pady=5)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=10)

        close_btn = ttk.Button(button_frame, text="Close", command=self.close_dialog, style="TButton")
        close_btn.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(close_btn, "Close, no changes will be made to the current image.")

        apply_btn = ttk.Button(button_frame, text="Apply", command=self.apply_changes, style="TButton")
        apply_btn.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(apply_btn, "Create the annotated output image")

        after_label = ttk.Label(button_frame, text="after :")
        after_label.pack(side=tk.LEFT, padx=(10, 3))

        ttk.Button(button_frame, text="C", width=2, command=lambda: self.switch_image("combined")).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="O", width=2, command=lambda: self.switch_image("overlay")).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="T", width=2, command=lambda: self.switch_image("table")).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="N", width=2, command=lambda: self.switch_image("original")).pack(side=tk.LEFT, padx=2)

        btn_obj = ttk.Button(button_frame, text="Object", command=self.show_or_focus_object_window)
        btn_obj.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(btn_obj, "Open or focus the Object Control window")

    def show_or_focus_object_window(self):
        if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
            self.object_control_window.lift()
            self.object_control_window.focus_force()
        elif hasattr(self, 'df_all') and self.df_all is not None:
            if self._view_mode == "csv":
                # CSVモード中はフィルタ無しでそのまま
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
                self.catalogs[catalog_key].color_label.config(background=color_code[1])

    def apply_changes(self, from_cli=False, is_reapply=False):
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

                fit = self.siril.get_image()
                fit.ensure_data_type(np.float32)

                try:
                    self.siril.pix2radec(0, 0)
                except ValueError:
                    self.siril.log("The image is not plate solved", color=s.LogColor.RED)
                    if not from_cli:
                        self.siril.error_messagebox("The image is not plate solved")
                    return

                # ★ Apply時は完全初期化 & 通常モードへ
                if not is_reapply:
                    self.df_all = None
                    self.custom_object_colors.clear()
                    self.visible_object_flags.clear()
                    self.display_name_vars = {}
                    self._object_defaults_snapshot = None
                    self._view_mode = "normal"
                    if hasattr(self, 'visible_object_names'):
                        del self.visible_object_names

                # --- Step 1: 描画 ---
                result = annotate_fit(
                    self.siril, fit, self.catalogs, output,
                    title, logo_path, overlay_alpha, overlay_type,
                    self.custom_object_colors,
                    visible_object_names=self.visible_object_names if is_reapply and hasattr(self, 'visible_object_names') else None,
                    preloaded_df=self.df_all if is_reapply and hasattr(self, 'df_all') else None,
                    reapply=is_reapply,
                    display_name_vars=self.display_name_vars if is_reapply else None
                )

                # --- Step 2: 結果チェック ---
                if isinstance(result, tuple) and len(result) == 3:
                    dfi, found, df_all = result
                    self.df_all = df_all
                else:
                    if not from_cli:
                        messagebox.showerror("Error", "Unexpected result from annotate_fit().")
                    else:
                        print("Error: Unexpected result from annotate_fit().")
                    return

                # --- Step 3: Apply後のGUI初期化（選択カタログのみ管理）
                if not from_cli and not is_reapply:
                    if 'original_display_name' in self.df_all.columns:
                        self.df_all['display_name'] = self.df_all['original_display_name']

                    selected_types = {k for k, v in self.catalogs.items() if v.get_selected()}
                    self.visible_object_flags.clear()
                    self.custom_object_colors.clear()
                    for row in self.df_all.itertuples(index=False):
                        ctype = row.TYPE
                        if ctype not in selected_types:
                            continue
                        name = row.main_id
                        self.visible_object_flags[name] = tk.BooleanVar(value=True)
                        self.custom_object_colors[name] = self.catalogs[ctype].color

                    # ★ M/NGC/IC 重複の2つ目以降をOFF（Apply時のみ）
                    primary = [t for t in ['M', 'NGC', 'IC'] if t in selected_types]
                    if len(primary) >= 2 and isinstance(self.df_all, pd.DataFrame):
                        df_mni = self.df_all[self.df_all['TYPE'].isin(primary)].copy()
                        if not df_mni.empty and {'px', 'py'}.issubset(df_mni.columns):
                            order_map = {k: i for i, k in enumerate(self.catalogs.keys())}

                            def alias_set(v):
                                if pd.isna(v) or v is None:
                                    return set()
                                return set([p.strip() for p in str(v).split('/') if p.strip()])

                            rows = list(df_mni.sort_values(by='TYPE', key=lambda s: s.map(order_map)).iterrows())
                            used = set()
                            for i, a in rows:
                                if i in used:
                                    continue
                                group = [i]
                                for j, b in rows:
                                    if j <= i or j in used:
                                        continue
                                    same_pos = (abs(int(a.px) - int(b.px)) <= 1) and (abs(int(a.py) - int(b.py)) <= 1)
                                    da = float(a.galdim_majaxis) if pd.notna(a.get('galdim_majaxis', np.nan)) else float('nan')
                                    db = float(b.galdim_majaxis) if pd.notna(b.get('galdim_majaxis', np.nan)) else float('nan')
                                    if math.isnan(da) or math.isnan(db):
                                        same_rad = True
                                    else:
                                        tol = min(0.5, 0.1 * max(da, db))
                                        same_rad = abs(da - db) <= tol
                                    alias_hit = (str(a.main_id) in alias_set(b.get('alias', None))) or \
                                                (str(b.main_id) in alias_set(a.get('alias', None)))
                                    if (same_pos and same_rad) or alias_hit:
                                        group.append(j)
                                        used.add(j)
                                if len(group) > 1:
                                    for j in group[1:]:
                                        nm = df_mni.loc[j, 'main_id']
                                        if nm in self.visible_object_flags:
                                            self.visible_object_flags[nm].set(False)

                # --- Step 4: 可視名リスト
                if not is_reapply:
                    self.visible_object_names = [name for name, var in self.visible_object_flags.items() if var.get()]

                if found and found > 0:
                    # Objectウィンドウへ渡すDF
                    if is_reapply or self._view_mode == "csv":
                        df_for_object = self.df_all.copy()  # フィルタ無し
                    else:
                        types_selected = [k for k, v in self.catalogs.items() if v.get_selected()]
                        df_for_object = self.df_all[self.df_all['TYPE'].isin(types_selected)].copy()

                    if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
                        self.object_control_window.lift()
                        self.object_control_window.focus_force()
                    else:
                        self.show_object_selection_dialog(df_for_object, is_reapply=is_reapply)

                    self.siril.log("Annotations image created successfully.", color=s.LogColor.GREEN)

                    if self.load_in_siril.get() == 'C':
                        self.siril.cmd("load", "\"" + get_combined_filename(output) + "\"")
                    elif self.load_in_siril.get() == 'O':
                        self.siril.cmd("load", "\"" + get_overlay_filename(output) + "\"")
                    elif self.load_in_siril.get() == 'T':
                        self.siril.cmd("load", "\"" + get_table_filename(output) + "\"")

        except SirilError as e:
            if from_cli:
                print(f"Error: {str(e)}")
            else:
                messagebox.showerror("Error", str(e))

    def switch_image(self, kind):
        try:
            if kind == "combined":
                filepath = get_combined_filename(self.output.get())
            elif kind == "overlay":
                filepath = get_overlay_filename(self.output.get())
            elif kind == "table":
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

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image:\n{str(e)}")

    def close_dialog(self):
        if hasattr(self, 'root'):
            self.root.quit()
            self.root.destroy()

    def select_all(self):
        for key, value in self.catalogs.items():
            value.checkbox_var.set(True)

    def select_none(self):
        for key, value in self.catalogs.items():
            value.checkbox_var.set(False)

    def show_object_selection_dialog(self, dataframe, is_reapply=False):
        dataframe = dataframe.dropna(subset=['main_id', 'TYPE']).copy()

        self.color_vars = {}
        self.color_labels = {}
        self.display_name_vars = {}

        self.object_control_window = tk.Toplevel(self.root)
        window = self.object_control_window
        window.title("Customize Objects")
        window.geometry("600x380")

        top_frame = ttk.Frame(window)
        top_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(top_frame, background="#2e2e2e")
        scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollable_frame = ttk.Frame(canvas, style="Custom.TFrame")
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        scrollable_frame.bind("<Configure>", on_frame_configure)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        select_frame = ttk.Frame(window)
        select_frame.pack(pady=0, padx=0, anchor="w")

        ttk.Label(select_frame, text="Select:").pack(side="left", padx=(0, 0))
        ttk.Button(select_frame, text="All",   command=lambda: self._select_objects(True)).pack(side="left", padx=2)
        ttk.Button(select_frame, text="None",  command=lambda: self._select_objects(False)).pack(side="left", padx=2)
        ttk.Button(select_frame, text="Defaults", command=self._reset_object_defaults).pack(side="left", padx=2)

        def save_object_data_to_csv():
            import csv
            from tkinter import filedialog

            save_path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv")],
                title="Save Object Settings"
            )
            if not save_path:
                return

            try:
                with open(save_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(["main_id", "TYPE", "visible", "color", "ra", "dec", "diameter", "display_name"])
                    for row in dataframe.itertuples(index=False):
                        name = row.main_id
                        ctype = row.TYPE
                        visible = self.visible_object_flags.get(name, tk.BooleanVar(value=False)).get()
                        color = self.custom_object_colors.get(name, self.catalogs.get(ctype, CatalogEntry("")).color)

                        ra = getattr(row, 'ra', '')
                        dec = getattr(row, 'dec', '')
                        diameter = getattr(row, 'galdim_majaxis', '')

                        display_name = ""
                        if hasattr(self, 'df_all') and isinstance(self.df_all, pd.DataFrame) and 'display_name' in self.df_all.columns:
                            m = self.df_all.loc[self.df_all['main_id'] == name, 'display_name']
                            if not m.empty:
                                display_name = str(m.values[0])

                        writer.writerow([name, ctype, visible, color, ra, dec, diameter, display_name])

                messagebox.showinfo("Success", f"Saved object settings to:\n{save_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save CSV:\n{e}")

        save_btn = ttk.Button(select_frame, text="Save", command=save_object_data_to_csv)
        save_btn.pack(side="left", padx=2)

        def replace_object_data_from_csv():
            import csv
            from tkinter import filedialog

            load_path = filedialog.askopenfilename(
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv")],
                title="Replace all object settings from CSV"
            )
            if not load_path:
                return

            try:
                # 既存状態をクリア
                self.visible_object_flags.clear()
                self.custom_object_colors.clear()
                self.display_name_vars = {}
                self.color_vars = {}
                self.color_labels = {}

                new_rows = []
                with open(load_path, newline='', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        main_id = row.get("main_id")
                        ctype   = row.get("TYPE", "Unknown")
                        visible = row.get("visible", "True").strip().lower() == "true"
                        color   = row.get("color", "#ffffff")
                        display_name = row.get("display_name", main_id)

                        ra = float(row["ra"]) if "ra" in row and row["ra"] else np.nan
                        dec = float(row["dec"]) if "dec" in row and row["dec"] else np.nan
                        diameter = float(row["diameter"]) if "diameter" in row and row["diameter"] else np.nan

                        new_rows.append({
                            "main_id": main_id,
                            "TYPE": ctype,
                            "ra": ra,
                            "dec": dec,
                            "galdim_majaxis": diameter,
                            "display_name": display_name,
                            "original_display_name": display_name
                        })

                        self.visible_object_flags[main_id] = tk.BooleanVar(value=visible)
                        self.custom_object_colors[main_id] = color

                # CSVの並びそのまま & CSVモードへ
                self.df_all = pd.DataFrame(new_rows)
                self._view_mode = "csv"

                # ReApply時に使う可視名リストもCSV可視状態から作成
                self.visible_object_names = [k for k, v in self.visible_object_flags.items() if v.get()]

                # フィルタ無しで表示
                if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
                    self.object_control_window.destroy()
                self.show_object_selection_dialog(self.df_all.copy(), is_reapply=True)

                # タイトルにCSVファイル名
                if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
                    import os
                    filename_only = os.path.basename(load_path)
                    self.object_control_window.title(f"Customize Objects (from {filename_only})")

            except Exception as e:
                messagebox.showerror("Error", f"Failed to replace from CSV:\n{e}")

        replace_btn = ttk.Button(select_frame, text="Replace from CSV", command=replace_object_data_from_csv)
        replace_btn.pack(side="left", padx=2)

        header_labels = ["", "Name", "Catalog", "Color", "Hex", "Display Name"]
        for col, text in enumerate(header_labels):
            lbl = ttk.Label(scrollable_frame, text=text, font=('Segoe UI', 9, 'bold'), anchor="center")
            lbl.grid(row=0, column=col, sticky="nsew", padx=2, pady=(0, 2))

        for i, row in enumerate(dataframe.itertuples(index=False)):
            name = row.main_id
            ctype = row.TYPE
            default_color = self.catalogs.get(ctype, CatalogEntry("")).color
            current_color = self.custom_object_colors.get(name, default_color)

            if name not in self.visible_object_flags:
                self.visible_object_flags[name] = tk.BooleanVar(value=True)
            visible_var = self.visible_object_flags[name]

            check = ttk.Checkbutton(scrollable_frame, variable=visible_var)
            check.grid(row=i + 1, column=0, sticky="w", padx=2)

            name_label = ttk.Label(scrollable_frame, text=name, width=18)
            name_label.grid(row=i + 1, column=1, sticky="w", padx=5, pady=2)

            catalog_label = ttk.Label(scrollable_frame, text=ctype, width=8)
            catalog_label.grid(row=i + 1, column=2, sticky="w", padx=2)

            color_var = tk.StringVar(value=current_color)
            color_label = ttk.Label(scrollable_frame, textvariable=color_var, background=current_color, width=10)
            color_label.grid(row=i + 1, column=4, padx=5)

            self.color_vars[name] = color_var
            self.color_labels[name] = color_label

            display_value = str(row.display_name) if not isinstance(row.display_name, str) else row.display_name
            display_name_var = tk.StringVar(value=display_value)
            self.display_name_vars[name] = display_name_var

            if hasattr(self, 'df_all') and isinstance(self.df_all, pd.DataFrame) and 'display_name' in self.df_all.columns:
                self.df_all.loc[self.df_all['main_id'] == name, 'display_name'] = display_value

            display_entry = ttk.Entry(scrollable_frame, textvariable=display_name_var, width=32)
            display_entry.grid(row=i + 1, column=5, padx=2)

            def make_displayname_callback(n=name, var=display_name_var):
                def update_name(*args):
                    if hasattr(self, 'df_all') and isinstance(self.df_all, pd.DataFrame) and 'display_name' in self.df_all.columns:
                        self.df_all.loc[self.df_all['main_id'] == n, 'display_name'] = var.get()
                var.trace_add("write", update_name)
                return update_name()
            make_displayname_callback()

            def make_color_command(object_name=name, var=color_var, label=color_label):
                def change_color():
                    color = colorchooser.askcolor(color=var.get())[1]
                    if color:
                        var.set(color)
                        label.config(background=color)
                        self.custom_object_colors[object_name] = color
                    if hasattr(self, 'object_control_window') and self.object_control_window.winfo_exists():
                        self.object_control_window.lift()
                        self.object_control_window.focus_force()
                return change_color

            color_button = ttk.Button(scrollable_frame, text="Color", command=make_color_command())
            color_button.grid(row=i + 1, column=3, padx=5)

        # Customizeウィンドウ生成時のON/OFF状態をスナップショット
        try:
            names_in_window = set(dataframe['main_id'].astype(str).tolist())
            self._object_defaults_snapshot = {
                name: var.get()
                for name, var in self.visible_object_flags.items()
                if name in names_in_window
            }
        except Exception:
            self._object_defaults_snapshot = {name: var.get() for name, var in self.visible_object_flags.items()}

        bottom_frame = ttk.Frame(window)
        bottom_frame.pack(fill="x", pady=1)

        def reapply_with_confirmation():
            self.visible_object_names = [name for name, var in self.visible_object_flags.items() if var.get()]
            # ReApply は「フィルタなし・並び替えなし」だが、可視ONのものだけ描画
            self.apply_changes(from_cli=False, is_reapply=True)

        close_btn = ttk.Button(bottom_frame, text="Close", command=window.destroy)
        close_btn.pack(side="left", padx=5)

        reapply_btn = ttk.Button(bottom_frame, text="ReApply", command=reapply_with_confirmation)
        reapply_btn.pack(side="left", padx=5)

        after_label = ttk.Label(bottom_frame, text="after :")
        after_label.pack(side="left", padx=(10, 3))

        ttk.Button(bottom_frame, text="C", width=2, command=lambda: self.switch_image("combined")).pack(side="left", padx=2)
        ttk.Button(bottom_frame, text="O", width=2, command=lambda: self.switch_image("overlay")).pack(side="left", padx=2)
        ttk.Button(bottom_frame, text="T", width=2, command=lambda: self.switch_image("table")).pack(side="left", padx=2)
        ttk.Button(bottom_frame, text="N", width=2, command=lambda: self.switch_image("original")).pack(side="left", padx=2)

    def _select_objects(self, state: bool):
        for name, var in self.visible_object_flags.items():
            var.set(state)

    def _reset_object_defaults(self):
        """Customizeウィンドウの「Defaults」：ウィンドウ生成直後（またはCSV Replace直後）のON/OFF状態に戻す"""
        if getattr(self, "_object_defaults_snapshot", None):
            for name, var in self.visible_object_flags.items():
                if name in self._object_defaults_snapshot:
                    var.set(self._object_defaults_snapshot[name])
            return

        # フォールバック（スナップショットが無い場合）
        for name, var in self.visible_object_flags.items():
            default = False
            if hasattr(self, 'df_all') and self.df_all is not None:
                row = self.df_all[self.df_all['main_id'] == name]
                if not row.empty:
                    ctype = row.iloc[0]['TYPE']
                    if ctype in self.catalogs:
                        default = self.catalogs[ctype].selection_default
            var.set(default)

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
                lines = file.readlines()
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
        return logo_path, overlay_alpha, overlay_type, selected_catalogs

    def save_config_file(self, logo_path, overlay_alpha, overlay_type, selected_catalogs=None):
        config_dir = self.siril.get_siril_configdir()
        config_file_path = os.path.join(config_dir, CONFIG_FILENAME)
        try:
            with open(config_file_path, 'w') as file:
                file.write((logo_path or "") + "\n")
                file.write(f"{overlay_alpha:.2f}\n")
                file.write(overlay_type + "\n")
                if selected_catalogs is not None:
                    file.write(str(selected_catalogs) + "\n")
        except Exception as e:
            print(f"Error saving config file: {str(e)}")


def main():
    parser = argparse.ArgumentParser(description="Annotations script")
    parser.add_argument("-output", type=str, default=None, help="Output file name")
    parser.add_argument("-title", type=str, default="", help="Optional image title")
    parser.add_argument("-logo_path", type=str, default="", help="Optional logo image path")
    parser.add_argument("-overlay_alpha", type=float, default=0.6, help="Optional overlay alpha value")
    parser.add_argument("-overlay_type", type=str, default="circles", help="Optional type of annotation overlays to draw (circles, boxes)")

    args = parser.parse_args()

    try:
        if args.output is not None:
            AnnotationsScriptInterface(cli_args=args)
        else:
            siril = s.SirilInterface()
            try:
                siril.connect()
            except s.SirilConnectionError:
                messagebox.showerror("Error", "Sirilに接続できません。スクリプトを終了します。")
                return

            if not siril.is_image_loaded():
                messagebox.showerror("Error", "画像が開かれていません。\nSirilで画像を開いてから再実行してください。")
                siril.disconnect()
                return

            try:
                siril.pix2radec(0, 0)
            except ValueError:
                messagebox.showerror("Plate Solving Error", "現在開いている画像はプレートソルブされていません。\nプレートソルブ後保存した画像を開いてください。\nスクリプトを終了します。")
                siril.disconnect()
                return

            siril.disconnect()

            root = ThemedTk()
            root.geometry("550x550")
            AnnotationsScriptInterface(root)
            root.mainloop()

    except SirilError as e:
        print(f"Error initializing script: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
