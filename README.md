# bible-cli

`bible-cli` 是一組用於讀取特定聖經 App（e-Bible／恢復本聖經）內建 SQLite 資料庫的工具，提供命令列查詢與互動式終端機介面（TUI）兩種操作方式，支援中英對照顯示、大綱結構、註解顯示與全文搜尋功能。

## 目錄

- [概述](#概述)
- [版權聲明](#版權聲明)
- [系統需求](#系統需求)
- [安裝](#安裝)
- [資料庫準備](#資料庫準備)
- [元件說明](#元件說明)
  - [bible.py（命令列介面）](#biblepy命令列介面)
  - [bible_tui.py（互動式終端機介面）](#bible_tuipy互動式終端機介面)
- [資料庫結構](#資料庫結構)
- [已知限制](#已知限制)
- [授權](#授權)

## 概述

本專案提供兩種存取介面：

| 元件 | 說明 | 適用情境 |
| --- | --- | --- |
| `bible.py` | 一次性指令查詢，輸出至標準輸出 | 腳本化處理、單次查經、與其他工具整合 |
| `bible_tui.py` | 全螢幕互動式介面（基於 `curses`） | 互動式瀏覽、日常查經 |

兩者皆僅依賴 Python 標準函式庫，於 Ubuntu、macOS、Termux 等環境下皆可直接執行，無需額外安裝套件。`bible_tui.py` 匯入並重用 `bible.py` 中的資料庫存取函式。

## 版權聲明

本倉庫**不包含**任何聖經經文、註解、大綱等內容，僅提供讀取與呈現這些內容的程式碼。

App 內建資料庫（含恢復本聖經正文、註解、大綱）之版權屬原出版者水流職事站（Living Stream Ministry）所有。使用本工具的前提為使用者**本身合法持有**該 App，並自行從個人裝置取得資料庫檔案。使用本工具時請勿：

- 將資料庫檔案（`bible.db` 或任何 `.db`／`.db.NNN` 分割檔）提交至本倉庫或其他公開空間
- 重新散布資料庫內容

`.gitignore` 已預先排除所有 `.db` 相關檔案，以避免不慎提交。

## 系統需求

- Python 3.8 以上版本（`curses` 為標準函式庫，Ubuntu／macOS／Termux 皆已內建）
- 無需執行 `pip install`

## 安裝

```bash
git clone <倉庫網址>
cd bible-cli
```

## 資料庫準備

您必須先取得TWGBR出版之電子聖經的APK檔案，並使用apktool等工具解壓縮它。
App 的資料庫在裝置上通常以 `bible.db.001` ～ `bible.db.NNN` 的分割檔形式存放於 `assets/` 目錄下，需先合併回單一 SQLite 檔案：

```bash
./tools/merge_db.sh /path/to/app/assets ./bible.db
```

`merge_db.sh` 會依序合併分割檔，並驗證合併後的檔案是否為合法 SQLite 格式。若資料庫原本即為單一檔案，直接將其重新命名為 `bible.db` 並置於專案根目錄即可。

`bible.py` 與 `bible_tui.py` 預設讀取執行目錄下的 `bible.db`，亦可透過 `--db` 參數指定其他路徑：

```bash
python3 bible.py --db /any/path/bible.db list
```

## 元件說明

### bible.py（命令列介面）

**指令總覽**

```bash
bible.py list [舊約|新約]
bible.py read <書卷> <章>[:節] [--en] [--cuv] [--no-outline] [--no-footnote] [--no-color]
bible.py search <關鍵字> [--lang big5|gb|eng]
bible.py intro <書卷>
bible.py note <書卷> <章>:<節> <編號>
```

書卷名稱支援全名（例如創世記／创世记／Genesis）或簡稱（例如創／创／Gen.），不分語言、不分大小寫。

**使用範例**

```bash
python3 bible.py list                       # 列出所有書卷
python3 bible.py list 舊約                   # 僅列出舊約書卷

python3 bible.py read 創世記 1               # 讀取第 1 章，包含大綱與紅字註解編號
python3 bible.py read 創 1:1 --en            # 讀取第 1 節，並附加英文對照
python3 bible.py read 創世記 1 --cuv         # 改用和合本正文
python3 bible.py read 創世記 1 --no-outline --no-footnote --no-color

python3 bible.py search 起初                 # 全文搜尋（預設語言為繁體恢復本）
python3 bible.py search beginning --lang eng

python3 bible.py intro 創世記                # 顯示書卷簡介（著者／著時／著地等）
python3 bible.py note 創世記 1:1 2           # 查看第 1:1 節的第 2 則註解
```

### bible_tui.py（互動式終端機介面）

```bash
python3 bible_tui.py
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

滑鼠點擊功能需終端機支援 xterm 滑鼠事件回報。Ubuntu（gnome-terminal／Konsole）與 macOS（Terminal.app／iTerm2）預設皆支援；Termux 內建終端機支援度視版本而異，若滑鼠點擊無反應，鍵盤操作仍可完整取代所有滑鼠功能。

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

## 授權

程式碼採 MIT License（詳見 `LICENSE`），僅適用於本倉庫的程式碼本身，不適用於聖經文字內容（見上方版權聲明）。
