#!/bin/bash
# ================================================================
# 一键设置爬虫服务开机自启（只需运行一次）
# 运行方式：
#   chmod +x crawler/setup_autostart.sh
#   ./crawler/setup_autostart.sh
# ================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_TEMPLATE="$SCRIPT_DIR/com.xhs.dashboard.crawler.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.xhs.dashboard.crawler.plist"
LOG_DIR="$SCRIPT_DIR/logs"
SERVICE_LABEL="com.xhs.dashboard.crawler"
MEDIACRAWLER_DIR="${MEDIACRAWLER_DIR:-$HOME/MediaCrawler}"
PYTHON_BIN="${PYTHON_BIN:-$MEDIACRAWLER_DIR/.venv/bin/python}"

xml_escape() {
    printf '%s' "$1" | sed \
        -e 's/&/\&amp;/g' \
        -e 's/</\&lt;/g' \
        -e 's/>/\&gt;/g' \
        -e 's/"/\&quot;/g' \
        -e "s/'/\&apos;/g"
}

sed_escape() {
    printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}

render_plist() {
    local crawler_dir_xml
    local mediacrawler_dir_xml
    local python_bin_xml

    crawler_dir_xml="$(xml_escape "$SCRIPT_DIR")"
    mediacrawler_dir_xml="$(xml_escape "$MEDIACRAWLER_DIR")"
    python_bin_xml="$(xml_escape "$PYTHON_BIN")"

    sed \
        -e "s|__CRAWLER_DIR__|$(sed_escape "$crawler_dir_xml")|g" \
        -e "s|__MEDIACRAWLER_DIR__|$(sed_escape "$mediacrawler_dir_xml")|g" \
        -e "s|__PYTHON_BIN__|$(sed_escape "$python_bin_xml")|g" \
        "$PLIST_TEMPLATE"
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  XHS Dashboard 爬虫服务 — 自启动配置"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ ! -f "$PLIST_TEMPLATE" ]; then
    echo "❌ LaunchAgent 模板不存在: $PLIST_TEMPLATE"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/server.py" ]; then
    echo "❌ 找不到爬虫服务入口: $SCRIPT_DIR/server.py"
    exit 1
fi

if [ ! -d "$MEDIACRAWLER_DIR" ]; then
    echo "❌ MediaCrawler 目录不存在: $MEDIACRAWLER_DIR"
    echo "   可用 MEDIACRAWLER_DIR=/path/to/MediaCrawler ./setup_autostart.sh 指定"
    exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "❌ MediaCrawler Python 不可执行: $PYTHON_BIN"
    echo "   可用 PYTHON_BIN=/path/to/python ./setup_autostart.sh 指定"
    exit 1
fi

mkdir -p "$LOG_DIR" "$(dirname "$PLIST_DEST")"

# 卸载旧版本（如果存在）
if launchctl list | grep -q "$SERVICE_LABEL" 2>/dev/null; then
    echo "▶ 卸载旧版本..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# 安装新版本
echo "▶ 安装 LaunchAgent..."
render_plist > "$PLIST_DEST"
chmod 644 "$PLIST_DEST"

if command -v plutil >/dev/null 2>&1; then
    plutil -lint "$PLIST_DEST"
fi

launchctl load "$PLIST_DEST"

echo ""
echo "✅ 配置完成！爬虫服务将在每次登录后自动启动。"
echo ""
echo "当前配置："
echo "  爬虫目录：$SCRIPT_DIR"
echo "  MediaCrawler：$MEDIACRAWLER_DIR"
echo "  Python：$PYTHON_BIN"
echo ""
echo "常用命令："
echo "  查看状态：launchctl list | grep xhs"
echo "  查看日志：tail -f $LOG_DIR/server.log"
echo "  手动停止：launchctl unload $PLIST_DEST"
echo "  手动启动：launchctl load $PLIST_DEST"
echo ""
