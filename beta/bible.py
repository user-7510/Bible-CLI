#!/usr/bin/env python3
"""
bible.py — 恢復本聖經 CLI / TUI 合一版

用法：
    python3 bible.py                    # 不帶參數 -> 依同目錄檔案自動判斷要開啟的介面
    python3 bible.py --mode restore     # 強制啟動恢復本 TUI（需 bible.db）
    python3 bible.py --mode strong      # 強制啟動原文 Strong TUI 互動模式（需 .mybible）
    python3 bible.py --db X             # 指定資料庫路徑 -> 仍走上面的自動判斷邏輯
    python3 bible.py list [舊約|新約]    # 帶子指令 -> 走 CLI
    python3 bible.py read <書卷> <章>[:節] [--en] [--cuv] [--no-outline] [--no-footnote] [--no-color]
    python3 bible.py search <關鍵字> [--lang big5|gb|eng]
    python3 bible.py intro <書卷>
    python3 bible.py note <書卷> <章>:<節> <編號>
    python3 bible.py orig <書卷> <章>[:節] [--word N]   # CLI：原文 Strong 對照
    python3 bible.py strong <G26|H157>                    # CLI：查單一 Strong 編號

自動偵測（同目錄，即 bible.py 所在資料夾）：
    - 找到 bible.db -> 提供恢復本功能（list/read/search/intro/note，以及互動 TUI）。
    - 找到 *.dct.mybible -> 提供 Strong 字典查詢（strong 指令、原文模式的 w/s 指令）。
    - 找到 *.bbl.mybible（或內含 Bible 表的 .mybible）-> 提供原文 Strong 對照（orig 指令、
      原文模式的 b 指令）。
    - 恢復本與原文 Strong 共用同一個 TUI 介面。若 bible.db 與 Strong 聖經模組同時存在，
      不帶子指令啟動時直接進入恢復本畫面，可在任一畫面按 s 切換到原文 Strong 畫面，
      在原文 Strong 畫面則按 r 切回恢復本（搜尋輸入畫面除外），也可用 --mode 直接指定。
    - 原文 Strong 讀經畫面中，經文裡標色的原文字可直接用滑鼠點按（或觸控點按）
      叫出／收合該字的 Strong 字義，顯示方式與恢復本點按經文展開註解相同。

互動 TUI 指令模式（: 開頭，類似 vim，可在任何畫面呼叫，按 ? 或 :help 查看完整說明）：
    - 底端狀態列平時不顯示操作提示，只在指令模式輸入中，或剛執行完某個動作
      （複製、儲存筆記等）時顯示訊息。
    - 常用指令：:q（詢問後離開）、:Q（直接離開）、:strong / :S、:recovery / :R
      （切換模式並跳至本章節或指定書卷章節）、:footnote / :F、:intro、:copy / :C、
      :english / :E、:outline / :O、:search / :find（支援多字串交集查詢與 --exclude
      差集查詢，按 / 的搜尋與此指令共用同一套邏輯）、:reference / :ref。
      裸的 :1、:1 1、:genesis 1 1 用於直接跳至指定節／章節／書卷章節。
    - 一般模式仍保留 q/Q 離開、b/B 返回上一頁（含畫面與模式切換的完整紀錄）。
    - 預設不寫入任何檔案；執行 :setup-storage 後才會在本檔案所在目錄建立
      .bible-note.db，並啟用 :option（設定，一般模式 o/O 同義）、:note／:N（筆記）、
      :bookmark／:M（書籤）、:reference（串珠，顯示於經節後方 a、b、c...，可點按跳轉）
      等指令；下次啟動只要偵測到該檔案仍在，即自動視為已啟用。

本檔案同時相容 Linux / macOS / Windows：
    - Windows 未內建 curses，需先執行 `pip install windows-curses` 才能使用 TUI，
      若未安裝，程式會提示安裝方式並自動退回 CLI 說明，而不會直接崩潰。
    - 啟動時會嘗試開啟 Windows 主控台的 VT100 / UTF-8 支援，讓 ANSI 顏色與中文字元
      在 cmd.exe / PowerShell 下也能正常顯示。
"""

import argparse
import ctypes
import datetime
import io
import locale
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser

isWindows = os.name == "nt"

scriptDir = os.path.dirname(os.path.abspath(__file__))


def _sniffMybibleKind(path):
    try:
        c = sqlite3.connect(path)
        tables = {
            r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        c.close()
    except sqlite3.Error:
        return None
    if "dictionary" in tables:
        return "dict"
    if "Bible" in tables:
        return "bible"
    return None


def detectResources(baseDir=None):
    baseDir = baseDir or scriptDir
    resources = {"db": None, "dict": None, "strongBible": None}

    dbPath = os.path.join(baseDir, "bible.db")
    if os.path.isfile(dbPath):
        resources["db"] = dbPath

    try:
        entries = sorted(os.listdir(baseDir))
    except OSError:
        entries = []

    for fname in entries:
        full = os.path.join(baseDir, fname)
        if not os.path.isfile(full):
            continue
        lower = fname.lower()
        if lower.endswith(".dct.mybible"):
            resources["dict"] = resources["dict"] or full
        elif lower.endswith(".bbl.mybible"):
            resources["strongBible"] = resources["strongBible"] or full
        elif lower.endswith(".mybible"):
            kind = _sniffMybibleKind(full)
            if kind == "dict":
                resources["dict"] = resources["dict"] or full
            elif kind == "bible":
                resources["strongBible"] = resources["strongBible"] or full

    return resources


detectedResources = detectResources()

dbDefault = detectedResources["db"] or os.path.join(scriptDir, "bible.db")

zhLangs = ("big5", "gb", "cuv_big5", "cuv_gb")
enLangs = ("eng", "darby_eng", "kjv_eng")

introTypeLabel = {
    1: "著者",
    2: "著時",
    3: "著地",
    4: "受者",
    5: "主旨",
    6: "涵蓋時段",
}

red = "\033[31m"
cyan = "\033[36m"
bold = "\033[1m"
dim = "\033[2m"
reset = "\033[0m"

dictDefault = os.environ.get("BIBLE_STRONG_DICT") or detectedResources["dict"]

strongBibleDefault = os.environ.get("BIBLE_STRONG_BIBLE") or detectedResources["strongBible"]

zhBookNames = [
    "創世記", "出埃及記", "利未記", "民數記", "申命記",
    "約書亞記", "士師記", "路得記", "撒母耳記上", "撒母耳記下",
    "列王紀上", "列王紀下", "歷代志上", "歷代志下", "以斯拉記",
    "尼希米記", "以斯帖記", "約伯記", "詩篇", "箴言",
    "傳道書", "雅歌", "以賽亞書", "耶利米書", "耶利米哀歌",
    "以西結書", "但以理書", "何西阿書", "約珥書", "阿摩司書",
    "俄巴底亞書", "約拿書", "彌迦書", "那鴻書", "哈巴谷書",
    "西番雅書", "哈該書", "撒迦利亞書", "瑪拉基書",
    "馬太福音", "馬可福音", "路加福音", "約翰福音", "使徒行傳",
    "羅馬書", "哥林多前書", "哥林多後書", "加拉太書", "以弗所書",
    "腓立比書", "歌羅西書", "帖撒羅尼迦前書", "帖撒羅尼迦後書",
    "提摩太前書", "提摩太後書", "提多書", "腓利門書", "希伯來書",
    "雅各書", "彼得前書", "彼得後書", "約翰一書", "約翰二書",
    "約翰三書", "猶大書", "啟示錄",
]

enBookNames = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy",
    "Joshua", "Judges", "Ruth", "1 Samuel", "2 Samuel",
    "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra",
    "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
    "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations",
    "Ezekiel", "Daniel", "Hosea", "Joel", "Amos",
    "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk",
    "Zephaniah", "Haggai", "Zechariah", "Malachi",
    "Matthew", "Mark", "Luke", "John", "Acts",
    "Romans", "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians",
    "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians",
    "1 Timothy", "2 Timothy", "Titus", "Philemon", "Hebrews",
    "James", "1 Peter", "2 Peter", "1 John", "2 John",
    "3 John", "Jude", "Revelation",
]

colorOutline = 1
colorFootnote = 2
colorSection = 3
colorSecondary = 4
colorHeader = 5
colorHelp = 6
colorCmdLine = 7


def setupConsole():
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if not isWindows:
        return

    try:
        os.system("chcp 65001 >NUL 2>&1")
    except Exception:
        pass

    try:
        kernel32 = ctypes.windll.kernel32
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        for handleId in (-11, -12):
            handle = kernel32.GetStdHandle(handleId)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(
                    handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                )
    except Exception:
        pass


def supportsAnsiColor():
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def copyToClipboardText(text):
    if not text:
        return False
    if isWindows:
        candidates = [["clip"]]
    elif sys.platform == "darwin":
        candidates = [["pbcopy"]]
    else:
        candidates = [
            ["termux-clipboard-set"],
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    payload = text.encode("utf-8", errors="replace")
    for cmd in candidates:
        try:
            proc = subprocess.run(
                cmd, input=payload,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return True
    return False


def connect(dbPath):
    if not os.path.exists(dbPath):
        sys.stderr.write(f"找不到資料庫檔案: {dbPath}\n")
        sys.exit(1)
    conn = sqlite3.connect(dbPath)
    conn.row_factory = sqlite3.Row
    return conn


def resolveBook(conn, name):
    name = name.strip()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT book_index FROM book_name WHERE name = ? OR acronym_name = ? LIMIT 1",
        (name, name),
    ).fetchone()
    if row:
        return row["book_index"]

    row = cur.execute(
        "SELECT book_index FROM book_name WHERE lower(name) = lower(?) "
        "OR lower(acronym_name) = lower(?) LIMIT 1",
        (name, name),
    ).fetchone()
    if row:
        return row["book_index"]

    row = cur.execute(
        "SELECT book_index FROM book_name WHERE name LIKE ? OR acronym_name LIKE ? LIMIT 1",
        (f"%{name}%", f"%{name}%"),
    ).fetchone()
    if row:
        return row["book_index"]
    return None


def bookDisplayName(conn, bookIndex, lang="big5"):
    cur = conn.cursor()
    row = cur.execute(
        "SELECT name FROM book_name WHERE book_index=? AND language=?",
        (bookIndex, lang),
    ).fetchone()
    return row["name"] if row else f"[book {bookIndex}]"


def insertFootnoteMarkers(content, footnotes, color=True):
    if not footnotes:
        return content
    result = content
    for loc, seq in sorted(footnotes, key=lambda x: -x[0]):
        idx = loc - 1
        if idx < 0 or idx > len(result):
            continue
        marker = f"{seq}"
        if color:
            marker = f"{red}{marker}{reset}"
        result = result[:idx] + marker + result[idx:]
    return result


def getOutlines(conn, lang, bookIndex, chapter):
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT section, flag, level, outline FROM outline "
        "WHERE language=? AND book_index=? AND chapter=? "
        "ORDER BY section ASC, flag ASC, level ASC",
        (lang, bookIndex, chapter),
    ).fetchall()
    bySection = {}
    for r in rows:
        bySection.setdefault(r["section"], []).append(r)
    return bySection


def getFootnotes(conn, lang, bookIndex, chapter, section):
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT location, seq, note FROM footnote "
        "WHERE language=? AND book_index=? AND chapter=? AND section=? "
        "ORDER BY seq ASC",
        (lang, bookIndex, chapter, section),
    ).fetchall()
    return rows


def connectSqliteOrExit(path, missingPathHint):
    if not path:
        sys.stderr.write(missingPathHint + "\n")
        sys.exit(1)
    if not os.path.exists(path):
        sys.stderr.write(f"找不到檔案: {path}\n")
        sys.exit(1)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def connectDict(dictPath):
    return connectSqliteOrExit(
        dictPath,
        "尚未指定 Strong 字典路徑。請用 --dict 指定 .dct.mybible 檔案路徑，"
        "或設定環境變數 BIBLE_STRONG_DICT。",
    )


def connectStrongBible(biblePath):
    return connectSqliteOrExit(
        biblePath,
        "尚未指定含 Strong 編號的聖經模組路徑。請用 --strongbible 指定，"
        "例如 MySword 的 cuvt_bbl.mybible（或設定環境變數 BIBLE_STRONG_BIBLE）。",
    )


def normalizeStrongCode(code):
    code = code.strip().upper()
    if not code:
        return None
    if code[0] not in ("G", "H"):
        return None
    return code


class DictHtmlRenderer(HTMLParser):

    def __init__(self, color=True):
        super().__init__(convert_charrefs=True)
        self.color = color
        self.lines = [""]
        self.olStack = []

    def _write(self, text):
        self.lines[-1] += text

    def _newline(self):
        if self.lines[-1] != "":
            self.lines.append("")

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br"):
            self._newline()
        elif tag == "ol":
            self.olStack.append(0)
        elif tag == "li":
            self._newline()
            depth = len(self.olStack)
            if self.olStack:
                self.olStack[-1] += 1
                num = self.olStack[-1]
            else:
                num = 1
            indent = "  " * max(0, depth - 1)
            marker = f"{num}." if depth <= 1 else f"{chr(96 + num)})"
            self._write(f"{indent}{marker} ")
        elif tag in ("strong", "b"):
            if self.color:
                self._write(bold)
        elif tag in ("i", "em"):
            if self.color:
                self._write(dim)
        elif tag == "a":
            if self.color:
                self._write(cyan)

    def handle_endtag(self, tag):
        if tag == "ol":
            if self.olStack:
                self.olStack.pop()
            self._newline()
        elif tag == "li":
            self._newline()
        elif tag == "p":
            self._newline()
        elif tag in ("strong", "b", "i", "em", "a"):
            if self.color:
                self._write(reset)

    def handle_data(self, data):
        self._write(data)

    def getText(self):
        text = "\n".join(self.lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip("\n")


def renderDictHtml(htmlText, color=True):
    parser = DictHtmlRenderer(color=color)
    parser.feed(htmlText)
    return parser.getText()


def cmdStrong(args, _conn):
    code = normalizeStrongCode(args.code)
    if not code:
        sys.stderr.write(
            "請在編號前加上 G（希臘文）或 H（希伯來文），例如 G26 或 H157\n"
        )
        sys.exit(1)

    dconn = connectDict(args.dict)
    cur = dconn.cursor()
    row = cur.execute(
        "SELECT word, data FROM dictionary WHERE word = ?", (code,)
    ).fetchone()
    if not row:
        sys.stderr.write(f"查無 Strong 編號: {code}\n")
        sys.exit(1)

    color = (not args.noColor) and supportsAnsiColor()
    header = f"Strong {row['word']}"
    print(f"{bold}{header}{reset}\n" if color else f"{header}\n")
    print(renderDictHtml(row["data"], color=color))


def printStrongDefinition(dictPath, code, color):
    if code in ("G0", "H0"):
        print(f"{dim}[{code} 為佔位符，無對應字典資料]{reset}" if color
              else f"[{code} 為佔位符，無對應字典資料]")
        return
    dconn = connectDict(dictPath)
    cur = dconn.cursor()
    row = cur.execute(
        "SELECT word, data FROM dictionary WHERE word = ?", (code,)
    ).fetchone()
    if not row:
        sys.stderr.write(f"查無 Strong 編號: {code}\n")
        return
    header = f"Strong {row['word']}"
    print(f"\n{bold}{header}{reset}\n" if color else f"\n{header}\n")
    print(renderDictHtml(row["data"], color=color))


strongTagPattern = re.compile(r"<W([GH]\d+)>")


def splitStrongVerse(scripture):
    parts = re.split(r"(<W[GH]\d+>)", scripture)
    segments = []
    curText, curCodes = "", []
    first = True
    for part in parts:
        m = strongTagPattern.fullmatch(part)
        if m:
            curCodes.append(m.group(1))
        elif part == "":
            continue
        else:
            if not first:
                segments.append((curText, curCodes))
            curText, curCodes = part, []
            first = False
    segments.append((curText, curCodes))
    return segments


def resolveAnyBookName(name, conn=None):
    if name is None:
        return None
    name = name.strip()
    if not name:
        return None
    if name.isdigit():
        idx = int(name)
        return idx if 1 <= idx <= 66 else None
    for i, n in enumerate(zhBookNames, start=1):
        if n == name:
            return i
    norm = re.sub(r"\s+", "", name.lower())
    for i, n in enumerate(enBookNames, start=1):
        if re.sub(r"\s+", "", n.lower()) == norm:
            return i
    if conn is not None:
        idx = resolveBook(conn, name)
        if idx:
            return idx
    matches = [i for i, n in enumerate(zhBookNames, start=1) if name in n]
    if len(matches) == 1:
        return matches[0]
    matches = [i for i, n in enumerate(enBookNames, start=1) if norm and norm in re.sub(r"\s+", "", n.lower())]
    if len(matches) == 1:
        return matches[0]
    return None


def renderStrongVerse(segments, color):
    displayParts = []
    legend = {}
    idx = 0
    for text, codes in segments:
        if codes:
            idx += 1
            legend[idx] = codes
            marker = f"[{idx}]"
            if color:
                displayParts.append(f"{text}{dim}{marker}{reset}")
            else:
                displayParts.append(f"{text}{marker}")
        else:
            displayParts.append(text)
    return "".join(displayParts), legend


def cmdOrig(args, _conn):
    bookIndex = resolveAnyBookName(args.book)
    if bookIndex is None:
        sys.stderr.write(f"找不到書卷: {args.book}（請用中／英文書卷名或 1-66 的編號）\n")
        sys.exit(1)

    chapterArg = str(args.chapter)
    verseFilter = None
    if ":" in chapterArg:
        chapterS, verseS = chapterArg.split(":")
        chapter = int(chapterS)
        verseFilter = int(verseS)
    else:
        chapter = int(chapterArg)

    if args.word is not None and verseFilter is None:
        sys.stderr.write("使用 --word 查詢原文字義時，請同時指定確切的節，例如 3:16\n")
        sys.exit(1)

    bconn = connectStrongBible(args.strongbible)
    cur = bconn.cursor()
    rows = cur.execute(
        "SELECT Verse, Scripture FROM Bible WHERE Book=? AND Chapter=? "
        "ORDER BY Verse",
        (bookIndex, chapter),
    ).fetchall()
    if not rows:
        sys.stderr.write("查無此章節\n")
        sys.exit(1)

    color = (not args.noColor) and supportsAnsiColor()
    bookName = zhBookNames[bookIndex - 1]
    header = f"{bookName} 第{chapter}章"
    print(f"{bold}{header}{reset}\n" if color else f"{header}\n")

    targetLegend = None
    for r in rows:
        verse = r["Verse"]
        if verseFilter and verse != verseFilter:
            continue
        segments = splitStrongVerse(r["Scripture"])
        lineText, legend = renderStrongVerse(segments, color)
        verseLabel = f"{dim}{verse:>3}{reset}" if color else f"{verse:>3}"
        print(f"{verseLabel}  {lineText}")
        if verseFilter and verse == verseFilter:
            targetLegend = legend

    if verseFilter and targetLegend is not None and args.word is None:
        print()
        legendParts = [f"[{n}] {'/'.join(c)}" for n, c in sorted(targetLegend.items())]
        print("  ".join(legendParts))

    if args.word is not None:
        if targetLegend is None or args.word not in targetLegend:
            sys.stderr.write(f"這一節沒有第 {args.word} 個字\n")
            sys.exit(1)
        for code in targetLegend[args.word]:
            printStrongDefinition(args.dict, code, color)


def cmdList(args, conn):
    cur = conn.cursor()
    lang = "big5"
    rows = cur.execute(
        "SELECT book_index, name FROM book_name WHERE language=? ORDER BY book_index",
        (lang,),
    ).fetchall()
    start, end = 1, 66
    if args.testament == "舊約":
        start, end = 1, 39
    elif args.testament == "新約":
        start, end = 40, 66
    for r in rows:
        if start <= r["book_index"] <= end:
            print(f"{r['book_index']:>3}  {r['name']}")


def cmdIntro(args, conn):
    bookIndex = resolveAnyBookName(args.book, conn)
    if bookIndex is None:
        sys.stderr.write(f"找不到書卷: {args.book}\n")
        sys.exit(1)
    name = bookDisplayName(conn, bookIndex, "big5")
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT type, intro FROM book_intro WHERE language='big5' AND book_index=? ORDER BY type",
        (bookIndex,),
    ).fetchall()
    print(f"{bold}{name} 書卷簡介{reset}\n")
    for r in rows:
        label = introTypeLabel.get(r["type"], f"type{r['type']}")
        print(f"{dim}{label}{reset}  {r['intro']}\n")


def cmdNote(args, conn):
    bookIndex = resolveAnyBookName(args.book, conn)
    if bookIndex is None:
        sys.stderr.write(f"找不到書卷: {args.book}\n")
        sys.exit(1)
    try:
        chapterS, sectionS = args.ref.split(":")
        chapter, section = int(chapterS), int(sectionS)
    except ValueError:
        sys.stderr.write("章節格式錯誤，需為 章:節，例如 1:1\n")
        sys.exit(1)
    cur = conn.cursor()
    row = cur.execute(
        "SELECT note FROM footnote WHERE language='big5' AND book_index=? "
        "AND chapter=? AND section=? AND seq=?",
        (bookIndex, chapter, section, args.seq),
    ).fetchone()
    if not row:
        sys.stderr.write("查無此註解\n")
        sys.exit(1)
    name = bookDisplayName(conn, bookIndex, "big5")
    print(f"{bold}{name} {chapter}:{section} 註{args.seq}{reset}\n")
    print(row["note"])


def cmdSearch(args, conn):
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT book_index, chapter, section, content FROM content "
        "WHERE language=? AND content LIKE ? ORDER BY book_index, chapter, section",
        (args.lang, f"%{args.query}%"),
    ).fetchall()
    if not rows:
        print("沒有找到符合的經文")
        return
    for r in rows:
        acronymRow = cur.execute(
            "SELECT acronym_name FROM book_name WHERE book_index=? AND language=?",
            (r["book_index"], args.lang if args.lang in zhLangs else "big5"),
        ).fetchone()
        acr = acronymRow["acronym_name"] if acronymRow else str(r["book_index"])
        highlighted = r["content"].replace(
            args.query, f"{red}{args.query}{reset}"
        )
        print(f"{dim}{acr} {r['chapter']}:{r['section']}{reset}  {highlighted}")


def renderChapter(conn, bookIndex, chapter, sectionFilter, langPrimary,
                   langSecondary, showOutline, showFootnote, color):
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT section, content FROM content WHERE language=? AND book_index=? "
        "AND chapter=? ORDER BY section",
        (langPrimary, bookIndex, chapter),
    ).fetchall()
    if not rows:
        sys.stderr.write("查無此章節\n")
        sys.exit(1)

    outlines = getOutlines(conn, langPrimary, bookIndex, chapter) if showOutline else {}

    secondaryMap = {}
    if langSecondary:
        srows = cur.execute(
            "SELECT section, content FROM content WHERE language=? AND book_index=? "
            "AND chapter=? ORDER BY section",
            (langSecondary, bookIndex, chapter),
        ).fetchall()
        secondaryMap = {r["section"]: r["content"] for r in srows}

    indentUnit = "  "
    for r in rows:
        section = r["section"]
        if sectionFilter and section != sectionFilter:
            continue

        for o in outlines.get(section, []):
            indent = indentUnit * (o["level"] - 1)
            text = o["outline"]
            if color:
                print(f"{bold}{indent}{text}{reset}")
            else:
                print(f"{indent}{text}")

        content = r["content"]
        if showFootnote:
            fn = getFootnotes(conn, langPrimary, bookIndex, chapter, section)
            content = insertFootnoteMarkers(
                content, [(f["location"], f["seq"]) for f in fn], color=color
            )
        secLabel = f"{dim}{section:>3}{reset}" if color else f"{section:>3}"
        print(f"{secLabel}  {content}")

        if langSecondary and section in secondaryMap:
            secText = secondaryMap[section]
            if color:
                print(f"     {dim}{secText}{reset}")
            else:
                print(f"     {secText}")
        print()


def cmdRead(args, conn):
    bookIndex = resolveAnyBookName(args.book, conn)
    if bookIndex is None:
        sys.stderr.write(f"找不到書卷: {args.book}\n")
        sys.exit(1)

    chapter = args.chapter
    sectionFilter = None
    if ":" in str(chapter):
        chapterS, sectionS = str(chapter).split(":")
        chapter = int(chapterS)
        sectionFilter = int(sectionS)
    else:
        chapter = int(chapter)

    langPrimary = "cuv_big5" if args.cuv else "big5"
    langSecondary = "eng" if args.en else None

    name = bookDisplayName(conn, bookIndex, "big5")
    color = (not args.noColor) and supportsAnsiColor()
    header = f"{name} 第{chapter}章"
    if color:
        print(f"{bold}{header}{reset}\n")
    else:
        print(f"{header}\n")

    renderChapter(
        conn, bookIndex, chapter, sectionFilter,
        langPrimary, langSecondary,
        showOutline=not args.noOutline,
        showFootnote=not args.noFootnote,
        color=color,
    )


def buildParser():
    p = argparse.ArgumentParser(description="恢復本聖經 CLI / TUI")
    p.add_argument("--db", default=dbDefault, help="sqlite 資料庫路徑")
    p.add_argument(
        "--mode", choices=["auto", "restore", "strong"], default="auto",
        help="不帶子指令時要啟動的介面："
             "auto=依同目錄檔案自動判斷（兩者皆有時預設恢復本）、"
             "restore=強制恢復本 TUI、strong=強制原文 Strong TUI",
    )
    sub = p.add_subparsers(dest="cmd")

    colorParent = argparse.ArgumentParser(add_help=False)
    colorParent.add_argument("--no-color", dest="noColor", action="store_true")

    pList = sub.add_parser("list", help="列出書卷")
    pList.add_argument("testament", nargs="?", choices=["舊約", "新約"], default=None)
    pList.set_defaults(func=cmdList)

    pRead = sub.add_parser("read", parents=[colorParent], help="讀取經文")
    pRead.add_argument("book")
    pRead.add_argument("chapter", help="章數，或 章:節")
    pRead.add_argument("--en", action="store_true", help="附加英文對照(恢復本英文)")
    pRead.add_argument("--cuv", action="store_true", help="改用和合本正文")
    pRead.add_argument("--no-outline", dest="noOutline", action="store_true")
    pRead.add_argument("--no-footnote", dest="noFootnote", action="store_true")
    pRead.set_defaults(func=cmdRead)

    pSearch = sub.add_parser("search", help="全文搜尋")
    pSearch.add_argument("query")
    pSearch.add_argument("--lang", default="big5", choices=zhLangs + enLangs)
    pSearch.set_defaults(func=cmdSearch)

    pIntro = sub.add_parser("intro", help="書卷簡介")
    pIntro.add_argument("book")
    pIntro.set_defaults(func=cmdIntro)

    pNote = sub.add_parser("note", help="查看註解")
    pNote.add_argument("book")
    pNote.add_argument("ref", help="章:節，例如 1:1")
    pNote.add_argument("seq", type=int, help="註解編號")
    pNote.set_defaults(func=cmdNote)

    pStrong = sub.add_parser(
        "strong", parents=[colorParent], help="查詢 Strong 原文編號（需 MySword .dct.mybible 字典）"
    )
    pStrong.add_argument("code", help="Strong 編號，例如 G26 或 H157")
    pStrong.add_argument(
        "--dict", default=dictDefault,
        help="Strong 字典 .dct.mybible 檔案路徑（預設讀環境變數 BIBLE_STRONG_DICT）",
    )
    pStrong.set_defaults(func=cmdStrong)

    pOrig = sub.add_parser(
        "orig", parents=[colorParent],
        help="顯示和合本原文 Strong 編號對照（需 CUV+Strong 聖經模組，如 cuvt_bbl.mybible）",
    )
    pOrig.add_argument("book", help="書卷名（中／英文皆可），或 1-66 的編號")
    pOrig.add_argument("chapter", help="章數，或 章:節")
    pOrig.add_argument(
        "--strongbible", default=strongBibleDefault,
        help="含 Strong 編號的聖經模組路徑，如 cuvt_bbl.mybible"
             "（預設讀環境變數 BIBLE_STRONG_BIBLE）",
    )
    pOrig.add_argument(
        "--dict", default=dictDefault,
        help="配合 --word 查字義用，Strong 字典 .dct.mybible 路徑"
             "（預設讀環境變數 BIBLE_STRONG_DICT）",
    )
    pOrig.add_argument(
        "--word", type=int,
        help="直接查詢第 N 個標號字對應的原文字義（需同時指定確切的節，如 3:16）",
    )
    pOrig.set_defaults(func=cmdOrig)

    return p


def cwidth(ch):
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _isWordChar(ch):
    return ch.isascii() and (ch.isalnum() or ch in ("'", "-"))


def wrapMarked(chars, width):
    lines = []
    cur = []
    curw = 0
    pending = []
    pendw = 0

    def flushPending():
        nonlocal cur, curw, pending, pendw
        if not pending:
            return
        if curw + pendw <= width:
            cur.extend(pending)
            curw += pendw
        elif pendw <= width:
            lines.append(cur)
            cur = list(pending)
            curw = pendw
        else:
            for pc, pflag in pending:
                pw = cwidth(pc)
                if curw + pw > width:
                    lines.append(cur)
                    cur = []
                    curw = 0
                cur.append((pc, pflag))
                curw += pw
        pending = []
        pendw = 0

    for ch, flag in chars:
        if ch == "\n":
            flushPending()
            lines.append(cur)
            cur = []
            curw = 0
            continue
        if _isWordChar(ch):
            pending.append((ch, flag))
            pendw += cwidth(ch)
            continue
        flushPending()
        w = cwidth(ch)
        if curw + w > width:
            lines.append(cur)
            cur = []
            curw = 0
        cur.append((ch, flag))
        curw += w
    flushPending()
    lines.append(cur)
    return lines


def plainWrap(text, width):
    return wrapMarked([(c, 0) for c in text], width)


class Line:
    __slots__ = ("segments", "section", "clickable")

    def __init__(self, segments, section=None, clickable=False):
        self.segments = segments
        self.section = section
        self.clickable = clickable


class SegLine:
    __slots__ = ("segments", "verse")

    def __init__(self, segments, verse=None):
        self.segments = segments
        self.verse = verse


noteDbDefaultPath = os.path.join(scriptDir, ".bible-note.db")
noteDbPointerPath = os.path.join(scriptDir, ".bible-note.db.path")


def openNoteDb(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notes "
        "(book INTEGER, chapter INTEGER, section INTEGER, note TEXT, "
        "PRIMARY KEY(book, chapter, section))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bookmarks "
        "(book INTEGER, chapter INTEGER, section INTEGER, added_at TEXT, "
        "PRIMARY KEY(book, chapter, section))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS refs "
        "(book INTEGER, chapter INTEGER, section INTEGER, label TEXT, "
        "target_book INTEGER, target_chapter INTEGER, target_section INTEGER, "
        "PRIMARY KEY(book, chapter, section, label))"
    )
    conn.commit()
    return conn


optionFields = [
    ("recovery_db_path", "恢復本資料庫路徑 (bible.db)"),
    ("strong_db_path", "Strong 原文聖經模組路徑 (.bbl.mybible)"),
    ("dict_db_path", "Strong 原文字典路徑 (.dct.mybible)"),
    ("default_mode", "預設啟動模式 (restore 或 strong)"),
    ("default_english", "預設顯示英文對照 (1 或 0)"),
    ("default_outline", "預設顯示綱目及註解 (1 或 0)"),
    ("note_db_path", "筆記資料庫路徑 (.bible-note.db)"),
]


class World:
    """恢復本／原文 Strong 兩套平行畫面共用的導覽狀態容器。

    restore 與 strong 兩個模式在書卷清單／章節清單／讀經畫面上的捲動位置、
    目前選取的書卷章節、展開狀態、讀經內容快取等，結構完全相同，僅差在
    存取的資料來源與畫面文字／代號。這裡把該結構抽成一份，App 各持有一個
    self.restoreWorld 與 self.strongWorld 實例，避免同一組欄位在 __init__
    寫兩次、且日後修改時忘了同步另一份。
    """

    __slots__ = (
        "kind", "books",
        "bookIdx", "bookScroll",
        "selectedBookIndex", "chapterCount", "chapterIdx", "chapterScroll",
        "selectedChapter", "expanded",
        "readLines", "readScroll", "verseRow", "cacheKey", "cacheW",
        "booksTitle", "chaptersTitleSuffix",
        "bookClickTag", "chapterClickTag",
        "booksMode", "chaptersMode", "readMode",
        "backKeys", "supportsSearch",
    )

    def __init__(self, kind, books, booksTitle, chaptersTitleSuffix,
                 bookClickTag, chapterClickTag,
                 booksMode, chaptersMode, readMode,
                 backKeys, supportsSearch=False):
        self.kind = kind
        self.books = books

        self.bookIdx = 0
        self.bookScroll = 0

        self.selectedBookIndex = None
        self.chapterCount = 0
        self.chapterIdx = 0
        self.chapterScroll = 0

        self.selectedChapter = None
        self.expanded = set()

        self.readLines = []
        self.readScroll = 0
        self.verseRow = {}
        self.cacheKey = None
        self.cacheW = None

        self.booksTitle = booksTitle
        self.chaptersTitleSuffix = chaptersTitleSuffix
        self.bookClickTag = bookClickTag
        self.chapterClickTag = chapterClickTag
        self.booksMode = booksMode
        self.chaptersMode = chaptersMode
        self.readMode = readMode
        self.backKeys = backKeys
        self.supportsSearch = supportsSearch


class App:
    def __init__(self, curses_mod, stdscr, conn, strongBiblePath=None,
                 dictPath=None, initialMode="books"):
        self.curses = curses_mod
        self.stdscr = stdscr
        self.conn = conn
        self.hasDb = conn is not None

        self.strongBiblePath = strongBiblePath
        self.dictPath = dictPath
        self.hasStrongBible = bool(strongBiblePath)
        self.strongConn = None
        self.dictConn = None
        self.strongDefCache = {}

        self.mode = initialMode
        self.modeStack = []
        self.history = []
        self._quitPromptFrom = None
        self.statusMessage = None

        self.restoreWorld = World(
            kind="restore",
            books=self._loadBooks() if self.hasDb else [],
            booksTitle=" 書卷清單",
            chaptersTitleSuffix="",
            bookClickTag="book",
            chapterClickTag="chapter",
            booksMode="books",
            chaptersMode="chapters",
            readMode="read",
            backKeys=(27,),
            supportsSearch=True,
        )
        self.showEn = False
        self.showCuv = False
        self.showOutline = True

        self.searchQuery = ""
        self.searchInputText = ""
        self.searchResults = []
        self.searchScroll = 0
        self.searchIdx = 0

        self.strongWorld = World(
            kind="strong",
            books=list(enumerate(zhBookNames, start=1)) if self.hasStrongBible else [],
            booksTitle=" 書卷清單（原文 Strong）",
            chaptersTitleSuffix="（原文 Strong）",
            bookClickTag="strongbook",
            chapterClickTag="strongchapter",
            booksMode="strong_books",
            chaptersMode="strong_chapters",
            readMode="strong_read",
            backKeys=(27, self.curses.KEY_BACKSPACE, 127, 8),
            supportsSearch=False,
        )
        self._strongWordCodes = {}
        self.clickMapStrongWords = {}

        self.commandMode = False
        self.cmdBuffer = ""
        self.cmdError = None
        self._wantQuit = False
        self.helpScroll = 0
        self._helpTextLines = []

        self._textViewTitle = ""
        self._textViewRaw = ""
        self._textViewLines = []
        self._textViewScroll = 0
        self._textViewCacheW = None

        self.clickMapReadRefs = {}

        self.storageEnabled = False
        self.noteDbPath = None
        self.noteConn = None
        self.settings = {}
        self._optionFieldIdx = 0
        self._optionEditing = False
        self._optionEditBuffer = ""
        self._prevModeBeforeConfirm = None
        self._detectStorage()

    def _loadBooks(self):
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT book_index, name FROM book_name WHERE language='big5' ORDER BY book_index"
        ).fetchall()
        return [(r["book_index"], r["name"]) for r in rows]

    def _maxChapterFor(self, world, bookIndex):
        if world.kind == "strong":
            conn = self._openStrongConn()
            if conn is None:
                return 1
            row = conn.execute(
                "SELECT MAX(Chapter) AS m FROM Bible WHERE Book=?", (bookIndex,)
            ).fetchone()
        else:
            cur = self.conn.cursor()
            row = cur.execute(
                "SELECT MAX(chapter) AS m FROM content WHERE language='big5' AND book_index=?",
                (bookIndex,),
            ).fetchone()
        return row["m"] or 1


    def _pageStep(self):
        h, _w = self.stdscr.getmaxyx()
        return max(1, (h - 2) - 1)


    _NAV_KEYS = (
        "mode", "showEn", "showCuv", "showOutline",
        "searchQuery", "searchInputText", "searchResults", "searchScroll", "searchIdx",
    )

    _WORLD_NAV_KEYS = (
        "bookIdx", "bookScroll",
        "selectedBookIndex", "chapterCount", "chapterIdx", "chapterScroll",
        "selectedChapter", "expanded", "readScroll",
    )

    def _snapshotWorld(self, world):
        snap = {}
        for key in self._WORLD_NAV_KEYS:
            val = getattr(world, key)
            if isinstance(val, set):
                val = set(val)
            elif isinstance(val, list):
                val = list(val)
            snap[key] = val
        return snap

    def _snapshot(self):
        snap = {}
        for key in self._NAV_KEYS:
            val = getattr(self, key)
            if isinstance(val, set):
                val = set(val)
            elif isinstance(val, list):
                val = list(val)
            snap[key] = val
        snap["restoreWorld"] = self._snapshotWorld(self.restoreWorld)
        snap["strongWorld"] = self._snapshotWorld(self.strongWorld)
        return snap

    def _pushHistory(self):
        self.history.append(self._snapshot())

    def _goBack(self):
        if not self.history:
            return False
        snap = self.history.pop()
        for key, val in snap.items():
            if key == "restoreWorld":
                for k2, v2 in val.items():
                    setattr(self.restoreWorld, k2, v2)
            elif key == "strongWorld":
                for k2, v2 in val.items():
                    setattr(self.strongWorld, k2, v2)
            else:
                setattr(self, key, val)
        self.restoreWorld.cacheKey = None
        self.strongWorld.cacheKey = None
        return True


    def _copyToClipboard(self, text):
        return copyToClipboardText(text)

    def _copyTextSmart(self, text, label="經文"):
        if not text:
            return "沒有內容可複製"
        if self._copyToClipboard(text):
            return f"已複製{label}到剪貼簿"
        home = os.path.expanduser("~")
        path = os.path.join(home, ".bible-clipboard.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return f"找不到剪貼簿工具，已改將{label}存到 {path}"
        except OSError:
            return "找不到可用的剪貼簿工具，且無法寫入家目錄，複製失敗"

    def _currentReadSection(self):
        world = self.restoreWorld
        for line in world.readLines[world.readScroll:]:
            if line.section is not None:
                return line.section
        for line in world.readLines[:world.readScroll]:
            if line.section is not None:
                return line.section
        return None

    def _currentStrongReadVerse(self):
        world = self.strongWorld
        for line in world.readLines[world.readScroll:]:
            if line.verse is not None:
                return line.verse
        for line in world.readLines[:world.readScroll]:
            if line.verse is not None:
                return line.verse
        return None

    def _currentContextRef(self):
        r, s = self.restoreWorld, self.strongWorld
        if self.mode == "read" and r.selectedBookIndex and r.selectedChapter:
            return r.selectedBookIndex, r.selectedChapter, self._currentReadSection()
        if self.mode == "strong_read" and s.selectedBookIndex and s.selectedChapter:
            return s.selectedBookIndex, s.selectedChapter, self._currentStrongReadVerse()
        return None, None, None

    def _currentAnyBook(self):
        r, s = self.restoreWorld, self.strongWorld
        if self.mode in ("read", "chapters") and r.selectedBookIndex:
            return r.selectedBookIndex
        if self.mode == "books" and r.books:
            return r.books[r.bookIdx][0]
        if self.mode in ("strong_read", "strong_chapters") and s.selectedBookIndex:
            return s.selectedBookIndex
        if self.mode == "strong_books" and s.books:
            return s.books[s.bookIdx][0]
        return None

    def _parseRefArgs(self, tokens, ctxBook, ctxChapter):
        if len(tokens) == 0:
            if ctxBook is None or ctxChapter is None:
                raise ValueError("目前不在章節內，請提供完整卷章節")
            return ctxBook, ctxChapter, None
        if len(tokens) == 1:
            if ctxBook is None or ctxChapter is None:
                raise ValueError("目前不在章節內，請提供完整卷章節")
            if not tokens[0].isdigit():
                raise ValueError("節數需為數字")
            return ctxBook, ctxChapter, int(tokens[0])
        if len(tokens) == 2:
            if ctxBook is None:
                raise ValueError("目前未選擇書卷")
            if not (tokens[0].isdigit() and tokens[1].isdigit()):
                raise ValueError("章節需為數字")
            return ctxBook, int(tokens[0]), int(tokens[1])
        if len(tokens) == 3:
            bIdx = resolveAnyBookName(tokens[0], self.conn if self.hasDb else None)
            if bIdx is None:
                raise ValueError(f"找不到書卷: {tokens[0]}")
            if not (tokens[1].isdigit() and tokens[2].isdigit()):
                raise ValueError("章節需為數字")
            return bIdx, int(tokens[1]), int(tokens[2])
        raise ValueError("參數過多")

    def _toggleExpandSection(self, section):
        expanded = self.restoreWorld.expanded
        if section in expanded:
            expanded.discard(section)
        else:
            expanded.add(section)

    def _forceExpandSection(self, section):
        self.restoreWorld.expanded.add(section)
        self.restoreWorld.cacheKey = None

    def _copyCurrentVerse(self):
        world = self.restoreWorld
        section = self._currentReadSection()
        if section is None:
            self.statusMessage = "目前沒有可複製的經節"
            return
        langPrimary = "cuv_big5" if self.showCuv else "big5"
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT content FROM content WHERE language=? AND book_index=? "
            "AND chapter=? AND section=?",
            (langPrimary, world.selectedBookIndex, world.selectedChapter, section),
        ).fetchone()
        if not row:
            self.statusMessage = "查無經文內容"
            return
        bookName = bookDisplayName(self.conn, world.selectedBookIndex, "big5")
        text = f"{bookName} {world.selectedChapter}:{section}　{row['content']}"
        self.statusMessage = self._copyTextSmart(text, label=f"{bookName} {world.selectedChapter}:{section}")

    def _copyCurrentStrongVerse(self):
        world = self.strongWorld
        verse = self._currentStrongReadVerse()
        if verse is None:
            self.statusMessage = "目前沒有可複製的經節"
            return
        conn = self._openStrongConn()
        if conn is None:
            self.statusMessage = "找不到原文 Strong 聖經模組"
            return
        row = conn.execute(
            "SELECT Scripture FROM Bible WHERE Book=? AND Chapter=? AND Verse=?",
            (world.selectedBookIndex, world.selectedChapter, verse),
        ).fetchone()
        if not row:
            self.statusMessage = "查無經文內容"
            return
        text = strongTagPattern.sub("", row["Scripture"])
        bookName = zhBookNames[world.selectedBookIndex - 1]
        full = f"{bookName} {world.selectedChapter}:{verse}　{text}"
        self.statusMessage = self._copyTextSmart(full, label=f"{bookName} {world.selectedChapter}:{verse}")

    def _copyVersesForSections(self, bookIndex, chapter, sections, fromStrong):
        parts = []
        if fromStrong:
            conn = self._openStrongConn()
            if conn is None:
                self.statusMessage = "找不到原文 Strong 聖經模組"
                return
            bookName = zhBookNames[bookIndex - 1]
            for s in sections:
                row = conn.execute(
                    "SELECT Scripture FROM Bible WHERE Book=? AND Chapter=? AND Verse=?",
                    (bookIndex, chapter, s),
                ).fetchone()
                if row:
                    text = strongTagPattern.sub("", row["Scripture"])
                    parts.append(f"{bookName} {chapter}:{s}　{text}")
        else:
            langPrimary = "cuv_big5" if self.showCuv else "big5"
            bookName = bookDisplayName(self.conn, bookIndex, "big5")
            cur = self.conn.cursor()
            for s in sections:
                row = cur.execute(
                    "SELECT content FROM content WHERE language=? AND book_index=? "
                    "AND chapter=? AND section=?",
                    (langPrimary, bookIndex, chapter, s),
                ).fetchone()
                if row:
                    parts.append(f"{bookName} {chapter}:{s}　{row['content']}")
        if not parts:
            self.statusMessage = "查無指定經節"
            return
        self.statusMessage = self._copyTextSmart("\n".join(parts), label=f"{len(parts)} 節經文")

    def _copyFootnotesForSections(self, bookIndex, chapter, sections):
        if not self.hasDb:
            self.statusMessage = "找不到恢復本資料庫，無法複製註解"
            return
        langPrimary = "cuv_big5" if self.showCuv else "big5"
        parts = []
        for s in sections:
            for f in getFootnotes(self.conn, langPrimary, bookIndex, chapter, s):
                if f["note"]:
                    parts.append(f["note"])
        if not parts:
            self.statusMessage = "查無指定經節的註解"
            return
        self.statusMessage = self._copyTextSmart("\n".join(parts), label="註解")

    def _versePreview(self, bookIndex, chapter, section):
        if self.hasDb:
            langPrimary = "cuv_big5" if self.showCuv else "big5"
            row = self.conn.execute(
                "SELECT content FROM content WHERE language=? AND book_index=? "
                "AND chapter=? AND section=?",
                (langPrimary, bookIndex, chapter, section),
            ).fetchone()
            if row:
                return row["content"]
        conn = self._openStrongConn()
        if conn is not None:
            row = conn.execute(
                "SELECT Scripture FROM Bible WHERE Book=? AND Chapter=? AND Verse=?",
                (bookIndex, chapter, section),
            ).fetchone()
            if row:
                return strongTagPattern.sub("", row["Scripture"])
        return ""

    def _jumpRecovery(self, bookIndex, chapter, section):
        world = self.restoreWorld
        self._pushHistory()
        world.selectedBookIndex = bookIndex
        world.chapterCount = self._maxChapterFor(world, bookIndex)
        chapter = max(1, min(chapter, world.chapterCount))
        world.selectedChapter = chapter
        world.expanded = set()
        self.mode = world.readMode
        h, w = self.stdscr.getmaxyx()
        w = max(1, w)
        world.readLines, world.verseRow = self._buildReadLines(w)
        world.cacheKey = (
            bookIndex, chapter, self.showEn, self.showCuv, self.showOutline, frozenset(world.expanded),
        )
        world.cacheW = w
        world.readScroll = world.verseRow.get(section, 0) if section else 0

    def _jumpStrong(self, bookIndex, chapter, section):
        world = self.strongWorld
        self._pushHistory()
        world.selectedBookIndex = bookIndex
        world.chapterCount = self._maxChapterFor(world, bookIndex)
        chapter = max(1, min(chapter, world.chapterCount))
        world.selectedChapter = chapter
        world.expanded = set()
        self.mode = world.readMode
        h, w = self.stdscr.getmaxyx()
        w = max(1, w)
        world.readLines = self._buildStrongReadLines(w)
        world.cacheKey = (bookIndex, chapter, frozenset(world.expanded))
        world.cacheW = w
        world.readScroll = world.verseRow.get(section, 0) if section else 0

    def _openSearch(self):
        self._pushHistory()
        if self.searchQuery and self.searchResults:
            self.mode = "search_results"
        else:
            self.mode = "search_input"


    def _detectStorage(self):
        path = None
        if os.path.isfile(noteDbDefaultPath):
            path = noteDbDefaultPath
        elif os.path.isfile(noteDbPointerPath):
            try:
                with open(noteDbPointerPath, "r", encoding="utf-8") as f:
                    p = f.read().strip()
            except OSError:
                p = ""
            if p and os.path.isfile(p):
                path = p
        if not path:
            return
        try:
            conn = openNoteDb(path)
        except sqlite3.Error:
            return
        self.noteConn = conn
        self.noteDbPath = path
        self.storageEnabled = True
        self._loadSettings()

    def _openNoteDb(self):
        if self.noteConn is None and self.noteDbPath:
            try:
                self.noteConn = openNoteDb(self.noteDbPath)
            except sqlite3.Error:
                self.noteConn = None
        return self.noteConn

    def _loadSettings(self):
        conn = self._openNoteDb()
        if conn is None:
            return
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        self.settings = {r["key"]: r["value"] for r in rows}
        if self.settings.get("default_english") == "1":
            self.showEn = True
        elif self.settings.get("default_english") == "0":
            self.showEn = False
        if self.settings.get("default_outline") == "1":
            self.showOutline = True
        elif self.settings.get("default_outline") == "0":
            self.showOutline = False

    def _saveSetting(self, key, value):
        conn = self._openNoteDb()
        if conn is None:
            self.statusMessage = "無法開啟設定資料庫"
            return
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()
        self.settings[key] = value

    def _resetSettings(self):
        conn = self._openNoteDb()
        if conn is not None:
            conn.execute("DELETE FROM settings")
            conn.commit()
        self.settings = {}
        self.statusMessage = "已重設所有設定"

    def _isTypingText(self):
        return self.mode == "search_input" or (self.mode == "option" and self._optionEditing)

    def _setCmdError(self, message):
        self.cmdError = message

    def run(self):
        curses = self.curses
        curses.curs_set(0)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
            curses.mouseinterval(0)
        except curses.error:
            pass
        self.stdscr.keypad(True)
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(colorOutline, curses.COLOR_YELLOW, -1)
            curses.init_pair(colorFootnote, curses.COLOR_RED, -1)
            curses.init_pair(colorSection, curses.COLOR_CYAN, -1)
            curses.init_pair(colorSecondary, curses.COLOR_WHITE, -1)
            curses.init_pair(colorHeader, curses.COLOR_BLACK, curses.COLOR_YELLOW)
            curses.init_pair(colorHelp, curses.COLOR_BLACK, curses.COLOR_WHITE)
            curses.init_pair(colorCmdLine, curses.COLOR_WHITE, -1)
        except curses.error:
            pass

        while True:
            self.draw()
            try:
                ch = self.stdscr.get_wch()
            except curses.error:
                continue
            if not self.handleKey(ch):
                break

    def draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        if self.mode == "confirm_quit":
            drawMode = self._quitPromptFrom
        elif self.mode == "confirm_option_reset":
            drawMode = self._prevModeBeforeConfirm
        else:
            drawMode = self.mode
        if drawMode == "books":
            self._drawBooksFor(self.restoreWorld, h, w)
        elif drawMode == "chapters":
            self._drawChaptersFor(self.restoreWorld, h, w)
        elif drawMode == "read":
            self.drawRead(h, w)
        elif drawMode == "search_input":
            self.drawSearchInput(h, w)
        elif drawMode == "search_results":
            self.drawSearchResults(h, w)
        elif drawMode == "strong_books":
            self._drawBooksFor(self.strongWorld, h, w)
        elif drawMode == "strong_chapters":
            self._drawChaptersFor(self.strongWorld, h, w)
        elif drawMode == "strong_read":
            self.drawStrongRead(h, w)
        elif drawMode == "help":
            self.drawHelp(h, w)
        elif drawMode == "option":
            self.drawOption(h, w)
        elif drawMode == "text_view":
            self.drawTextView(h, w)
        if self.mode == "confirm_quit":
            self._drawConfirmPrompt(h, w, " 確定要離開程式嗎？(y/n) ")
        elif self.mode == "confirm_option_reset":
            self._drawConfirmPrompt(h, w, " 確定要重設所有設定嗎？(y/n) ")
        self.drawStatus(h, w)
        self.stdscr.refresh()

    def _drawConfirmPrompt(self, h, w, text):
        curses = self.curses
        y = h // 2
        x = max(0, (w - len(text)) // 2)
        try:
            self.stdscr.addstr(y, x, text[: max(0, w - 1)], curses.color_pair(colorHeader) | curses.A_BOLD)
        except curses.error:
            pass

    def drawStatus(self, h, w):
        curses = self.curses
        if self.commandMode:
            text = ":" + self.cmdBuffer
            attr = curses.color_pair(colorCmdLine) | curses.A_BOLD
            text = text[: max(0, w - 1)]
            try:
                self.stdscr.move(h - 1, 0)
                self.stdscr.clrtoeol()
                self.stdscr.addstr(h - 1, 0, text, attr)
            except curses.error:
                pass
            return
        if self.cmdError:
            text = self.cmdError
        else:
            text = self.statusMessage or ""
        text = text[: max(0, w - 1)]
        try:
            self.stdscr.addstr(h - 1, 0, text.ljust(w - 1), curses.color_pair(colorHelp))
        except curses.error:
            pass

    def _title(self, text, w):
        curses = self.curses
        try:
            self.stdscr.addstr(0, 0, text[: w - 1].ljust(w - 1), curses.color_pair(colorHeader) | curses.A_BOLD)
        except curses.error:
            pass

    def _bookNameFor(self, world, bookIndex):
        if world.kind == "strong":
            return zhBookNames[bookIndex - 1]
        return bookDisplayName(self.conn, bookIndex, "big5")

    def _drawBooksFor(self, world, h, w):
        curses = self.curses
        self._title(world.booksTitle, w)
        visible = h - 2
        if world.bookIdx < world.bookScroll:
            world.bookScroll = world.bookIdx
        if world.bookIdx >= world.bookScroll + visible:
            world.bookScroll = world.bookIdx - visible + 1

        self.clickMap = {}
        for rowI, (idx, name) in enumerate(world.books[world.bookScroll:world.bookScroll + visible]):
            y = rowI + 1
            testament = "舊約" if idx <= 39 else "新約"
            label = f"{idx:>3}  {name}  ({testament})"
            attr = curses.A_REVERSE if world.bookScroll + rowI == world.bookIdx else 0
            try:
                self.stdscr.addstr(y, 0, label[: w - 1].ljust(w - 1), attr)
            except curses.error:
                pass
            self.clickMap[y] = (world.bookClickTag, world.bookScroll + rowI)

    def _drawChaptersFor(self, world, h, w):
        curses = self.curses
        name = self._bookNameFor(world, world.selectedBookIndex)
        self._title(f" {name}{world.chaptersTitleSuffix}", w)
        visible = h - 2
        cols = max(1, (w - 1) // 8)
        self.clickMap = {}
        for i in range(world.chapterCount):
            row = i // cols
            col = i % cols
            y = row + 1 - world.chapterScroll
            if y < 1 or y > h - 2:
                continue
            x = col * 8
            label = f"第{i+1:>3}章"
            attr = curses.A_REVERSE if i == world.chapterIdx else 0
            try:
                self.stdscr.addstr(y, x, label, attr)
            except curses.error:
                pass
            self.clickMap[(y, col)] = (world.chapterClickTag, i)

    def _buildReadLines(self, w):
        curses = self.curses
        bookIndex = self.restoreWorld.selectedBookIndex
        chapter = self.restoreWorld.selectedChapter
        langPrimary = "cuv_big5" if self.showCuv else "big5"
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT section, content FROM content WHERE language=? AND book_index=? AND chapter=? ORDER BY section",
            (langPrimary, bookIndex, chapter),
        ).fetchall()
        outlines = getOutlines(self.conn, langPrimary, bookIndex, chapter) if self.showOutline else {}
        secondaryMap = {}
        if self.showEn:
            srows = cur.execute(
                "SELECT section, content FROM content WHERE language='eng' AND book_index=? AND chapter=? ORDER BY section",
                (bookIndex, chapter),
            ).fetchall()
            secondaryMap = {r["section"]: r["content"] for r in srows}

        fnEnabled = self.showOutline
        refsBySection = {}
        if self.storageEnabled:
            noteConn = self._openNoteDb()
            if noteConn is not None:
                for rr in noteConn.execute(
                    "SELECT section, label, target_book, target_chapter, target_section FROM refs "
                    "WHERE book=? AND chapter=? ORDER BY section, label",
                    (bookIndex, chapter),
                ).fetchall():
                    refsBySection.setdefault(rr["section"], []).append(rr)

        lines = []
        verseRow = {}
        indentUnit = "  "
        for r in rows:
            section = r["section"]
            for o in outlines.get(section, []):
                indent = indentUnit * (o["level"] - 1)
                for wl in plainWrap(indent + o["outline"], w - 1):
                    lines.append(Line([("".join(c for c, _ in wl), colorOutline | curses.A_BOLD, None)]))
            fn = getFootnotes(self.conn, langPrimary, bookIndex, chapter, section) if fnEnabled else []
            fnPairs = [(f["location"], f["seq"]) for f in fn]
            chars = []
            content = r["content"]
            marks = {loc - 1: seq for loc, seq in fnPairs}
            for i, c in enumerate(content):
                if i in marks:
                    for mc in str(marks[i]):
                        chars.append((mc, colorFootnote))
                chars.append((c, 0))
            for rr in refsBySection.get(section, []):
                target = (rr["target_book"], rr["target_chapter"], rr["target_section"])
                chars.append((rr["label"], ("ref", target)))
            prefix = f"{section:>3}  "
            wrapped = wrapMarked([(c, 0) for c in prefix] + chars, w - 1)
            verseRow[section] = len(lines)
            for wi, wl in enumerate(wrapped):
                segs = []
                curFlag = None
                buf = ""
                for c, flag in wl:
                    if flag != curFlag:
                        if buf:
                            segs.append(self._readSegment(buf, curFlag))
                        buf = c
                        curFlag = flag
                    else:
                        buf += c
                if buf:
                    segs.append(self._readSegment(buf, curFlag))
                lines.append(Line(segs, section=section, clickable=True))

            if self.showEn and section in secondaryMap:
                for wl in plainWrap("     " + secondaryMap[section], w - 1):
                    lines.append(Line([("".join(c for c, _ in wl), colorSecondary, None)], section=section))

            if fnEnabled and section in self.restoreWorld.expanded:
                for f in fn:
                    label = f"      [{f['seq']}] "
                    for wl in plainWrap(label + (f["note"] or ""), w - 1):
                        lines.append(Line([("".join(c for c, _ in wl), colorSecondary, None)]))
            lines.append(Line([("", 0, None)]))
        return lines, verseRow

    @staticmethod
    def _readSegment(text, flag):
        if isinstance(flag, tuple) and flag and flag[0] == "ref":
            return (text, colorSection, flag[1])
        return (text, flag if isinstance(flag, int) else 0, None)

    def drawRead(self, h, w):
        curses = self.curses
        world = self.restoreWorld
        name = bookDisplayName(self.conn, world.selectedBookIndex, "big5")
        flags = []
        if self.showEn:
            flags.append("英文")
        if self.showCuv:
            flags.append("和合本")
        flagS = ("　[" + "／".join(flags) + "]") if flags else ""
        self._title(f" {name} 第{world.selectedChapter}章{flagS}", w)

        cacheKey = (
            world.selectedBookIndex,
            world.selectedChapter,
            self.showEn,
            self.showCuv,
            self.showOutline,
            frozenset(world.expanded),
        )
        if cacheKey != world.cacheKey or w != world.cacheW:
            world.readLines, world.verseRow = self._buildReadLines(w)
            world.cacheKey = cacheKey
            world.cacheW = w
        visible = h - 2
        maxScroll = max(0, len(world.readLines) - visible)
        world.readScroll = max(0, min(world.readScroll, maxScroll))

        self.clickMapRead = {}
        self.clickMapReadRefs = {}
        for rowI, line in enumerate(world.readLines[world.readScroll:world.readScroll + visible]):
            y = rowI + 1
            x = 0
            regions = []
            for text, attr, refTarget in line.segments:
                color = curses.color_pair(attr & 0xF) if attr else 0
                try:
                    self.stdscr.addstr(y, x, text, color | (curses.A_BOLD if attr == (colorOutline | curses.A_BOLD) else 0))
                except curses.error:
                    pass
                textWidth = sum(cwidth(c) for c in text)
                if refTarget is not None:
                    regions.append((x, x + textWidth, refTarget))
                x += textWidth
            if regions:
                self.clickMapReadRefs[y] = regions
            if line.clickable:
                self.clickMapRead[y] = line.section

    def drawSearchInput(self, h, w):
        self._title(" 搜尋經文", w)
        try:
            self.stdscr.addstr(2, 0, "關鍵字：" + self.searchInputText)
        except self.curses.error:
            pass

    def drawSearchResults(self, h, w):
        curses = self.curses
        self._title(f" 搜尋「{self.searchQuery}」共 {len(self.searchResults)} 筆", w)
        visible = h - 2
        if self.searchIdx < self.searchScroll:
            self.searchScroll = self.searchIdx
        if self.searchIdx >= self.searchScroll + visible:
            self.searchScroll = self.searchIdx - visible + 1
        self.clickMap = {}
        for rowI, r in enumerate(self.searchResults[self.searchScroll:self.searchScroll + visible]):
            y = rowI + 1
            label = f"{r['acr']} {r['chapter']}:{r['section']}  {r['content']}"
            attr = curses.A_REVERSE if self.searchScroll + rowI == self.searchIdx else 0
            try:
                self.stdscr.addstr(y, 0, label[: w - 1].ljust(w - 1), attr)
            except curses.error:
                pass
            self.clickMap[y] = ("search_result", self.searchScroll + rowI)


    def _openStrongConn(self):
        if self.strongConn is None and self.strongBiblePath:
            self.strongConn = _openSqliteSoft(self.strongBiblePath)
        return self.strongConn

    def _openDictConn(self):
        if self.dictConn is None and self.dictPath:
            self.dictConn = _openSqliteSoft(self.dictPath)
        return self.dictConn

    def _strongDefinitionLines(self, code):
        if code in self.strongDefCache:
            return self.strongDefCache[code]
        if code in ("G0", "H0"):
            lines = [f"[{code} 為佔位符，無對應字典資料]"]
            self.strongDefCache[code] = lines
            return lines
        dconn = self._openDictConn()
        if dconn is None:
            lines = ["尚未偵測到 Strong 字典（.dct.mybible），無法查字義。"]
            self.strongDefCache[code] = lines
            return lines
        row = dconn.execute(
            "SELECT word, data FROM dictionary WHERE word = ?", (code,)
        ).fetchone()
        if not row:
            lines = [f"查無 Strong 編號: {code}"]
        else:
            header = f"── Strong {row['word']} ──"
            body = renderDictHtml(row["data"], color=False)
            lines = [header] + body.split("\n")
        self.strongDefCache[code] = lines
        return lines

    def _buildStrongReadLines(self, w):
        world = self.strongWorld
        bookIndex = world.selectedBookIndex
        chapter = world.selectedChapter
        conn = self._openStrongConn()
        self._strongWordCodes = {}
        world.verseRow = {}
        lines = []
        if conn is None:
            lines.append(SegLine([("找不到 Strong 原文聖經模組", 0, None)]))
            return lines

        rows = conn.execute(
            "SELECT Verse, Scripture FROM Bible WHERE Book=? AND Chapter=? ORDER BY Verse",
            (bookIndex, chapter),
        ).fetchall()
        if not rows:
            lines.append(SegLine([("查無此章節", 0, None)]))
            return lines

        for r in rows:
            verse = r["Verse"]
            segments = splitStrongVerse(r["Scripture"])
            prefix = f"{verse:>3}  "
            chars = [(c, None) for c in prefix]
            wordIdx = 0
            for text, codes in segments:
                if codes:
                    wordIdx += 1
                    key = (bookIndex, chapter, verse, wordIdx)
                    self._strongWordCodes[key] = codes
                    chars.extend((c, key) for c in text)
                else:
                    chars.extend((c, None) for c in text)

            wrapped = wrapMarked(chars, w - 1)
            world.verseRow[verse] = len(lines)
            for wl in wrapped:
                segs = []
                curKey = "__NONE__"
                buf = ""
                for c, key in wl:
                    if key != curKey:
                        if buf:
                            attr = 0
                            if curKey != "__NONE__" and curKey is not None:
                                attr = colorSection if curKey in world.expanded else colorFootnote
                            segs.append((buf, attr, None if curKey == "__NONE__" else curKey))
                        buf = c
                        curKey = key
                    else:
                        buf += c
                if buf:
                    attr = 0
                    if curKey != "__NONE__" and curKey is not None:
                        attr = colorSection if curKey in world.expanded else colorFootnote
                    segs.append((buf, attr, None if curKey == "__NONE__" else curKey))
                lines.append(SegLine(segs, verse=verse))

            for wi in range(1, wordIdx + 1):
                key = (bookIndex, chapter, verse, wi)
                if key not in world.expanded:
                    continue
                for code in self._strongWordCodes.get(key, []):
                    for defLine in self._strongDefinitionLines(code):
                        for wl2 in plainWrap("      " + defLine, w - 1):
                            text = "".join(c for c, _ in wl2)
                            lines.append(SegLine([(text, colorSecondary, None)]))

            lines.append(SegLine([("", 0, None)]))
        return lines

    def drawStrongRead(self, h, w):
        curses = self.curses
        world = self.strongWorld
        name = zhBookNames[world.selectedBookIndex - 1]
        self._title(f" {name} 第{world.selectedChapter}章（原文 Strong）", w)

        cacheKey = (
            world.selectedBookIndex,
            world.selectedChapter,
            frozenset(world.expanded),
        )
        if cacheKey != world.cacheKey or w != world.cacheW:
            world.readLines = self._buildStrongReadLines(w)
            world.cacheKey = cacheKey
            world.cacheW = w

        visible = h - 2
        maxScroll = max(0, len(world.readLines) - visible)
        world.readScroll = max(0, min(world.readScroll, maxScroll))

        self.clickMapStrongWords = {}
        for rowI, line in enumerate(
            world.readLines[world.readScroll:world.readScroll + visible]
        ):
            y = rowI + 1
            x = 0
            regions = []
            for text, attr, key in line.segments:
                color = curses.color_pair(attr & 0xF) if attr else 0
                try:
                    self.stdscr.addstr(y, x, text, color)
                except curses.error:
                    pass
                textWidth = sum(cwidth(c) for c in text)
                if key is not None:
                    regions.append((x, x + textWidth, key))
                x += textWidth
            if regions:
                self.clickMapStrongWords[y] = regions

    def _keyBooksFor(self, world, ch):
        curses = self.curses
        n = len(world.books)
        if ch in (curses.KEY_UP, ord("k")):
            world.bookIdx = max(0, world.bookIdx - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            world.bookIdx = min(n - 1, world.bookIdx + 1)
        elif ch == curses.KEY_NPAGE or ch == ord(" "):
            world.bookIdx = min(n - 1, world.bookIdx + self._pageStep())
        elif ch == curses.KEY_PPAGE:
            world.bookIdx = max(0, world.bookIdx - self._pageStep())
        elif ch in (10, 13, curses.KEY_ENTER):
            self._enterBookFor(world)
        elif world.supportsSearch and ch == ord("/"):
            self._openSearch()
        elif ch in world.backKeys:
            self._goBack()
        return True

    def _enterBookFor(self, world):
        self._pushHistory()
        world.selectedBookIndex = world.books[world.bookIdx][0]
        world.chapterCount = self._maxChapterFor(world, world.selectedBookIndex)
        world.chapterIdx = 0
        world.chapterScroll = 0
        self.mode = world.chaptersMode

    def _keyChaptersFor(self, world, ch):
        curses = self.curses
        cols = max(1, (curses.COLS - 1) // 8) if hasattr(curses, "COLS") else 8
        if ch in (curses.KEY_UP, ord("k")):
            world.chapterIdx = max(0, world.chapterIdx - cols)
        elif ch in (curses.KEY_DOWN, ord("j")):
            world.chapterIdx = min(world.chapterCount - 1, world.chapterIdx + cols)
        elif ch in (curses.KEY_LEFT, ord("h")):
            world.chapterIdx = max(0, world.chapterIdx - 1)
        elif ch in (curses.KEY_RIGHT, ord("l")):
            world.chapterIdx = min(world.chapterCount - 1, world.chapterIdx + 1)
        elif ch == curses.KEY_NPAGE or ch == ord(" "):
            world.chapterIdx = min(
                world.chapterCount - 1, world.chapterIdx + self._pageStep() * cols
            )
        elif ch == curses.KEY_PPAGE:
            world.chapterIdx = max(0, world.chapterIdx - self._pageStep() * cols)
        elif ch in (10, 13, curses.KEY_ENTER):
            self._enterChapterFor(world)
        elif ch in (27, curses.KEY_BACKSPACE, 127, 8):
            self._goBack()
        return True

    def _enterChapterFor(self, world):
        self._pushHistory()
        world.selectedChapter = world.chapterIdx + 1
        world.readScroll = 0
        world.expanded = set()
        self.mode = world.readMode

    def _keyStrongRead(self, ch):
        curses = self.curses
        world = self.strongWorld
        if ch in (curses.KEY_UP, ord("k")):
            world.readScroll = max(0, world.readScroll - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            world.readScroll += 1
        elif ch == curses.KEY_NPAGE or ch == ord(" "):
            world.readScroll += self._pageStep()
        elif ch == curses.KEY_PPAGE:
            world.readScroll = max(0, world.readScroll - self._pageStep())
        elif ch in (curses.KEY_LEFT, ord("h")):
            if world.selectedChapter > 1:
                world.selectedChapter -= 1
                world.readScroll = 0
                world.expanded = set()
        elif ch in (curses.KEY_RIGHT, ord("l")):
            if world.selectedChapter < world.chapterCount:
                world.selectedChapter += 1
                world.readScroll = 0
                world.expanded = set()
        elif ch in (27, curses.KEY_BACKSPACE, 127, 8):
            self._goBack()
        return True

    def _buildHelpLines(self):
        lines = []
        lines.append("↑↓／j k／PageUp／PageDown／Space 捲動本頁，按 b/B/Esc 或其他鍵關閉")
        lines.append("")
        lines.append("一般模式：")
        lines.append("  ↑↓ 或 j k 移動／捲動，Enter 或滑鼠左鍵點擊 選取")
        lines.append("  PageUp/PageDown 或 Space  整頁上下捲動（類似 w3m）")
        lines.append("  讀經畫面 ←→ 切換上下章；e 英文對照；c 恢復本／和合本；n 大綱")
        lines.append("  讀經畫面點擊經文或 Enter 對準該節  展開／收合該節註解")
        lines.append("  y   複製目前經節　　/   搜尋全經文")
        lines.append("  b 或 B   返回上一頁（含畫面／模式切換的完整紀錄）")
        lines.append("  q   離開程式（詢問 y/n）　　Q   直接離開程式")
        lines.append("  :   進入指令模式（類似 vim），可輸入以下指令")
        if self.hasStrongBible:
            lines.append("  s   快速切換到原文 Strong 畫面")
        if self.hasDb:
            lines.append("  r   快速切回恢復本畫面")
        if self.storageEnabled:
            lines.append("  o 或 O   開啟設定（同 :option）")
        lines.append("")
        lines.append("指令模式：")
        lines.append("  :q                    結束程式 (Y/n)")
        lines.append("  :Q                    直接結束程式")
        lines.append("  :strong 或 :S         切換為 Strong 模式並跳至本章節")
        lines.append("                        （不在章節內時跳至目錄）")
        lines.append("  :recovery 或 :R       切換為恢復本，規則同上")
        lines.append("  :strong genesis 1 1   切換至 Strong 模式並跳至指定書卷章節")
        lines.append("                        （參數可只給部分：:strong 1／:strong 1 1）")
        lines.append("  :recovery genesis 1 1 同上，切換至恢復本")
        lines.append("  :1                    跳至本章指定節")
        lines.append("  :1 1                  跳至本卷指定章節")
        lines.append("  :genesis 1 1          跳至指定書卷章節")
        lines.append("  :footnote 或 :F       顯示本節註解（參數規則同 :strong）")
        lines.append("  :intro [書卷]         顯示書卷簡介（省略書卷則用目前書卷）")
        lines.append("  :copy 或 :C           複製目前經文")
        lines.append("  :copy 1 3-5 7         複製本章指定經節（x-y 連續／空白分隔不連續）")
        lines.append("  :copy #1              複製本章指定節的註解")
        lines.append("  :english on/off 或 :E 開關英文對照（不帶參數則切換）")
        lines.append("  :outline on/off 或 :O 開關綱目及註解顯示（不帶參數則切換）")
        lines.append("  :search 或 :find      在目前經文版本搜尋（可多字串，交集查詢）")
        lines.append("  :search -e Christ     在英文經文搜尋")
        lines.append("  :search a b --exclude c   同時含 a、b 後再扣除含 c 的結果")
        lines.append("  按 / 搜尋             與 :search 同一套查詢邏輯（交集／-e／--exclude）")
        lines.append("  :help                 顯示本說明")
        lines.append("")
        lines.append("　（註：:S 已配給 :strong、:R 已配給 :recovery，")
        lines.append("　  :search／:reference 則另有 :find／:ref 簡寫）")
        lines.append("")
        if self.storageEnabled:
            lines.append(f"儲存功能（已啟用，資料存於 {self.noteDbPath}）：")
            lines.append("  :setup-storage        （已啟用，無需再次執行）")
            lines.append("  :option               進入設定模式；一般模式 o/O 同此")
            lines.append("  :option reset         重設所有設定 (Y/n)")
            lines.append("  :note 或 :N           對目前經節做筆記（開啟外部編輯器）")
            lines.append("  :note show            顯示目前經節的筆記（參數規則同 :strong）")
            lines.append("  :bookmark／:M／:mark  將目前經節加入書籤")
            lines.append("  :bookmark show        顯示所有書籤")
            lines.append("  :reference 或 :ref    為目前經節加上指向本章指定節的串珠")
            lines.append("  :reference 1          （同上，指向本章指定節）")
            lines.append("  :reference genesis 1 1 genesis 2 2")
            lines.append("                        在兩個完整經節之間建立串珠")
            lines.append("                        （串珠顯示於經節後方 a,b,...，可點按跳轉）")
        else:
            lines.append("儲存功能尚未啟用：執行 :setup-storage 以啟用")
            lines.append("設定／筆記／書籤／串珠功能（會在本程式所在目錄建立 .bible-note.db）")
        lines.append("")
        lines.append("新舊約書卷中英對照：")
        for i, (zh, en) in enumerate(zip(zhBookNames, enBookNames), start=1):
            lines.append(f"  {i:>2}  {zh:<6}{en}")
        return lines

    def _cmdHelp(self):
        self.modeStack.append(self.mode)
        self.helpScroll = 0
        self._helpTextLines = self._buildHelpLines()
        self.mode = "help"

    def drawHelp(self, h, w):
        self._title(" 說明", w)
        visible = h - 2
        lines = self._helpTextLines
        maxScroll = max(0, len(lines) - visible)
        self.helpScroll = max(0, min(self.helpScroll, maxScroll))
        for i, l in enumerate(lines[self.helpScroll:self.helpScroll + visible]):
            try:
                self.stdscr.addstr(i + 1, 1, l[: max(0, w - 2)])
            except self.curses.error:
                pass

    def drawOption(self, h, w):
        curses = self.curses
        self._title(" 設定 (Enter 編輯／儲存，Esc 取消編輯，b 返回)", w)
        for i, (key, label) in enumerate(optionFields):
            y = i + 1
            if y > h - 2:
                break
            if self._optionEditing and i == self._optionFieldIdx:
                line = f"{label}: {self._optionEditBuffer}"
            else:
                curVal = self.settings.get(key, "") or ""
                line = f"{label}: {curVal}"
            attr = curses.A_REVERSE if i == self._optionFieldIdx else 0
            try:
                self.stdscr.addstr(y, 0, line[: w - 1].ljust(w - 1), attr)
            except curses.error:
                pass

    def _openTextView(self, title, bodyText):
        self._pushHistory()
        self._textViewTitle = title
        self._textViewRaw = bodyText
        self._textViewScroll = 0
        self._textViewCacheW = None
        self._textViewLines = []
        self.mode = "text_view"

    def drawTextView(self, h, w):
        self._title(f" {self._textViewTitle}", w)
        if w != self._textViewCacheW:
            wrapped = []
            for raw in self._textViewRaw.split("\n"):
                if raw == "":
                    wrapped.append("")
                    continue
                for wl in plainWrap(raw, max(1, w - 1)):
                    wrapped.append("".join(c for c, _ in wl))
            self._textViewLines = wrapped
            self._textViewCacheW = w
        lines = self._textViewLines
        visible = h - 2
        maxScroll = max(0, len(lines) - visible)
        self._textViewScroll = max(0, min(self._textViewScroll, maxScroll))
        for i, l in enumerate(lines[self._textViewScroll:self._textViewScroll + visible]):
            try:
                self.stdscr.addstr(i + 1, 0, l[: max(0, w - 1)])
            except self.curses.error:
                pass

    def _keyTextView(self, ch):
        curses = self.curses
        if ch in (curses.KEY_UP, ord("k")):
            self._textViewScroll = max(0, self._textViewScroll - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self._textViewScroll += 1
        elif ch == curses.KEY_NPAGE or ch == ord(" "):
            self._textViewScroll += self._pageStep()
        elif ch == curses.KEY_PPAGE:
            self._textViewScroll = max(0, self._textViewScroll - self._pageStep())
        elif ch in (27, curses.KEY_BACKSPACE, 127, 8):
            self._goBack()
        return True

    def _keyOption(self, ch):
        curses = self.curses
        if self._optionEditing:
            if ch in (10, 13, curses.KEY_ENTER):
                key, _label = optionFields[self._optionFieldIdx]
                self._applyOptionValue(key, self._optionEditBuffer.strip())
                self._optionEditing = False
            elif ch == 27:
                self._optionEditing = False
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                self._optionEditBuffer = self._optionEditBuffer[:-1]
            elif 32 <= ch < 0x110000:
                try:
                    self._optionEditBuffer += chr(ch)
                except ValueError:
                    pass
            return True
        if ch in (curses.KEY_UP, ord("k")):
            self._optionFieldIdx = max(0, self._optionFieldIdx - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self._optionFieldIdx = min(len(optionFields) - 1, self._optionFieldIdx + 1)
        elif ch in (10, 13, curses.KEY_ENTER):
            key, _label = optionFields[self._optionFieldIdx]
            self._optionEditBuffer = self.settings.get(key, "") or ""
            self._optionEditing = True
        elif ch in (27, curses.KEY_BACKSPACE, 127, 8):
            self._goBack()
        return True

    def _keyHelp(self, ch):
        curses = self.curses
        if ch in (curses.KEY_UP, ord("k")):
            self.helpScroll = max(0, self.helpScroll - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.helpScroll += 1
        elif ch == curses.KEY_NPAGE or ch == ord(" "):
            self.helpScroll += self._pageStep()
        elif ch == curses.KEY_PPAGE:
            self.helpScroll = max(0, self.helpScroll - self._pageStep())
        else:
            self.mode = self.modeStack.pop() if self.modeStack else "books"
        return True


    def _handleCommandModeKey(self, ch):
        curses = self.curses
        if ch in (10, 13, curses.KEY_ENTER):
            cmdline = self.cmdBuffer
            self.commandMode = False
            self.cmdBuffer = ""
            self._executeCommand(cmdline)
            if self._wantQuit:
                return False
            return True
        if ch == 27:
            self.commandMode = False
            self.cmdBuffer = ""
            return True
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            self.cmdBuffer = self.cmdBuffer[:-1]
            return True
        if 32 <= ch < 0x110000:
            try:
                self.cmdBuffer += chr(ch)
            except ValueError:
                pass
            return True
        return True

    def _executeCommand(self, cmdline):
        cmdline = cmdline.strip()
        self.cmdError = None
        if not cmdline:
            return
        tokens = cmdline.split()
        head = tokens[0]
        rest = tokens[1:]
        headLower = head.lower()
        try:
            if head == "q":
                self._quitPromptFrom = self.mode
                self.mode = "confirm_quit"
            elif head == "Q":
                self._wantQuit = True
            elif headLower == "strong" or head == "S":
                self._cmdSwitchMode(rest, toStrong=True)
            elif headLower == "recovery" or head == "R":
                self._cmdSwitchMode(rest, toStrong=False)
            elif headLower == "footnote" or head == "F":
                self._cmdFootnote(rest)
            elif headLower == "intro":
                self._cmdIntro(rest)
            elif headLower == "copy" or head == "C":
                self._cmdCopy(rest)
            elif headLower == "english" or head == "E":
                self._cmdToggle(rest, "showEn", "英文對照")
            elif headLower == "outline" or head == "O":
                self._cmdToggle(rest, "showOutline", "綱目及註解")
            elif headLower in ("search", "find"):
                self._cmdSearch(rest)
            elif headLower == "help":
                self._cmdHelp()
            elif headLower == "setup-storage":
                self._cmdSetupStorage()
            elif headLower == "option":
                self._cmdOption(rest)
            elif headLower == "note" or head == "N":
                self._cmdNote(rest)
            elif headLower in ("bookmark", "mark") or head == "M":
                self._cmdBookmark(rest)
            elif headLower in ("reference", "ref"):
                self._cmdReference(rest)
            else:
                self._cmdGoto(tokens)
        except Exception as e:
            self.cmdError = f"指令執行錯誤: {e}"

    def _cmdGoto(self, tokens):
        inStrongWorld = self.mode.startswith("strong")
        ctxBook, ctxChapter, _ = self._currentContextRef()
        if ctxBook is None:
            if inStrongWorld:
                ctxBook, ctxChapter = self.strongWorld.selectedBookIndex, self.strongWorld.selectedChapter
            else:
                ctxBook, ctxChapter = self.restoreWorld.selectedBookIndex, self.restoreWorld.selectedChapter
        try:
            bookIndex, chapter, section = self._parseRefArgs(tokens, ctxBook, ctxChapter)
        except ValueError as e:
            self._setCmdError(str(e))
            return
        if inStrongWorld:
            if not self.hasStrongBible:
                self._setCmdError("找不到原文 Strong 聖經模組")
                return
            self._jumpStrong(bookIndex, chapter, section)
        else:
            if not self.hasDb:
                self._setCmdError("找不到恢復本資料庫")
                return
            self._jumpRecovery(bookIndex, chapter, section)

    def _cmdSwitchMode(self, tokens, toStrong):
        if not tokens:
            if self.mode == "read" and self.restoreWorld.selectedBookIndex and self.restoreWorld.selectedChapter:
                ctxBook, ctxChapter = self.restoreWorld.selectedBookIndex, self.restoreWorld.selectedChapter
            elif self.mode == "strong_read" and self.strongWorld.selectedBookIndex and self.strongWorld.selectedChapter:
                ctxBook, ctxChapter = self.strongWorld.selectedBookIndex, self.strongWorld.selectedChapter
            else:
                ctxBook, ctxChapter = None, None
            if ctxBook and ctxChapter:
                if toStrong:
                    if not self.hasStrongBible:
                        self._setCmdError("找不到原文 Strong 聖經模組")
                        return
                    self._jumpStrong(ctxBook, ctxChapter, None)
                else:
                    if not self.hasDb:
                        self._setCmdError("找不到恢復本資料庫")
                        return
                    self._jumpRecovery(ctxBook, ctxChapter, None)
            else:
                if toStrong and not self.hasStrongBible:
                    self._setCmdError("找不到原文 Strong 聖經模組")
                    return
                if (not toStrong) and not self.hasDb:
                    self._setCmdError("找不到恢復本資料庫")
                    return
                self._pushHistory()
                self.mode = "strong_books" if toStrong else "books"
            return
        ctxBook, ctxChapter, _ = self._currentContextRef()
        try:
            bookIndex, chapter, section = self._parseRefArgs(tokens, ctxBook, ctxChapter)
        except ValueError as e:
            self._setCmdError(str(e))
            return
        if toStrong:
            if not self.hasStrongBible:
                self._setCmdError("找不到原文 Strong 聖經模組")
                return
            self._jumpStrong(bookIndex, chapter, section)
        else:
            if not self.hasDb:
                self._setCmdError("找不到恢復本資料庫")
                return
            self._jumpRecovery(bookIndex, chapter, section)

    def _cmdFootnote(self, tokens):
        if not self.hasDb:
            self._setCmdError("找不到恢復本資料庫")
            return
        if not tokens:
            if self.mode == "read" and self.restoreWorld.selectedBookIndex and self.restoreWorld.selectedChapter:
                section = self._currentReadSection()
                if section is None:
                    self._setCmdError("目前沒有可顯示註解的經節")
                    return
                self._forceExpandSection(section)
                return
            if self.mode == "strong_read" and self.strongWorld.selectedBookIndex and self.strongWorld.selectedChapter:
                verse = self._currentStrongReadVerse()
                if verse is None:
                    self._setCmdError("目前沒有可顯示註解的經節")
                    return
                self._jumpRecovery(self.strongWorld.selectedBookIndex, self.strongWorld.selectedChapter, verse)
                self._forceExpandSection(verse)
                return
            self._setCmdError("目前不在章節內，請提供完整卷章節")
            return
        ctxBook, ctxChapter, _ = self._currentContextRef()
        try:
            bookIndex, chapter, section = self._parseRefArgs(tokens, ctxBook, ctxChapter)
        except ValueError as e:
            self._setCmdError(str(e))
            return
        if section is None:
            self._setCmdError("請指定節數")
            return
        self._jumpRecovery(bookIndex, chapter, section)
        self._forceExpandSection(section)

    def _cmdIntro(self, tokens):
        if not self.hasDb:
            self._setCmdError("找不到恢復本資料庫")
            return
        if tokens:
            name = " ".join(tokens)
            bookIndex = resolveAnyBookName(name, self.conn)
            if bookIndex is None:
                self._setCmdError(f"找不到書卷: {name}")
                return
        else:
            bookIndex = self._currentAnyBook()
            if bookIndex is None:
                self._setCmdError("目前未選擇書卷")
                return
        bookName = bookDisplayName(self.conn, bookIndex, "big5")
        rows = self.conn.execute(
            "SELECT type, intro FROM book_intro WHERE language='big5' AND book_index=? ORDER BY type",
            (bookIndex,),
        ).fetchall()
        if not rows:
            text = "（查無書卷簡介）"
        else:
            parts = []
            for r in rows:
                label = introTypeLabel.get(r["type"], f"type{r['type']}")
                parts.append(f"{label}\n{r['intro']}")
            text = "\n\n".join(parts)
        self._openTextView(f"{bookName} 書卷簡介", text)

    def _cmdCopy(self, tokens):
        if not tokens:
            if self.mode == "read":
                self._copyCurrentVerse()
            elif self.mode == "strong_read":
                self._copyCurrentStrongVerse()
            else:
                self._setCmdError("目前沒有可複製的經節")
            return
        footnoteMode = tokens[0].startswith("#")
        sections = []
        for tok in tokens:
            if footnoteMode != tok.startswith("#"):
                self._setCmdError("請統一使用 # 前綴以複製註解，或省略以複製經文")
                return
            t = tok[1:] if footnoteMode else tok
            try:
                if "-" in t:
                    a, b = t.split("-", 1)
                    a, b = int(a), int(b)
                    sections.extend(range(min(a, b), max(a, b) + 1))
                else:
                    sections.append(int(t))
            except ValueError:
                self._setCmdError("格式錯誤，請用 1 3-5 7 這樣的格式")
                return
        ctxBook, ctxChapter, _ = self._currentContextRef()
        if ctxBook is None or ctxChapter is None:
            self._setCmdError("目前不在章節內")
            return
        if footnoteMode:
            self._copyFootnotesForSections(ctxBook, ctxChapter, sections)
        else:
            self._copyVersesForSections(ctxBook, ctxChapter, sections, fromStrong=(self.mode == "strong_read"))

    def _cmdToggle(self, tokens, attrName, label):
        if not tokens:
            setattr(self, attrName, not getattr(self, attrName))
        elif tokens[0].lower() == "on":
            setattr(self, attrName, True)
        elif tokens[0].lower() == "off":
            setattr(self, attrName, False)
        else:
            self._setCmdError("請用 on 或 off，或不帶參數直接切換")
            return
        self.restoreWorld.cacheKey = None
        state = "開啟" if getattr(self, attrName) else "關閉"
        self.statusMessage = f"已{state}{label}"

    def _parseSearchTokens(self, tokens):
        useEnglish = False
        if tokens and tokens[0] == "-e":
            useEnglish = True
            tokens = tokens[1:]
        includeTerms, excludeTerms = [], []
        excludeMode = False
        for tok in tokens:
            if tok == "--exclude":
                excludeMode = True
                continue
            (excludeTerms if excludeMode else includeTerms).append(tok)
        if not includeTerms:
            return None
        return useEnglish, includeTerms, excludeTerms

    def _execSearchQuery(self, useEnglish, includeTerms, excludeTerms):
        lang = "eng" if useEnglish else ("cuv_big5" if self.showCuv else "big5")
        where = " AND ".join(["content LIKE ?"] * len(includeTerms))
        params = [lang] + [f"%{t}%" for t in includeTerms]
        sql = f"SELECT book_index, chapter, section, content FROM content WHERE language=? AND ({where})"
        if excludeTerms:
            notWhere = " OR ".join(["content LIKE ?"] * len(excludeTerms))
            sql += f" AND NOT ({notWhere})"
            params += [f"%{t}%" for t in excludeTerms]
        sql += " ORDER BY book_index, chapter, section"
        cur = self.conn.cursor()
        rows = cur.execute(sql, params).fetchall()
        acrLang = lang if lang in zhLangs else "big5"
        results = []
        for r in rows:
            acrRow = cur.execute(
                "SELECT acronym_name FROM book_name WHERE book_index=? AND language=?",
                (r["book_index"], acrLang),
            ).fetchone()
            results.append({
                "book_index": r["book_index"],
                "acr": acrRow["acronym_name"] if acrRow else str(r["book_index"]),
                "chapter": r["chapter"],
                "section": r["section"],
                "content": r["content"],
            })
        label = "／".join(includeTerms)
        if excludeTerms:
            label += "　排除：" + "／".join(excludeTerms)
        return label, results

    def _cmdSearch(self, tokens):
        if not self.hasDb:
            self._setCmdError("找不到恢復本資料庫")
            return
        parsed = self._parseSearchTokens(tokens)
        if parsed is None:
            self._setCmdError("請至少輸入一個搜尋字串")
            return
        useEnglish, includeTerms, excludeTerms = parsed
        label, results = self._execSearchQuery(useEnglish, includeTerms, excludeTerms)
        self._pushHistory()
        self.searchInputText = " ".join(tokens)
        self.searchQuery = label
        self.searchResults = results
        self.searchIdx = 0
        self.searchScroll = 0
        self.mode = "search_results"

    def _cmdSetupStorage(self):
        if self.storageEnabled:
            self.statusMessage = "儲存功能已啟用"
            return
        try:
            conn = openNoteDb(noteDbDefaultPath)
        except sqlite3.Error as e:
            self._setCmdError(f"無法建立儲存資料庫: {e}")
            return
        self.noteConn = conn
        self.noteDbPath = noteDbDefaultPath
        self.storageEnabled = True
        self.statusMessage = f"已啟用儲存功能（{noteDbDefaultPath}）"

    def _cmdOption(self, rest):
        if not self.storageEnabled:
            self._setCmdError("請先執行 :setup-storage 啟用儲存功能")
            return
        if rest and rest[0] == "reset":
            self._prevModeBeforeConfirm = self.mode
            self.mode = "confirm_option_reset"
            return
        self._pushHistory()
        self.mode = "option"
        self._optionFieldIdx = 0
        self._optionEditing = False

    def _applyOptionValue(self, key, value):
        if key == "note_db_path" and value and value != self.noteDbPath:
            try:
                newConn = openNoteDb(value)
            except sqlite3.Error as e:
                self.statusMessage = f"無法開啟資料庫: {e}"
                return
            if self.noteConn is not None:
                try:
                    self.noteConn.close()
                except sqlite3.Error:
                    pass
            self.noteConn = newConn
            self.noteDbPath = value
            try:
                with open(noteDbPointerPath, "w", encoding="utf-8") as f:
                    f.write(value)
            except OSError:
                pass
        self._saveSetting(key, value)
        self.statusMessage = "已儲存設定"

    def _cmdNote(self, tokens):
        if not self.storageEnabled:
            self._setCmdError("請先執行 :setup-storage 啟用儲存功能")
            return
        show = False
        if tokens and tokens[0] == "show":
            show = True
            tokens = tokens[1:]
        ctxBook, ctxChapter, ctxSection = self._currentContextRef()
        try:
            bookIndex, chapter, section = self._parseRefArgs(tokens, ctxBook, ctxChapter)
        except ValueError as e:
            self._setCmdError(str(e))
            return
        if section is None:
            section = ctxSection
        if section is None:
            self._setCmdError("請指定節數")
            return
        if show:
            self._showNote(bookIndex, chapter, section)
        else:
            self._editNote(bookIndex, chapter, section)

    def _showNote(self, bookIndex, chapter, section):
        conn = self._openNoteDb()
        text = ""
        if conn is not None:
            row = conn.execute(
                "SELECT note FROM notes WHERE book=? AND chapter=? AND section=?",
                (bookIndex, chapter, section),
            ).fetchone()
            text = row["note"] if row else ""
        bookName = zhBookNames[bookIndex - 1] if 1 <= bookIndex <= 66 else str(bookIndex)
        self._openTextView(f"{bookName} {chapter}:{section} 筆記", text or "（尚無筆記）")

    def _editNote(self, bookIndex, chapter, section):
        conn = self._openNoteDb()
        if conn is None:
            self.statusMessage = "無法開啟筆記資料庫"
            return
        row = conn.execute(
            "SELECT note FROM notes WHERE book=? AND chapter=? AND section=?",
            (bookIndex, chapter, section),
        ).fetchone()
        existing = row["note"] if row else ""
        editor = os.environ.get("EDITOR") or ("notepad" if isWindows else "nano")
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as tf:
                tf.write(existing)
                tmpPath = tf.name
        except OSError as e:
            self.statusMessage = f"無法建立暫存筆記檔: {e}"
            return
        curses = self.curses
        try:
            curses.def_prog_mode()
        except curses.error:
            pass
        curses.endwin()
        editorOk = True
        try:
            subprocess.run([editor, tmpPath])
        except (FileNotFoundError, OSError) as e:
            editorOk = False
            self.statusMessage = (
                f"無法開啟編輯器 {editor}: {e}　"
                f"（可設定環境變數 EDITOR 指定其他編輯器）"
            )
        finally:
            try:
                curses.reset_prog_mode()
            except curses.error:
                pass
            self.stdscr.refresh()
        if not editorOk:
            try:
                os.unlink(tmpPath)
            except OSError:
                pass
            return
        try:
            with open(tmpPath, "r", encoding="utf-8") as f:
                newText = f.read()
        except OSError:
            newText = existing
        finally:
            try:
                os.unlink(tmpPath)
            except OSError:
                pass
        newText = newText.rstrip("\n")
        if newText.strip():
            conn.execute(
                "INSERT INTO notes(book, chapter, section, note) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(book, chapter, section) DO UPDATE SET note=excluded.note",
                (bookIndex, chapter, section, newText),
            )
        else:
            conn.execute(
                "DELETE FROM notes WHERE book=? AND chapter=? AND section=?",
                (bookIndex, chapter, section),
            )
        conn.commit()
        self.statusMessage = "已儲存筆記"

    def _cmdBookmark(self, tokens):
        if not self.storageEnabled:
            self._setCmdError("請先執行 :setup-storage 啟用儲存功能")
            return
        if tokens and tokens[0] == "show":
            self._showBookmarks()
            return
        ctxBook, ctxChapter, ctxSection = self._currentContextRef()
        if ctxBook is None or ctxChapter is None or ctxSection is None:
            self._setCmdError("目前沒有可加入書籤的經節")
            return
        conn = self._openNoteDb()
        if conn is None:
            self.statusMessage = "無法開啟書籤資料庫"
            return
        conn.execute(
            "INSERT INTO bookmarks(book, chapter, section, added_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(book, chapter, section) DO UPDATE SET added_at=excluded.added_at",
            (ctxBook, ctxChapter, ctxSection, datetime.datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
        self.statusMessage = "已加入書籤"

    def _showBookmarks(self):
        conn = self._openNoteDb()
        lines = []
        if conn is not None:
            rows = conn.execute(
                "SELECT book, chapter, section, added_at FROM bookmarks ORDER BY book, chapter, section"
            ).fetchall()
            for r in rows:
                bookName = zhBookNames[r["book"] - 1] if 1 <= r["book"] <= 66 else str(r["book"])
                preview = self._versePreview(r["book"], r["chapter"], r["section"])
                lines.append(f"{bookName} {r['chapter']}:{r['section']}　{preview}")
        text = "\n".join(lines) if lines else "（尚無書籤）"
        self._openTextView("書籤", text)

    def _cmdReference(self, tokens):
        if not self.storageEnabled:
            self._setCmdError("請先執行 :setup-storage 啟用儲存功能")
            return
        if len(tokens) == 6:
            try:
                srcBook = resolveAnyBookName(tokens[0], self.conn if self.hasDb else None)
                if srcBook is None:
                    raise ValueError(f"找不到書卷: {tokens[0]}")
                if not (tokens[1].isdigit() and tokens[2].isdigit()):
                    raise ValueError("章節需為數字")
                srcChapter, srcSection = int(tokens[1]), int(tokens[2])
                tgtBook = resolveAnyBookName(tokens[3], self.conn if self.hasDb else None)
                if tgtBook is None:
                    raise ValueError(f"找不到書卷: {tokens[3]}")
                if not (tokens[4].isdigit() and tokens[5].isdigit()):
                    raise ValueError("章節需為數字")
                tgtChapter, tgtSection = int(tokens[4]), int(tokens[5])
            except ValueError as e:
                self._setCmdError(str(e))
                return
        else:
            ctxBook, ctxChapter, ctxSection = self._currentContextRef()
            if ctxBook is None or ctxChapter is None or ctxSection is None:
                self._setCmdError("目前沒有可加上串珠的經節")
                return
            try:
                tgtBook, tgtChapter, tgtSection = self._parseRefArgs(tokens, ctxBook, ctxChapter)
            except ValueError as e:
                self._setCmdError(str(e))
                return
            if tgtSection is None:
                self._setCmdError("請指定目標節數")
                return
            srcBook, srcChapter, srcSection = ctxBook, ctxChapter, ctxSection
        conn = self._openNoteDb()
        if conn is None:
            self.statusMessage = "無法開啟串珠資料庫"
            return
        existing = conn.execute(
            "SELECT label FROM refs WHERE book=? AND chapter=? AND section=?",
            (srcBook, srcChapter, srcSection),
        ).fetchall()
        used = {r["label"] for r in existing}
        label = None
        for i in range(26):
            cand = chr(ord("a") + i)
            if cand not in used:
                label = cand
                break
        if label is None:
            self.statusMessage = "本節串珠已達上限"
            return
        conn.execute(
            "INSERT INTO refs(book, chapter, section, label, target_book, target_chapter, target_section) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (srcBook, srcChapter, srcSection, label, tgtBook, tgtChapter, tgtSection),
        )
        conn.commit()
        if self.mode == "read" and srcBook == self.restoreWorld.selectedBookIndex and srcChapter == self.restoreWorld.selectedChapter:
            self.restoreWorld.cacheKey = None
        self.statusMessage = f"已加上串珠 {label}"

    def handleKey(self, ch):
        curses = self.curses
        if isinstance(ch, str):
            ch = ord(ch)
        self.statusMessage = None
        self.cmdError = None

        if ch == curses.KEY_MOUSE:
            if self.commandMode:
                try:
                    curses.getmouse()
                except curses.error:
                    pass
                return True
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                return True
            self._handleMouse(my, mx, bstate)
            return True

        if self.commandMode:
            return self._handleCommandModeKey(ch)

        if self.mode == "confirm_quit":
            if ch in (ord("y"), ord("Y")):
                return False
            if ch in (ord("n"), ord("N"), 27):
                self.mode = self._quitPromptFrom
                self._quitPromptFrom = None
            return True

        if self.mode == "confirm_option_reset":
            if ch in (ord("y"), ord("Y")):
                self._resetSettings()
                self.mode = self._prevModeBeforeConfirm or "books"
                self._prevModeBeforeConfirm = None
            elif ch in (ord("n"), ord("N"), 27):
                self.mode = self._prevModeBeforeConfirm or "books"
                self._prevModeBeforeConfirm = None
            return True

        if ch == ord("?") and self.mode != "help":
            self._cmdHelp()
            return True
        if self.mode == "help":
            return self._keyHelp(ch)

        if ch == ord(":") and not self._isTypingText():
            self.commandMode = True
            self.cmdBuffer = ""
            self.cmdError = None
            return True

        if ch == ord("Q") and not self._isTypingText():
            return False
        if ch == ord("q") and not self._isTypingText():
            self._quitPromptFrom = self.mode
            self.mode = "confirm_quit"
            return True
        if ch in (ord("b"), ord("B")) and not self._isTypingText():
            self._goBack()
            return True

        if not self._isTypingText():
            if ch in (ord("s"), ord("S")) and self.hasStrongBible and not self.mode.startswith("strong"):
                self._pushHistory()
                self.mode = "strong_books"
                return True
            if ch in (ord("r"), ord("R")) and self.hasDb and self.mode.startswith("strong"):
                self._pushHistory()
                self.mode = "books"
                return True
            if ch in (ord("o"), ord("O")) and self.storageEnabled and self.mode != "option":
                self._cmdOption([])
                return True

        if self.mode == "books":
            return self._keyBooksFor(self.restoreWorld, ch)
        elif self.mode == "chapters":
            return self._keyChaptersFor(self.restoreWorld, ch)
        elif self.mode == "read":
            return self._keyRead(ch)
        elif self.mode == "search_input":
            return self._keySearchInput(ch)
        elif self.mode == "search_results":
            return self._keySearchResults(ch)
        elif self.mode == "strong_books":
            return self._keyBooksFor(self.strongWorld, ch)
        elif self.mode == "strong_chapters":
            return self._keyChaptersFor(self.strongWorld, ch)
        elif self.mode == "strong_read":
            return self._keyStrongRead(ch)
        elif self.mode == "option":
            return self._keyOption(ch)
        elif self.mode == "text_view":
            return self._keyTextView(ch)
        return True

    def _handleMouse(self, y, x, bstate):
        curses = self.curses
        if bstate & getattr(curses, "BUTTON4_PRESSED", 0):
            self._scrollCurrent(-3)
            return
        if bstate & getattr(curses, "BUTTON5_PRESSED", 0):
            self._scrollCurrent(3)
            return
        clicked = bool(bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_DOUBLE_CLICKED))
        if not clicked:
            return
        if self.mode == "books":
            item = self.clickMap.get(y)
            if item and item[0] == self.restoreWorld.bookClickTag:
                self.restoreWorld.bookIdx = item[1]
                self._enterBookFor(self.restoreWorld)
        elif self.mode == "chapters":
            for key, item in self.clickMap.items():
                if isinstance(key, tuple) and key[0] == y:
                    self.restoreWorld.chapterIdx = item[1]
                    self._enterChapterFor(self.restoreWorld)
                    break
        elif self.mode == "read":
            refRegions = self.clickMapReadRefs.get(y)
            jumped = False
            if refRegions:
                for xs, xe, target in refRegions:
                    if xs <= x < xe:
                        tb, tc, ts = target
                        self._jumpRecovery(tb, tc, ts)
                        jumped = True
                        break
            if not jumped:
                section = self.clickMapRead.get(y)
                if section is not None:
                    self._toggleExpandSection(section)
        elif self.mode == "search_results":
            item = self.clickMap.get(y)
            if item and item[0] == "search_result":
                self.searchIdx = item[1]
                self._gotoSearchResult()
        elif self.mode == "strong_books":
            item = self.clickMap.get(y)
            if item and item[0] == self.strongWorld.bookClickTag:
                self.strongWorld.bookIdx = item[1]
                self._enterBookFor(self.strongWorld)
        elif self.mode == "strong_chapters":
            for key, item in self.clickMap.items():
                if isinstance(key, tuple) and key[0] == y:
                    self.strongWorld.chapterIdx = item[1]
                    self._enterChapterFor(self.strongWorld)
                    break
        elif self.mode == "strong_read":
            regions = self.clickMapStrongWords.get(y)
            if regions:
                for xs, xe, key in regions:
                    if xs <= x < xe:
                        expanded = self.strongWorld.expanded
                        if key in expanded:
                            expanded.discard(key)
                        else:
                            expanded.add(key)
                        break

    def _scrollCurrent(self, delta):
        if self.mode == "books":
            r = self.restoreWorld
            r.bookIdx = max(0, min(len(r.books) - 1, r.bookIdx + delta))
        elif self.mode == "chapters":
            self.restoreWorld.chapterScroll = max(0, self.restoreWorld.chapterScroll + delta)
        elif self.mode == "read":
            self.restoreWorld.readScroll = max(0, self.restoreWorld.readScroll + delta)
        elif self.mode == "search_results":
            self.searchIdx = max(0, min(len(self.searchResults) - 1, self.searchIdx + delta))
        elif self.mode == "strong_books":
            s = self.strongWorld
            s.bookIdx = max(0, min(len(s.books) - 1, s.bookIdx + delta))
        elif self.mode == "strong_chapters":
            self.strongWorld.chapterScroll = max(0, self.strongWorld.chapterScroll + delta)
        elif self.mode == "strong_read":
            self.strongWorld.readScroll = max(0, self.strongWorld.readScroll + delta)
        elif self.mode == "text_view":
            self._textViewScroll = max(0, self._textViewScroll + delta)
        elif self.mode == "help":
            self.helpScroll = max(0, self.helpScroll + delta)

    def _keyRead(self, ch):
        curses = self.curses
        world = self.restoreWorld
        if ch in (curses.KEY_UP, ord("k")):
            world.readScroll = max(0, world.readScroll - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            world.readScroll += 1
        elif ch == curses.KEY_NPAGE or ch == ord(" "):
            world.readScroll += self._pageStep()
        elif ch == curses.KEY_PPAGE:
            world.readScroll = max(0, world.readScroll - self._pageStep())
        elif ch in (curses.KEY_LEFT, ord("h")):
            if world.selectedChapter > 1:
                world.selectedChapter -= 1
                world.readScroll = 0
                world.expanded = set()
        elif ch in (curses.KEY_RIGHT, ord("l")):
            if world.selectedChapter < world.chapterCount:
                world.selectedChapter += 1
                world.readScroll = 0
                world.expanded = set()
        elif ch == ord("e"):
            self.showEn = not self.showEn
        elif ch == ord("c"):
            self.showCuv = not self.showCuv
        elif ch == ord("n"):
            self.showOutline = not self.showOutline
        elif ch in (10, 13, curses.KEY_ENTER):
            section = self._currentReadSection()
            if section is not None:
                self._toggleExpandSection(section)
        elif ch in (ord("y"), ord("Y")):
            self._copyCurrentVerse()
        elif ch == ord("/"):
            self._openSearch()
        elif ch in (27, curses.KEY_BACKSPACE, 127, 8):
            self._goBack()
        return True

    def _keySearchInput(self, ch):
        curses = self.curses
        if ch in (10, 13, curses.KEY_ENTER):
            self._runSearch()
            self.mode = "search_results"
        elif ch == 27:
            self._goBack()
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.searchInputText = self.searchInputText[:-1]
        elif 32 <= ch < 0x110000:
            try:
                self.searchInputText += chr(ch)
            except ValueError:
                pass
        return True

    def _runSearch(self):
        if not self.hasDb:
            self.searchResults = []
            return
        tokens = self.searchInputText.split()
        parsed = self._parseSearchTokens(tokens)
        if parsed is None:
            self.searchResults = []
            return
        useEnglish, includeTerms, excludeTerms = parsed
        label, results = self._execSearchQuery(useEnglish, includeTerms, excludeTerms)
        self.searchQuery = label
        self.searchResults = results
        self.searchIdx = 0
        self.searchScroll = 0

    def _keySearchResults(self, ch):
        curses = self.curses
        if ch in (curses.KEY_UP, ord("k")):
            self.searchIdx = max(0, self.searchIdx - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.searchIdx = min(len(self.searchResults) - 1, self.searchIdx + 1)
        elif ch == curses.KEY_NPAGE or ch == ord(" "):
            self.searchIdx = min(len(self.searchResults) - 1, self.searchIdx + self._pageStep())
        elif ch == curses.KEY_PPAGE:
            self.searchIdx = max(0, self.searchIdx - self._pageStep())
        elif ch in (10, 13, curses.KEY_ENTER):
            self._gotoSearchResult()
        elif ch == ord("/"):
            self._pushHistory()
            self.mode = "search_input"
        elif ch in (27, curses.KEY_BACKSPACE, 127, 8):
            self._goBack()
        return True

    def _gotoSearchResult(self):
        if not self.searchResults:
            return
        self._pushHistory()
        r = self.searchResults[self.searchIdx]
        world = self.restoreWorld
        world.selectedBookIndex = r["book_index"]
        world.chapterCount = self._maxChapterFor(world, world.selectedBookIndex)
        world.selectedChapter = r["chapter"]
        world.readScroll = 0
        world.expanded = {r["section"]}
        self.mode = "read"


def _tuiMain(stdscr, curses_mod, dbPath, strongBiblePath, dictPath, initialMode):
    conn = connect(dbPath) if dbPath else None
    app = App(
        curses_mod, stdscr, conn,
        strongBiblePath=strongBiblePath, dictPath=dictPath, initialMode=initialMode,
    )
    app.run()


def runTui(dbPath, strongBiblePath=None, dictPath=None, initialMode="books"):
    try:
        import curses
    except ImportError:
        sys.stderr.write(
            "無法載入 curses 模組，互動式 TUI 需要它才能執行。\n"
        )
        if isWindows:
            sys.stderr.write(
                "偵測到目前為 Windows 系統，請先執行下列指令安裝後再試一次：\n"
                "    pip install windows-curses\n\n"
            )
        sys.stderr.write("在此之前，您仍可使用 CLI 模式，例如：\n")
        sys.stderr.write("    python3 bible.py list\n")
        sys.stderr.write("    python3 bible.py read 創世記 1\n")
        sys.stderr.write("    python3 bible.py orig 創世記 1\n")
        sys.exit(1)

    if dbPath and not os.path.exists(dbPath):
        dbPath = None

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    os.environ.setdefault("ESCDELAY", "25")

    curses.wrapper(_tuiMain, curses, dbPath, strongBiblePath, dictPath, initialMode)


def _openSqliteSoft(path):
    if not path or not os.path.exists(path):
        return None
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _printStrongDefinitionSafe(dictPath, code, color):
    if code in ("G0", "H0"):
        msg = f"[{code} 為佔位符，無對應字典資料]"
        print(f"{dim}{msg}{reset}" if color else msg)
        return
    dconn = _openSqliteSoft(dictPath)
    if dconn is None:
        print("尚未偵測到 Strong 字典（.dct.mybible），無法查字義。")
        return
    row = dconn.execute(
        "SELECT word, data FROM dictionary WHERE word = ?", (code,)
    ).fetchone()
    if not row:
        print(f"查無 Strong 編號: {code}")
        return
    header = f"Strong {row['word']}"
    print(f"\n{bold}{header}{reset}\n" if color else f"\n{header}\n")
    print(renderDictHtml(row["data"], color=color))


def _printOrigChapter(bconn, bookIndex, chapter, verseFilter, color):
    rows = bconn.execute(
        "SELECT Verse, Scripture FROM Bible WHERE Book=? AND Chapter=? ORDER BY Verse",
        (bookIndex, chapter),
    ).fetchall()
    if not rows:
        print("查無此章節")
        return None

    bookName = zhBookNames[bookIndex - 1]
    header = f"{bookName} 第{chapter}章"
    print(f"{bold}{header}{reset}\n" if color else f"{header}\n")

    targetLegend = None
    for r in rows:
        verse = r["Verse"]
        if verseFilter and verse != verseFilter:
            continue
        segments = splitStrongVerse(r["Scripture"])
        lineText, legend = renderStrongVerse(segments, color)
        verseLabel = f"{dim}{verse:>3}{reset}" if color else f"{verse:>3}"
        print(f"{verseLabel}  {lineText}")
        if verseFilter and verse == verseFilter:
            targetLegend = legend

    if verseFilter and targetLegend is not None:
        legendParts = [f"[{n}] {'/'.join(c)}" for n, c in sorted(targetLegend.items())]
        print("  ".join(legendParts))
    return targetLegend


def runStrongRepl(strongBiblePath, dictPath, canSwitchToRestore=False):
    color = supportsAnsiColor()
    bconn = _openSqliteSoft(strongBiblePath)
    if bconn is None:
        sys.stderr.write(f"找不到 Strong 原文聖經模組: {strongBiblePath}\n")
        return None

    title = "原文 Strong 查詢模式"
    print(f"{bold}{title}{reset}" if color else title)
    print("指令：")
    print("  b <書卷> <章>[:節]   顯示原文對照經文（指定節時，末尾會列出標號對照 Strong 編號）")
    print("  w <編號>            查詢上一次顯示的節中，第 N 個標號字的字義")
    print("  s <G26|H157>        直接查 Strong 編號")
    if canSwitchToRestore:
        print("  r                   切換回恢復本介面")
    print("  q                   離開")

    lastLegend = None
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "q":
            return None
        if cmd in ("r", "restore") and canSwitchToRestore:
            return "restore"
        if cmd == "b" and len(parts) >= 3:
            bookIndex = resolveAnyBookName(parts[1])
            if bookIndex is None:
                print(f"找不到書卷: {parts[1]}（請用中／英文書卷名或 1-66 的編號）")
                continue
            chapterArg = parts[2]
            verseFilter = None
            try:
                if ":" in chapterArg:
                    chapterS, verseS = chapterArg.split(":")
                    chapter, verseFilter = int(chapterS), int(verseS)
                else:
                    chapter = int(chapterArg)
            except ValueError:
                print("章節格式錯誤，需為 章 或 章:節，例如 1 或 1:1")
                continue
            lastLegend = _printOrigChapter(bconn, bookIndex, chapter, verseFilter, color)
        elif cmd == "w" and len(parts) >= 2:
            if not lastLegend:
                print("請先用 b 指令顯示含節號的經文（需含 :節）")
                continue
            try:
                n = int(parts[1])
            except ValueError:
                print("請輸入數字編號")
                continue
            if n not in lastLegend:
                print(f"這一節沒有第 {n} 個標號字")
                continue
            for code in lastLegend[n]:
                _printStrongDefinitionSafe(dictPath, code, color)
        elif cmd == "s" and len(parts) >= 2:
            code = normalizeStrongCode(parts[1])
            if not code:
                print("請在編號前加上 G（希臘文）或 H（希伯來文），例如 G26 或 H157")
                continue
            _printStrongDefinitionSafe(dictPath, code, color)
        else:
            options = "b / w / s" + (" / r" if canSwitchToRestore else "") + " / q"
            print(f"無法辨識的指令，可用: {options}")


def _loadStoredSettingsDict():
    path = None
    if os.path.isfile(noteDbDefaultPath):
        path = noteDbDefaultPath
    elif os.path.isfile(noteDbPointerPath):
        try:
            with open(noteDbPointerPath, "r", encoding="utf-8") as f:
                p = f.read().strip()
        except OSError:
            p = ""
        if p and os.path.isfile(p):
            path = p
    if not path:
        return {}
    try:
        conn = sqlite3.connect(path)
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    return {k: v for k, v in rows}


def launchInteractive(args, resources):
    storedSettings = _loadStoredSettingsDict()

    dbPath = args.db if os.path.exists(args.db) else resources["db"]
    if not (dbPath and os.path.exists(dbPath)):
        storedDb = storedSettings.get("recovery_db_path")
        if storedDb and os.path.exists(storedDb):
            dbPath = storedDb
    hasDb = bool(dbPath and os.path.exists(dbPath))

    strongBiblePath = resources["strongBible"]
    if not strongBiblePath:
        storedStrong = storedSettings.get("strong_db_path")
        if storedStrong and os.path.exists(storedStrong):
            strongBiblePath = storedStrong
    hasStrongBible = bool(strongBiblePath)

    dictPath = resources["dict"]
    if not dictPath:
        storedDict = storedSettings.get("dict_db_path")
        if storedDict and os.path.exists(storedDict):
            dictPath = storedDict

    mode = args.mode
    if mode == "auto":
        stored = storedSettings.get("default_mode")
        if stored == "strong" and hasStrongBible:
            mode = "strong"
        elif stored == "restore" and hasDb:
            mode = "restore"
        elif hasDb:
            mode = "restore"
        elif hasStrongBible:
            mode = "strong"
        else:
            sys.stderr.write(
                "在目前目錄找不到可用的聖經資料庫。\n"
                "請確認同目錄下存在 bible.db（恢復本）或 .mybible 檔案（Strong 原文模組）。\n"
            )
            sys.exit(1)
    elif mode == "restore" and not hasDb:
        sys.stderr.write(f"找不到恢復本資料庫: {dbPath}\n")
        sys.exit(1)
    elif mode == "strong" and not hasStrongBible:
        sys.stderr.write("找不到 Strong 原文聖經模組 (.bbl.mybible)。\n")
        sys.exit(1)

    initialMode = "books" if mode == "restore" else "strong_books"
    runTui(
        dbPath if hasDb else None,
        strongBiblePath if hasStrongBible else None,
        dictPath,
        initialMode=initialMode,
    )


def main():
    setupConsole()
    parser = buildParser()
    args = parser.parse_args()

    resources = detectResources()

    if getattr(args, "cmd", None) is None:
        launchInteractive(args, resources)
        return

    if args.cmd in ("strong", "orig"):
        args.func(args, None)
        return

    if not os.path.exists(args.db):
        sys.stderr.write(f"找不到恢復本資料庫: {args.db}\n")
        if resources["strongBible"] or resources["dict"]:
            sys.stderr.write(
                "偵測到同目錄下有 Strong 相關模組，"
                "可改用 `python3 bible.py orig ...` 或 `python3 bible.py strong ...`。\n"
            )
        sys.exit(1)

    conn = connect(args.db)
    args.func(args, conn)


if __name__ == "__main__":
    main()
