#!/usr/bin/env python3

import argparse
import curses
import locale
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bible as B

locale.setlocale(locale.LC_ALL, "")

os.environ.setdefault("ESCDELAY", "25")

colorOutline = 1
colorFootnote = 2
colorSection = 3
colorSecondary = 4
colorHeader = 5
colorHelp = 6


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
    def __init__(self, stdscr, conn):
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
        curses.curs_set(0)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
            curses.mouseinterval(0)
        except curses.error:
            pass
        self.stdscr.keypad(True)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(colorOutline, curses.COLOR_YELLOW, -1)
        curses.init_pair(colorFootnote, curses.COLOR_RED, -1)
        curses.init_pair(colorSection, curses.COLOR_CYAN, -1)
        curses.init_pair(colorSecondary, curses.COLOR_WHITE, -1)
        curses.init_pair(colorHeader, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(colorHelp, curses.COLOR_BLACK, curses.COLOR_WHITE)

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
        text = self.status[: max(0, w - 1)]
        try:
            self.stdscr.addstr(h - 1, 0, text.ljust(w - 1), curses.color_pair(colorHelp))
        except curses.error:
            pass

    def _title(self, text, w):
        try:
            self.stdscr.addstr(0, 0, text[: w - 1].ljust(w - 1), curses.color_pair(colorHeader) | curses.A_BOLD)
        except curses.error:
            pass

    def drawBooks(self, h, w):
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
        name = B.bookDisplayName(self.conn, self.selectedBookIndex, "big5")
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
        bookIndex = self.selectedBookIndex
        chapter = self.selectedChapter
        langPrimary = "cuv_big5" if self.showCuv else "big5"
        cur = self.conn.cursor()
        rows = cur.execute(
            "SELECT section, content FROM content WHERE language=? AND book_index=? AND chapter=? ORDER BY section",
            (langPrimary, bookIndex, chapter),
        ).fetchall()
        outlines = B.getOutlines(self.conn, langPrimary, bookIndex, chapter) if self.showOutline else {}
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
            fn = B.getFootnotes(self.conn, langPrimary, bookIndex, chapter, section)
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
        name = B.bookDisplayName(self.conn, self.selectedBookIndex, "big5")
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
                bold = curses.A_BOLD if attr and (attr & curses.A_BOLD) else 0
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
        except curses.error:
            pass

    def drawSearchResults(self, h, w):
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
            except curses.error:
                pass

    def handleKey(self, ch):
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


def main(stdscr, dbPath):
    conn = B.connect(dbPath)
    app = App(stdscr, conn)
    app.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="恢復本聖經互動式 TUI")
    parser.add_argument("--db", default=B.dbDefault)
    args = parser.parse_args()
    if not os.path.exists(args.db):
        sys.stderr.write(f"找不到資料庫檔案: {args.db}\n")
        sys.exit(1)
    curses.wrapper(main, args.db)
