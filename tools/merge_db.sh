#!/usr/bin/env bash

set -euo pipefail

srcDir="${1:?請提供 assets 來源目錄，例如 ~/bible/assets}"
outFile="${2:-./bible.db}"

if [ ! -d "$srcDir" ]; then
    echo "找不到目錄: $srcDir" >&2
    exit 1
fi

parts=("$srcDir"/bible.db.[0-9][0-9][0-9])
if [ ! -e "${parts[0]}" ]; then
    echo "在 $srcDir 找不到 bible.db.001 這類分割檔" >&2
    exit 1
fi

echo "合併 ${#parts[@]} 個分割檔 -> $outFile"
cat "${parts[@]}" > "$outFile"

if file "$outFile" | grep -q "SQLite"; then
    echo "完成，已確認為合法 SQLite 檔案：$outFile"
else
    echo "警告：合併後的檔案看起來不是標準 SQLite 格式，請確認分割方式是否正確" >&2
    exit 1
fi
