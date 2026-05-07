#!/bin/bash
# ANBM 项目提交辅助脚本
# 用法: bash scripts/commit.sh

set -e

CONFIG_FILE="commit-config.json"
TEMPLATE_FILE=".gitmessage"

# 读取当前前缀
prefix=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['projectPrefix'])" 2>/dev/null || echo "ANBM")

echo "============================================"
echo "  ANBM 项目提交辅助工具"
echo "============================================"
echo ""
echo "当前项目前缀: $prefix"
read -p "是否修改项目前缀？(y/n): " change_prefix

if [ "$change_prefix" = "y" ]; then
    read -p "输入新的项目前缀: " new_prefix
    # 更新 commit-config.json
    python3 -c "
import json
with open('$CONFIG_FILE') as f:
    config = json.load(f)
config['projectPrefix'] = '$new_prefix'
with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print('commit-config.json 已更新')
"
    # 更新 .gitmessage 模板中的占位符
    sed -i "s/\[${prefix}-/[${new_prefix}-/g" "$TEMPLATE_FILE"
    prefix="$new_prefix"
    echo "项目前缀已改为: $prefix"
fi

echo ""
echo "请按以下格式提交："
echo "  [${prefix}-任务ID] <type>(<scope>): <subject>"
echo ""
echo "type 可选: feat, fix, docs, style, refactor, perf, test, chore"
echo "scope 可选: core, adapter, api, executor, health, cli, mcp, client, scripts, tests, docs, config"
echo ""
echo "示例:"
echo "  [${prefix}-101] feat(adapter): 新增 mastodon 无限滚动适配器"
echo "  [${prefix}-102] fix(core): 修复 state_history 无限增长"
echo ""
echo "============================================"
