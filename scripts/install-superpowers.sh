#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
upstream_url="https://github.com/obra/superpowers.git"
upstream_commit="22f0b463e7a5e579904dd6211a520321035526f7"
vendor_dir="$project_root/.agents/vendor/superpowers"
skill_root="$project_root/.agents/skills"

mkdir -p "$project_root/.agents/vendor" "$skill_root"
if [[ ! -d "$vendor_dir/.git" ]]; then
  if [[ -e "$vendor_dir" ]]; then
    echo "Refusing to overwrite existing non-repository path: $vendor_dir" >&2
    exit 1
  fi
  git clone --depth 1 "$upstream_url" "$vendor_dir"
fi

if [[ "$(git -C "$vendor_dir" remote get-url origin)" != "$upstream_url" ]]; then
  echo "Superpowers origin differs from the expected upstream; not changing it." >&2
  exit 1
fi
if [[ -n "$(git -C "$vendor_dir" status --porcelain)" ]]; then
  echo "Superpowers checkout has local modifications; not replacing them." >&2
  exit 1
fi
if ! git -C "$vendor_dir" cat-file -e "$upstream_commit^{commit}" 2>/dev/null; then
  git -C "$vendor_dir" fetch --depth 1 origin "$upstream_commit"
fi
git -C "$vendor_dir" checkout --detach "$upstream_commit"

skill_count=0
for skill_file in "$vendor_dir"/skills/*/SKILL.md; do
  skill_name="$(basename -- "$(dirname -- "$skill_file")")"
  link_path="$skill_root/superpowers-$skill_name"
  link_target="../vendor/superpowers/skills/$skill_name"
  if [[ -e "$link_path" || -L "$link_path" ]]; then
    if [[ ! -L "$link_path" || "$(readlink -- "$link_path")" != "$link_target" ]]; then
      echo "Refusing to replace existing skill: $link_path" >&2
      exit 1
    fi
  else
    ln -s -- "$link_target" "$link_path"
  fi
  [[ -r "$link_path/SKILL.md" ]]
  skill_count=$((skill_count + 1))
done
printf 'Installed %s project skills at commit %s\n' "$skill_count" "$upstream_commit"
