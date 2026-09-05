#!/usr/bin/env bash
# 將本腳本所在目錄（即 bible-cli 專案根目錄）加入 PATH，
# 並寫入 ~/.bashrc 與 ~/.zshrc，讓你能在任何位置直接執行 `bible`。
#
# 用法：
#   chmod +x add-to-path.sh
#   ./add-to-path.sh
#
# 重複執行是安全的：腳本會先移除舊的設定行再寫入新的，不會累積重複內容。

set -euo pipefail

# 專案根目錄＝本腳本所在目錄的絕對路徑
projectDir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

marker="# added by bible-cli/add-to-path.sh"
pathLine="export PATH=\"$projectDir:\$PATH\"  $marker"

updateRc() {
    local rcFile="$1"
    local tmpFile

    [ -f "$rcFile" ] || touch "$rcFile"

    tmpFile="$(mktemp)"
    # 先移除舊的設定行，再用 awk 去除結尾多餘空白行（純用 awk 以兼顧 macOS/BSD 相容性），
    # 避免每次重新執行都累積空行
    { grep -Fv "$marker" "$rcFile" || true; } \
        | awk 'BEGIN{buf=""} {buf = buf $0 "\n"} END{sub(/\n+$/, "\n", buf); printf "%s", buf}' \
        > "$tmpFile"
    printf '\n%s\n' "$pathLine" >> "$tmpFile"
    mv "$tmpFile" "$rcFile"

    echo "已更新 $rcFile"
}

updateRc "$HOME/.bashrc"
updateRc "$HOME/.zshrc"

# 確保 bible 具有可執行權限
if [ -f "$projectDir/bible" ]; then
    chmod +x "$projectDir/bible"
fi

echo ""
echo "設定完成，專案目錄已加入 PATH："
echo "    $projectDir"
echo ""
echo "請重新開啟終端機，或執行以下指令套用變更："
echo "    source ~/.bashrc   # 若使用 bash"
echo "    source ~/.zshrc    # 若使用 zsh"
echo ""
echo "之後即可在任何目錄下直接執行："
echo "    bible"
echo "    bible read 創世記 1"
