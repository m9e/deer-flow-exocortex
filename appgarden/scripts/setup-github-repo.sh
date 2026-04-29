#!/usr/bin/env bash
# Bootstrap GitHub repo with topics, develop branch, branch naming rules, and branch protection.
# Requirements: gh CLI authenticated with repo admin rights, yq for config file parsing.
#
# Usage:
#   ./scripts/setup-github-repo.sh                    # Interactive mode (prompts with defaults)
#   CONFIG_FILE=.github/repo-setup.yml ./scripts/...  # Non-interactive from config
#   OWNER=org REPO=name ./scripts/...                 # Override repo detection
#
# Config file location (checked in order):
#   1. $CONFIG_FILE env var
#   2. .github/repo-setup.yml
#   3. Defaults (interactive prompts if TTY available)

set -euo pipefail

# Disable gh CLI pagination for non-interactive use
export GH_PAGER=""
export PAGER=""

# =============================================================================
# Defaults
# =============================================================================
DEFAULT_TOPICS="extensions"
DEFAULT_BRANCH="main"
DEFAULT_CREATE_DEVELOP="true"
DEFAULT_BRANCH_NAMING_ENABLED="true"
DEFAULT_BRANCH_NAMING_PATTERN='^(main|develop|feature/.+|fix/.+|hotfix/.+|release/.+|chore/.+|docs/.+|refactor/.+|ci/.+|build/.+|test/.+|perf/.+|deps/.+|dependabot/.+|renovate/.+)$'
DEFAULT_PROTECTION_ENABLED="true"
DEFAULT_PROTECTED_BRANCHES="main develop"
DEFAULT_REQUIRE_PR_REVIEWS="true"
DEFAULT_REQUIRED_APPROVERS="1"
DEFAULT_DISMISS_STALE_REVIEWS="true"
DEFAULT_REQUIRE_STATUS_CHECKS="true"
DEFAULT_REQUIRE_UP_TO_DATE="true"
DEFAULT_BLOCK_FORCE_PUSH="true"
DEFAULT_BLOCK_DELETIONS="true"
DEFAULT_REQUIRE_CONVERSATION_RESOLUTION="false"
DEFAULT_REQUIRE_SIGNED_COMMITS="false"
DEFAULT_REQUIRE_LINEAR_HISTORY="false"

# =============================================================================
# Helper Functions
# =============================================================================
info()  { echo "[info] $*"; }
warn()  { echo "[warn] $*" >&2; }
error() { echo "[error] $*" >&2; exit 1; }
success() { echo "[success] $*"; }

# Check if running interactively
is_interactive() {
  [[ -t 0 && -t 1 ]]
}

# Prompt for yes/no with default
prompt_bool() {
  local prompt="$1"
  local default="$2"
  local result

  if ! is_interactive; then
    echo "$default"
    return
  fi

  local hint="[Y/n]"
  [[ "$default" == "false" ]] && hint="[y/N]"

  read -r -p "$prompt $hint: " result </dev/tty
  result="${result:-$default}"

  case "${result,,}" in
    y|yes|true|1) echo "true" ;;
    n|no|false|0) echo "false" ;;
    *) echo "$default" ;;
  esac
}

# Prompt for value with default
prompt_value() {
  local prompt="$1"
  local default="$2"
  local result

  if ! is_interactive; then
    echo "$default"
    return
  fi

  read -r -p "$prompt [$default]: " result </dev/tty
  echo "${result:-$default}"
}

# Check if yq is available
has_yq() {
  command -v yq >/dev/null 2>&1
}

# Read value from YAML config file
read_config() {
  local key="$1"
  local default="$2"
  local config_file="${CONFIG_FILE:-}"

  if [[ -z "$config_file" ]]; then
    echo "$default"
    return
  fi

  if ! has_yq; then
    warn "yq not found, cannot parse config file"
    echo "$default"
    return
  fi

  local value
  value=$(yq -r ".$key // \"\"" "$config_file" 2>/dev/null || echo "")

  if [[ -z "$value" || "$value" == "null" ]]; then
    echo "$default"
  else
    echo "$value"
  fi
}

# Read array from YAML config file as space-separated string
read_config_array() {
  local key="$1"
  local default="$2"
  local config_file="${CONFIG_FILE:-}"

  if [[ -z "$config_file" ]]; then
    echo "$default"
    return
  fi

  if ! has_yq; then
    echo "$default"
    return
  fi

  local value
  value=$(yq -r ".$key // [] | .[]" "$config_file" 2>/dev/null | tr '\n' ' ' | sed 's/ $//' || echo "")

  if [[ -z "$value" ]]; then
    echo "$default"
  else
    echo "$value"
  fi
}

# =============================================================================
# Repository Detection
# =============================================================================
detect_repo() {
  OWNER=${OWNER:-}
  REPO=${REPO:-}

  if [[ -z "$OWNER" || -z "$REPO" ]]; then
    local remote_url
    remote_url=$(git config --get remote.origin.url 2>/dev/null || true)
    remote_url=${remote_url%.git}
    if [[ -n "$remote_url" && "$remote_url" =~ github.com[:/]{1}([^/]+)/([^/]+)$ ]]; then
      OWNER=${OWNER:-"${BASH_REMATCH[1]}"}
      REPO=${REPO:-"${BASH_REMATCH[2]}"}
    fi
  fi

  if [[ -z "$OWNER" || -z "$REPO" ]]; then
    error "Cannot detect repository. Set OWNER and REPO env vars or configure git remote 'origin'."
  fi

  FULL_REPO="$OWNER/$REPO"
}

# =============================================================================
# Configuration Loading
# =============================================================================
load_config() {
  # Find config file
  if [[ -z "${CONFIG_FILE:-}" ]]; then
    if [[ -f ".github/repo-setup.yml" ]]; then
      CONFIG_FILE=".github/repo-setup.yml"
      info "Using config file: $CONFIG_FILE"
    elif [[ -f ".github/repo-setup.yaml" ]]; then
      CONFIG_FILE=".github/repo-setup.yaml"
      info "Using config file: $CONFIG_FILE"
    fi
  elif [[ -n "${CONFIG_FILE:-}" && ! -f "$CONFIG_FILE" ]]; then
    error "Config file not found: $CONFIG_FILE"
  fi

  # Load or prompt for each setting
  if [[ -n "${CONFIG_FILE:-}" ]]; then
    info "Loading configuration from $CONFIG_FILE"
    TOPICS=$(read_config_array "topics" "$DEFAULT_TOPICS")
    DEFAULT_BRANCH_NAME=$(read_config "default_branch" "$DEFAULT_BRANCH")
    CREATE_DEVELOP=$(read_config "create_develop" "$DEFAULT_CREATE_DEVELOP")
    BRANCH_NAMING_ENABLED=$(read_config "branch_naming_enabled" "$DEFAULT_BRANCH_NAMING_ENABLED")
    BRANCH_NAMING_PATTERN=$(read_config "branch_naming_pattern" "$DEFAULT_BRANCH_NAMING_PATTERN")
    PROTECTION_ENABLED=$(read_config "protection_enabled" "$DEFAULT_PROTECTION_ENABLED")
    PROTECTED_BRANCHES=$(read_config_array "protected_branches" "$DEFAULT_PROTECTED_BRANCHES")
    REQUIRE_PR_REVIEWS=$(read_config "require_pr_reviews" "$DEFAULT_REQUIRE_PR_REVIEWS")
    REQUIRED_APPROVERS=$(read_config "required_approvers" "$DEFAULT_REQUIRED_APPROVERS")
    DISMISS_STALE_REVIEWS=$(read_config "dismiss_stale_reviews" "$DEFAULT_DISMISS_STALE_REVIEWS")
    REQUIRE_STATUS_CHECKS=$(read_config "require_status_checks" "$DEFAULT_REQUIRE_STATUS_CHECKS")
    REQUIRE_UP_TO_DATE=$(read_config "require_up_to_date" "$DEFAULT_REQUIRE_UP_TO_DATE")
    BLOCK_FORCE_PUSH=$(read_config "block_force_push" "$DEFAULT_BLOCK_FORCE_PUSH")
    BLOCK_DELETIONS=$(read_config "block_deletions" "$DEFAULT_BLOCK_DELETIONS")
    REQUIRE_CONVERSATION_RESOLUTION=$(read_config "require_conversation_resolution" "$DEFAULT_REQUIRE_CONVERSATION_RESOLUTION")
    REQUIRE_SIGNED_COMMITS=$(read_config "require_signed_commits" "$DEFAULT_REQUIRE_SIGNED_COMMITS")
    REQUIRE_LINEAR_HISTORY=$(read_config "require_linear_history" "$DEFAULT_REQUIRE_LINEAR_HISTORY")
  else
    if is_interactive; then
      echo ""
      echo "=== GitHub Repository Setup ==="
      echo "Repository: $FULL_REPO"
      echo "Press Enter to accept defaults, or type a new value."
      echo ""
    fi

    # Topics
    TOPICS=$(prompt_value "Topics (space-separated)" "$DEFAULT_TOPICS")

    # Branches
    DEFAULT_BRANCH_NAME=$(prompt_value "Default branch" "$DEFAULT_BRANCH")
    CREATE_DEVELOP=$(prompt_bool "Create develop branch?" "$DEFAULT_CREATE_DEVELOP")

    # Branch naming
    BRANCH_NAMING_ENABLED=$(prompt_bool "Enable branch naming rules?" "$DEFAULT_BRANCH_NAMING_ENABLED")
    if [[ "$BRANCH_NAMING_ENABLED" == "true" ]]; then
      BRANCH_NAMING_PATTERN=$(prompt_value "Branch naming pattern (regex)" "$DEFAULT_BRANCH_NAMING_PATTERN")
    else
      BRANCH_NAMING_PATTERN="$DEFAULT_BRANCH_NAMING_PATTERN"
    fi

    # Branch protection
    PROTECTION_ENABLED=$(prompt_bool "Enable branch protection?" "$DEFAULT_PROTECTION_ENABLED")
    if [[ "$PROTECTION_ENABLED" == "true" ]]; then
      PROTECTED_BRANCHES=$(prompt_value "Branches to protect (space-separated)" "$DEFAULT_PROTECTED_BRANCHES")
      REQUIRE_PR_REVIEWS=$(prompt_bool "Require pull request reviews?" "$DEFAULT_REQUIRE_PR_REVIEWS")
      if [[ "$REQUIRE_PR_REVIEWS" == "true" ]]; then
        REQUIRED_APPROVERS=$(prompt_value "Required approvers" "$DEFAULT_REQUIRED_APPROVERS")
        DISMISS_STALE_REVIEWS=$(prompt_bool "Dismiss stale reviews on new commits?" "$DEFAULT_DISMISS_STALE_REVIEWS")
      else
        REQUIRED_APPROVERS="$DEFAULT_REQUIRED_APPROVERS"
        DISMISS_STALE_REVIEWS="$DEFAULT_DISMISS_STALE_REVIEWS"
      fi
      REQUIRE_STATUS_CHECKS=$(prompt_bool "Require status checks to pass?" "$DEFAULT_REQUIRE_STATUS_CHECKS")
      if [[ "$REQUIRE_STATUS_CHECKS" == "true" ]]; then
        REQUIRE_UP_TO_DATE=$(prompt_bool "Require branch to be up-to-date before merge?" "$DEFAULT_REQUIRE_UP_TO_DATE")
      else
        REQUIRE_UP_TO_DATE="$DEFAULT_REQUIRE_UP_TO_DATE"
      fi
      BLOCK_FORCE_PUSH=$(prompt_bool "Block force pushes?" "$DEFAULT_BLOCK_FORCE_PUSH")
      BLOCK_DELETIONS=$(prompt_bool "Block branch deletions?" "$DEFAULT_BLOCK_DELETIONS")
      REQUIRE_CONVERSATION_RESOLUTION=$(prompt_bool "Require conversation resolution before merge?" "$DEFAULT_REQUIRE_CONVERSATION_RESOLUTION")
      REQUIRE_SIGNED_COMMITS=$(prompt_bool "Require signed commits?" "$DEFAULT_REQUIRE_SIGNED_COMMITS")
      REQUIRE_LINEAR_HISTORY=$(prompt_bool "Require linear history (no merge commits)?" "$DEFAULT_REQUIRE_LINEAR_HISTORY")
    else
      PROTECTED_BRANCHES="$DEFAULT_PROTECTED_BRANCHES"
      REQUIRE_PR_REVIEWS="$DEFAULT_REQUIRE_PR_REVIEWS"
      REQUIRED_APPROVERS="$DEFAULT_REQUIRED_APPROVERS"
      DISMISS_STALE_REVIEWS="$DEFAULT_DISMISS_STALE_REVIEWS"
      REQUIRE_STATUS_CHECKS="$DEFAULT_REQUIRE_STATUS_CHECKS"
      REQUIRE_UP_TO_DATE="$DEFAULT_REQUIRE_UP_TO_DATE"
      BLOCK_FORCE_PUSH="$DEFAULT_BLOCK_FORCE_PUSH"
      BLOCK_DELETIONS="$DEFAULT_BLOCK_DELETIONS"
      REQUIRE_CONVERSATION_RESOLUTION="$DEFAULT_REQUIRE_CONVERSATION_RESOLUTION"
      REQUIRE_SIGNED_COMMITS="$DEFAULT_REQUIRE_SIGNED_COMMITS"
      REQUIRE_LINEAR_HISTORY="$DEFAULT_REQUIRE_LINEAR_HISTORY"
    fi
  fi
}

# =============================================================================
# Setup Functions
# =============================================================================
setup_topics() {
  info "Adding topics: $TOPICS"
  for topic in $TOPICS; do
    gh repo edit "$FULL_REPO" --add-topic "$topic" 2>/dev/null || true
  done
}

setup_develop_branch() {
  if [[ "$CREATE_DEVELOP" != "true" ]]; then
    info "Skipping develop branch creation"
    return
  fi

  info "Ensuring develop branch exists"
  local main_sha
  main_sha=$(gh api "repos/$FULL_REPO/git/refs/heads/$DEFAULT_BRANCH_NAME" --jq .object.sha 2>/dev/null || true)

  if [[ -z "$main_sha" ]]; then
    warn "Could not get SHA for $DEFAULT_BRANCH_NAME - is the repo initialized with commits?"
    return
  fi

  if gh api "repos/$FULL_REPO/git/refs/heads/develop" --jq .object.sha >/dev/null 2>&1; then
    info "develop branch already exists"
  else
    gh api -X POST "repos/$FULL_REPO/git/refs" -f ref="refs/heads/develop" -f sha="$main_sha" >/dev/null
    info "Created develop branch from $DEFAULT_BRANCH_NAME"
  fi
}

setup_branch_naming() {
  if [[ "$BRANCH_NAMING_ENABLED" != "true" ]]; then
    info "Skipping branch naming rules"
    return
  fi

  info "Configuring branch naming rules"

  # Check if ruleset already exists
  local existing_ruleset
  existing_ruleset=$(gh api "repos/$FULL_REPO/rulesets" --jq '.[] | select(.name == "branch-name-policy") | .id' 2>/dev/null || true)

  if [[ -n "$existing_ruleset" ]]; then
    info "Branch naming ruleset already exists (id: $existing_ruleset), updating..."
    gh api -X PUT \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "repos/$FULL_REPO/rulesets/$existing_ruleset" \
      --input - >/dev/null <<JSON
{
  "name": "branch-name-policy",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["~ALL"],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "branch_name_pattern",
      "parameters": {
        "name": "Allowed branch prefixes",
        "operator": "regex",
        "pattern": "${BRANCH_NAMING_PATTERN}"
      }
    }
  ]
}
JSON
    info "Updated branch naming ruleset"
  else
    gh api -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "repos/$FULL_REPO/rulesets" \
      --input - >/dev/null <<JSON
{
  "name": "branch-name-policy",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["~ALL"],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "branch_name_pattern",
      "parameters": {
        "name": "Allowed branch prefixes",
        "operator": "regex",
        "pattern": "${BRANCH_NAMING_PATTERN}"
      }
    }
  ]
}
JSON
    info "Created branch naming ruleset"
  fi
}

setup_branch_protection() {
  if [[ "$PROTECTION_ENABLED" != "true" ]]; then
    info "Skipping branch protection"
    return
  fi

  info "Configuring branch protection"

  for branch in $PROTECTED_BRANCHES; do
    info "Setting up protection for branch: $branch"

    # Check if branch exists
    if ! gh api "repos/$FULL_REPO/branches/$branch" >/dev/null 2>&1; then
      warn "Branch '$branch' does not exist, skipping protection"
      continue
    fi

    # Build the protection payload
    local required_reviews_json="null"
    if [[ "$REQUIRE_PR_REVIEWS" == "true" ]]; then
      required_reviews_json=$(cat <<JSON
{
  "required_approving_review_count": $REQUIRED_APPROVERS,
  "dismiss_stale_reviews": $DISMISS_STALE_REVIEWS,
  "require_code_owner_reviews": false,
  "require_last_push_approval": false
}
JSON
)
    fi

    local required_checks_json="null"
    if [[ "$REQUIRE_STATUS_CHECKS" == "true" ]]; then
      required_checks_json=$(cat <<JSON
{
  "strict": $REQUIRE_UP_TO_DATE,
  "checks": []
}
JSON
)
    fi

    # Apply branch protection
    gh api -X PUT \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "repos/$FULL_REPO/branches/$branch/protection" \
      --input - >/dev/null <<JSON
{
  "required_status_checks": $required_checks_json,
  "enforce_admins": false,
  "required_pull_request_reviews": $required_reviews_json,
  "restrictions": null,
  "required_linear_history": $REQUIRE_LINEAR_HISTORY,
  "allow_force_pushes": $([ "$BLOCK_FORCE_PUSH" == "true" ] && echo "false" || echo "true"),
  "allow_deletions": $([ "$BLOCK_DELETIONS" == "true" ] && echo "false" || echo "true"),
  "required_conversation_resolution": $REQUIRE_CONVERSATION_RESOLUTION,
  "required_signatures": $REQUIRE_SIGNED_COMMITS
}
JSON

    info "Branch protection configured for: $branch"
  done
}

print_summary() {
  echo ""
  echo "=== Configuration Summary ==="
  echo "Repository:        $FULL_REPO"
  echo "Topics:            $TOPICS"
  echo "Default branch:    $DEFAULT_BRANCH_NAME"
  echo "Create develop:    $CREATE_DEVELOP"
  echo ""
  echo "Branch naming:     $BRANCH_NAMING_ENABLED"
  if [[ "$BRANCH_NAMING_ENABLED" == "true" ]]; then
    echo "  Pattern:         ${BRANCH_NAMING_PATTERN:0:50}..."
  fi
  echo ""
  echo "Branch protection: $PROTECTION_ENABLED"
  if [[ "$PROTECTION_ENABLED" == "true" ]]; then
    echo "  Branches:        $PROTECTED_BRANCHES"
    echo "  Require PRs:     $REQUIRE_PR_REVIEWS (approvers: $REQUIRED_APPROVERS)"
    echo "  Dismiss stale:   $DISMISS_STALE_REVIEWS"
    echo "  Status checks:   $REQUIRE_STATUS_CHECKS (up-to-date: $REQUIRE_UP_TO_DATE)"
    echo "  Block force:     $BLOCK_FORCE_PUSH"
    echo "  Block delete:    $BLOCK_DELETIONS"
    echo "  Conversations:   $REQUIRE_CONVERSATION_RESOLUTION"
    echo "  Signed commits:  $REQUIRE_SIGNED_COMMITS"
    echo "  Linear history:  $REQUIRE_LINEAR_HISTORY"
  fi
  echo ""
}

# =============================================================================
# Main
# =============================================================================
main() {
  detect_repo
  load_config
  print_summary

  # Confirm if interactive
  if is_interactive && [[ -z "${CONFIG_FILE:-}" ]]; then
    local confirm
    read -r -p "Proceed with setup? [Y/n]: " confirm </dev/tty
    confirm="${confirm:-y}"
    if [[ "${confirm,,}" != "y" && "${confirm,,}" != "yes" ]]; then
      echo "Aborted."
      exit 0
    fi
    echo ""
  fi

  setup_topics
  setup_develop_branch
  setup_branch_naming
  setup_branch_protection

  success "Repository $FULL_REPO configured successfully!"
}

main "$@"
