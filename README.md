# bible-cli

`bible-cli` 是一組用於讀取特定聖經 App（e-Bible／恢復本聖經）內建 SQLite 資料庫的工具，單一執行檔 `bible` 同時提供命令列查詢與互動式終端機介面（TUI）兩種操作方式，支援中英對照顯示、大綱結構、註解顯示與全文搜尋功能。

## 目錄

- [概述](#概述)
- [版權聲明](#版權聲明)
- [系統需求](#系統需求)
- [安裝](#安裝)
- [資料庫準備](#資料庫準備)
- [使用方式](#使用方式)
  - [啟動互動式 TUI](#啟動互動式-tui)
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
| `./bible <子指令> ...` | 帶子指令（`list`／`read`／`search`／`intro`／`note`） -> 一次性查詢，輸出至標準輸出 | 腳本化處理、單次查經、與其他工具整合 |

僅依賴 Python 標準函式庫，於 Linux、macOS、Termux 等環境下皆可直接執行，無需額外安裝套件；Windows 則需額外安裝一個套件才能使用 TUI，詳見〈[Windows 使用說明](#windows-使用說明)〉。

## 版權聲明

本倉庫**不包含**任何聖經經文、註解、大綱等內容，僅提供讀取與呈現這些內容的程式碼。

App 內建資料庫（含恢復本聖經正文、註解、大綱）之版權屬原出版者水流職事站（Living Stream Ministry）所有。使用本工具的前提為使用者**本身合法持有**該 App，並自行從個人裝置取得資料庫檔案。使用本工具時請勿：

- 將資料庫檔案（`bible.db` 或任何 `.db`／`.db.NNN` 分割檔）提交至本倉庫或其他公開空間
- 重新散布資料庫內容

`.gitignore` 已預先排除所有 `.db` 相關檔案，以避免不慎提交。

## 系統需求

- Python 3.8 以上版本
- Linux／macOS／Termux：`curses` 為標準函式庫內建，無需額外安裝
- Windows：需另外安裝 `windows-curses` 才能使用 TUI（CLI 指令則不需要，見下方說明）

## 安裝

```bash
git clone <倉庫網址>
cd bible-cli
chmod +x bible
```

Windows 使用者可略過 `chmod +x`，直接以 `python bible` 執行即可（詳見〈[Windows 使用說明](#windows-使用說明)〉）。

## 資料庫準備

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

## 使用方式

### 啟動互動式 TUI

不帶任何子指令即可啟動 TUI；若僅加上 `--db` 指定資料庫路徑，仍會啟動 TUI（改用該資料庫），只有出現 `list`／`read`／`search`／`intro`／`note` 等子指令時才會切換為 CLI 模式。

```bash
./bible                       # 使用預設資料庫啟動 TUI
./bible --db /any/path/bible.db   # 使用指定資料庫啟動 TUI
```

支援鍵盤與滑鼠雙重操作方式，鍵盤指令如下：

| 按鍵 | 功能 |
| --- | --- |
| `↑` `↓` / `j` `k` | 上下移動或捲動內文 |
| `←` `→` / `h` `l` | 讀經畫面中切換上下章 |
| `Enter` / 滑鼠左鍵點擊 | 選取項目 |
| `e` | 切換是否顯示英文對照 |
| `c` | 切換恢復本／和合本正文 |
| `n` | 切換是否顯示大綱 |
| 點擊某節經文 | 展開／收合該節註解 |
| `/` | 全文搜尋 |
| `q` / `Backspace` | 返回上一層 |
| `?` | 開啟操作說明 |

滑鼠點擊功能需終端機支援 xterm 滑鼠事件回報。Ubuntu（gnome-terminal／Konsole）與 macOS（Terminal.app／iTerm2）預設皆支援；Termux 內建終端機支援度視版本而異；Windows Terminal 亦支援，若滑鼠點擊無反應，鍵盤操作仍可完整取代所有滑鼠功能。

### CLI 指令

**指令總覽**

```bash
bible list [舊約|新約]
bible read <書卷> <章>[:節] [--en] [--cuv] [--no-outline] [--no-footnote] [--no-color]
bible search <關鍵字> [--lang big5|gb|eng]
bible intro <書卷>
bible note <書卷> <章>:<節> <編號>
```

書卷名稱支援全名（例如創世記／创世记／Genesis）或簡稱（例如創／创／Gen.），不分語言、不分大小寫。

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
```

輸出若被重新導向至檔案或管線（非互動式終端機），顏色碼會自動關閉，避免檔案中夾雜跳脫字元。

## Windows 使用說明

`bible` 已針對 Windows 做以下相容性處理：

- 啟動時會自動切換主控台編碼頁為 UTF-8，並嘗試開啟 ANSI 顏色支援，讓中文與顏色標記在 `cmd.exe`／PowerShell 下能正常顯示。
- CLI 子指令（`list`／`read`／`search`／`intro`／`note`）在 Windows 上可直接使用，無需安裝任何額外套件。
- TUI（不帶子指令執行）在 Windows 上需要額外安裝 `windows-curses`，因為 `curses` 並非 Windows 版 Python 標準函式庫內建的模組：

  ```powershell
  pip install windows-curses
  ```

  若未安裝就嘗試啟動 TUI，`bible` 會印出上述安裝指令並自動退出，不會造成程式崩潰。

- Windows 沒有 Unix 的 shebang／可執行位元機制，因此無法直接以 `./bible` 執行，請改用：

  ```powershell
  python bible list
  python bible read 創世記 1
  python bible          # 啟動 TUI（需先安裝 windows-curses）
  ```

  也可視需求將 `bible` 複製一份為 `bible.py`，方便部分僅辨識副檔名的環境或編輯器操作，兩者程式內容完全相同。

## 資料庫結構

以下資料表結構供有意進行二次開發者參考：

| 資料表 | 內容 |
| --- | --- |
| `book_name` | 書卷索引、全名、簡稱（依 `language` 欄位區分繁體／簡體／英文） |
| `content` | 正文內容，`language` 欄位區分恢復本／和合本／英譯本等版本 |
| `outline` | 大綱標題，`level` 欄位決定縮排層級 |
| `footnote` | 註解內容，`location` 為插入正文的字元位置，`seq` 為顯示用紅字編號 |
| `book_intro` | 書卷簡介，`type` 欄位對應著者／著時／著地／涵蓋時段等分類 |
| `topic`、`book_mark`、`progress_oneyear` | App 原生功能相關資料表，本工具目前未使用 |

## 已知限制

- 英文內容斷行目前依字元寬度概略換行，並非正式的單字斷行（word-wrap），較長的英文單字可能於行尾被截斷
- `book_intro.type` 僅對照過創世記已出現的編號（1／2／3／6），其餘書卷若含有其他 `type` 值，將顯示為 `type<N>` 作為暫代標籤
- 尚未支援資料庫加密（SQLCipher）情形；若資料庫版本經過加密，本工具無法直接讀取
- Windows 上的 TUI 依賴 `windows-curses` 這個第三方套件模擬 `curses` 行為，部分終端機（尤其舊版 `cmd.exe`）的滑鼠事件或色彩支援可能不如 Linux／macOS 完整，建議搭配 Windows Terminal 使用

## 授權

程式碼採 MIT License（詳見 `LICENSE`），僅適用於本倉庫的程式碼本身，不適用於聖經文字內容（見上方版權聲明）。
