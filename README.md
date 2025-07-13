# Siril用 Galaxy Annotationsスクリプト（バージョン 1.0.2-gk.2.2 作成者 gonkane）

このスクリプトは、Siril v1.4.0-beta 用に Steffen Schreiber 氏および Patrick Wagner 氏によって開発された Python スクリプト「Galaxy_Annotations.py」バージョン 1.0.2 をもとに、gonkane が改良を加えたものです。

元のプロジェクトは以下の GitLab で公開されています：
https://gitlab.com/schreiberste/siril-scripts

このスクリプトは、Simbad データベースから天体情報を取得し、  
Siril 上の天体画像にアノテーション（天体名など）を重ねて表示する高機能なツールです。  
元の作者の方々の優れた開発と公開に深く感謝いたします。

---

## 追加機能一覧

- Messier、NGC、IC の一部天体が正しくアノテーションされない問題に対応（Siril 内蔵カタログに切り替え）
- カタログごとに色を自由に設定可能
- GUI 上のカタログ一覧を縦スクロール対応に改善
- アノテーションサイズの計算を改良（RA±、DEC±の 4方向評価による WCS ベースの処理）
- サイズ情報がない天体に対するフォールバック処理を追加
- GUI にて、作成後の画像を切り替える C / O / T / N ボタン を追加
　C：合成画像　O：オーバーレイ画像　T：天体サムネイル表画像　N：元画像（処理前の FITS）

---

## 対応環境

- Siril バージョン 1.4.0-beta2 以上
- Pythonモジュール（Sirilが自動でインストールまたは要求する）：
  - sirilpy（バージョン 0.6.37 以上）
  - numpy, pandas, matplotlib, Pillow
  - astropy, astroquery, scikit-image, ttkthemes

---

## スクリーンショット

### GUI画面

![Galaxy Annotation Script GUI](images/102gk2_1/siril_gui_102gk2_1.jpg)

### 出力例 1

![Example Output 1](images/102gk2_2/sample1_102gk2_2.jpg)

### 出力例 2

![Example Output 2](images/102gk2_2/sample2_102gk2_2.jpg)

---

## Siril での使い方（準備から実行まで）

### 1. Siril のバージョン確認

このスクリプトは Siril v1.4.0-beta2 以降で動作します。  
Siril のメニュー「ヘルプ → バージョン情報」で確認してください。

---

### 2. スクリプトを保存する

`Galaxy_Annotations_102gk1.py` を、任意の使いやすいフォルダに保存します。  
例： `C:\Users\<あなたの名前>\Documents\SirilScripts\`

---

### 3. Siril にスクリプトの保存先を設定する

1. Siril を起動  
2. メニューから「≡ → 環境 設定」を開く  
3. 「スクリプト」タブを開く  
4. 「スクリプト保存ディレクトリ」の欄に、上で保存したフォルダのパスを入力する  
5. 「適用」を押して環境設定を閉じる  

もしこの設定の仕方がよく分からない場合は、通常であれば  
`C:\Users\（ユーザー名）\AppData\Local\siril-scripts\utility`  
の中に元の `Galaxy_Annotations.py` があるので、そこに `Galaxy_Annotations_102gk2_1.py` を置いておくだけでも問題ありません。

---

### 4. 星の位置情報が付与された画像を開く

このスクリプトは赤経・赤緯（RA/DEC）情報をもとに銀河の位置を特定するため、  
必ずSirilのアストロメトリーなどで星の位置情報が付与された画像を使用してください。

---

### 5. スクリプトを実行する

1. Siril のメニューから「スクリプト → Python Scripts」を選択  
2. `Galaxy_Annotations_102gk2_1.py` を選んで実行  

---

### 6. 設定してアノテーションを生成

設定ウィンドウが表示されます：

- Title：作成画像に表示される名前
　日本語が入っているとその部分は四角になります。
- Logo：指定したJPEGやPNG画像を天体一覧の右下に追加する
- 表示したいカタログ：チェックを入れて選択、色もカスタマイズ可能

すべて設定したら「Apply」ボタンをクリックしてください。

---

### 7. 出力ファイルについて

画像処理が完了すると、次の3種類の画像が出力されます（元画像と同じフォルダに保存されます）：

| ファイル名例                  | 内容                             |
|------------------------------|----------------------------------|
| `annotated_M101_overlay.png` | 天体アノテーション付きの画像     |
| `annotated_M101_table.png`   | 検出された天体のサムネイル表     |
| `annotated_M101.png`         | 上記2枚を縦に結合した最終画像     |

Siril の画面でどれを読み込むかを選ぶオプションも用意されています。

---

## 注意点

Messier、NGC、IC のデータについては、Siril に内蔵されている以下の `.csv` ファイルを使用します：

C:/Program Files/Siril/share/siril/catalogue


この中に次のファイルが存在する必要があります：

- `messier.csv`
- `ngc.csv`
- `ic.csv`

スクリプト実行時にこれらのファイルが見つからずエラーが発生する場合は、  
お使いのPC内で `messier.csv` を検索し、スクリプト内の該当パス（約166行目）を実際の場所に合わせて修正してください。

---

## バージョン履歴

### 最新バージョン：[Galaxy_Annotations_102gk2_2.py](Galaxy_Annotations_102gk2_2.py)
- バージョン: 1.0.2-gk.2.2
- radec2pix() が inf や nan を返す場合に発生していた OverflowError を修正
- ピクセル座標変換時に非有限値（NaN、Inf）を除外するチェックを追加
- 以上の修正で Siril v1.4.0-beta3 に対応

### 最新バージョン：[Galaxy_Annotations_102gk2_1.py](Galaxy_Annotations_102gk2_1.py)
- バージョン: 1.0.2-gk.2.1
- C/O/T/N ボタンによる画像切替機能を GUI に追加
- 現在はこちらの使用を推奨します

### 旧バージョン：[Galaxy_Annotations_102gk2.py](Galaxy_Annotations_102gk2.py)
- バージョン: 1.0.2-gk.2  
- RA±・DEC± の 4方向評価に基づくアノテーションサイズの計算を改良

### 旧バージョン：[Galaxy_Annotations_102gk1.py](Galaxy_Annotations_102gk1.py)
- 最初に公開したバージョンです

---

## 著作権とライセンス

このスクリプトは、以下のプロジェクトをベースにした改良版です：

- オリジナル作者: Steffen Schreiber 氏、Patrick Wagner 氏  
- 元スクリプト：<https://gitlab.com/schreiberste/siril-scripts>

ライセンスは GNU General Public License v3 またはそれ以降です。  
詳しくはリポジトリ内の `LICENSE` ファイルをご参照ください。
