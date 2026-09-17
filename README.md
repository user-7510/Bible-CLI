# bible-cli

`bible-cli` 是一組用於讀取特定聖經 App（e-Bible／恢復本聖經）內建 SQLite 資料庫的工具，單一執行檔 `bible` 同時提供命令列查詢與互動式終端機介面（TUI）兩種操作方式，支援中英對照顯示、大綱結構、註解顯示與全文搜尋功能。除恢復本正文外，亦可選擇性搭配 MySword 格式的 **Strong 原文對照模組**，在讀經畫面中直接點按經文中的原文字，查看該字對應的希臘文／希伯來文字義。

## 目錄

- [概述](#概述)
- [版權聲明](#版權聲明)
- [系統需求](#系統需求)
- [安裝](#安裝)
- [資料庫準備](#資料庫準備)
  - [恢復本聖經資料庫](#恢復本聖經資料庫)
  - [原文 Strong 對照模組（選用）](#原文-strong-對照模組選用)
- [使用方式](#使用方式)
  - [啟動互動式 TUI](#啟動互動式-tui)
  - [原文 Strong 畫面](#原文-strong-畫面)
  - [CLI 指令](#cli-指令)
- [Windows 使用說明](#windows-使用說明)
- [資料庫結構](#資料庫結構)
- [已知限制](#已知限制)
- [授權](#授權)

## 概述

`bible` 是單一 Python 檔案，依執行時是否帶有子指令自動切換模式：

| 執行方式 | 說明 | 適用情境 |
| --- | --- | --- |
| `./bible` | 不帶子指令 -> 啟動全螢幕互動式 TUI（基於 `curses`） | 互動式瀏覽、日常查經 |
| `./bible <子指令> ...` | 帶子指令（`list`／`read`／`search`／`intro`／`note`／`orig`／`strong`） -> 一次性查詢，輸出至標準輸出 | 腳本化處理、單次查經、與其他工具整合 |

執行目錄下若同時偵測到恢復本資料庫（`bible.db`）與 Strong 原文模組（`.mybible`），互動式 TUI 會直接以恢復本畫面開啟，可在**任一畫面**按 `s` 切換到原文 Strong 畫面、按 `r` 切回恢復本（搜尋輸入畫面除外），兩種畫面共用同一個 TUI session，切換時不會有畫面重啟或閃爍。詳見〈[原文 Strong 畫面](#原文-strong-畫面)〉。

僅依賴 Python 標準函式庫，於 Linux、macOS、Termux 等環境下皆可直接執行，無需額外安裝套件；Windows 則需額外安裝一個套件才能使用 TUI，詳見〈[Windows 使用說明](#windows-使用說明)〉。TUI 中另提供一鍵複製經文／註解到系統剪貼簿的功能（`y` 鍵，展開註解時亦會自動複製），此功能需另外安裝對應平台的命令列剪貼簿工具，詳見〈[系統需求](#系統需求)〉。

## 版權聲明

本倉庫**不包含**任何聖經經文、註解、大綱、原文字義等內容，僅提供讀取與呈現這些內容的程式碼。

App 內建資料庫（含恢復本聖經正文、註解、大綱）之版權屬原出版者水流職事站（Living Stream Ministry）所有。若另外搭配 MySword 格式的 Strong 原文對照模組（`.mybible`），該模組之版權則屬其原始製作者或發行單位所有。使用本工具的前提為使用者**本身合法持有**上述資料，並自行從個人裝置或合法管道取得對應檔案。使用本工具時請勿：

- 將資料庫檔案（`bible.db` 或任何 `.db`／`.db.NNN` 分割檔）、或 `.mybible` 模組檔案提交至本倉庫或其他公開空間
- 重新散布資料庫或模組內容

`.gitignore` 已預先排除所有 `.db`／`.mybible` 相關檔案，以避免不慎提交。

## 系統需求

- Python 3.8 以上版本
- Linux／macOS／Termux：`curses` 為標準函式庫內建，無需額外安裝
- Windows：需另外安裝 `windows-curses` 才能使用 TUI（CLI 指令則不需要，見下方說明）
- 原文 Strong 對照功能為選用功能，僅需額外準備 `.mybible` 檔案，無需安裝額外 Python 套件
- 剪貼簿複製功能（TUI 中的 `y` 鍵、展開註解時自動複製）為選用功能，未安裝對應工具時該功能會直接顯示複製失敗訊息，不影響其餘功能；依平台安裝對應的命令列剪貼簿工具：

  | 平台 | 命令列剪貼簿工具 | 安裝指令 |
  | --- | --- | --- |
  | macOS | `pbcopy`（系統內建） | 不需安裝 |
  | Linux（X11） | `xclip` 或 `xsel` | `sudo apt install xclip`（Debian／Ubuntu）或 `sudo dnf install xclip`（Fedora） |
  | Linux（Wayland） | `wl-clipboard`（提供 `wl-copy`） | `sudo apt install wl-clipboard`（Debian／Ubuntu）或 `sudo dnf install wl-clipboard`（Fedora） |
  | Termux | `termux-api`（提供 `termux-clipboard-set`） | `pkg install termux-api`（並另外安裝 Termux:API App） |
  | Windows | `clip`（系統內建） | 不需安裝 |

## 安裝

```bash
git clone <倉庫網址>
cd bible-cli
chmod +x bible
```

Windows 使用者可略過 `chmod +x`，直接以 `python bible` 執行即可（詳見〈[Windows 使用說明](#windows-使用說明)〉）。

## 資料庫準備

### 恢復本聖經資料庫

您必須先取得TWGBR出版之電子聖經的APK檔案，並使用apktool等工具解壓縮它。
App 的資料庫在裝置上通常以 `bible.db.001` ～ `bible.db.NNN` 的分割檔形式存放於 `assets/` 目錄下，需先合併回單一 SQLite 檔案：

```bash
./tools/merge_db.sh /path/to/app/assets ./bible.db
```

`merge_db.sh` 會依序合併分割檔，並驗證合併後的檔案是否為合法 SQLite 格式。若資料庫原本即為單一檔案，直接將其重新命名為 `bible.db` 並置於專案根目錄即可。

`bible` 預設讀取執行目錄下的 `bible.db`，亦可透過 `--db` 參數指定其他路徑：

```bash
./bible --db /any/path/bible.db list
```

### 原文 Strong 對照模組（選用）

若您另外持有 MySword 格式的聖經模組，`bible` 可自動偵測並提供原文 Strong 編號對照與字義查詢功能，這是完全獨立於恢復本資料庫的**選用**功能，不需要 `bible.db` 也能單獨使用。

將以下檔案放在與 `bible` 相同的目錄下即可被自動偵測到：

| 檔案類型 | 檔名慣例 | 提供的功能 |
| --- | --- | --- |
| Strong 字典模組 | `*.dct.mybible`（或內含 `dictionary` 資料表的 `.mybible`） | 依 Strong 編號（如 `G26`、`H157`）查詢原文字義 |
| 含 Strong 編號的聖經模組 | `*.bbl.mybible`（或內含 `Bible` 資料表的 `.mybible`），例如 MySword 的 `cuvt_bbl.mybible` | 提供和合本經文＋每個字對應的 Strong 編號 |

若檔名不符合上述慣例，`bible` 會嘗試連線讀取資料表名稱自動判斷模組種類。也可以用環境變數或參數手動指定路徑，不依賴自動偵測：

```bash
export BIBLE_STRONG_DICT=/path/to/xxx.dct.mybible
export BIBLE_STRONG_BIBLE=/path/to/cuvt_bbl.mybible
```

或在個別 CLI 指令上以 `--dict`／`--strongbible` 參數覆寫（見下方 CLI 指令說明）。

## 使用方式

### 啟動互動式 TUI

不帶任何子指令即可啟動 TUI；若僅加上 `--db` 指定資料庫路徑或 `--mode` 指定要開啟的畫面，仍會啟動 TUI，只有出現 `list`／`read`／`search`／`intro`／`note`／`orig`／`strong` 等子指令時才會切換為 CLI 模式。

```bash
./bible                            # 依偵測到的檔案自動判斷，兩者都有時直接開恢復本畫面
./bible --db /any/path/bible.db    # 使用指定資料庫啟動 TUI
./bible --mode restore             # 強制開啟恢復本畫面（需 bible.db）
./bible --mode strong              # 強制開啟原文 Strong 畫面（需 .mybible 模組）
```

支援鍵盤與滑鼠雙重操作方式，鍵盤指令如下：

| 按鍵 | 功能 |
| --- | --- |
| `↑` `↓` / `j` `k` | 上下移動或捲動內文 |
| `←` `→` / `h` `l` | 讀經畫面中切換上下章 |
| `Enter` / 滑鼠左鍵點擊 | 選取項目 |
| `e` | 切換是否顯示英文對照（恢復本畫面） |
| `c` | 切換恢復本／和合本正文（恢復本畫面） |
| `n` | 切換是否顯示大綱（恢復本畫面） |
| 點擊某節經文 | 展開／收合該節註解（恢復本畫面） |
| `s` | 切換到原文 Strong 畫面（任一畫面皆可按，需偵測到 `.mybible` 模組） |
| `r` | 切回恢復本畫面（任一畫面皆可按，需偵測到 `bible.db`） |
| `y` | 複製目前畫面附近該節經文到剪貼簿（讀經畫面；展開註解時會自動複製註解內容） |
| `/` | 全文搜尋（恢復本畫面） |
| `q` / `Backspace` | 返回上一層 |
| `?` | 開啟操作說明 |

滑鼠點擊功能需終端機支援 xterm 滑鼠事件回報。Ubuntu（gnome-terminal／Konsole）與 macOS（Terminal.app／iTerm2）預設皆支援；Termux 內建終端機支援度視版本而異；Windows Terminal 亦支援，若滑鼠點擊無反應，鍵盤操作仍可完整取代所有滑鼠功能。

### 原文 Strong 畫面

當偵測到 `.mybible` 模組後，TUI 內會多出一組與恢復本畫面平行、操作邏輯相同的畫面：書卷清單 → 章節清單 → 讀經畫面。在原文 Strong 讀經畫面中：

- 經文裡帶有 Strong 編號的原文字會標成紅色。
- 直接用滑鼠（或觸控螢幕）點按該字，即可在該行下方展開對應的原文字義；已展開時該字會變成青色，再點一次即可收合。
- 一個字若對應多個 Strong 編號，會依序列出每個編號的字義。
- 若只找到含 Strong 編號的聖經模組、未提供字典模組，仍可瀏覽經文與編號，但點按時會提示尚未偵測到字典。

書卷清單、章節清單畫面的上下移動、翻頁、`Enter`／滑鼠點選等操作方式與恢復本畫面完全相同。

### CLI 指令

**指令總覽**

```bash
bible list [舊約|新約]
bible read <書卷> <章>[:節] [--en] [--cuv] [--no-outline] [--no-footnote] [--no-color]
bible search <關鍵字> [--lang big5|gb|eng]
bible intro <書卷>
bible note <書卷> <章>:<節> <編號>
bible orig <書卷> <章>[:節] [--word N] [--strongbible PATH] [--dict PATH] [--no-color]
bible strong <G26|H157> [--dict PATH] [--no-color]
```

書卷名稱支援全名（例如創世記／创世记／Genesis）或簡稱（例如創／创／Gen.），不分語言、不分大小寫；`orig` 指令則採用和合本書卷順序，可直接輸入書卷名或 1-66 的編號。

**使用範例**

```bash
./bible list                       # 列出所有書卷
./bible list 舊約                   # 僅列出舊約書卷

./bible read 創世記 1               # 讀取第 1 章，包含大綱與紅字註解編號
./bible read 創 1:1 --en            # 讀取第 1 節，並附加英文對照
./bible read 創世記 1 --cuv         # 改用和合本正文
./bible read 創世記 1 --no-outline --no-footnote --no-color

./bible search 起初                 # 全文搜尋（預設語言為繁體恢復本）
./bible search beginning --lang eng

./bible intro 創世記                # 顯示書卷簡介（著者／著時／著地等）
./bible note 創世記 1:1 2           # 查看第 1:1 節的第 2 則註解

./bible orig 創世記 1               # 顯示第 1 章原文對照，經文後標出 [n] 對應原文字
./bible orig 創世記 1:1 --word 2    # 直接查詢第 1:1 節第 2 個標號字的原文字義
./bible strong G26                  # 直接查詢單一 Strong 編號的字義
```

`orig`／`strong` 兩個指令只需要 Strong 相關模組即可執行，即使目前目錄沒有 `bible.db` 也可以使用；若自動偵測到的路徑不正確，可用 `--strongbible`／`--dict` 參數覆寫。

輸出若被重新導向至檔案或管線（非互動式終端機），顏色碼會自動關閉，避免檔案中夾雜跳脫字元。

## Windows 使用說明

`bible` 已針對 Windows 做以下相容性處理：

- 啟動時會自動切換主控台編碼頁為 UTF-8，並嘗試開啟 ANSI 顏色支援，讓中文與顏色標記在 `cmd.exe`／PowerShell 下能正常顯示。
- CLI 子指令（`list`／`read`／`search`／`intro`／`note`／`orig`／`strong`）在 Windows 上可直接使用，無需安裝任何額外套件。
- TUI（不帶子指令執行，含恢復本與原文 Strong 兩種畫面）在 Windows 上需要額外安裝 `windows-curses`，因為 `curses` 並非 Windows 版 Python 標準函式庫內建的模組：

  ```powershell
  pip install windows-curses
  ```

  若未安裝就嘗試啟動 TUI，`bible` 會印出上述安裝指令並自動退出，不會造成程式崩潰。

- Windows 沒有 Unix 的 shebang／可執行位元機制，因此無法直接以 `./bible` 執行，請改用：

  ```powershell
  python bible list
  python bible orig 創世記 1
  python bible          # 啟動 TUI（需先安裝 windows-curses）
  ```

  也可視需求將 `bible` 複製一份為 `bible.py`，方便部分僅辨識副檔名的環境或編輯器操作，兩者程式內容完全相同。

## 資料庫結構

以下資料表結構供有意進行二次開發者參考。

**恢復本資料庫（`bible.db`）**

| 資料表 | 內容 |
| --- | --- |
| `book_name` | 書卷索引、全名、簡稱（依 `language` 欄位區分繁體／簡體／英文） |
| `content` | 正文內容，`language` 欄位區分恢復本／和合本／英譯本等版本 |
| `outline` | 大綱標題，`level` 欄位決定縮排層級 |
| `footnote` | 註解內容，`location` 為插入正文的字元位置，`seq` 為顯示用紅字編號 |
| `book_intro` | 書卷簡介，`type` 欄位對應著者／著時／著地／涵蓋時段等分類 |
| `topic`、`book_mark`、`progress_oneyear` | App 原生功能相關資料表，本工具目前未使用 |

**Strong 原文對照模組（`.mybible`，MySword 格式）**

| 資料表 | 所在檔案 | 內容 |
| --- | --- | --- |
| `dictionary` | `*.dct.mybible` | `word` 欄位為 Strong 編號（如 `G26`）、`data` 欄位為 HTML 格式的字義說明 |
| `Bible` | `*.bbl.mybible` | `Book`／`Chapter`／`Verse`／`Scripture` 欄位，`Scripture` 內以 `<WG####>`／`<WH####>` 標籤標示每個字對應的 Strong 編號 |

## 已知限制

- 英文內容斷行目前依字元寬度概略換行，並非正式的單字斷行（word-wrap），較長的英文單字可能於行尾被截斷
- `book_intro.type` 僅對照過創世記已出現的編號（1／2／3／6），其餘書卷若含有其他 `type` 值，將顯示為 `type<N>` 作為暫代標籤
- 尚未支援資料庫加密（SQLCipher）情形；若資料庫版本經過加密，本工具無法直接讀取
- 原文 Strong 畫面目前不支援全文搜尋（`/` 僅在恢復本畫面提供）
- Windows 上的 TUI 依賴 `windows-curses` 這個第三方套件模擬 `curses` 行為，部分終端機（尤其舊版 `cmd.exe`）的滑鼠事件或色彩支援可能不如 Linux／macOS 完整，建議搭配 Windows Terminal 使用

## 授權

程式碼採 MIT License（詳見 `LICENSE`），僅適用於本倉庫的程式碼本身，不適用於聖經文字內容與 Strong 原文模組內容（見上方版權聲明）。

## AI輔助揭露

- 本專案之部分函式為AI協作。

