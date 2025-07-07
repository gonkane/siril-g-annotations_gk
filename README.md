# Galaxy Annotation Script for Siril (Version 1.0.2-gk.1, by gonkane)

This is a customized version of a Python script that adds galaxy annotations to astronomical images in Siril.  
It is based on the original script created by Steffen Schreiber and Patrick Wagner.

This version includes multiple enhancements such as built-in catalog support and GUI improvements.

---

## Features

- Supports Siril's built-in catalogs (Messier, NGC, IC)
- Queries additional galaxies from Simbad (LEDA, UGC, etc.)
- Scrollable catalog list with per-catalog color selection
- Output includes:
  - Annotated overlay image with galaxy names
  - Thumbnail table of detected galaxies
  - Final combined image (overlay + table stacked vertically)
- GUI operation with Tkinter
- Executable from Siril's Python script launcher

---

## Requirements

- Siril version 1.4.0-beta2 or later
- Python modules (automatically requested by Siril if missing):
  - `sirilpy` (version 0.6.37 or later)
  - numpy, pandas, matplotlib, Pillow
  - astropy, astroquery, scikit-image, ttkthemes

---

## Screenshots

### GUI view

![Galaxy Annotation Script GUI](images/siril_gui.jpg)

### Example Output 1

![Example Output 1](images/sample1.png)

### Example Output 2

![Example Output 2](images/sample2.png)

---

## How to Use with Siril

### 1. Check Siril Version

This script requires Siril version 1.4.0-beta2 or later.  
You can check this from the "Help → About" menu in Siril.

---

### 2. Save the Script

Save `Galaxy_Annotations_102gk1.py` in any convenient folder of your choice.  
Example: `C:\Users\<YourName>\Documents\SirilScripts\`

---

### 3. Set Script Folder in Siril

1. Launch Siril  
2. Open the menu: "≡ → Preferences"  
3. Go to the "Scripts" tab  
4. Set the "Script directory" to the folder where you saved the script  
5. Click "Apply" to save and close the preferences

If you are unsure how to do this, you can also place the script in this default location:  
`C:\Users\<YourName>\AppData\Local\siril-scripts\utility`  
This folder usually contains the original `Galaxy_Annotations.py`.

---

### 4. Open a Plate-Solved Image

This script requires images that contain RA/DEC (celestial coordinate) information.  
Make sure your image has been plate-solved using Siril’s astrometry tool (e.g., ImageSolver).

---

### 5. Run the Script

1. In Siril, go to the menu: "Scripts → Python Scripts"  
2. Select `Galaxy_Annotations_102gk1.py` and run it

---

### 6. Configure and Generate Annotations

Once the script starts, a settings window will appear.

- **Title**: This will appear on the output image  
  (Note: Japanese characters may be rendered as boxes)  
- **Logo**: You can optionally add a PNG or JPEG image to the lower right of the thumbnail table  
- **Catalogs**: Select which catalogs to display, and assign colors

Click the **"Apply"** button to start processing.

---

### 7. Output Files

After processing, three image files will be created and saved in the same folder as the input image:

| File Name Example            | Description                            |
|-----------------------------|----------------------------------------|
| `annotated_M101_overlay.png` | Overlay image with galaxy annotations |
| `annotated_M101_table.png`   | Thumbnail table of detected galaxies  |
| `annotated_M101.png`         | Combined image (overlay + table)      |

You can choose which one to load back into Siril after generation.

---

## Notes

For the Messier, NGC, and IC catalogs, this script uses the built-in `.csv` files provided by Siril,  
which are typically located at:

C:/Program Files/Siril/share/siril/catalogue

The following files must be available in that directory:

- `messier.csv`
- `ngc.csv`
- `ic.csv`

If the script cannot find these files and encounters an error during execution,  
please search your system for `messier.csv` and update the script’s path accordingly.  
This path is defined near line 162 of the script file (`Galaxy_Annotations_102gk1.py`).

---

## Credits and License

This script is a customized version based on the following project:

- Original authors: Steffen Schreiber and Patrick Wagner  
- Original repository: <https://gitlab.com/schreiberste/siril-scripts>

This script is licensed under the **GNU General Public License v3 or later**.  
See the `LICENSE` file in this repository for full details.
