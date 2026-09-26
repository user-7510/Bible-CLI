import argparse
import ctypes
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

def sniffMybibleKind(path):
    try:
        c = sqlite3.connect(path)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        c.close()
    except sqlite3.Error:
        return None
    if "dictionary" in tables: return "dict"
    if "Bible" in tables: return "bible"
    return None

def detectResources(baseDir=None):
    baseDir = baseDir or scriptDir
    resources = {"db": None, "dict": None, "strongBible": None}
    dbPath = os.path.join(baseDir, "bible.db")
    if os.path.isfile(dbPath): resources["db"] = dbPath
    try: entries = sorted(os.listdir(baseDir))
    except OSError: entries = []
    for fname in entries:
        full = os.path.join(baseDir, fname)
        if not os.path.isfile(full): continue
        lower = fname.lower()
        if lower.endswith(".dct.mybible"): resources["dict"] = resources["dict"] or full
        elif lower.endswith(".bbl.mybible"): resources["strongBible"] = resources["strongBible"] or full
        elif lower.endswith(".mybible"):
            kind = sniffMybibleKind(full)
            if kind == "dict": resources["dict"] = resources["dict"] or full
            elif kind == "bible": resources["strongBible"] = resources["strongBible"] or full
    return resources

detectedResources = detectResources()
dbDefault = detectedResources["db"] or os.path.join(scriptDir, "bible.db")
zhLangs = ("big5", "gb", "cuv_big5", "cuv_gb")
enLangs = ("eng", "darby_eng", "kjv_eng")
introTypeLabel = {1: "著者", 2: "著時", 3: "著地", 4: "受者", 5: "主旨", 6: "涵蓋時段"}

red = "\033[31m"
cyan = "\033[36m"
bold = "\033[1m"
dim = "\033[2m"
reset = "\033[0m"

dictDefault = os.environ.get("BIBLE_STRONG_DICT") or detectedResources["dict"]
strongBibleDefault = os.environ.get("BIBLE_STRONG_BIBLE") or detectedResources["strongBible"]

zhBookNames = [
    "創世記", "出埃及記", "利未記", "民數記", "申命記", "約書亞記", "士師記", "路得記", "撒母耳記上", "撒母耳記下",
    "列王紀上", "列王紀下", "歷代志上", "歷代志下", "以斯拉記", "尼希米記", "以斯帖記", "約伯記", "詩篇", "箴言",
    "傳道書", "雅歌", "以賽亞書", "耶利米書", "耶利米哀歌", "以西結書", "但以理書", "何西阿書", "約珥書", "阿摩司書",
    "俄巴底亞書", "約拿書", "彌迦書", "那鴻書", "哈巴谷書", "西番雅書", "哈該書", "撒迦利亞書", "瑪拉基書",
    "馬太福音", "馬可福音", "路加福音", "約翰福音", "使徒行傳", "羅馬書", "哥林多前書", "哥林多後書", "加拉太書", "以弗所書",
    "腓立比書", "歌羅西書", "帖撒羅尼迦前書", "帖撒羅尼迦後書", "提摩太前書", "提摩太後書", "提多書", "腓利門書", "希伯來書",
    "雅各書", "彼得前書", "彼得後書", "約翰一書", "約翰二書", "約翰三書", "猶大書", "啟示錄",
]

colorOutline = 1
colorFootnote = 2
colorSection = 3
colorSecondary = 4
colorHeader = 5
colorHelp = 6

def setupConsole():
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            if hasattr(stream, "reconfigure"): stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception: pass
    if not isWindows: return
    try: os.system("chcp 65001 >NUL 2>&1")
    except Exception: pass
    try:
        kernel32 = ctypes.windll.kernel32
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        for handleId in (-11, -12):
            handle = kernel32.GetStdHandle(handleId)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception: pass

def supportsAnsiColor():
    try: return sys.stdout.isatty()
    except Exception: return False

def copyToClipboardText(text):
    if not text: return False
    if isWindows: candidates = [["clip"]]
    elif sys.platform == "darwin": candidates = [["pbcopy"]]
    else: candidates = [["termux-clipboard-set"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    payload = text.encode("utf-8", errors="replace")
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, input=payload, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            if proc.returncode == 0: return True
        except (FileNotFoundError, OSError, subprocess.SubprocessError): continue
    try:
        with open(os.path.expanduser("~/.bible-clipboard.txt"), "a", encoding="utf-8") as f:
            f.write(text + "\n")
        return True
    except Exception: return False

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
    row = cur.execute("SELECT book_index FROM book_name WHERE name = ? OR acronym_name = ? LIMIT 1", (name, name)).fetchone()
    if row: return row["book_index"]
    row = cur.execute("SELECT book_index FROM book_name WHERE lower(name) = lower(?) OR lower(acronym_name) = lower(?) LIMIT 1", (name, name)).fetchone()
    if row: return row["book_index"]
    row = cur.execute("SELECT book_index FROM book_name WHERE name LIKE ? OR acronym_name LIKE ? LIMIT 1", (f"%{name}%", f"%{name}%")).fetchone()
    if row: return row["book_index"]
    return None

def bookDisplayName(conn, bookIndex, lang="big5"):
    cur = conn.cursor()
    row = cur.execute("SELECT name FROM book_name WHERE book_index=? AND language=?", (bookIndex, lang)).fetchone()
    return row["name"] if row else f"[book {bookIndex}]"

def insertFootnoteMarkers(content, footnotes, color=True):
    if not footnotes: return content
    result = content
    for loc, seq in sorted(footnotes, key=lambda x: -x[0]):
        idx = loc - 1
        if idx < 0 or idx > len(result): continue
        marker = f"{seq}"
        if color: marker = f"{red}{marker}{reset}"
        result = result[:idx] + marker + result[idx:]
    return result

def getOutlines(conn, lang, bookIndex, chapter):
    cur = conn.cursor()
    rows = cur.execute("SELECT section, flag, level, outline FROM outline WHERE language=? AND book_index=? AND chapter=? ORDER BY section ASC, flag ASC, level ASC", (lang, bookIndex, chapter)).fetchall()
    bySection = {}
    for r in rows: bySection.setdefault(r["section"], []).append(r)
    return bySection

def getFootnotes(conn, lang, bookIndex, chapter, section):
    cur = conn.cursor()
    return cur.execute("SELECT location, seq, note FROM footnote WHERE language=? AND book_index=? AND chapter=? AND section=? ORDER BY seq ASC", (lang, bookIndex, chapter, section)).fetchall()

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
    return connectSqliteOrExit(dictPath, "尚未指定 Strong 字典路徑。")

def connectStrongBible(biblePath):
    return connectSqliteOrExit(biblePath, "尚未指定含 Strong 編號的聖經模組路徑。")

def normalizeStrongCode(code):
    code = code.strip().upper()
    if not code or code[0] not in ("G", "H"): return None
    return code

class DictHtmlRenderer(HTMLParser):
    def __init__(self, color=True):
        super().__init__(convert_charrefs=True)
        self.color = color
        self.lines = [""]
        self.olStack = []

    def _write(self, text): self.lines[-1] += text
    def _newline(self):
        if self.lines[-1] != "": self.lines.append("")

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br"): self._newline()
        elif tag == "ol": self.olStack.append(0)
        elif tag == "li":
            self._newline()
            depth = len(self.olStack)
            num = self.olStack[-1] = self.olStack[-1] + 1 if self.olStack else 1
            indent = "  " * max(0, depth - 1)
            marker = f"{num}." if depth <= 1 else f"{chr(96 + num)})"
            self._write(f"{indent}{marker} ")
        elif tag in ("strong", "b") and self.color: self._write(bold)
        elif tag in ("i", "em") and self.color: self._write(dim)
        elif tag == "a" and self.color: self._write(cyan)

    def handle_endtag(self, tag):
        if tag == "ol":
            if self.olStack: self.olStack.pop()
            self._newline()
        elif tag in ("li", "p"): self._newline()
        elif tag in ("strong", "b", "i", "em", "a") and self.color: self._write(reset)

    def handle_data(self, data): self._write(data)
    def getText(self):
        text = "\n".join(self.lines)
        return re.sub(r"\n{3,}", "\n\n", text).strip("\n")

def renderDictHtml(htmlText, color=True):
    parser = DictHtmlRenderer(color=color)
    parser.feed(htmlText)
    return parser.getText()

def cmdStrong(args, _conn):
    code = normalizeStrongCode(args.code)
    if not code:
        sys.stderr.write("請在編號前加上 G（希臘文）或 H（希伯來文）\n")
        sys.exit(1)
    cur = connectDict(args.dict).cursor()
    row = cur.execute("SELECT word, data FROM dictionary WHERE word = ?", (code,)).fetchone()
    if not row:
        sys.stderr.write(f"查無 Strong 編號: {code}\n")
        sys.exit(1)
    color = (not args.noColor) and supportsAnsiColor()
    header = f"Strong {row['word']}"
    print(f"{bold}{header}{reset}\n" if color else f"{header}\n")
    print(renderDictHtml(row["data"], color=color))

def printStrongDefinition(dictPath, code, color):
    if code in ("G0", "H0"):
        print(f"{dim}[{code} 為佔位符，無對應字典資料]{reset}" if color else f"[{code} 為佔位符，無對應字典資料]")
        return
    cur = connectDict(dictPath).cursor()
    row = cur.execute("SELECT word, data FROM dictionary WHERE word = ?", (code,)).fetchone()
    if not row:
        sys.stderr.write(f"查無 Strong 編號: {code}\n")
        return
    header = f"Strong {row['word']}"
    print(f"\n{bold}{header}{reset}\n" if color else f"\n{header}\n")
    print(renderDictHtml(row["data"], color=color))

strongTagPattern = re.compile(r"<W([GH]\d+)>")

def splitStrongVerse(scripture):
    parts = re.split(r"(<W[GH]\d+>)", scripture)
    segments, curText, curCodes, first = [], "", [], True
    for part in parts:
        m = strongTagPattern.fullmatch(part)
        if m: curCodes.append(m.group(1))
        elif part == "": continue
        else:
            if not first: segments.append((curText, curCodes))
            curText, curCodes, first = part, [], False
    segments.append((curText, curCodes))
    return segments

def resolveZhBookIndex(name):
    name = name.strip()
    if name.isdigit():
        idx = int(name)
        return idx if 1 <= idx <= 66 else None
    for i, n in enumerate(zhBookNames, start=1):
        if n == name: return i
    matches = [i for i, n in enumerate(zhBookNames, start=1) if name in n]
    if len(matches) == 1: return matches[0]
    return None

def renderStrongVerse(segments, color):
    displayParts, legend, idx = [], {}, 0
    for text, codes in segments:
        if codes:
            idx += 1
            legend[idx] = codes
            marker = f"[{idx}]"
            displayParts.append(f"{text}{dim}{marker}{reset}" if color else f"{text}{marker}")
        else: displayParts.append(text)
    return "".join(displayParts), legend

def cmdOrig(args, _conn):
    bookIndex = resolveZhBookIndex(args.book)
    if bookIndex is None:
        sys.stderr.write(f"找不到書卷: {args.book}\n")
        sys.exit(1)
    chapterArg = str(args.chapter)
    verseFilter = None
    if ":" in chapterArg:
        chapterS, verseS = chapterArg.split(":")
        chapter, verseFilter = int(chapterS), int(verseS)
    else: chapter = int(chapterArg)
    if args.word is not None and verseFilter is None:
        sys.stderr.write("使用 --word 時請指定確切的節\n")
        sys.exit(1)
    cur = connectStrongBible(args.strongbible).cursor()
    rows = cur.execute("SELECT Verse, Scripture FROM Bible WHERE Book=? AND Chapter=? ORDER BY Verse", (bookIndex, chapter)).fetchall()
    if not rows:
        sys.stderr.write("查無此章節\n")
        sys.exit(1)
    color = (not args.noColor) and supportsAnsiColor()
    header = f"{zhBookNames[bookIndex - 1]} 第{chapter}章"
    print(f"{bold}{header}{reset}\n" if color else f"{header}\n")
    targetLegend = None
    for r in rows:
        verse = r["Verse"]
        if verseFilter and verse != verseFilter: continue
        lineText, legend = renderStrongVerse(splitStrongVerse(r["Scripture"]), color)
        verseLabel = f"{dim}{verse:>3}{reset}" if color else f"{verse:>3}"
        print(f"{verseLabel}  {lineText}")
        if verseFilter and verse == verseFilter: targetLegend = legend
    if verseFilter and targetLegend is not None and args.word is None:
        print()
        print("  ".join([f"[{n}] {'/'.join(c)}" for n, c in sorted(targetLegend.items())]))
    if args.word is not None:
        if targetLegend is None or args.word not in targetLegend:
            sys.stderr.write(f"無第 {args.word} 個字\n")
            sys.exit(1)
        for code in targetLegend[args.word]: printStrongDefinition(args.dict, code, color)

def cmdList(args, conn):
    cur = conn.cursor()
    rows = cur.execute("SELECT book_index, name FROM book_name WHERE language='big5' ORDER BY book_index").fetchall()
    start, end = (1, 39) if args.testament == "舊約" else (40, 66) if args.testament == "新約" else (1, 66)
    for r in rows:
        if start <= r["book_index"] <= end: print(f"{r['book_index']:>3}  {r['name']}")

def cmdIntro(args, conn):
    bookIndex = resolveBook(conn, args.book)
    if bookIndex is None:
        sys.stderr.write(f"找不到書卷: {args.book}\n")
        sys.exit(1)
    name = bookDisplayName(conn, bookIndex, "big5")
    cur = conn.cursor()
    rows = cur.execute("SELECT type, intro FROM book_intro WHERE language='big5' AND book_index=? ORDER BY type", (bookIndex,)).fetchall()
    print(f"{bold}{name} 書卷簡介{reset}\n")
    for r in rows:
        print(f"{dim}{introTypeLabel.get(r['type'], f'type{r['type']}')}{reset}  {r['intro']}\n")

def cmdNote(args, conn):
    bookIndex = resolveBook(conn, args.book)
    if bookIndex is None:
        sys.stderr.write(f"找不到書卷: {args.book}\n")
        sys.exit(1)
    try:
        chapter, section = map(int, args.ref.split(":"))
    except ValueError:
        sys.stderr.write("格式需為 章:節\n")
        sys.exit(1)
    row = conn.cursor().execute("SELECT note FROM footnote WHERE language='big5' AND book_index=? AND chapter=? AND section=? AND seq=?", (bookIndex, chapter, section, args.seq)).fetchone()
    if not row:
        sys.stderr.write("查無此註解\n")
        sys.exit(1)
    print(f"{bold}{bookDisplayName(conn, bookIndex, 'big5')} {chapter}:{section} 註{args.seq}{reset}\n\n{row['note']}")

def cmdSearch(args, conn):
    cur = conn.cursor()
    rows = cur.execute("SELECT book_index, chapter, section, content FROM content WHERE language=? AND content LIKE ? ORDER BY book_index, chapter, section", (args.lang, f"%{args.query}%")).fetchall()
    if not rows:
        print("沒有找到符合的經文")
        return
    for r in rows:
        acrRow = cur.execute("SELECT acronym_name FROM book_name WHERE book_index=? AND language=?", (r["book_index"], args.lang if args.lang in zhLangs else "big5")).fetchone()
        acr = acrRow["acronym_name"] if acrRow else str(r["book_index"])
        print(f"{dim}{acr} {r['chapter']}:{r['section']}{reset}  {r['content'].replace(args.query, f'{red}{args.query}{reset}')}")

def renderChapter(conn, bookIndex, chapter, sectionFilter, langPrimary, langSecondary, showOutline, showFootnote, color):
    cur = conn.cursor()
    rows = cur.execute("SELECT section, content FROM content WHERE language=? AND book_index=? AND chapter=? ORDER BY section", (langPrimary, bookIndex, chapter)).fetchall()
    if not rows:
        sys.stderr.write("查無此章節\n")
        sys.exit(1)
    outlines = getOutlines(conn, langPrimary, bookIndex, chapter) if showOutline else {}
    secondaryMap = {}
    if langSecondary:
        srows = cur.execute("SELECT section, content FROM content WHERE language=? AND book_index=? AND chapter=? ORDER BY section", (langSecondary, bookIndex, chapter)).fetchall()
        secondaryMap = {r["section"]: r["content"] for r in srows}
    for r in rows:
        section = r["section"]
        if sectionFilter and section != sectionFilter: continue
        for o in outlines.get(section, []):
            text = "  " * (o["level"] - 1) + o["outline"]
            print(f"{bold}{text}{reset}" if color else text)
        content = r["content"]
        if showFootnote:
            content = insertFootnoteMarkers(content, [(f["location"], f["seq"]) for f in getFootnotes(conn, langPrimary, bookIndex, chapter, section)], color=color)
        secLabel = f"{dim}{section:>3}{reset}" if color else f"{section:>3}"
        print(f"{secLabel}  {content}")
        if langSecondary and section in secondaryMap:
            secText = secondaryMap[section]
            print(f"     {dim}{secText}{reset}" if color else f"     {secText}")
        print()

def cmdRead(args, conn):
    bookIndex = resolveBook(conn, args.book)
    if bookIndex is None:
        sys.stderr.write(f"找不到書卷: {args.book}\n")
        sys.exit(1)
    chapter, sectionFilter = map(int, str(args.chapter).split(":")) if ":" in str(args.chapter) else (int(args.chapter), None)
    color = (not args.noColor) and supportsAnsiColor()
    header = f"{bookDisplayName(conn, bookIndex, 'big5')} 第{chapter}章"
    print(f"{bold}{header}{reset}\n" if color else f"{header}\n")
    renderChapter(conn, bookIndex, chapter, sectionFilter, "cuv_big5" if args.cuv else "big5", "eng" if args.en else None, not args.noOutline, not args.noFootnote, color)

def buildParser():
    p = argparse.ArgumentParser(description="恢復本聖經 CLI / TUI")
    p.add_argument("--db", default=dbDefault)
    p.add_argument("--mode", choices=["auto", "restore", "strong"], default="auto")
    sub = p.add_subparsers(dest="cmd")
    pList = sub.add_parser("list")
    pList.add_argument("testament", nargs="?", choices=["舊約", "新約"], default=None)
    pList.set_defaults(func=cmdList)
    pRead = sub.add_parser("read")
    pRead.add_argument("book")
    pRead.add_argument("chapter")
    pRead.add_argument("--en", action="store_true")
    pRead.add_argument("--cuv", action="store_true")
    pRead.add_argument("--no-outline", dest="noOutline", action="store_true")
    pRead.add_argument("--no-footnote", dest="noFootnote", action="store_true")
    pRead.add_argument("--no-color", dest="noColor", action="store_true")
    pRead.set_defaults(func=cmdRead)
    pSearch = sub.add_parser("search")
    pSearch.add_argument("query")
    pSearch.add_argument("--lang", default="big5", choices=zhLangs + enLangs)
    pSearch.set_defaults(func=cmdSearch)
    pIntro = sub.add_parser("intro")
    pIntro.add_argument("book")
    pIntro.set_defaults(func=cmdIntro)
    pNote = sub.add_parser("note")
    pNote.add_argument("book")
    pNote.add_argument("ref")
    pNote.add_argument("seq", type=int)
    pNote.set_defaults(func=cmdNote)
    pStrong = sub.add_parser("strong")
    pStrong.add_argument("code")
    pStrong.add_argument("--dict", default=dictDefault)
    pStrong.add_argument("--no-color", dest="noColor", action="store_true")
    pStrong.set_defaults(func=cmdStrong)
    pOrig = sub.add_parser("orig")
    pOrig.add_argument("book")
    pOrig.add_argument("chapter")
    pOrig.add_argument("--strongbible", default=strongBibleDefault)
    pOrig.add_argument("--dict", default=dictDefault)
    pOrig.add_argument("--word", type=int)
    pOrig.add_argument("--no-color", dest="noColor", action="store_true")
    pOrig.set_defaults(func=cmdOrig)
    return p

def cWidth(ch): return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1

def isWordChar(ch): return ch.isascii() and (ch.isalnum() or ch in ("'", "-"))

def wrapMarked(chars, width):
    lines, cur, curw, pending, pendw = [], [], 0, [], 0
    def flushPending():
        nonlocal cur, curw, pending, pendw
        if not pending: return
        if curw + pendw <= width:
            cur.extend(pending)
            curw += pendw
        elif pendw <= width:
            lines.append(cur)
            cur, curw = list(pending), pendw
        else:
            for pc, pflag in pending:
                pw = cWidth(pc)
                if curw + pw > width:
                    lines.append(cur)
                    cur, curw = [], 0
                cur.append((pc, pflag))
                curw += pw
        pending, pendw = [], 0
    for ch, flag in chars:
        if ch == "\n":
            flushPending()
            lines.append(cur)
            cur, curw = [], 0
            continue
        if isWordChar(ch):
            pending.append((ch, flag))
            pendw += cWidth(ch)
            continue
        flushPending()
        w = cWidth(ch)
        if curw + w > width:
            lines.append(cur)
            cur, curw = [], 0
        cur.append((ch, flag))
        curw += w
    flushPending()
    lines.append(cur)
    return lines

def plainWrap(text, width): return wrapMarked([(c, 0) for c in text], width)

class Line:
    __slots__ = ("segments", "section", "clickable")
    def __init__(self, segments, section=None, clickable=False):
        self.segments = segments
        self.section = section
        self.clickable = clickable

class SegLine:
    __slots__ = ("segments",)
    def __init__(self, segments): self.segments = segments

class App:
    def __init__(self, curses_mod, stdscr, conn, strongBiblePath=None, dictPath=None, initialMode="books"):
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
        self.quitPromptFrom = None
        
        self.cmdMode = False
        self.cmdBuffer = ""
        self.storageEnabled = False
        self.storagePath = ".bible-cli.db"
        self.userDb = None

        self.books = self.loadBooks() if self.hasDb else []
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
        self.readCacheKey = None
        self.readCacheW = None
        self.searchQuery = ""
        self.searchResults = []
        self.searchScroll = 0
        self.searchIdx = 0

        self.strongBooks = list(enumerate(zhBookNames, start=1)) if self.hasStrongBible else []
        self.strongBookIdx = 0
        self.strongBookScroll = 0
        self.strongSelectedBookIndex = None
        self.strongChapterCount = 0
        self.strongChapterIdx = 0
        self.strongChapterScroll = 0
        self.strongSelectedChapter = None
        self.expandedStrongWords = set()
        self.strongWordCodes = {}
        self.strongReadLines = []
        self.strongReadScroll = 0
        self.strongReadCacheKey = None
        self.strongReadCacheW = None
        self.clickMapStrongWords = {}

    def loadBooks(self):
        return [(r["book_index"], r["name"]) for r in self.conn.cursor().execute("SELECT book_index, name FROM book_name WHERE language='big5' ORDER BY book_index").fetchall()]

    def maxChapter(self, bookIndex):
        return self.conn.cursor().execute("SELECT MAX(chapter) AS m FROM content WHERE language='big5' AND book_index=?", (bookIndex,)).fetchone()["m"] or 1

    def pageStep(self):
        h, _w = self.stdscr.getmaxyx()
        return max(1, (h - 2) - 1)

    NAV_KEYS = ("mode", "bookIdx", "bookScroll", "selectedBookIndex", "chapterCount", "chapterIdx", "chapterScroll", "selectedChapter", "showEn", "showCuv", "showOutline", "expanded", "readScroll", "searchQuery", "searchResults", "searchScroll", "searchIdx", "strongBookIdx", "strongBookScroll", "strongSelectedBookIndex", "strongChapterCount", "strongChapterIdx", "strongChapterScroll", "strongSelectedChapter", "expandedStrongWords", "strongReadScroll")

    def snapshot(self):
        snap = {}
        for key in self.NAV_KEYS:
            val = getattr(self, key)
            snap[key] = set(val) if isinstance(val, set) else list(val) if isinstance(val, list) else val
        return snap

    def pushHistory(self): self.history.append(self.snapshot())

    def goBack(self):
        if not self.history: return False
        for key, val in self.history.pop().items(): setattr(self, key, val)
        self.readCacheKey = self.strongReadCacheKey = None
        return True

    def currentReadSection(self):
        for line in self.readLines[self.readScroll:]:
            if line.section is not None: return line.section
        for line in self.readLines[:self.readScroll]:
            if line.section is not None: return line.section
        return None

    def run(self):
        curses = self.curses
        curses.curs_set(0)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
            curses.mouseinterval(0)
        except curses.error: pass
        self.stdscr.keypad(True)
        try:
            curses.start_color()
            curses.use_default_colors()
            for i, c in enumerate([curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_CYAN, curses.COLOR_WHITE], 1): curses.init_pair(i, c, -1)
            curses.init_pair(colorHeader, curses.COLOR_BLACK, curses.COLOR_YELLOW)
            curses.init_pair(colorHelp, curses.COLOR_BLACK, curses.COLOR_WHITE)
        except curses.error: pass

        while True:
            self.draw()
            try: ch = self.stdscr.get_wch()
            except curses.error: continue
            if not self.handleKey(ch): break

    def draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        drawMode = self.quitPromptFrom if self.mode == "confirm_quit" else self.mode
        if drawMode == "books": self.drawBooks(h, w)
        elif drawMode == "chapters": self.drawChapters(h, w)
        elif drawMode == "read": self.drawRead(h, w)
        elif drawMode == "search_results": self.drawSearchResults(h, w)
        elif drawMode == "strong_books": self.drawStrongBooks(h, w)
        elif drawMode == "strong_chapters": self.drawStrongChapters(h, w)
        elif drawMode == "strong_read": self.drawStrongRead(h, w)
        elif drawMode == "help": self.drawHelp(h, w)
        elif drawMode == "intro_view": self.drawIntroView(h, w)
        elif drawMode == "note_view": self.drawNoteView(h, w)
        elif drawMode == "bookmark_view": self.drawBookmarkView(h, w)
        
        if self.mode == "confirm_quit": self.drawQuitPrompt(h, w)
        self.drawStatus(h, w)
        self.stdscr.refresh()

    def drawQuitPrompt(self, h, w):
        text = " 確定要離開程式嗎？(y/n) "
        try: self.stdscr.addstr(h // 2, max(0, (w - len(text)) // 2), text[: max(0, w - 1)], self.curses.color_pair(colorHeader) | self.curses.A_BOLD)
        except self.curses.error: pass

    def drawStatus(self, h, w):
        text = f":{self.cmdBuffer}" if self.cmdMode else ""
        try: self.stdscr.addstr(h - 1, 0, text.ljust(w - 1), self.curses.color_pair(colorHelp))
        except self.curses.error: pass

    def title(self, text, w):
        try: self.stdscr.addstr(0, 0, text[: w - 1].ljust(w - 1), self.curses.color_pair(colorHeader) | self.curses.A_BOLD)
        except self.curses.error: pass

    def drawBooks(self, h, w):
        self.title(" 書卷清單", w)
        visible = h - 2
        if self.bookIdx < self.bookScroll: self.bookScroll = self.bookIdx
        if self.bookIdx >= self.bookScroll + visible: self.bookScroll = self.bookIdx - visible + 1
        self.clickMap = {}
        for rowI, (idx, name) in enumerate(self.books[self.bookScroll:self.bookScroll + visible]):
            y = rowI + 1
            label = f"{idx:>3}  {name}  ({'舊約' if idx <= 39 else '新約'})"
            attr = self.curses.A_REVERSE if self.bookScroll + rowI == self.bookIdx else 0
            try: self.stdscr.addstr(y, 0, label[: w - 1].ljust(w - 1), attr)
            except self.curses.error: pass
            self.clickMap[y] = ("book", self.bookScroll + rowI)

    def drawChapters(self, h, w):
        self.title(f" {bookDisplayName(self.conn, self.selectedBookIndex, 'big5')}", w)
        cols = max(1, (w - 1) // 8)
        self.clickMap = {}
        for i in range(self.chapterCount):
            y = i // cols + 1 - self.chapterScroll
            if 1 <= y <= h - 2:
                try: self.stdscr.addstr(y, (i % cols) * 8, f"第{i+1:>3}章", self.curses.A_REVERSE if i == self.chapterIdx else 0)
                except self.curses.error: pass
                self.clickMap[(y, i % cols)] = ("chapter", i)

    def buildReadLines(self, w):
        cur = self.conn.cursor()
        langPrimary = "cuv_big5" if self.showCuv else "big5"
        rows = cur.execute("SELECT section, content FROM content WHERE language=? AND book_index=? AND chapter=? ORDER BY section", (langPrimary, self.selectedBookIndex, self.selectedChapter)).fetchall()
        outlines = getOutlines(self.conn, langPrimary, self.selectedBookIndex, self.selectedChapter) if self.showOutline else {}
        secondaryMap = {r["section"]: r["content"] for r in cur.execute("SELECT section, content FROM content WHERE language='eng' AND book_index=? AND chapter=? ORDER BY section", (self.selectedBookIndex, self.selectedChapter)).fetchall()} if self.showEn else {}
        lines, verseRow = [], {}
        for r in rows:
            section = r["section"]
            for o in outlines.get(section, []):
                for wl in plainWrap("  " * (o["level"] - 1) + o["outline"], w - 1):
                    lines.append(Line([("".join(c for c, _ in wl), colorOutline | self.curses.A_BOLD)]))
            fn = getFootnotes(self.conn, langPrimary, self.selectedBookIndex, self.selectedChapter, section)
            chars = []
            marks = {loc - 1: seq for loc, seq in [(f["location"], f["seq"]) for f in fn]}
            for i, c in enumerate(r["content"]):
                if i in marks:
                    for mc in str(marks[i]): chars.append((mc, colorFootnote))
                chars.append((c, 0))
            verseRow[section] = len(lines)
            for wl in wrapMarked([(c, 0) for c in f"{section:>3}  "] + chars, w - 1):
                segs, curAttr, buf = [], None, ""
                for c, flag in wl:
                    if flag != curAttr:
                        if buf: segs.append((buf, curAttr))
                        buf, curAttr = c, flag
                    else: buf += c
                if buf: segs.append((buf, curAttr))
                lines.append(Line(segs, section=section, clickable=True))
            if self.showEn and section in secondaryMap:
                for wl in plainWrap("     " + secondaryMap[section], w - 1): lines.append(Line([("".join(c for c, _ in wl), colorSecondary)], section=section))
            if section in self.expanded:
                for f in fn:
                    for wl in plainWrap(f"      [{f['seq']}] " + (f["note"] or ""), w - 1): lines.append(Line([("".join(c for c, _ in wl), colorSecondary)]))
            lines.append(Line([("", 0)]))
        return lines, verseRow

    def drawRead(self, h, w):
        flags = [f for f, cond in zip(["英文", "和合本"], [self.showEn, self.showCuv]) if cond]
        self.title(f" {bookDisplayName(self.conn, self.selectedBookIndex, 'big5')} 第{self.selectedChapter}章{(' [' + '／'.join(flags) + ']') if flags else ''}", w)
        cacheKey = (self.selectedBookIndex, self.selectedChapter, self.showEn, self.showCuv, self.showOutline, frozenset(self.expanded))
        if cacheKey != self.readCacheKey or w != self.readCacheW:
            self.readLines, self.readVerseRow = self.buildReadLines(w)
            self.readCacheKey, self.readCacheW = cacheKey, w
        self.readScroll = max(0, min(self.readScroll, max(0, len(self.readLines) - (h - 2))))
        self.clickMapRead = {}
        for rowI, line in enumerate(self.readLines[self.readScroll:self.readScroll + h - 2]):
            y, x = rowI + 1, 0
            for text, attr in line.segments:
                color = self.curses.color_pair(attr & 0xF) if attr else 0
                try: self.stdscr.addstr(y, x, text, color | (self.curses.A_BOLD if attr == (colorOutline | self.curses.A_BOLD) else 0))
                except self.curses.error: pass
                x += sum(cWidth(c) for c in text)
            if line.clickable: self.clickMapRead[y] = line.section

    def drawSearchResults(self, h, w):
        self.title(f" 搜尋「{self.searchQuery}」共 {len(self.searchResults)} 筆", w)
        visible = h - 2
        if self.searchIdx < self.searchScroll: self.searchScroll = self.searchIdx
        if self.searchIdx >= self.searchScroll + visible: self.searchScroll = self.searchIdx - visible + 1
        self.clickMap = {}
        for rowI, r in enumerate(self.searchResults[self.searchScroll:self.searchScroll + visible]):
            y = rowI + 1
            attr = self.curses.A_REVERSE if self.searchScroll + rowI == self.searchIdx else 0
            try: self.stdscr.addstr(y, 0, f"{r['acr']} {r['chapter']}:{r['section']}  {r['content']}"[: w - 1].ljust(w - 1), attr)
            except self.curses.error: pass
            self.clickMap[y] = ("search_result", self.searchScroll + rowI)

    def drawIntroView(self, h, w):
        self.title(" 書卷簡介", w)
        for i, l in enumerate(getattr(self, 'introLines', [])[:h-2]):
            try: self.stdscr.addstr(i + 1, 0, l[:w-1])
            except self.curses.error: pass

    def drawNoteView(self, h, w):
        self.title(" 筆記內容", w)
        for i, l in enumerate(getattr(self, 'noteLines', [])[:h-2]):
            try: self.stdscr.addstr(i + 1, 0, l[:w-1])
            except self.curses.error: pass

    def drawBookmarkView(self, h, w):
        self.title(" 書籤列表", w)
        for i, l in enumerate(getattr(self, 'bookmarkLines', [])[:h-2]):
            try: self.stdscr.addstr(i + 1, 0, l[:w-1])
            except self.curses.error: pass

    def openStrongConn(self):
        if self.strongConn is None and self.strongBiblePath:
            self.strongConn = _openSqliteSoft(self.strongBiblePath)
        return self.strongConn

    def openDictConn(self):
        if self.dictConn is None and self.dictPath:
            self.dictConn = _openSqliteSoft(self.dictPath)
        return self.dictConn

    def strongDefinitionLines(self, code):
        if code in self.strongDefCache: return self.strongDefCache[code]
        if code in ("G0", "H0"): return self.strongDefCache.setdefault(code, [f"[{code} 為佔位符，無對應字典資料]"])
        dconn = self.openDictConn()
        if dconn is None: return self.strongDefCache.setdefault(code, ["尚未偵測到 Strong 字典（.dct.mybible）"])
        row = dconn.execute("SELECT word, data FROM dictionary WHERE word = ?", (code,)).fetchone()
        res = [f"── Strong {row['word']} ──"] + renderDictHtml(row["data"], color=False).split("\n") if row else [f"查無 Strong 編號: {code}"]
        return self.strongDefCache.setdefault(code, res)

    def drawStrongBooks(self, h, w):
        self.title(" 書卷清單（原文 Strong）", w)
        visible = h - 2
        if self.strongBookIdx < self.strongBookScroll: self.strongBookScroll = self.strongBookIdx
        if self.strongBookIdx >= self.strongBookScroll + visible: self.strongBookScroll = self.strongBookIdx - visible + 1
        self.clickMap = {}
        for rowI, (idx, name) in enumerate(self.strongBooks[self.strongBookScroll:self.strongBookScroll + visible]):
            y = rowI + 1
            attr = self.curses.A_REVERSE if self.strongBookScroll + rowI == self.strongBookIdx else 0
            try: self.stdscr.addstr(y, 0, f"{idx:>3}  {name}  ({'舊約' if idx <= 39 else '新約'})"[: w - 1].ljust(w - 1), attr)
            except self.curses.error: pass
            self.clickMap[y] = ("strongbook", self.strongBookScroll + rowI)

    def drawStrongChapters(self, h, w):
        self.title(f" {zhBookNames[self.strongSelectedBookIndex - 1]}（原文 Strong）", w)
        cols = max(1, (w - 1) // 8)
        self.clickMap = {}
        for i in range(self.strongChapterCount):
            y = i // cols + 1 - self.strongChapterScroll
            if 1 <= y <= h - 2:
                try: self.stdscr.addstr(y, (i % cols) * 8, f"第{i+1:>3}章", self.curses.A_REVERSE if i == self.strongChapterIdx else 0)
                except self.curses.error: pass
                self.clickMap[(y, i % cols)] = ("strongchapter", i)

    def buildStrongReadLines(self, w):
        conn, lines, self.strongWordCodes = self.openStrongConn(), [], {}
        if conn is None: return [SegLine([("找不到 Strong 原文聖經模組", 0, None)])]
        rows = conn.execute("SELECT Verse, Scripture FROM Bible WHERE Book=? AND Chapter=? ORDER BY Verse", (self.strongSelectedBookIndex, self.strongSelectedChapter)).fetchall()
        if not rows: return [SegLine([("查無此章節", 0, None)])]
        for r in rows:
            verse, chars, wordIdx = r["Verse"], [(c, None) for c in f"{r['Verse']:>3}  "], 0
            for text, codes in splitStrongVerse(r["Scripture"]):
                if codes:
                    wordIdx += 1
                    key = (self.strongSelectedBookIndex, self.strongSelectedChapter, verse, wordIdx)
                    self.strongWordCodes[key] = codes
                    chars.extend((c, key) for c in text)
                else: chars.extend((c, None) for c in text)
            for wl in wrapMarked(chars, w - 1):
                segs, curKey, buf = [], "__NONE__", ""
                for c, key in wl:
                    if key != curKey:
                        if buf: segs.append((buf, colorSection if curKey in self.expandedStrongWords else colorFootnote if curKey not in ("__NONE__", None) else 0, None if curKey == "__NONE__" else curKey))
                        buf, curKey = c, key
                    else: buf += c
                if buf: segs.append((buf, colorSection if curKey in self.expandedStrongWords else colorFootnote if curKey not in ("__NONE__", None) else 0, None if curKey == "__NONE__" else curKey))
                lines.append(SegLine(segs))
            for wi in range(1, wordIdx + 1):
                key = (self.strongSelectedBookIndex, self.strongSelectedChapter, verse, wi)
                if key not in self.expandedStrongWords: continue
                for code in self.strongWordCodes.get(key, []):
                    for defLine in self.strongDefinitionLines(code):
                        for wl2 in plainWrap("      " + defLine, w - 1): lines.append(SegLine([("".join(c for c, _ in wl2), colorSecondary, None)]))
            lines.append(SegLine([("", 0, None)]))
        return lines

    def drawStrongRead(self, h, w):
        self.title(f" {zhBookNames[self.strongSelectedBookIndex - 1]} 第{self.strongSelectedChapter}章（原文 Strong）", w)
        cacheKey = (self.strongSelectedBookIndex, self.strongSelectedChapter, frozenset(self.expandedStrongWords))
        if cacheKey != self.strongReadCacheKey or w != self.strongReadCacheW:
            self.strongReadLines = self.buildStrongReadLines(w)
            self.strongReadCacheKey, self.strongReadCacheW = cacheKey, w
        self.strongReadScroll = max(0, min(self.strongReadScroll, max(0, len(self.strongReadLines) - (h - 2))))
        self.clickMapStrongWords = {}
        for rowI, line in enumerate(self.strongReadLines[self.strongReadScroll:self.strongReadScroll + h - 2]):
            y, x, regions = rowI + 1, 0, []
            for text, attr, key in line.segments:
                try: self.stdscr.addstr(y, x, text, self.curses.color_pair(attr & 0xF) if attr else 0)
                except self.curses.error: pass
                textWidth = sum(cWidth(c) for c in text)
                if key is not None: regions.append((x, x + textWidth, key))
                x += textWidth
            if regions: self.clickMapStrongWords[y] = regions

    def drawHelp(self, h, w):
        self.title(" 說明  (按任意鍵返回)", w)
        lines = [
            "  :q 離開程式 ; :Q 直接離開",
            "  :strong 或 :S 切換 Strong 模式 ; :recovery 或 :R 切換恢復本模式",
            "  :1 1 跳轉經節 (卷 章 節)",
            "  :footnote 或 :F 顯示註解",
            "  :intro 顯示本卷書介",
            "  :copy 或 :C 複製經文或註解",
            "  :english 或 :E 切換英文對照",
            "  :outline 或 :O 切換綱目及註解標記",
            "  :search 關鍵字 (可加上 -e 查英文，--exclude 排除)",
            "  :setup-storage 啟用儲存空間",
            "  :option 設定 ; o/O 也可開啟設定",
            "  :note 或 :N 筆記 ; :bookmark 或 :M 書籤 ; :reference 或 :ref 串珠",
            "  b / B 返回上一頁",
            "  使用滑鼠點擊可以展開或收合註解/原文字義",
        ]
        for i, l in enumerate(lines[:h-2]):
            try: self.stdscr.addstr(i + 1, 0, l[:w-1])
            except self.curses.error: pass

    def handleKey(self, ch):
        curses = self.curses
        if isinstance(ch, str):
            ch = ord(ch)
        if self.mode == "help":
            self.mode = "read" if self.hasDb else "strong_read"
            return True

        if self.mode == "confirm_quit":
            if ch in (ord('y'), ord('Y'), 10, 13, curses.KEY_ENTER): return False
            self.mode = self.quitPromptFrom
            return True

        if self.cmdMode:
            if ch in (10, 13, curses.KEY_ENTER):
                self.executeCommand(self.cmdBuffer)
                self.cmdMode = False
                self.cmdBuffer = ""
            elif ch in (27,):
                self.cmdMode = False
                self.cmdBuffer = ""
            elif ch in (curses.KEY_BACKSPACE, 127, 8): self.cmdBuffer = self.cmdBuffer[:-1]
            elif isinstance(ch, int) and 32 <= ch < 0x110000: self.cmdBuffer += chr(ch)
            return True

        if ch == ord(':'):
            self.cmdMode = True
            self.cmdBuffer = ""
            return True

        if ch in (ord('q'), ord('Q')):
            if ch == ord('Q'): return False
            self.quitPromptFrom = self.mode
            self.mode = "confirm_quit"
            return True

        if ch in (ord('b'), ord('B')):
            self.goBack()
            return True
            
        if ch in (ord('o'), ord('O')):
            self.executeCommand("option")
            return True

        if ch == curses.KEY_MOUSE:
            try: _, mx, my, _, bstate = curses.getmouse()
            except curses.error: return True
            if bstate & curses.BUTTON1_CLICKED: self.handleClick(my, mx)
            return True

        h, _w = self.stdscr.getmaxyx()
        visible = h - 2

        if self.mode == "books":
            if ch == curses.KEY_UP: self.bookIdx = max(0, self.bookIdx - 1)
            elif ch == curses.KEY_DOWN: self.bookIdx = min(len(self.books) - 1, self.bookIdx + 1)
            elif ch in (10, 13, curses.KEY_ENTER):
                self.pushHistory()
                self.selectedBookIndex = self.books[self.bookIdx][0]
                self.chapterCount = self.maxChapter(self.selectedBookIndex)
                self.chapterIdx, self.chapterScroll = 0, 0
                self.mode = "chapters"
        elif self.mode == "chapters":
            cols = max(1, (_w - 1) // 8)
            if ch == curses.KEY_UP: self.chapterIdx = max(0, self.chapterIdx - cols)
            elif ch == curses.KEY_DOWN: self.chapterIdx = min(self.chapterCount - 1, self.chapterIdx + cols)
            elif ch == curses.KEY_LEFT: self.chapterIdx = max(0, self.chapterIdx - 1)
            elif ch == curses.KEY_RIGHT: self.chapterIdx = min(self.chapterCount - 1, self.chapterIdx + 1)
            elif ch in (10, 13, curses.KEY_ENTER):
                self.pushHistory()
                self.selectedChapter = self.chapterIdx + 1
                self.readScroll = 0
                self.expanded.clear()
                self.mode = "read"
        elif self.mode == "read":
            if ch == curses.KEY_UP: self.readScroll = max(0, self.readScroll - 1)
            elif ch == curses.KEY_DOWN: self.readScroll = min(max(0, len(self.readLines) - visible), self.readScroll + 1)
            elif ch == curses.KEY_PPAGE: self.readScroll = max(0, self.readScroll - visible)
            elif ch == curses.KEY_NPAGE: self.readScroll = min(max(0, len(self.readLines) - visible), self.readScroll + visible)
        elif self.mode == "search_results":
            if ch == curses.KEY_UP: self.searchIdx = max(0, self.searchIdx - 1)
            elif ch == curses.KEY_DOWN: self.searchIdx = min(len(self.searchResults) - 1, self.searchIdx + 1)
            elif ch in (10, 13, curses.KEY_ENTER):
                r = self.searchResults[self.searchIdx]
                self.pushHistory()
                self.selectedBookIndex = r["book_index"]
                self.selectedChapter = r["chapter"]
                self.expanded.clear()
                self.mode = "read"
                self.readCacheKey = None
                self.buildReadLines(_w)
                self.readScroll = max(0, self.readVerseRow.get(r["section"], 0) - visible // 2)
        elif self.mode == "strong_books":
            if ch == curses.KEY_UP: self.strongBookIdx = max(0, self.strongBookIdx - 1)
            elif ch == curses.KEY_DOWN: self.strongBookIdx = min(len(self.strongBooks) - 1, self.strongBookIdx + 1)
            elif ch in (10, 13, curses.KEY_ENTER):
                self.pushHistory()
                self.strongSelectedBookIndex = self.strongBooks[self.strongBookIdx][0]
                self.strongChapterCount = _getStrongMaxChapter(self.openStrongConn(), self.strongSelectedBookIndex)
                self.strongChapterIdx, self.strongChapterScroll = 0, 0
                self.mode = "strong_chapters"
        elif self.mode == "strong_chapters":
            cols = max(1, (_w - 1) // 8)
            if ch == curses.KEY_UP: self.strongChapterIdx = max(0, self.strongChapterIdx - cols)
            elif ch == curses.KEY_DOWN: self.strongChapterIdx = min(self.strongChapterCount - 1, self.strongChapterIdx + cols)
            elif ch == curses.KEY_LEFT: self.strongChapterIdx = max(0, self.strongChapterIdx - 1)
            elif ch == curses.KEY_RIGHT: self.strongChapterIdx = min(self.strongChapterCount - 1, self.strongChapterIdx + 1)
            elif ch in (10, 13, curses.KEY_ENTER):
                self.pushHistory()
                self.strongSelectedChapter = self.strongChapterIdx + 1
                self.strongReadScroll = 0
                self.expandedStrongWords.clear()
                self.mode = "strong_read"
        elif self.mode == "strong_read":
            if ch == curses.KEY_UP: self.strongReadScroll = max(0, self.strongReadScroll - 1)
            elif ch == curses.KEY_DOWN: self.strongReadScroll = min(max(0, len(self.strongReadLines) - visible), self.strongReadScroll + 1)
            elif ch == curses.KEY_PPAGE: self.strongReadScroll = max(0, self.strongReadScroll - visible)
            elif ch == curses.KEY_NPAGE: self.strongReadScroll = min(max(0, len(self.strongReadLines) - visible), self.strongReadScroll + visible)
        elif self.mode in ("intro_view", "note_view", "bookmark_view"):
            if ch in (27, ord('q'), curses.KEY_ENTER, 10, 13):
                self.goBack()
        return True

    def handleClick(self, y, x):
        curses = self.curses
        if self.mode == "books" and y in getattr(self, "clickMap", {}):
            self.bookIdx = self.clickMap[y][1]
            self.handleKey(curses.KEY_ENTER)
        elif self.mode == "chapters" and (y, x // 8) in getattr(self, "clickMap", {}):
            self.chapterIdx = self.clickMap[(y, x // 8)][1]
            self.handleKey(curses.KEY_ENTER)
        elif self.mode == "read" and y in getattr(self, "clickMapRead", {}):
            section = self.clickMapRead[y]
            if section in self.expanded: self.expanded.remove(section)
            else: self.expanded.add(section)
        elif self.mode == "search_results" and y in getattr(self, "clickMap", {}):
            self.searchIdx = self.clickMap[y][1]
            self.handleKey(curses.KEY_ENTER)
        elif self.mode == "strong_books" and y in getattr(self, "clickMap", {}):
            self.strongBookIdx = self.clickMap[y][1]
            self.handleKey(curses.KEY_ENTER)
        elif self.mode == "strong_chapters" and (y, x // 8) in getattr(self, "clickMap", {}):
            self.strongChapterIdx = self.clickMap[(y, x // 8)][1]
            self.handleKey(curses.KEY_ENTER)
        elif self.mode == "strong_read" and y in getattr(self, "clickMapStrongWords", {}):
            for rx1, rx2, key in self.clickMapStrongWords[y]:
                if rx1 <= x < rx2:
                    if key in self.expandedStrongWords: self.expandedStrongWords.remove(key)
                    else: self.expandedStrongWords.add(key)
                    break

    def setupStorage(self):
        try:
            self.userDb = sqlite3.connect(self.storagePath)
            self.userDb.execute("CREATE TABLE IF NOT EXISTS options (key TEXT PRIMARY KEY, val TEXT)")
            self.userDb.execute("CREATE TABLE IF NOT EXISTS notes (book INT, chapter INT, verse INT, content TEXT, PRIMARY KEY(book, chapter, verse))")
            self.userDb.execute("CREATE TABLE IF NOT EXISTS bookmarks (book INT, chapter INT, verse INT, PRIMARY KEY(book, chapter, verse))")
            self.userDb.execute("CREATE TABLE IF NOT EXISTS crossrefs (s_book INT, s_ch INT, s_v INT, d_book INT, d_ch INT, d_v INT)")
            self.userDb.commit()
            self.storageEnabled = True
        except Exception: pass

    def parseLoc(self, args):
        curB = getattr(self, "selectedBookIndex", None) or getattr(self, "strongSelectedBookIndex", None) or 1
        curC = getattr(self, "selectedChapter", None) or getattr(self, "strongSelectedChapter", None) or 1
        curV = self.currentReadSection() or 1
        if not args: return curB, curC, curV
        bIdx = resolveBook(self.conn, args[0]) if self.conn else resolveZhBookIndex(args[0])
        if bIdx and not args[0].isdigit():
            if len(args) == 1: return bIdx, 1, 1
            if len(args) == 2: return bIdx, int(args[1]), 1
            return bIdx, int(args[1]), int(args[2])
        if len(args) == 1: return curB, curC, int(args[0])
        if len(args) == 2: return curB, int(args[0]), int(args[1])
        if len(args) == 3 and args[0].isdigit():
            return int(args[0]), int(args[1]), int(args[2])
        return curB, curC, curV

    def doJump(self, loc, forceMode=None):
        if not loc: return
        b, c, v = loc
        self.pushHistory()
        targetMode = forceMode or ("strong_read" if "strong" in self.mode else "read")
        if targetMode == "read":
            if not self.hasDb: return
            self.selectedBookIndex, self.selectedChapter = b, c
            self.chapterCount = self.maxChapter(b)
            self.mode = "read"
            self.readCacheKey = None
            self.buildReadLines(self.stdscr.getmaxyx()[1])
            self.readScroll = max(0, self.readVerseRow.get(v, 0) - self.pageStep() // 2)
        else:
            if not self.hasStrongBible: return
            self.strongSelectedBookIndex, self.strongSelectedChapter = b, c
            self.strongChapterCount = _getStrongMaxChapter(self.openStrongConn(), b)
            self.mode = "strong_read"
            self.strongReadCacheKey = None
            self.buildStrongReadLines(self.stdscr.getmaxyx()[1])
            self.strongReadScroll = max(0, v - self.pageStep() // 2)

    def openEditor(self, initialText):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(initialText.encode('utf-8'))
            tmpName = tf.name
        self.curses.endwin()
        subprocess.run([os.environ.get('EDITOR', 'nano'), tmpName])
        self.stdscr.refresh()
        with open(tmpName, 'r', encoding='utf-8') as f:
            res = f.read()
        os.remove(tmpName)
        return res

    def executeCommand(self, cmdStr):
        import shlex
        try: parts = shlex.split(cmdStr)
        except ValueError: parts = cmdStr.split()
        if not parts: return
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("q", "quit"): self.mode = "confirm_quit"
        elif cmd in ("Q", "quit!"): sys.exit(0)
        elif cmd in ("help", "h"):
            self.pushHistory()
            self.mode = "help"
        elif cmd in ("strong", "s"):
            if self.hasStrongBible: self.doJump(self.parseLoc(args), "strong")
        elif cmd in ("recovery", "r"):
            if self.hasDb: self.doJump(self.parseLoc(args), "recovery")
        elif cmd in ("footnote", "f"):
            loc = self.parseLoc(args)
            if loc:
                self.doJump(loc, "read")
                self.expanded.add(loc[2])
        elif cmd == "intro":
            loc = self.parseLoc(args)
            if loc and self.hasDb:
                self.pushHistory()
                rows = self.conn.cursor().execute("SELECT type, intro FROM book_intro WHERE language='big5' AND book_index=? ORDER BY type", (loc[0],)).fetchall()
                self.introLines = []
                for r in rows:
                    typeLabel = introTypeLabel.get(r["type"], f"type{r['type']}")
                    self.introLines.append(f"{typeLabel}: {r['intro']}")
                self.mode = "intro_view"
        elif cmd in ("copy", "c"):
            if args and args[0].startswith("#"):
                seq = int(args[0][1:])
                loc = self.parseLoc(args[1:])
                row = self.conn.cursor().execute("SELECT note FROM footnote WHERE language='big5' AND book_index=? AND chapter=? AND section=? AND seq=?", (loc[0], loc[1], loc[2], seq)).fetchone()
                if row: copyToClipboardText(row["note"])
            else:
                loc = self.parseLoc(args)
                if loc:
                    row = self.conn.cursor().execute("SELECT content FROM content WHERE language='big5' AND book_index=? AND chapter=? AND section=?", (loc[0], loc[1], loc[2])).fetchone()
                    if row: copyToClipboardText(row["content"])
        elif cmd in ("english", "e"): self.showEn = not self.showEn if not args else args[0] == "on"
        elif cmd in ("outline", "o"): self.showOutline = not self.showOutline if not args else args[0] == "on"
        elif cmd == "search":
            isEng = "-e" in args
            args = [a for a in args if a != "-e"]
            exclude = []
            if "--exclude" in args:
                idx = args.index("--exclude")
                exclude = args[idx+1:]
                args = args[:idx]
            lang = "eng" if isEng else "big5"
            q = "SELECT book_index, chapter, section, content FROM content WHERE language=?"
            params = [lang]
            for a in args:
                q += " AND content LIKE ?"
                params.append(f"%{a}%")
            for e in exclude:
                q += " AND content NOT LIKE ?"
                params.append(f"%{e}%")
            q += " ORDER BY book_index, chapter, section"
            self.pushHistory()
            self.searchResults = self.conn.cursor().execute(q, params).fetchall()
            for r in self.searchResults:
                acrRow = self.conn.cursor().execute("SELECT acronym_name FROM book_name WHERE book_index=? AND language=?", (r["book_index"], lang if lang in zhLangs else "big5")).fetchone()
                r.update({"acr": acrRow["acronym_name"] if acrRow else str(r["book_index"])})
            self.searchQuery = " ".join(args)
            self.searchIdx = self.searchScroll = 0
            self.mode = "search_results"
        elif cmd == "setup-storage": self.setupStorage()
        elif cmd == "option": pass 
        elif cmd in ("note", "n"):
            if not self.storageEnabled: return
            loc = self.parseLoc(args)
            if loc:
                row = self.userDb.execute("SELECT content FROM notes WHERE book=? AND chapter=? AND verse=?", loc).fetchone()
                init = row[0] if row else ""
                newContent = self.openEditor(init)
                self.userDb.execute("INSERT OR REPLACE INTO notes (book, chapter, verse, content) VALUES (?, ?, ?, ?)", loc + (newContent,))
                self.userDb.commit()
        elif cmd in ("bookmark", "m", "mark"):
            if not self.storageEnabled: return
            if args and args[0] == "show":
                self.pushHistory()
                rows = self.userDb.execute("SELECT book, chapter, verse FROM bookmarks").fetchall()
                self.bookmarkLines = [f"{r[0]} {r[1]}:{r[2]}" for r in rows]
                self.mode = "bookmark_view"
            else:
                loc = self.parseLoc(args)
                if loc:
                    self.userDb.execute("INSERT OR REPLACE INTO bookmarks (book, chapter, verse) VALUES (?, ?, ?)", loc)
                    self.userDb.commit()
        elif cmd in ("reference", "ref"):
            if not self.storageEnabled: return
            curLoc = self.parseLoc([])
            targetLoc = self.parseLoc(args)
            if curLoc and targetLoc:
                self.userDb.execute("INSERT INTO crossrefs (s_book, s_ch, s_v, d_book, d_ch, d_v) VALUES (?, ?, ?, ?, ?, ?)", curLoc + targetLoc)
                self.userDb.commit()
        else:
            loc = self.parseLoc(parts)
            if loc and (parts[0].isdigit() or resolveBook(self.conn, parts[0]) or resolveZhBookIndex(parts[0])):
                self.doJump(loc)

def _openSqliteSoft(path):
    if not os.path.exists(path): return None
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c

def _getStrongMaxChapter(conn, bookIndex):
    if not conn: return 1
    row = conn.execute("SELECT MAX(Chapter) as m FROM Bible WHERE Book=?", (bookIndex,)).fetchone()
    return row["m"] if row and row["m"] else 1

def main():
    setupConsole()
    parser = buildParser()
    if len(sys.argv) > 1 and sys.argv[1] not in ("--db", "--mode", "-h", "--help"):
        args = parser.parse_args()
        conn = connect(args.db) if hasattr(args, "func") and args.func not in (cmdStrong, cmdOrig) else None
        args.func(args, conn)
        sys.exit(0)
    args = parser.parse_args()
    conn = None
    if os.path.exists(args.db): conn = sqlite3.connect(args.db)
    if conn: conn.row_factory = sqlite3.Row
    if args.mode == "strong" and not strongBibleDefault:
        sys.stderr.write("強制作為原文 Strong 模式啟動，但找不到 .bbl.mybible 模組。\n")
        sys.exit(1)
    if args.mode == "restore" and not conn:
        sys.stderr.write(f"強制作為恢復本模式啟動，但找不到資料庫：{args.db}\n")
        sys.exit(1)
    initialMode = "strong_books" if args.mode == "strong" or (args.mode == "auto" and not conn and strongBibleDefault) else "books"
    if not conn and not strongBibleDefault:
        sys.stderr.write("目錄下找不到 bible.db 或 .mybible，請確認檔案位置。\n")
        sys.exit(1)
    try: import curses
    except ImportError:
        sys.stderr.write("本作業系統未內建 curses，請先執行 `pip install windows-curses` 才能使用互動式介面。\n")
        parser.print_help()
        sys.exit(1)
    def run_curses(stdscr): App(curses, stdscr, conn, strongBibleDefault, dictDefault, initialMode).run()
    curses.wrapper(run_curses)

if __name__ == "__main__":
    main()
