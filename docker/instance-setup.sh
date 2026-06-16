#!/usr/bin/env bash
# instance-setup.sh — idempotent bootstrap for a {{PACKAGE_NAME}} Hermes instance.
#
# Wires the shared package into a Hermes instance's data directory (HERMES_HOME)
# WITHOUT baking anything into the image: it clones/updates the code, seeds a
# SOUL.md if you don't have one yet, and links the shared skill. The domain
# binaries come from the image (docker/Dockerfile); everything here is the
# hot-mounted code/skill/soul layer.
#
# Usage — run host-side against the mounted data dir:
#   HERMES_HOME=/path/to/your/datadir bash docker/instance-setup.sh
# or inside a running container:
#   docker exec <container> bash /opt/data/{{PACKAGE_DIR}}/docker/instance-setup.sh
#
# Environment variables (all optional — defaults shown):
#   HERMES_HOME          Path to the agent's data dir.   Default: /opt/data
#   PACKAGE_REPO_URL     Git URL of this package repo.   Default: see REPO_URL below
#
# Safe to re-run at any time. It NEVER overwrites content you own — your SOUL.md,
# your skills, and your engagement data are left untouched.
#
# This is deliberately NOT a container ENTRYPOINT. The base image runs s6-overlay
# (/init as PID 1); overriding the entrypoint breaks init and privilege drop.
# Run this once after container creation, or on every start from your harness
# manager (HSM) startup hook — whichever fits your operational model.

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────
DATA_DIR="${HERMES_HOME:-${1:-/opt/data}}"

# {{PLACEHOLDER: Set the canonical Git URL for your package repo.}}
REPO_URL="${PACKAGE_REPO_URL:-https://github.com/{{GITHUB_ORG}}/{{PACKAGE_REPO}}.git}"

# {{PLACEHOLDER: Set the directory name the package clones into under DATA_DIR.}}
PACKAGE_DIR="{{PACKAGE_DIR}}"

# {{PLACEHOLDER: Set the Hermes skill name (used as the skills/ subdirectory name).}}
SKILL_NAME="{{SKILL_NAME}}"

# {{PLACEHOLDER: Set the Hermes plugin name (must match the key in config.yaml).}}
PLUGIN_NAME="{{PLUGIN_NAME}}"

PKG_DIR="$DATA_DIR/$PACKAGE_DIR"

echo "[${PACKAGE_DIR}-setup] data dir: $DATA_DIR"

# ── 1. Code ───────────────────────────────────────────────────────────
# Clone or fast-forward the shared package. A fast-forward pull never clobbers
# your private data (it lives outside tracked files; see CONTRIBUTING.md).
if [ -d "$PKG_DIR/.git" ]; then
  echo "[${PACKAGE_DIR}-setup] updating $PACKAGE_DIR (git pull --ff-only)…"
  git -C "$PKG_DIR" pull --ff-only \
    || echo "[${PACKAGE_DIR}-setup] pull skipped (diverged or offline) — left as-is"
else
  echo "[${PACKAGE_DIR}-setup] cloning $PACKAGE_DIR → $PKG_DIR"
  git clone "$REPO_URL" "$PKG_DIR"
fi

# ── 2. Soul ───────────────────────────────────────────────────────────
# Seed from the template ONLY if no SOUL.md exists yet. Once you customize it,
# this script will never touch it again. Your soul is yours.
if [ ! -f "$DATA_DIR/SOUL.md" ]; then
  cp "$PKG_DIR/docker/SOUL.template.md" "$DATA_DIR/SOUL.md"
  echo "[${PACKAGE_DIR}-setup] seeded SOUL.md from template — customize it; it is yours"
else
  echo "[${PACKAGE_DIR}-setup] SOUL.md already exists — left untouched"
fi

# ── 3. Skill ──────────────────────────────────────────────────────────
# Symlink the SHARED package skill so it auto-updates on every git pull.
# If you need instance-specific skill content, add it as a SEPARATE skill file
# under skills/ — never edit the shared file in place, or a future pull will
# conflict.
SKILL_DIR="$DATA_DIR/skills/$SKILL_NAME"
mkdir -p "$SKILL_DIR"
if [ ! -e "$SKILL_DIR/SKILL.md" ]; then
  ln -s "../../${PACKAGE_DIR}/hermes-skill/SKILL.md" "$SKILL_DIR/SKILL.md"
  echo "[${PACKAGE_DIR}-setup] linked shared skill at skills/$SKILL_NAME (auto-updates on pull)"
else
  echo "[${PACKAGE_DIR}-setup] skills/$SKILL_NAME/SKILL.md exists — left untouched"
fi

# ── 4. Plugin ─────────────────────────────────────────────────────────
# Plugin enablement lives in config.yaml. This script does not edit it
# automatically — your harness manager owns the config. We check and report.
CFG="$DATA_DIR/config.yaml"
if [ -f "$CFG" ] && grep -qE "^[[:space:]]*-[[:space:]]*${PLUGIN_NAME}[[:space:]]*$" "$CFG"; then
  echo "[${PACKAGE_DIR}-setup] ${PLUGIN_NAME} plugin already enabled in config.yaml ✓"
else
  echo "[${PACKAGE_DIR}-setup] ACTION: enable the '${PLUGIN_NAME}' plugin."
  echo "    Add it under plugins.enabled in config.yaml,"
  echo "    or enable it via your harness manager (HSM)."
fi

echo "[${PACKAGE_DIR}-setup] done."
echo "[${PACKAGE_DIR}-setup] Domain binaries come from the image (docker/Dockerfile);"
echo "[${PACKAGE_DIR}-setup] code/skill/soul live in $DATA_DIR and update with git pull."
