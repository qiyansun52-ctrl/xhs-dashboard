#!/bin/bash
# ================================================================
# 一键运行：MediaCrawler 爬取 → 导入 Supabase
# 使用方式：
#   chmod +x run.sh
#   ./run.sh              # 正常运行
#   ./run.sh --dry-run    # 测试模式，不写入数据库
# ================================================================

set -e  # 任何步骤出错就停止

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEDIACRAWLER_DIR="${MEDIACRAWLER_DIR:-$HOME/MediaCrawler}"
LOG_FILE="$SCRIPT_DIR/logs/run_$(date +%Y%m%d_%H%M%S).log"
DRY_RUN=${1:-""}

mkdir -p "$SCRIPT_DIR/logs"

echo "========================================"
echo "  XHS 数据同步  $(date '+%Y-%m-%d %H:%M')"
echo "========================================"

# ── Step 1: 运行 MediaCrawler ─────────────────────────────────
echo ""
echo "▶ Step 1: 运行 MediaCrawler 爬取账号数据..."

if [ ! -d "$MEDIACRAWLER_DIR" ]; then
    echo "❌ MediaCrawler 目录不存在: $MEDIACRAWLER_DIR"
    echo "   可用 MEDIACRAWLER_DIR=/path/to/MediaCrawler ./run.sh 指定"
    exit 1
fi

cd "$MEDIACRAWLER_DIR"

# 读取 config.py 中的账号 ID 列表
# 格式：python3 main.py --platform xhs --lt qrcode --type creator --creator_ids "id1,id2"
CREATOR_IDS=$(python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR')
from config import ACCOUNT_MAP
print(','.join(ACCOUNT_MAP.keys()))
")

echo "   爬取账号 IDs: $CREATOR_IDS"
python3 main.py \
    --platform xhs \
    --lt cookie \
    --type creator \
    --creator_ids "$CREATOR_IDS" \
    2>&1 | tee -a "$LOG_FILE"

echo "✅ MediaCrawler 爬取完成"

# ── Step 2: 导入 Supabase ─────────────────────────────────────
echo ""
echo "▶ Step 2: 导入数据到 Supabase..."

cd "$SCRIPT_DIR"
python3 import_stats.py $DRY_RUN 2>&1 | tee -a "$LOG_FILE"

echo ""
echo "✅ 全部完成！日志保存在: $LOG_FILE"
