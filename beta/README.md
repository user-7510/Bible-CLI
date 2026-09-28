# 恢復本聖經 CLI / TUI

單一 Python 檔案（`bible.py`）提供的恢復本聖經查詢工具，同時支援命令列（CLI）批次查詢與互動式終端機（TUI）瀏覽，並可對照原文 Strong 編號查字義。不需要額外安裝資料庫伺服器，僅依賴同目錄下的 sqlite 檔案（`bible.db`、MySword 的 `.mybible` 模組）運作。


## Features

- 恢復本經文瀏覽：書卷／章／節查詢，含大綱、註解、英文對照、和合本正文切換
- 原文 Strong 編號對照：逐字標色顯示 Strong 編號，可查希臘文／希伯來文字義
- 恢復本與原文 Strong 畫面可在 TUI 中以 `s` / `r` 即時切換，兩邊瀏覽狀態互不干擾
- 全文搜尋：支援多字串交集查詢、`--exclude` 差集查詢
- 類 vim 的 `:` 指令模式，可直接輸入 `:創世記 1 1` 之類的參照跳轉
- 滑鼠／觸控支援：點擊書卷、章節、經文展開註解、原文標色字查字義
- 選用的筆記／書籤／串珠功能（需執行 `:setup-storage` 啟用，才會建立本機資料庫）
- 同時相容 Linux / macOS / Windows（Windows 需另外安裝 `windows-curses`）


## Tech Stack

**執行環境：** Python 3

**核心套件：** `sqlite3`、`curses`（Windows 為 `windows-curses`）、`argparse`

**資料來源：** `bible.db`（恢復本內容）、MySword 格式的 `.dct.mybible`（Strong 字典）與 `.bbl.mybible`（含 Strong 編號的聖經模組）

**您需要自行合法取得資料庫檔案，通常在APK的assets資料夾中。合併.db可以使用./tools/merge_db.sh工具。**

## Environment Variables

以下環境變數為選用，用於指定原文 Strong 相關資料檔案路徑（若省略，程式會自動偵測 `bible.py` 所在目錄下的檔案）：

`BIBLE_STRONG_DICT`　Strong 字典 `.dct.mybible` 檔案路徑

`BIBLE_STRONG_BIBLE`　含 Strong 編號的聖經模組路徑，例如 `cuvt_bbl.mybible`


## Installation

將 `bible.py` 與所需的資料檔案（`bible.db` 及／或 `*.mybible`）放在同一個目錄下即可，不需要額外安裝套件。

Windows 使用者若要使用互動式 TUI，需另外安裝 `windows-curses`：

```bash
  pip install windows-curses
```

未安裝時程式會自動偵測並提示安裝方式，退回可用的 CLI 說明，不會直接崩潰。


## Run Locally

不帶任何子指令執行，程式會依同目錄下偵測到的檔案自動判斷要開啟的介面：

```bash
  python3 bible.py
```

強制指定介面：

```bash
  python3 bible.py --mode restore
  python3 bible.py --mode strong
```


## Usage/Examples

列出書卷：

```bash
  python3 bible.py list
  python3 bible.py list 新約
```

讀取經文（書卷名支援中／英文，也可用 1-66 的編號）：

```bash
  python3 bible.py read 創世記 1
  python3 bible.py read Genesis 1:1 --en --cuv
```

全文搜尋：

```bash
  python3 bible.py search 起初 --lang big5
```

查看書卷簡介、經文註解：

```bash
  python3 bible.py intro 創世記
  python3 bible.py note 創世記 1:1 1
```

原文 Strong 對照與查詢：

```bash
  python3 bible.py orig 創世記 1:1 --word 1
  python3 bible.py strong G26
```

以上指令列出的行說明如下：

1：查看整本書卷的簡介
2：查看指定章節第 1 個註解的內容
4：顯示創世記 1:1 的原文對照，並直接查第 1 個標號字的字義
5：直接以 Strong 編號查希臘文字義（G 開頭為希臘文，H 開頭為希伯來文）


## Appendix

互動式 TUI 中常用按鍵（完整說明可在程式內按 `?` 或輸入 `:help` 查看）：

| 按鍵 | 功能 |
| :--- | :--- |
| `↑` `↓` / `j` `k` | 移動／捲動 |
| `PageUp` `PageDown` / `Space` | 整頁捲動 |
| `Enter` | 選取／展開收合經節註解 |
| `←` `→` | 讀經畫面切換上下章 |
| `e` / `c` / `n` | 讀經畫面切換英文對照／和合本正文／大綱顯示 |
| `y` | 複製目前經節 |
| `/` | 全文搜尋 |
| `s` / `r` | 切換到原文 Strong 畫面／切回恢復本畫面 |
| `b` / `B` | 返回上一頁 |
| `:` | 進入指令模式（類 vim，如 `:strong`、`:copy`、`:note`） |
| `q` / `Q` | 離開程式（詢問後離開／直接離開） |

滑鼠／觸控：可直接點擊書卷、章節、經文展開註解，或點擊原文 Strong 畫面中標色的原文字查字義。

## 人工智慧使用聲明

- 本程式有使用AI輔助開發與優化。
