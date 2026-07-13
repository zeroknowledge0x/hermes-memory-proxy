#!/usr/bin/env bash
# scripts/sync_public.sh — one-way mirror of PUBLIC-FACING code/docs from the
# private working repo (memory-proxy) to the public etalase (hermes-memory-proxy).
#
# WHY: keep the OSS "etalase" in sync with the real brain without leaking
# private notes (DECISIONS.md, PROGRESS.md, identity/SOUL.md, identity/USER.md)
# or runtime logs.
#
# USAGE:  bash scripts/sync_public.sh        # dry-run (shows what would copy)
#         bash scripts/sync_public.sh --push # copy + commit + push public repo
#
# Safe: never touches private-only files; never overwrites public DECISIONS/PROGRESS
# (those are generated public-friendly notes, not the private brain's notes).

set -euo pipefail

PRIVATE="${PRIVATE_REPO:-/root/memory-proxy}"
PUBLIC="${PUBLIC_REPO:-/root/hermes-memory-proxy}"
PUSH="${1:-}"

# Files/dirs that are PRIVATE-ONLY — never copy to public.
EXCLUDE=(
  "DECISIONS.md" "ARCHITECTURE_FUTURE.md" "DEPLOY.md"
  "IMPLEMENTATION_PLAN.md" "docs/phase0-findings.md"
  "identity/SOUL.md" "identity/USER.md"
  "src/logs" "scripts/reembed.py"
)

# Files that are PUBLIC-ONLY — never overwrite from private.
# (Public docs are English/etalase; private docs are Indonesian/internal notes.
#  If a public doc also lives in the private repo, list it here so the curated
#  English version is never clobbered by the Indonesian source.)
PUBLIC_ONLY=(
  "CONCEPTS.md" "FOR_AGENT.md" "LICENSE" "CONTRIBUTING.md"
  "CHANGELOG.md" "ARCHITECTURE.md"
  "examples" "Dockerfile" "README.md"
  "hermes-skill" "hermes-plugin" "identity/TEMPLATE" "docs"
  "scripts/backup_to_github.sh"
)

copy_if_public() {
  local rel="$1"
  # skip private-only
  for ex in "${EXCLUDE[@]}"; do
    [[ "$rel" == "$ex"* ]] && return
  done
  # skip public-only (don't clobber curated public docs)
  for po in "${PUBLIC_ONLY[@]}"; do
    [[ "$rel" == "$po"* ]] && return
  done
  echo "  sync: $rel"
  mkdir -p "$PUBLIC/$(dirname "$rel")"
  cp "$PRIVATE/$rel" "$PUBLIC/$rel"
}

echo "== Mirroring code + shared docs private -> public =="
# Core source
while IFS= read -r f; do copy_if_public "$f"; done < <(
  cd "$PRIVATE" && git ls-files \
    | grep -E '^src/|^tests/|^migrations/|^scripts/(backup|backup_to_github|dedupe_memories|merge_to_single_user|memory-proxy\.service)\.py$' \
    | grep -vE 'src/logs|reembed'
)
# Shared docs (not in EXCLUDE/PUBLIC_ONLY)
for d in ARCHITECTURE.md docker-compose.yml .env.example; do
  [ -f "$PRIVATE/$d" ] && copy_if_public "$d"
done
# config package (canonical location)
copy_if_public "src/memory_proxy/config/settings.py"

if [[ "$PUSH" == "--push" ]]; then
  cd "$PUBLIC"
  if [[ -n "$(git status --porcelain)" ]]; then
    git add -A
    git -c user.email='zeroknowledge0x@users.noreply.github.com' \
        -c user.name='zeroknowledge0x' \
        commit -m "chore: sync public-facing code/docs from private brain"
    git push origin main
    echo "== PUSHED to public =="
  else
    echo "== nothing to push (already in sync) =="
  fi
else
  echo "== dry-run only (no changes written). Re-run with --push to apply. =="
fi
