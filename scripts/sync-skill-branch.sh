#!/usr/bin/env bash
#
# 把 main 上的源码同步到 skill 发布分支，不带任何运行产物（data / reports / detail）。
#
# 用法：
#   bash scripts/sync-skill-branch.sh [版本号]
#   例如：bash scripts/sync-skill-branch.sh 1.0.1
#
# 行为：
#   1. 从 main 检出下面这组「源码」路径覆盖到 skill 分支
#   2. skill 分支上的 data/ reports/ detail/ 保持干净（不动）
#   3. 强制把 skill 分支的 config.toml 设为 auto_git_push=false（发布制品默认不自动推送）
#   4. 有变更才提交并推送，最后切回原分支
#
set -euo pipefail

VERSION="${1:-}"
SRC_BRANCH="main"
DST_BRANCH="skill"

# 需要随发布制品一起分发的「源码」路径（不含运行产物）
SOURCE_PATHS=(
  "scripts"
  "index.html"
  "config.toml"
  "README.md"
  "SKILL.md"
  "references"
  ".github"
  ".env.example"
  "requirements.txt"
  ".gitignore"
  ".gitattributes"
)

# --- 前置检查 -------------------------------------------------------------
ORIG_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "✗ 工作区有未提交的改动，请先提交或 stash 再运行。" >&2
  exit 1
fi

if ! git show-ref --verify --quiet "refs/heads/${DST_BRANCH}"; then
  echo "✗ 本地没有 ${DST_BRANCH} 分支。先执行：git fetch && git checkout ${DST_BRANCH}" >&2
  exit 1
fi

echo "→ 从 ${SRC_BRANCH} 同步源码到 ${DST_BRANCH}..."
git checkout "${DST_BRANCH}"
git pull --rebase --autostash || true

# --- 覆盖源码路径 ---------------------------------------------------------
git checkout "${SRC_BRANCH}" -- "${SOURCE_PATHS[@]}"

# 发布制品：默认关闭自动 git 推送（安装者需显式开启模式 B）
if [ -f config.toml ]; then
  sed -i -E 's/^auto_git_push[[:space:]]*=.*/auto_git_push = false/' config.toml
  git add config.toml
fi

# --- 提交并推送 -----------------------------------------------------------
if git diff --cached --quiet && git diff --quiet; then
  echo "✓ 与 ${SRC_BRANCH} 源码一致，无需发布。"
else
  git add -A
  if [ -n "${VERSION}" ]; then
    MSG="release: sync v${VERSION} from ${SRC_BRANCH}"
  else
    MSG="release: sync from ${SRC_BRANCH} ($(date '+%Y-%m-%d %H:%M'))"
  fi
  git commit -m "${MSG}"
  git push
  echo "✓ 已发布：${MSG}"
fi

# --- 收尾 ----------------------------------------------------------------
git checkout "${ORIG_BRANCH}"
echo "→ 已切回 ${ORIG_BRANCH}"
