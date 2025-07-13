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
# Customized by: gonkane, 2025 — version 1.0.2-gk.2.2
# See version history below for details.
#
# License: GPL v3 or later (see LICENSE file for details)

"""
Galaxy Annotation Script for Siril (Custom Version 1.0.2-gk.2.2 by gonkane)

This is a respectful customization of the official Galaxy Annotations Script (v1.0.2),
originally developed by Steffen Schreiber and Patrick Wagner.

I deeply appreciate their excellent work. This version adds:

- Support for Siril's built-in catalogs (Messier, NGC, IC)
- Simbad and local catalog annotation integration
- GUI improvements including scrollable catalog list and color customization
- Improved patch size estimation using WCS-based angular radius

Please see the version history below for more information.
"""

# Version History

# --- Based on Official Version v1.0.2 ---
# See: https://gitlab.com/schreiberste/siril-scripts

# --- Custom Version History (by gonkane, 2025) ---
# 1.0.2-gk.1
#   - Added support for built-in Siril catalogs (Messier, NGC, IC)
#   - Integrated Simbad and local catalog annotation
#   - GUI improvements: scrollable catalog list, per-catalog color picker
#   - Refactored code structure for better flexibility
# 1.0.2-gk.2
#   - Improved patch size calculation using 4-direction WCS evaluation (RA±, DEC±)
#   - Ensured fallback behavior for objects without size data
# 1.0.2-gk.2.1
#   - Implemented C/O/T/N image switch buttons in GUI:
#       C = Combined image
#       O = Overlay image
#       T = Thumbnail table image
#       N = Original image
# 1.0.2-gk.2.2
#   - Fixed OverflowError when radec2pix returned inf or nan (Siril v1.4.0-beta3+ compatibility)
#   - Added check for non-finite pixel positions before conversion


# Core module imports
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
s.ensure_installed("astropy", "astroquery", "matplotlib", "numpy", "pandas", "Pillow", "scikit-image", "subprocess" )

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

VERSION = "1.0.2-gk.2.2"
CONFIG_FILENAME = "Galaxy_Annotations.conf"

def load_builtin_catalog(filepath, catalog_type):
    """
    カタログCSVファイルを読み込み、必要な列だけを整理して返す。
    引数:filepath (str): CSVファイルのパス。
        catalog_type (str): カタログ名（例: 'M', 'NGC' など）。
    戻り値:pd.DataFrame: 整理済みデータ（ra, dec, main_id, TYPE, galdim_majaxis を含む）。
    """
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

    return df

def annotate_fit(siril, fit, catalogs, output, title, logo_path, overlay_alpha, overlay_type):
    """
    The main processing function for creating the annotation images.
    Returns the number of found and annotated objects.
    """
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

    # --- Step 1: ローカルカタログ（M, NGC, IC）読み込み ---
    CATALOG_DIR = "C:/Program Files/Siril/share/siril/catalogue"
    catalog_files = {
        "M": os.path.join(CATALOG_DIR, "messier.csv"),
        "NGC": os.path.join(CATALOG_DIR, "ngc.csv"),
        "IC": os.path.join(CATALOG_DIR, "ic.csv")
    }
    df_list = []

    for key, filename in catalog_files.items():
        if catalogs.get(key) and catalogs[key].get_selected():
            df_cat = load_builtin_catalog(filename, key)
            df_list.append(df_cat)

    # --- Step 2: Simbad クエリ（M, NGC, IC以外のカタログ） ---
    EXCLUDED_SOURCES = ['M', 'NGC', 'IC']
    simbad_catalogs = [key for key in catalogs.keys()
                       if key not in EXCLUDED_SOURCES and catalogs[key].get_selected()]

    if simbad_catalogs:
        simbad = Simbad()
        simbad.TIMEOUT = 120
        simbad.add_votable_fields("otype", "galdim_majaxis")

        target_coord = SkyCoord(ra=center_ra, dec=center_dec, unit=(u.deg, u.deg), frame='icrs')
        (TL_ra, TL_dec) = siril.pix2radec(0, 0)
        radius_deg = max([abs(center_ra - TL_ra), abs(center_dec - TL_dec)])
        (pixsize_ra, pixsize_dec) = siril.pix2radec(1, 1)
        pixsize_arcmin = 60 * max([abs(pixsize_ra - TL_ra), abs(pixsize_dec - TL_dec)])
        minsize_arcmin = minsize_pixels * pixsize_arcmin 
        radius = f"{radius_deg}d"
        criteria_opt = f"otype='Galaxy..' AND (galdim_majaxis>{minsize_arcmin} OR (galdim_majaxis IS NULL))"

        print(f"Query radius: {radius}")
        print(f"      minimum size: {minsize_pixels} pixels ~ {minsize_arcmin}′")
        print(f"      criteria: {criteria_opt}")
        result_table = simbad.query_region(target_coord, radius, criteria=criteria_opt)
        result_table.sort("galdim_majaxis", reverse=True)
        df_simbad = result_table.to_pandas()
        print(f"Simbad query results: {df_simbad.shape[0]} entries")

        import re
        df_simbad['TYPE'] = df_simbad['main_id'].apply(
            lambda x: re.match(r'^([A-Za-z0-9]+)', str(x)).group(1) if re.match(r'^([A-Za-z0-9]+)', str(x)) else 'Unknown'
        )

        # M, NGC, IC を除外
        df_simbad = df_simbad[~df_simbad['TYPE'].isin(catalog_files.keys())]
        df_list.append(df_simbad)

    # --- Step 3: すべてのデータを結合 ---
    if not df_list:
        print("No catalog data loaded.")
        return 0

    df = pd.concat(df_list, ignore_index=True)

    # --- Step 4: ピクセル位置を計算し、画面内でフィルタ ---
    import warnings
    from astropy.utils.exceptions import AstropyWarning

    # 警告を抑制
    warnings.filterwarnings("ignore", category=UserWarning, message=".*all_world2pix.*")
    warnings.filterwarnings("ignore", category=AstropyWarning)

    # 変換失敗リストを保持
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

    # 無効な座標（nan, inf）を除外
    df = df[df['Pixel_Position'].apply(lambda x: np.isfinite(x[0]) and np.isfinite(x[1]))]

    # ピクセル座標へ変換
    df['px'] = df['Pixel_Position'].apply(lambda x: int(round(x[0])))
    df['py'] = df['Pixel_Position'].apply(lambda x: int(round(x[1])))

    # 画像サイズ内にあるものだけに絞る
    df = df[(df.px > min_patch_size) & (df.py > min_patch_size)
          & (df.px < W - min_patch_size) & (df.py < H - min_patch_size)]

    print(f"Filtered query result by image coordinates: {df.shape[0]} entries")


    # カタログ名でフィルタ処理
    import re
    def extract_catalog_type(name):
        match = re.match(r'^(M|NGC|IC)', name.upper())
        return match.group(1) if match else 'OTHER'

    filter_types = []
    for key, value in catalogs.items():
        if value.get_selected():
            filter_types.append(key)

    # カタログ名でフィルタ
    filtered_result = Table.from_pandas(df[df['TYPE'].isin(filter_types)])
    dfi = filtered_result.to_pandas()
    print(f"Filtered by catalog: {dfi.shape[0]} entries")

    # remove duplicates
    dfi = dfi.drop_duplicates(subset=['px', 'py'])
    print(f"Filtered after removing duplicates: {dfi.shape[0]} entries")

    if dfi.shape[0] == 0:
        print("No objects found in image boundary.")
        return 0

    sub = 1
    dpi = 200
    # sorting order from catalogs list position
    rep_dic = {}
    for i, key in enumerate(catalogs.keys()):
        rep_dic[key] = f"{i:02d}"
        
    dfi['sorting'] = dfi.TYPE.replace(rep_dic)
    dfi.main_id = dfi.main_id.apply(lambda x: x.replace(' ', ''))
    dfi = dfi.sort_values(['sorting', 'main_id'], ascending=True).reset_index()
    # dfi = dfi.sort_values(['galdim_majaxis', 'main_id'], ascending=False).reset_index()
    # print(dfi)

    # set up the plot
    plt.style.use('dark_background')
    # figure size in inch for the upper image with overlays
    # Try to get roughly the size of the input image...
    extra_axis_label_size_inches = 1.15 # estimated extra size for axis labels
    fig = plt.figure(
        figsize=(W / dpi + extra_axis_label_size_inches, H / dpi + extra_axis_label_size_inches))
    ax1 = plt.subplot(projection=wcs, label='overlays')
    ax1.imshow(img[::sub, ::sub])
    ax1.coords.grid(True, color='white', ls=':', alpha=overlay_alpha)
    ax1.coords[0].set_axislabel('Right Ascension (J2000)')
    ax1.coords[1].set_axislabel('Declination (J2000)', minpad=-1)
    ax1.set_title(title, fontsize=24)

    all_patches = []
    filter_idxs = []
    
    for i, row in dfi.iterrows():
        siril.update_progress(f"Creating patches", i / (10 * dfi.shape[0]))
        # default style
        fontsize = 12
        try:
            color = catalogs[row.TYPE].color
        except KeyError:
            color = '#ff0000'
        
        # try to derive the patch size from galaxy angular size
        angular_size = row.galdim_majaxis
        size_factor = 2

        # fallback for missing sizes
        if math.isnan(angular_size):
            angular_size = 0
            if row.TYPE == 'M':
                if row.main_id == "M8":
                    angular_size = 90
                elif row.main_id == "M40":
                    angular_size = 0.86
                elif row.main_id == "M43":
                    angular_size = 20
                elif row.main_id == "M78":
                    angular_size = 8
                elif row.main_id == "M82":
                    angular_size = 11.2

        if angular_size == 0:
            patch_size = min_patch_size
            patch_diameter_pix = min_patch_size
        else:
            try:
                half_diam_deg = (angular_size / 2.0) / 60.0  # arcmin → deg

                # 四方向の端点（RA±, DEC±）
                coord_top = SkyCoord(ra=row.ra * u.deg, dec=(row.dec + half_diam_deg) * u.deg)
                coord_bottom = SkyCoord(ra=row.ra * u.deg, dec=(row.dec - half_diam_deg) * u.deg)
                coord_left = SkyCoord(ra=(row.ra - half_diam_deg) * u.deg, dec=row.dec * u.deg)
                coord_right = SkyCoord(ra=(row.ra + half_diam_deg) * u.deg, dec=row.dec * u.deg)

                # ピクセル座標変換
                px_top, py_top = siril.radec2pix(coord_top.ra.deg, coord_top.dec.deg)
                px_bottom, py_bottom = siril.radec2pix(coord_bottom.ra.deg, coord_bottom.dec.deg)
                px_left, py_left = siril.radec2pix(coord_left.ra.deg, coord_left.dec.deg)
                px_right, py_right = siril.radec2pix(coord_right.ra.deg, coord_right.dec.deg)

                # 2方向のピクセル距離
                d_dec = math.hypot(px_top - px_bottom, py_top - py_bottom)
                d_ra = math.hypot(px_right - px_left, py_right - py_left)

                # 平均直径をピクセルで算出
                patch_diameter_pix = (d_dec + d_ra) / 2.0

                # パッチサイズ（整数）を決定
                patch_size = int(round(patch_diameter_pix * size_factor))
                patch_size = max(min_patch_size, patch_size)

            except Exception as e:
                siril.log(f"{row.main_id}: WCS radius estimation failed: {e}", color=s.LogColor.RED)
                patch_size = min_patch_size
                patch_diameter_pix = min_patch_size
                    
        # type dependent style
        if row.main_id == main_object:
            fontsize=20
            color = 'white'
        elif row.TYPE == 'M':
            fontsize = 18
        elif row.TYPE == 'NGC':
            fontsize = 18
        elif row.TYPE == 'SAI':
            fontsize = 16
        elif row.TYPE == 'UGC':
            fontsize = 16
        elif row.TYPE == 'MCG':
            fontsize = 16
        elif row.TYPE == 'IC':
            fontsize = 16
        elif row.TYPE == 'LEDA':
            # LEDA apparently often has large errors on galdim_majaxis
            # resulting in much too large patches. Usually, LEDA galaxies
            # are small...
            if not math.isnan(row.galdim_majaxis) and row.galdim_majaxis > 1.8:
                patch_size = min_patch_size
                patch_diameter_pix = min_patch_size
                print(f"Unlikely large LEDA galaxy {row.main_id}: {row.galdim_majaxis} -> patch size {patch_size}")

        annotation_text = str(i + 1)
        if patch_size > 200:
            annotation_text = f"{annotation_text}: {row.main_id}"
        
        # clip the patch size on image borders
        clipped = min(patch_size, (W - row.px) * 2)
        clipped = min(clipped, (H - row.py) * 2)
        clipped = min(clipped, row.px * 2)
        clipped = min(clipped, row.py * 2)
        
        x1 = row.px - clipped // 2
        x2 = row.px + clipped // 2
        y1 = H-row.py - clipped // 2
        y2 = H-row.py + clipped // 2
        
        if overlay_type == "boxes":
            # annotation rectangle
            rect = Rectangle((x1, y1), x2-x1, y2-y1, 
                alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
            ax1.add_patch(rect)
            text_y = y1 - 6
            v_align = 'top'
            if text_y < 0:
                text_y = min(y2 + 6, H - (3*fontsize))
                v_align = 'bottom'
        else:
            # annotation circle
            annot_radius = max(min_patch_size, 1.2 * patch_diameter_pix / 2.0) 
            circ = Circle((row.px, H-row.py), radius=annot_radius,
                alpha=overlay_alpha, linewidth=1, edgecolor=color, facecolor='none')
            ax1.add_patch(circ)
            text_y = H-row.py - 6 - annot_radius
            v_align = 'top'
            if text_y < 0:
                text_y = min(H-row.py + 6  + annot_radius, H - (3*fontsize))
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

    overlay_image = plt.imread(output_overlay_fname)

    # Resize and process patches
    new_patch_size = 512  # Adjust the patch size to your desired resolution

    siril.update_progress("Resizing patch images...", 0.4)
    all_patches_resized = [resize(patch, (new_patch_size, new_patch_size)) for patch in all_patches]
    all_patches = np.array(all_patches_resized)
    siril.update_progress("Patch images resized.", 0.5)

    # Define the scale for the subplots
    scale = 3  # inches per patch

    # Calculate numbers of rows and columns
    n = len(all_patches)
    mincols = 6 if (logo_path != "") else 5 
    ncols = max(mincols, int(np.floor(np.sqrt(n))))
    nrows = int(np.ceil(n / ncols))
    print(f"Grid size: nrows={nrows}, ncols={ncols}")

    # Create the subplots with the adjusted dimensions
    fig, axarr = plt.subplots(nrows, ncols, figsize=(ncols * scale, nrows * scale))

    # Create a filtered DataFrame with the desired indices
    dft = dfi.iloc[filter_idxs].reset_index()

    for i, row in dft.iterrows():
        if nrows > 1:
            ax = axarr[i // ncols, i % ncols]
        else:
            ax = axarr[i]

        try:
            color = catalogs[row.TYPE].color
        except KeyError:
            color = '#ff0000'
                
        ax.imshow(all_patches[i][::-1])
        ax.set_title(row.main_id, fontsize=12, color=color)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_edgecolor(color)
        ax.text(2, 2, str(i + 1), ha='left', va='top', color='white', fontsize=18)

    for i in range(n, nrows * ncols):
        if nrows > 1:
            ax = axarr[i // ncols, i % ncols]
        else:
            ax = axarr[i]
        ax.axis('off')

    # If logo is requested, put it in the last grid cell
    # (as long as the cell is free)
    if (logo_path != "") and (nrows * ncols > n):
        logo_img = plt.imread(logo_path)
        if nrows > 1:
            axarr[nrows - 1, ncols - 1].imshow(logo_img)
        else:
            axarr[ncols - 1].imshow(logo_img)

    siril.update_progress("Creating thumbnail table...", 0.6)
    plt.tight_layout()
    plt.savefig(output_table_fname, bbox_inches='tight', pad_inches=.1, dpi=dpi)
    siril.update_progress("Saved thumbnail table image.", 0.7)

    table_image = plt.imread(output_table_fname)

    # Resize table_image to match overlay_image dimensions
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
    
    return dfi.shape[0]
    
def get_output_filename(output_basename, suffix=''):
    filename, extension = os.path.splitext(output_basename)
    if extension == '':
        extension = '.png'
    else:
        # is extension a supported output formats for matplotlib savefig?
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
    """ This class provides properties of a catalog entry """
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
    """ This class provides the GUI and related callbacks """
    def __init__(self, root=None, cli_args=None):
        # If no CLI args, create a default namespace with defaults
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
        
        # Catalog definitions
        self.catalogs = {
            'M': CatalogEntry('Messier Catalog', '#80ff80', True), 
            'IC': CatalogEntry('Index Catalogue', '#80ffff', True),
            'NGC': CatalogEntry('New General Catalogue', '#ffffff', True),
            'MGC': CatalogEntry('Millennium Galaxy Catalogue', '#30a500', False),
            'UGC': CatalogEntry('Uppsala General Catalogue', '#3abed1', False),
            'MCG': CatalogEntry('Morphological Catalogue of Galaxies', '#955ec2', False),
            'Mrk': CatalogEntry('Markarian galaxies', '#fbbd70', False),
            'LEDA': CatalogEntry('Lyon-Meudon Extragalactic Database', '#c29d94', False),
            'Z': CatalogEntry('Zwicky Catalogue of galaxies and of clusters of galaxies', '#fb9795', False),
            'Gaia': CatalogEntry('Gaia catalogues', '#c6aed8', False),
            '2MASX': CatalogEntry('Two Micron All Sky Survey, Extended source catalogue', '#895447', False),
            'SDSS': CatalogEntry('Sloan Digital Sky Survey', '#b2c5eb', False),
            'SDSSCGB': CatalogEntry('SDSS DR6 Compact Group Catalogue B', '#b2c5eb', False),
            'UGCA': CatalogEntry('Uppsala Selected non-UGC Galaxies', '#f5b3d3', False),
            'MASS': CatalogEntry(None, '#c8c8c8', False),
            'MFGC': CatalogEntry(None, '#b9c200', False),
            '2MFGC': CatalogEntry('2MASS Flat Galaxy Catalog', '#d9df85', False),
            'FIRST': CatalogEntry('FIRST Survey Catalogs', '#a3dae7', False),
            '2MASS': CatalogEntry('Two Micron All Sky Survey', '#895447', False)
        }

        if root:
            self.root.title(f"Galaxy Annotations Script - v{VERSION}")
            self.root.resizable(False, False)
            self.style = tksiril.standard_style()

        # Initialize Siril connection
        self.siril = s.SirilInterface()

        try:
            self.siril.connect()
        except s.SirilConnectionError:
            if root:
                self.siril.error_messagebox("Failed to connect to Siril")
            else:
                print("Failed to connect to Siril")
            return

        # Initial checks: example - check if an image is loaded
        if not self.siril.is_image_loaded():
            if root:
                self.siril.error_messagebox("No image is loaded")
            else:
                print("No image is loaded")
            return
            
        # Check if the version of Siril is high enough
        try:
            self.siril.cmd("requires", "1.4.0-beta2")
        except s.CommandError:
            return

        if self.cli_args.output is None:
            # get the default output file name from input image file name
            basename = os.path.basename(self.siril.get_image_filename())
            filename, extension = os.path.splitext(basename)
            self.cli_args.output = "annotated_" + filename 

        if self.cli_args.title is None:
            # get the default title from the file name
            basename = os.path.basename(self.siril.get_image_filename())
            filename, extension = os.path.splitext(basename)
            self.cli_args.title = filename 

        # Initialization to do in GUI mode...
        if root:
            # load options from config file
            logo_path, overlay_alpha, overlay_type, selected_catalogs = self.load_config_file()
            self.cli_args.logo_path = logo_path
            self.cli_args.overlay_alpha = overlay_alpha
            self.cli_args.overlay_type = overlay_type
            # Create the UI and match its theme to Siril
            self.create_widgets()
            tksiril.match_theme_to_siril(self.root, self.siril)

            # Sirilで現在開いている元画像を記録
            self._original_image = self.siril.get_image_filename()
            print("Original image at GUI startup:", self._original_image)
            
        # Only apply changes if in CLI mode
        if self.siril.is_cli():
            print("Apply changes from CLI")
            self.apply_changes(from_cli=True)

    def _browse_logo_file(self):
        """
        Use a TK filedialog to browse for the logo file.
        """
        filename = filedialog.askopenfilename(
            title="Select a Logo Image File",
            initialdir=os.path.expanduser("~"),
            filetypes=[("Image file",".png .jpg .jpeg .ico .bmp .gif")]
        )
        if filename:
            self.logo_path.set(filename)
            # update config file
            self.save_config_file(filename, self.overlay_alpha_var.get(), self.overlay_type_var.get(), None)

    def create_widgets(self):
        """Create the GUI's widgets, connect signals etc. """
        # Main frame with no padding
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Title
        title_label = ttk.Label(
            main_frame,
            text="Galaxy Annotations Script",
            style="Header.TLabel"
        )
        title_label.pack(pady=(0, 5))
        version_label = ttk.Label(main_frame, text=f"Script version: {VERSION}")
        version_label.pack(pady=(0, 0))

        # Separator
        sep = ttk.Separator(main_frame, orient='horizontal')
        sep.pack(fill=tk.X, pady=5)

        # Parameters frame
        params_frame = ttk.LabelFrame(main_frame, text="Output", padding=10)
        params_frame.pack(fill=tk.BOTH, padx=5, pady=5)
        params_frame.columnconfigure(1, weight=1)  # use all space in col 1
        
        # image title
        row = 0
        titlelbl = ttk.Label(params_frame, text="Title: ")
        titlelbl.grid(column=0, row=row, sticky="WENS")
        self.title = tk.StringVar(self.root, value=self.cli_args.title)
        title_entry = ttk.Entry(params_frame, textvariable=self.title)
        title_entry.grid(column=1, row=row, sticky="WENS", padx=2, pady=2)
        ttk.Label(params_frame, text="").grid(column=2, row=row, sticky="WENS")

        # Logo file selection
        row = row + 1
        logolbl = ttk.Label(params_frame,text="Logo: ")
        logolbl.grid(column=0, row=row, sticky="WENS")
        self.logo_path = tk.StringVar(self.root, value=self.cli_args.logo_path)
        logo_file_entry = ttk.Entry(params_frame, textvariable=self.logo_path)
        logo_file_entry.grid(column=1, row=row, sticky="WENS", padx=2, pady=2)
        
        browsebtn = ttk.Button(params_frame, text="Browse", command=self._browse_logo_file, style="TButton")
        browsebtn.grid(column=2, row=row, sticky="W")

        # Output file name
        row = row + 1
        output_label = ttk.Label(params_frame, text="Output file: ")
        output_label.grid(column=0, row=row, sticky="WENS")
        self.output = tk.StringVar(self.root, value=self.cli_args.output)
        output_file_entry = ttk.Entry(params_frame, textvariable=self.output)
        output_file_entry.grid(column=1, row=row, sticky="WENS", padx=2, pady=2)

        # Overlay settings
        overlay_settings_label = ttk.Label(params_frame, text="Overlay: ")
        overlay_settings_label.grid(column=0, row=row, sticky="WENS")

        overlay_alpha_frame = ttk.Frame(params_frame)
        overlay_alpha_frame.grid(column=1, row=row, sticky="WENS")
        alpha_label = ttk.Label(overlay_alpha_frame, text="Alpha:")
        alpha_label.pack(side=tk.LEFT, padx=5)
        
        self.overlay_alpha_var = tk.DoubleVar(value=self.cli_args.overlay_alpha)
        overlay_alpha_slider = ttk.Scale(overlay_alpha_frame,
            from_=0.0, to=1.0, orient=tk.HORIZONTAL,
            variable=self.overlay_alpha_var
        )
        overlay_alpha_slider.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tksiril.create_tooltip(overlay_alpha_slider, "Adjust the visibility of "
                "the annotation overlays. Smaller values result in more "
                "transparent overlays.")
        self.overlay_alpha_label = ttk.Label(overlay_alpha_frame, text=f"{self.cli_args.overlay_alpha}")
        self.overlay_alpha_label.pack(side=tk.RIGHT, padx=5)
        self.overlay_alpha_var.trace_add("write", self._update_alpha_label)

        self.overlay_type_var = tk.StringVar(self.root, value=self.cli_args.overlay_type)
        overlay_type_cb = ttk.Combobox(params_frame, 
            textvariable=self.overlay_type_var,
            values = ('circles', 'boxes'),
            state="readonly", justify='center', width=5)
        overlay_type_cb.grid(column=2, row=row, sticky="WENS")
        tksiril.create_tooltip(overlay_type_cb, 
            "The type of annotations to draw around galaxies.")


        # Load in Siril options
        row = row + 1
        loadlbl = ttk.Label(params_frame, text="Load in Siril: ")
        loadlbl.grid(column=0, row=row, sticky="WENS")
        self.load_in_siril = tk.StringVar(None, 'C')
        load_frame = ttk.Frame(params_frame)
        load_frame.grid(column=1, row=row, columnspan=2, sticky="WENS")
        rbtn = ttk.Radiobutton(load_frame, text='Combined', value='C', variable=self.load_in_siril)
        rbtn.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(rbtn, "Load the combined result image in Siril")
        rbtn = ttk.Radiobutton(load_frame, text='Overlay', value='O', variable=self.load_in_siril)
        rbtn.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(rbtn, "Load the result image with annotation overlays in Siril")
        rbtn = ttk.Radiobutton(load_frame, text='Table', value='T', variable=self.load_in_siril)
        rbtn.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(rbtn, "Load the thumbnail table image in Siril")
        rbtn = ttk.Radiobutton(load_frame, text='None', value='', variable=self.load_in_siril)
        rbtn.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(rbtn, "Just create output files without loading anything in Siril")

        # スクロール対応カタログセクション
        catalogs_frame = ttk.LabelFrame(main_frame, text="Catalogs", padding=0)
        catalogs_frame.pack(fill=tk.BOTH, padx=5, pady=0, expand=True)

        # ★スクロール領域を分けるための「内部フレーム」追加
        catalogs_scroll_frame = ttk.Frame(catalogs_frame)
        catalogs_scroll_frame.pack(fill=tk.BOTH, expand=True)

        # CanvasとScrollbarを作成
        canvas = tk.Canvas(catalogs_frame, height=300)  # 高さを制限（必要に応じて調整）
        scrollbar = ttk.Scrollbar(catalogs_frame, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)

        # スクロール内のFrame（カタログをここに並べる）
        catalogs_inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=catalogs_inner, anchor="nw")

        # カタログチェック・色ボタンなどを catalogs_inner に追加する
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

        # canvas に catalogs_inner を追加したあと
        inner_window = canvas.create_window((0, 0), window=catalogs_inner, anchor="nw")

        # frame内での列伸縮
        catalogs_inner.grid_columnconfigure(1, weight=1)

        # 高さ・スクロール範囲を自動で調整
        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        catalogs_inner.bind("<Configure>", _on_frame_configure)

        # 横幅をcanvasに合わせる
        def _on_canvas_resize(event):
            canvas.itemconfig(inner_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_resize)
            
        # スクロール領域サイズを自動調整
        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1*(event.delta/120)), "units"))

        catalogs_inner.bind("<Configure>", _on_frame_configure)
            
        # buttons for mass- (de-) selection
        select_frame = ttk.Frame(main_frame)  # catalogs_frame → main_frame に変更
        select_frame.pack(fill="x", pady=5)   # pack を使って下に固定表示

        ttk.Label(select_frame, text="Select: ").grid(row=0, column=0, padx=5)
        select_all_btn = ttk.Button(select_frame, text="All", command=self.select_all)
        select_all_btn.grid(row=0, column=1, padx=2)
        select_none_btn = ttk.Button(select_frame, text="None", command=self.select_none)
        select_none_btn.grid(row=0, column=2, padx=2)
        select_default_btn = ttk.Button(select_frame, text="Defaults", command=self.select_default)
        select_default_btn.grid(row=0, column=3, padx=2)

        # Separator
        sep2 = ttk.Separator(main_frame, orient='horizontal')
        sep2.pack(fill=tk.X, pady=5)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(pady=10)

        close_btn = ttk.Button(
            button_frame,
            text="Close",
            command=self.close_dialog,
            style="TButton"
        )
        close_btn.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(close_btn, "Close, no changes will be made to the current image.")

        apply_btn = ttk.Button(
            button_frame,
            text="Apply",
            command=self.apply_changes,
            style="TButton"
        )
        apply_btn.pack(side=tk.LEFT, padx=5)
        tksiril.create_tooltip(apply_btn, "Create the annotated output image")

        # 「after :」ラベル
        after_label = ttk.Label(button_frame, text="after :")
        after_label.pack(side=tk.LEFT, padx=(10, 3))  # 少し余白をつけて左寄せ

        # C: Combined
        btn_c = ttk.Button(button_frame, text="C", width=2, command=lambda: self.switch_image("combined"))
        btn_c.pack(side=tk.LEFT, padx=2)
        tksiril.create_tooltip(btn_c, "Show Combined Image")

        # O: Overlay
        btn_o = ttk.Button(button_frame, text="O", width=2, command=lambda: self.switch_image("overlay"))
        btn_o.pack(side=tk.LEFT, padx=2)
        tksiril.create_tooltip(btn_o, "Show Overlay Image")

        # T: Table
        btn_t = ttk.Button(button_frame, text="T", width=2, command=lambda: self.switch_image("table"))
        btn_t.pack(side=tk.LEFT, padx=2)
        tksiril.create_tooltip(btn_t, "Show Table Image")

        # N: Original
        btn_n = ttk.Button(button_frame, text="N", width=2, command=lambda: self.switch_image("original"))
        btn_n.pack(side=tk.LEFT, padx=2)
        tksiril.create_tooltip(btn_n, "Show Original Image")

    def choose_color(self, catalog_key):
        current_color = self.catalogs[catalog_key].color_var.get()
        color_code = colorchooser.askcolor(title=f"Choose color for {catalog_key}", color=current_color)
        if color_code[1] is not None:
            self.catalogs[catalog_key].color_var.set(color_code[1])
            self.catalogs[catalog_key].color = color_code[1]
            if hasattr(self.catalogs[catalog_key], "color_label"):
                self.catalogs[catalog_key].color_label.config(background=color_code[1])

    def apply_changes(self, from_cli=False):
        """
        Get the necessary variables from CLI args or the GUI and call the algorithm
        """
        try:
            # 元画像を記録（切り替えボタンN用）
            self._original_image = self.siril.get_image_filename()

            # Get the thread
            with self.siril.image_lock():
                # Determine parameters: prefer CLI args if provided,
                # else use GUI values
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
                    # update config file
                    self.save_config_file(logo_path, overlay_alpha, overlay_type, None)

                # Get current image
                fit = self.siril.get_image()
                fit.ensure_data_type(np.float32)

                # ensure is plate solved
                try:
                    self.siril.pix2radec(0, 0)
                except ValueError:
                    self.siril.log("The image is not plate solved", color=s.LogColor.RED)
                    if not from_cli:
                        self.siril.error_messagebox("The image is not plate solved")
                    return

                # Create the annotated image
                found = annotate_fit(self.siril, fit, self.catalogs, output, title, logo_path, overlay_alpha, overlay_type)
                
                if found > 0:
                    self.siril.log("Annotations image created successfully.", color=s.LogColor.RED)
                    # Optionally load the annotated image in Siril
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

    def switch_image(self, kind):  # 👈 この位置でOK！
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
        """ Close dialog """
        if hasattr(self, 'root'):
            self.root.quit()
            self.root.destroy()
            
    def select_all(self):
        """ Select all catalogs """
        for key, value in self.catalogs.items():
            value.checkbox_var.set(True)
    
    def select_none(self):
        """ Select no catalogs """
        for key, value in self.catalogs.items():
            value.checkbox_var.set(False)

    def select_default(self):
        """ Select default set of catalogs """
        for key, value in self.catalogs.items():
            value.checkbox_var.set(value.selection_default)

    def _update_alpha_label(self, *args):
        """Update the overlay alpha value label when slider changes"""
        self.overlay_alpha_label.config(text=f"{self.overlay_alpha_var.get():.2f}")

    def load_config_file(self):
        """
        Check for a saved options in the configuration file.
        Returns (logo_path, overlay_alpha, overlay_type, selected_catalogs) or default values if not found.
        """
        config_dir = self.siril.get_siril_configdir()
        config_file_path = os.path.join(config_dir, CONFIG_FILENAME)
        logo_path = None
        overlay_alpha = 0.6
        overlay_type = "circle"
        selected_catalogs = None
        if os.path.isfile(config_file_path):
            with open(config_file_path, 'r') as file:
                lines = file.readlines()
                if len(lines) > 0:
                    logo_path = lines[0].strip()
                    if not os.path.isfile(logo_path):
                        logo_path = None
                if len(lines) > 1:
                    overlay_alpha = float(lines[1].strip())
                if len(lines) > 2:
                    overlay_type = lines[2].strip()
                if len(lines) > 3:
                    selected_catalogs = lines[2].strip()
        return logo_path, overlay_alpha, overlay_type, selected_catalogs

    def save_config_file(self, logo_path, overlay_alpha, overlay_type, selected_catalogs=None):
        """
        Save the options to the configuration file.
        """
        config_dir = self.siril.get_siril_configdir()
        config_file_path = os.path.join(config_dir, CONFIG_FILENAME)
        try:
            with open(config_file_path, 'w') as file:
                file.write(logo_path + "\n")
                file.write(f"{overlay_alpha:.2f}" + "\n")
                file.write(overlay_type + "\n")
                if selected_catalogs is not None:
                    file.write(str(selected_catalogs) + "\n")
        except Exception as e:
            print(f"Error saving config file: {str(e)}")

def main():
    """ Main entry point """
    parser = argparse.ArgumentParser(description="Annotations script")
    parser.add_argument("-output", type=str, default=None,
                        help="Output file name")
    parser.add_argument("-title", type=str, default="",
                        help="Optional image title")
    parser.add_argument("-logo_path", type=str, default="",
                        help="Optional logo image path")
    parser.add_argument("-overlay_alpha", type=float, default=0.6,
                        help="Optional overlay alpha value")
    parser.add_argument("-overlay_type", type=str, default="circles",
                        help="Optional type of annotation overlays to draw (circles, boxes)")

    args = parser.parse_args()

    try:
        if args.output != None:
            # CLI mode
            AnnotationsScriptInterface(cli_args=args)
        else:
            # GUI mode
            root = ThemedTk()
            root.geometry("550x640") # 追加
            AnnotationsScriptInterface(root)
            root.mainloop()
    except SirilError as e:
        print(f"Error initializing script: {str(e)}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
