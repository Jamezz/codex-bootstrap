#!/usr/bin/env bash
set -euo pipefail

readonly DEFAULT_REPO="https://github.com/Jamezz/codex-bootstrap.git"
readonly DEFAULT_REF="main"
readonly DEFAULT_TEMPLATE="java-gradle-cli"
readonly DEFAULT_PAGES_URL="https://jamezz.github.io/codex-bootstrap"

project_slug=""
template="$DEFAULT_TEMPLATE"
package_name=""
repo_url="$DEFAULT_REPO"
repo_ref="$DEFAULT_REF"
target_parent="$PWD"
force=0
dry_run=0
list_templates=0
templates_file=""
tmp_dir=""

usage() {
  cat <<'USAGE'
Codex Bootstrap installer

Usage:
  install.sh <project-slug> [options]
  install.sh --list-templates [--templates-file path]

Options:
  --template <id>          Template id to materialize. Defaults to java-gradle-cli.
  --package <name>         Java package name. Java templates derive com.example.<slug> when omitted.
  --repo <url>             Bootstrap catalog Git URL. Defaults to https://github.com/Jamezz/codex-bootstrap.git.
  --ref <ref>              Git ref to install from. Defaults to main.
  --dir <path>             Parent directory for the generated project. Defaults to the current directory.
  --force                  Replace an existing target project directory.
  --dry-run                Print the install plan without cloning or changing files.
  --list-templates         List templates from GitHub Pages or --templates-file.
  --templates-file <path>  Read template metadata from a local templates.json file.
  --help                   Show this help.

Examples:
  curl -fsSL https://jamezz.github.io/codex-bootstrap/install.sh | bash -s -- my-app --template python-uv-cli
  curl -fsSL https://jamezz.github.io/codex-bootstrap/install.sh | bash -s -- my-app --template java-gradle-cli --package com.acme.myapp
USAGE
}

die() {
  printf 'codex-bootstrap installer: %s\n' "$*" >&2
  exit 2
}

cleanup() {
  if [ -n "$tmp_dir" ] && [ -d "$tmp_dir" ]; then
    rm -rf -- "$tmp_dir"
  fi
}

trap cleanup EXIT INT TERM

while [ "$#" -gt 0 ]; do
  case "$1" in
    --template)
      [ "$#" -ge 2 ] || die "--template requires a value"
      template=$2
      shift 2
      ;;
    --package)
      [ "$#" -ge 2 ] || die "--package requires a value"
      package_name=$2
      shift 2
      ;;
    --repo)
      [ "$#" -ge 2 ] || die "--repo requires a value"
      repo_url=$2
      shift 2
      ;;
    --ref)
      [ "$#" -ge 2 ] || die "--ref requires a value"
      repo_ref=$2
      shift 2
      ;;
    --dir)
      [ "$#" -ge 2 ] || die "--dir requires a value"
      target_parent=$2
      shift 2
      ;;
    --force)
      force=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --list-templates)
      list_templates=1
      shift
      ;;
    --templates-file)
      [ "$#" -ge 2 ] || die "--templates-file requires a value"
      templates_file=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      if [ -n "$project_slug" ]; then
        die "unexpected argument: $1"
      fi
      project_slug=$1
      shift
      ;;
  esac
done

if [ "$#" -gt 0 ]; then
  if [ -n "$project_slug" ]; then
    die "unexpected argument: $1"
  fi
  project_slug=$1
  shift
fi

if [ "$#" -gt 0 ]; then
  die "unexpected argument: $1"
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required"
}

validate_project_slug() {
  case "$1" in
    ""|-*|*-|*--*|[0-9]*|*_*|*[!abcdefghijklmnopqrstuvwxyz0123456789-]*)
      die "project slug must be lowercase hyphenated, like my-app"
      ;;
  esac
}

validate_java_package() {
  python3 - "$1" <<'PY'
import keyword
import re
import sys

value = sys.argv[1]
parts = value.split(".")
java_keywords = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while",
}
valid = (
    len(parts) >= 2
    and all(re.fullmatch(r"[a-z][a-z0-9_]*", part) for part in parts)
    and not any(part in java_keywords or keyword.iskeyword(part) for part in parts)
)
if not valid:
    raise SystemExit(1)
PY
}

derive_java_package() {
  local segment
  segment=${project_slug//-/}
  local derived="com.example.$segment"
  if ! validate_java_package "$derived"; then
    die "cannot derive a valid Java package from '$project_slug'; pass --package"
  fi
  printf '%s\n' "$derived"
}

list_template_metadata() {
  require_command python3
  if [ -n "$templates_file" ]; then
    [ -f "$templates_file" ] || die "templates file not found: $templates_file"
    python3 - "$templates_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
for template in payload.get("templates", []):
    required = ", ".join(template.get("requiredInputs", []))
    suffix = f" (requires: {required})" if required else ""
    print(f"{template['id']}: {template['displayName']}{suffix}")
PY
    return
  fi

  require_command curl
  payload=$(curl -fsSL "${CODEX_BOOTSTRAP_PAGES_URL:-$DEFAULT_PAGES_URL}/templates.json")
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
for template in payload.get("templates", []):
    required = ", ".join(template.get("requiredInputs", []))
    suffix = f" (requires: {required})" if required else ""
    print("{}: {}{}".format(template["id"], template["displayName"], suffix))
' <<< "$payload"
}

if [ "$list_templates" -eq 1 ]; then
  list_template_metadata
  exit 0
fi

[ -n "$project_slug" ] || die "missing required project slug"
validate_project_slug "$project_slug"

case "$template" in
  java-gradle-cli|python-uv-cli|typescript-bun-cli)
    ;;
  *)
    die "unknown template '$template'; run --list-templates"
    ;;
esac

if [ "$template" = "java-gradle-cli" ]; then
  if [ -z "$package_name" ]; then
    package_name=$(derive_java_package)
  elif ! validate_java_package "$package_name"; then
    die "invalid Java package: $package_name"
  fi
elif [ -n "$package_name" ]; then
  die "--package is only supported by java-gradle-cli"
fi

if [ "$dry_run" -eq 1 ]; then
  case "$target_parent" in
    /*)
      ;;
    *)
      target_parent="$PWD/$target_parent"
      ;;
  esac
else
  mkdir -p "$target_parent" || die "cannot create target parent: $target_parent"
  target_parent=$(cd "$target_parent" 2>/dev/null && pwd) || die "target parent does not exist: $target_parent"
fi
target_dir="$target_parent/$project_slug"

if [ "$dry_run" -eq 1 ]; then
  printf 'Install plan:\n'
  printf '  repo: %s\n' "$repo_url"
  printf '  ref: %s\n' "$repo_ref"
  printf '  template: %s\n' "$template"
  printf '  project: %s\n' "$project_slug"
  printf '  target: %s\n' "$target_dir"
  if [ "$template" = "java-gradle-cli" ]; then
    printf '  package: %s\n' "$package_name"
  fi
  if [ -e "$target_dir" ] && [ "$force" -eq 0 ]; then
    printf '  target-status: exists and would be refused without --force\n'
  fi
  exit 0
fi

require_command git
require_command python3

if [ -e "$target_dir" ] && [ "$force" -eq 0 ]; then
  die "target already exists: $target_dir; pass --force to replace it"
fi

tmp_dir=$(mktemp -d "$target_parent/.codex-bootstrap.XXXXXX")
git clone --depth 1 "$repo_url" "$tmp_dir"
if ! git -C "$tmp_dir" checkout --detach "$repo_ref" >/dev/null 2>&1; then
  git -C "$tmp_dir" fetch --depth 1 origin "$repo_ref"
  git -C "$tmp_dir" checkout --detach FETCH_HEAD
fi

bootstrap_args=(
  "./bootstrap"
  "--template" "$template"
  "--name" "$project_slug"
  "--yes"
)
if [ "$template" = "java-gradle-cli" ]; then
  bootstrap_args+=("--package" "$package_name")
fi

(
  cd "$tmp_dir"
  "${bootstrap_args[@]}"
)

if [ -e "$target_dir" ]; then
  rm -rf -- "$target_dir"
fi
mv "$tmp_dir" "$target_dir"
tmp_dir=""

printf 'Created %s from %s (%s).\n' "$target_dir" "$template" "$repo_ref"
