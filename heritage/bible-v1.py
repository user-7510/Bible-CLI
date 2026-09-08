#!/usr/bin/env python3
"""
bible.py — 恢復本聖經 CLI / TUI 合一版

用法：
    python3 bible.py                    # 不帶參數 -> 啟動互動式 TUI
    python3 bible.py --db X             # 僅指定資料庫路徑 -> 仍啟動 TUI（改用該資料庫）
    python3 bible.py list [舊約|新約]    # 帶子指令 -> 走 CLI
    python3 bible.py read <書卷> <章>[:節] [--en] [--cuv] [--no-outline] [--no-footnote] [--no-color]
    python3 bible.py search <關鍵字> [--lang big5|gb|eng]
    python3 bible.py intro <書卷>
    python3 bible.py note <書卷> <章>:<節> <編號>

本檔案同時相容 Linux / macOS / Windows：
    - Windows 未內建 curses，需先執行 `pip install windows-curses` 才能使用 TUI，
      若未安裝，程式會提示安裝方式並自動退回 CLI 說明，而不會直接崩潰。
    - 啟動時會嘗試開啟 Windows 主控台的 VT100 / UTF-8 支援，讓 ANSI 顏色與中文字元
      在 cmd.exe / PowerShell 下也能正常顯示。
"""

import argparse
import ctypes
import io
import locale
import os
import sqlite3
import sys
import unicodedata

isWindows = os.name == "nt"

dbDefault = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bible.db")

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
bold = "\033[1m"
dim = "\033[2m"
reset = "\033[0m"

# curses 色彩配對編號（僅在 TUI 模式下配合 curses.init_pair 使用，不需在模組層級匯入 curses）
colorOutline = 1
colorFootnote = 2
colorSection = 3
colorSecondary = 4
colorHeader = 5
colorHelp = 6


# ---------------------------------------------------------------------------
# Windows 相容性輔助函式
# ---------------------------------------------------------------------------

def setupConsole():
    """在程式啟動時呼叫一次：讓 Windows 主控台支援 UTF-8 輸出與 ANSI 顏色碼。
    在非 Windows 平台上此函式幾乎不做任何事。"""
    # 讓標準輸出/輸入/錯誤流以 UTF-8 處理，避免中文在 Windows 預設編碼（cp950/cp936）下亂碼
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if not isWindows:
        return

    # 切換主控台編碼頁為 UTF-8（65001），忽略失敗（例如非互動式主控台）
    try:
        os.system("chcp 65001 >NUL 2>&1")
    except Exception:
        pass

    # 開啟 Windows 10+ 主控台的 VT100（ANSI escape）支援，讓 \033[31m 這類顏色碼能正確顯示
    try:
        kernel32 = ctypes.windll.kernel32
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        for handleId in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handleId)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(
                    handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                )
    except Exception:
        pass


def supportsAnsiColor():
    """判斷目前輸出是否適合顯示 ANSI 顏色碼（一般終端機皆可；非 tty 時關閉顏色較保險）。"""
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 資料庫存取（CLI 與 TUI 共用）
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# CLI 子指令
# ---------------------------------------------------------------------------

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
    bookIndex = resolveBook(conn, args.book)
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
    bookIndex = resolveBook(conn, args.book)
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
    bookIndex = resolveBook(conn, args.book)
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
    # 不設 required=True：不帶子指令時交由 main() 啟動 TUI
    sub = p.add_subparsers(dest="cmd")

    pList = sub.add_parser("list", help="列出書卷")
    pList.add_argument("testament", nargs="?", choices=["舊約", "新約"], default=None)
    pList.set_defaults(func=cmdList)

    pRead = sub.add_parser("read", help="讀取經文")
    pRead.add_argument("book")
    pRead.add_argument("chapter", help="章數，或 章:節")
    pRead.add_argument("--en", action="store_true", help="附加英文對照(恢復本英文)")
    pRead.add_argument("--cuv", action="store_true", help="改用和合本正文")
    pRead.add_argument("--no-outline", dest="noOutline", action="store_true")
    pRead.add_argument("--no-footnote", dest="noFootnote", action="store_true")
    pRead.add_argument("--no-color", dest="noColor", action="store_true")
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

    return p


# ---------------------------------------------------------------------------
# TUI（互動式終端機介面）
# ---------------------------------------------------------------------------

def cwidth(ch):
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def wrapMarked(chars, width):
    lines = []
    cur = []
    curw = 0
    for ch, flag in chars:
        w = cwidth(ch)
        if ch == "\n" or curw + w > width:
            lines.append(cur)
            cur = []
            curw = 0
            if ch == "\n":
                continue
        cur.append((ch, flag))
        curw += w
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


class App:
    def __init__(self, curses_mod, stdscr, conn):
        self.curses = curses_mod
        self.stdscr = stdscr
        self.conn = conn
        self.mode = "books"
        self.modeStack = []

        self.books = self._loadBooks()
        self.bookIdx = 0
        self.bookScroll = 0

        self.selectedBookIndex = None
        self.chapterCount = 0
        self.chapterIdx = 0
        self.chapterScroll = 0

        self.selectedChapter = None
        self.showEn = False
        self.showCuv = False
        self.showOutline = True
        self.expanded = set()
        self.readLines = []
        self.readScroll = 0
        self.readVerseRow = {}
        self._readCacheKey = None
        self._readCacheW = None

        self.searchQuery = ""
        self.searchResults = []
        self.searchScroll = 0
        self.searchIdx = 0

        self.status = "按 ? 查看說明"

    def _loadBooks(self):
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT book_index, name FROM book_name WHERE language='big5' ORDER BY book_index"
        ).fetchall()
        return [(r["book_index"], r["name"]) for r in rows]

    def _maxChapter(self, bookIndex):
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT MAX(chapter) AS m FROM content WHERE language='big5' AND book_index=?",
            (bookIndex,),
        ).fetchone()
        return row["m"] or 1

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
        except curses.error:
            # 部分終端機（含某些 Windows 主控台）不支援自訂色彩，退回無色顯示
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
        if self.mode == "books":
            self.drawBooks(h, w)
        elif self.mode == "chapters":
            self.drawChapters(h, w)
        elif self.mode == "read":
            self.drawRead(h, w)
        elif self.mode == "search_input":
            self.drawSearchInput(h, w)
        elif self.mode == "search_results":
            self.drawSearchResults(h, w)
        elif self.mode == "help":
            self.drawHelp(h, w)
        self.drawStatus(h, w)
        self.stdscr.refresh()

    def drawStatus(self, h, w):
        curses = self.curses
        text = self.status[: max(0, w - 1)]
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

    def drawBooks(self, h, w):
        curses = self.curses
        self._title(" 書卷清單", w)
        visible = h - 2
        if self.bookIdx < self.bookScroll:
            self.bookScroll = self.bookIdx
        if self.bookIdx >= self.bookScroll + visible:
            self.bookScroll = self.bookIdx - visible + 1

        self.clickMap = {}
        for rowI, (idx, name) in enumerate(self.books[self.bookScroll:self.bookScroll + visible]):
            y = rowI + 1
            testament = "舊約" if idx <= 39 else "新約"
            label = f"{idx:>3}  {name}  ({testament})"
            attr = curses.A_REVERSE if self.bookScroll + rowI == self.bookIdx else 0
            try:
                self.stdscr.addstr(y, 0, label[: w - 1].ljust(w - 1), attr)
            except curses.error:
                pass
            self.clickMap[y] = ("book", self.bookScroll + rowI)

    def drawChapters(self, h, w):
        curses = self.curses
        name = bookDisplayName(self.conn, self.selectedBookIndex, "big5")
        self._title(f" {name}", w)
        visible = h - 2
        cols = max(1, (w - 1) // 8)
        self.clickMap = {}
        for i in range(self.chapterCount):
            row = i // cols
            col = i % cols
            y = row + 1 - self.chapterScroll
            if y < 1 or y > h - 2:
                continue
            x = col * 8
            label = f"第{i+1:>3}章"
            attr = curses.A_REVERSE if i == self.chapterIdx else 0
            try:
                self.stdscr.addstr(y, x, label, attr)
            except curses.error:
                pass
            self.clickMap[(y, col)] = ("chapter", i)

    def _buildReadLines(self, w):
        curses = self.curses
        bookIndex = self.selectedBookIndex
        chapter = self.selectedChapter
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

        lines = []
        verseRow = {}
        indentUnit = "  "
        for r in rows:
            section = r["section"]
            for o in outlines.get(section, []):
                indent = indentUnit * (o["level"] - 1)
                for wl in plainWrap(indent + o["outline"], w - 1):
                    lines.append(Line([("".join(c for c, _ in wl), colorOutline | curses.A_BOLD)]))
            fn = getFootnotes(self.conn, langPrimary, bookIndex, chapter, section)
            fnPairs = [(f["location"], f["seq"]) for f in fn]
            chars = []
            content = r["content"]
            marks = {loc - 1: seq for loc, seq in fnPairs}
            for i, c in enumerate(content):
                if i in marks:
                    for mc in str(marks[i]):
                        chars.append((mc, colorFootnote))
                chars.append((c, 0))
            prefix = f"{section:>3}  "
            wrapped = wrapMarked([(c, 0) for c in prefix] + chars, w - 1)
            verseRow[section] = len(lines)
            for wi, wl in enumerate(wrapped):
                segs = []
                curAttr = None
                buf = ""
                for c, flag in wl:
                    a = flag
                    if a != curAttr:
                        if buf:
                            segs.append((buf, curAttr))
                        buf = c
                        curAttr = a
                    else:
                        buf += c
                if buf:
                    segs.append((buf, curAttr))
                lines.append(Line(segs, section=section, clickable=True))

            if self.showEn and section in secondaryMap:
                for wl in plainWrap("     " + secondaryMap[section], w - 1):
                    lines.append(Line([("".join(c for c, _ in wl), colorSecondary)], section=section))

            if section in self.expanded:
                for f in fn:
                    label = f"      [{f['seq']}] "
                    for wl in plainWrap(label + (f["note"] or ""), w - 1):
                        lines.append(Line([("".join(c for c, _ in wl), colorSecondary)]))
            lines.append(Line([("", 0)]))
        return lines, verseRow

    def drawRead(self, h, w):
        curses = self.curses
        name = bookDisplayName(self.conn, self.selectedBookIndex, "big5")
        flags = []
        if self.showEn:
            flags.append("英文")
        if self.showCuv:
            flags.append("和合本")
        flagS = ("　[" + "／".join(flags) + "]") if flags else ""
        self._title(f" {name} 第{self.selectedChapter}章{flagS}", w)

        cacheKey = (
            self.selectedBookIndex,
            self.selectedChapter,
            self.showEn,
            self.showCuv,
            self.showOutline,
            frozenset(self.expanded),
        )
        if cacheKey != self._readCacheKey or w != self._readCacheW:
            self.readLines, self.readVerseRow = self._buildReadLines(w)
            self._readCacheKey = cacheKey
            self._readCacheW = w
        visible = h - 2
        maxScroll = max(0, len(self.readLines) - visible)
        self.readScroll = max(0, min(self.readScroll, maxScroll))

        self.clickMapRead = {}
        for rowI, line in enumerate(self.readLines[self.readScroll:self.readScroll + visible]):
            y = rowI + 1
            x = 0
            for text, attr in line.segments:
                color = curses.color_pair(attr & 0xF) if attr else 0
                try:
                    self.stdscr.addstr(y, x, text, color | (curses.A_BOLD if attr == (colorOutline | curses.A_BOLD) else 0))
                except curses.error:
                    pass
                x += sum(cwidth(c) for c in text)
            if line.clickable:
                self.clickMapRead[y] = line.section

    def drawSearchInput(self, h, w):
        self._title(" 搜尋經文", w)
        try:
            self.stdscr.addstr(2, 0, "關鍵字：" + self.searchQuery)
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

    def drawHelp(self, h, w):
        self._title(" 說明  (按任意鍵返回)", w)
        lines = [
            "書卷清單／章節清單／搜尋結果：",
            "  ↑↓ 或 j k 移動，Enter 或滑鼠左鍵點擊 選取",
            "",
            "讀經畫面：",
            "  ↑↓ 或 j k 捲動內文，←→ 切換上下章",
            "  e   切換是否顯示英文對照",
            "  c   切換恢復本／和合本正文",
            "  n   切換是否顯示大綱",
            "  滑鼠點擊某節經文 / Enter 對準該節  可展開或收合該節註解",
            "",
            "共通：",
            "  /   搜尋全經文",
            "  q 或 Backspace   返回上一層 / 離開",
        ]
        for i, l in enumerate(lines):
            try:
                self.stdscr.addstr(i + 2, 2, l)
            except self.curses.error:
                pass

    def handleKey(self, ch):
        curses = self.curses
        if isinstance(ch, str):
            ch = ord(ch)

        if ch == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                return True
            self._handleMouse(my, mx, bstate)
            return True

        if ch in (ord("?"),) and self.mode != "help":
            self.modeStack.append(self.mode)
            self.mode = "help"
            return True
        if self.mode == "help":
            self.mode = self.modeStack.pop() if self.modeStack else "books"
            return True

        if self.mode == "books":
            return self._keyBooks(ch)
        elif self.mode == "chapters":
            return self._keyChapters(ch)
        elif self.mode == "read":
            return self._keyRead(ch)
        elif self.mode == "search_input":
            return self._keySearchInput(ch)
        elif self.mode == "search_results":
            return self._keySearchResults(ch)
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
            if item and item[0] == "book":
                self.bookIdx = item[1]
                self._enterBook()
        elif self.mode == "chapters":
            for key, item in self.clickMap.items():
                if isinstance(key, tuple) and key[0] == y:
                    self.chapterIdx = item[1]
                    self._enterChapter()
                    break
        elif self.mode == "read":
            section = self.clickMapRead.get(y)
            if section is not None:
                if section in self.expanded:
                    self.expanded.discard(section)
                else:
                    self.expanded.add(section)
        elif self.mode == "search_results":
            item = self.clickMap.get(y)
            if item and item[0] == "search_result":
                self.searchIdx = item[1]
                self._gotoSearchResult()

    def _scrollCurrent(self, delta):
        if self.mode == "books":
            self.bookIdx = max(0, min(len(self.books) - 1, self.bookIdx + delta))
        elif self.mode == "chapters":
            self.chapterScroll = max(0, self.chapterScroll + delta)
        elif self.mode == "read":
            self.readScroll = max(0, self.readScroll + delta)
        elif self.mode == "search_results":
            self.searchIdx = max(0, min(len(self.searchResults) - 1, self.searchIdx + delta))

    def _keyBooks(self, ch):
        curses = self.curses
        if ch in (curses.KEY_UP, ord("k")):
            self.bookIdx = max(0, self.bookIdx - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.bookIdx = min(len(self.books) - 1, self.bookIdx + 1)
        elif ch in (10, 13, curses.KEY_ENTER):
            self._enterBook()
        elif ch == ord("/"):
            self.modeStack.append(self.mode)
            self.searchQuery = ""
            self.mode = "search_input"
        elif ch in (ord("q"), 27):
            return False
        return True

    def _enterBook(self):
        self.selectedBookIndex = self.books[self.bookIdx][0]
        self.chapterCount = self._maxChapter(self.selectedBookIndex)
        self.chapterIdx = 0
        self.chapterScroll = 0
        self.mode = "chapters"

    def _keyChapters(self, ch):
        curses = self.curses
        cols = max(1, (curses.COLS - 1) // 8) if hasattr(curses, "COLS") else 8
        if ch in (curses.KEY_UP, ord("k")):
            self.chapterIdx = max(0, self.chapterIdx - cols)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.chapterIdx = min(self.chapterCount - 1, self.chapterIdx + cols)
        elif ch in (curses.KEY_LEFT, ord("h")):
            self.chapterIdx = max(0, self.chapterIdx - 1)
        elif ch in (curses.KEY_RIGHT, ord("l")):
            self.chapterIdx = min(self.chapterCount - 1, self.chapterIdx + 1)
        elif ch in (10, 13, curses.KEY_ENTER):
            self._enterChapter()
        elif ch in (ord("q"), 27, curses.KEY_BACKSPACE, 127, 8):
            self.mode = "books"
        return True

    def _enterChapter(self):
        self.selectedChapter = self.chapterIdx + 1
        self.readScroll = 0
        self.expanded = set()
        self.mode = "read"

    def _keyRead(self, ch):
        curses = self.curses
        if ch in (curses.KEY_UP, ord("k")):
            self.readScroll = max(0, self.readScroll - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.readScroll += 1
        elif ch == curses.KEY_NPAGE:
            self.readScroll += 10
        elif ch == curses.KEY_PPAGE:
            self.readScroll = max(0, self.readScroll - 10)
        elif ch in (curses.KEY_LEFT, ord("h")):
            if self.selectedChapter > 1:
                self.selectedChapter -= 1
                self.readScroll = 0
                self.expanded = set()
        elif ch in (curses.KEY_RIGHT, ord("l")):
            if self.selectedChapter < self.chapterCount:
                self.selectedChapter += 1
                self.readScroll = 0
                self.expanded = set()
        elif ch == ord("e"):
            self.showEn = not self.showEn
        elif ch == ord("c"):
            self.showCuv = not self.showCuv
        elif ch == ord("n"):
            self.showOutline = not self.showOutline
        elif ch == ord("/"):
            self.modeStack.append(self.mode)
            self.searchQuery = ""
            self.mode = "search_input"
        elif ch in (ord("q"), 27, curses.KEY_BACKSPACE, 127, 8):
            self.mode = "chapters"
        return True

    def _keySearchInput(self, ch):
        curses = self.curses
        if ch in (10, 13, curses.KEY_ENTER):
            self._runSearch()
            self.mode = "search_results"
        elif ch == 27:
            self.mode = self.modeStack.pop() if self.modeStack else "books"
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            self.searchQuery = self.searchQuery[:-1]
        elif 32 <= ch < 0x110000:
            try:
                self.searchQuery += chr(ch)
            except ValueError:
                pass
        return True

    def _runSearch(self):
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT book_index, chapter, section, content FROM content "
            "WHERE language='big5' AND content LIKE ? ORDER BY book_index, chapter, section LIMIT 500",
            (f"%{self.searchQuery}%",),
        ).fetchall()
        results = []
        for r in rows:
            acrRow = cur.execute(
                "SELECT acronym_name FROM book_name WHERE book_index=? AND language='big5'",
                (r["book_index"],),
            ).fetchone()
            results.append(
                {
                    "book_index": r["book_index"],
                    "acr": acrRow["acronym_name"] if acrRow else str(r["book_index"]),
                    "chapter": r["chapter"],
                    "section": r["section"],
                    "content": r["content"],
                }
            )
        self.searchResults = results
        self.searchIdx = 0
        self.searchScroll = 0

    def _keySearchResults(self, ch):
        curses = self.curses
        if ch in (curses.KEY_UP, ord("k")):
            self.searchIdx = max(0, self.searchIdx - 1)
        elif ch in (curses.KEY_DOWN, ord("j")):
            self.searchIdx = min(len(self.searchResults) - 1, self.searchIdx + 1)
        elif ch in (10, 13, curses.KEY_ENTER):
            self._gotoSearchResult()
        elif ch in (ord("q"), 27, curses.KEY_BACKSPACE, 127, 8):
            self.mode = self.modeStack.pop() if self.modeStack else "books"
        return True

    def _gotoSearchResult(self):
        if not self.searchResults:
            return
        r = self.searchResults[self.searchIdx]
        self.selectedBookIndex = r["book_index"]
        self.chapterCount = self._maxChapter(self.selectedBookIndex)
        self.selectedChapter = r["chapter"]
        self.readScroll = 0
        self.expanded = {r["section"]}
        self.mode = "read"


def _tuiMain(stdscr, curses_mod, dbPath):
    conn = connect(dbPath)
    app = App(curses_mod, stdscr, conn)
    app.run()


def runTui(dbPath):
    """啟動互動式 TUI。若目前平台缺少 curses（常見於未安裝 windows-curses 的 Windows），
    會印出友善的安裝提示並改為顯示 CLI 用法，而不是直接丟出例外。"""
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
        sys.exit(1)

    if not os.path.exists(dbPath):
        sys.stderr.write(f"找不到資料庫檔案: {dbPath}\n")
        sys.exit(1)

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    os.environ.setdefault("ESCDELAY", "25")

    curses.wrapper(_tuiMain, curses, dbPath)


# ---------------------------------------------------------------------------
# 進入點：無子指令 -> TUI；有子指令 -> CLI
# ---------------------------------------------------------------------------

def main():
    setupConsole()
    parser = buildParser()
    args = parser.parse_args()

    if getattr(args, "cmd", None) is None:
        # 不帶子指令（可能只帶了 --db）-> 啟動 TUI
        runTui(args.db)
        return

    conn = connect(args.db)
    args.func(args, conn)


if __name__ == "__main__":
    main()
