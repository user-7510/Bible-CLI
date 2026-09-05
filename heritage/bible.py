#!/usr/bin/env python3

import argparse
import sqlite3
import sys
import os

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
    color = not args.noColor
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
    p = argparse.ArgumentParser(description="恢復本聖經 CLI")
    p.add_argument("--db", default=dbDefault, help="sqlite 資料庫路徑")
    sub = p.add_subparsers(dest="cmd", required=True)

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


def main():
    parser = buildParser()
    args = parser.parse_args()
    conn = connect(args.db)
    args.func(args, conn)


if __name__ == "__main__":
    main()
