#!/bin/bash
#
# Interactive Demo Script for Kamiwaza Extensions Lifecycle
#
# This script demonstrates the complete lifecycle of App Garden apps and Tool Shed tools
# with narration and pauses for discussion.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'

# Demo artifacts to clean up
DEMO_ARTIFACTS=()

# Cleanup function
cleanup() {
    echo -e "\n${CYAN}Cleaning up demo artifacts...${NC}"
    for artifact in "${DEMO_ARTIFACTS[@]}"; do
        if [[ -e "$artifact" ]]; then
            rm -rf "$artifact"
            echo "  Removed: $artifact"
        fi
    done
}

trap cleanup EXIT

# Helper functions
pause_for_discussion() {
    echo -e "\n${MAGENTA}${BOLD}Press Enter to continue...${NC}"
    read -r
}

narrate() {
    echo -e "\n${CYAN}${BOLD}📢 $1${NC}"
}

show_command() {
    echo -e "\n${YELLOW}Running: ${GREEN}$1${NC}"
}

demo_step() {
    local step_name=$1
    echo -e "\n${BLUE}${BOLD}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}${BOLD}DEMO STEP: $step_name${NC}"
    echo -e "${BLUE}${BOLD}═══════════════════════════════════════════════════${NC}"
}

# Main demo
main() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║       KAMIWAZA EXTENSIONS LIFECYCLE DEMO                 ║"
    echo "║                                                          ║"
    echo "║  Demonstrating App Garden Apps & Tool Shed Tools         ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    narrate "Welcome to the Kamiwaza Extensions lifecycle demo!"
    narrate "This demo will walk through creating, building, and managing extensions."
    pause_for_discussion

    # Step 1: Repository Overview
    demo_step "1. Repository Overview"
    narrate "Let's start by exploring the repository structure."

    show_command "tree -L 2 -I 'node_modules|__pycache__|.git|build'"
    cd "$REPO_ROOT"
    tree -L 2 -I 'node_modules|__pycache__|.git|build'

    narrate "The repository contains:"
    echo -e "  • ${GREEN}apps/${NC} - App Garden applications (full UI applications)"
    echo -e "  • ${GREEN}tools/${NC} - Tool Shed tools (MCP protocol servers)"
    echo -e "  • ${GREEN}scripts/${NC} - Automation and management scripts"
    echo -e "  • ${GREEN}Makefile${NC} - Primary developer interface"
    pause_for_discussion

    # Step 2: Discovery
    demo_step "2. Extension Discovery"
    narrate "Let's see what extensions are currently available."

    show_command "make list"
    make list

    narrate "This shows all extensions with their metadata and status."
    pause_for_discussion

    # Step 3: Creating a Tool
    demo_step "3. Creating a New Tool Shed Tool"
    narrate "Let's create a new MCP tool from scratch."

    show_command "make new TYPE=tool NAME=demo-search-tool"
    make new TYPE=tool NAME=demo-search-tool
    DEMO_ARTIFACTS+=("$REPO_ROOT/tools/demo-search-tool")

    narrate "A new tool has been scaffolded. Let's examine its structure."

    show_command "tree tools/demo-search-tool"
    tree tools/demo-search-tool || ls -la tools/demo-search-tool

    narrate "Every extension needs a kamiwaza.json metadata file."
    show_command "cat tools/demo-search-tool/kamiwaza.json"
    cat tools/demo-search-tool/kamiwaza.json 2>/dev/null || echo "No kamiwaza.json yet - let's create one!"
    pause_for_discussion

    # Step 4: Adding Metadata
    demo_step "4. Adding Extension Metadata"
    narrate "Let's create proper metadata for our tool."

    cat > "$REPO_ROOT/tools/demo-search-tool/kamiwaza.json" <<EOF
{
  "name": "demo-search-tool",
  "version": "1.0.0",
  "description": "Demo MCP tool for searching",
  "source_type": "kamiwaza",
  "visibility": "public",
  "risk_tier": 1,
  "verified": false,
  "image": "demo-search-tool:latest",
  "mcp_endpoint": "http://localhost:8000/mcp"
}
EOF

    show_command "cat tools/demo-search-tool/kamiwaza.json"
    cat tools/demo-search-tool/kamiwaza.json

    narrate "Key metadata fields:"
    echo -e "  • ${GREEN}source_type${NC} - 'kamiwaza' for internal, 'external' for third-party"
    echo -e "  • ${GREEN}risk_tier${NC} - 0 (safe), 1 (moderate), 2 (elevated risk)"
    echo -e "  • ${GREEN}mcp_endpoint${NC} - For tools, the MCP protocol endpoint"
    pause_for_discussion

    # Step 5: Validation
    demo_step "5. Validating Extensions"
    narrate "Let's validate our extension metadata."

    show_command "make validate"
    make validate || true

    narrate "Validation checks:"
    echo -e "  • Required metadata fields"
    echo -e "  • Semantic versioning"
    echo -e "  • Naming conventions"
    echo -e "  • Docker compose compatibility"
    pause_for_discussion

    # Step 6: Creating an App
    demo_step "6. Creating an App Garden Application"
    narrate "Now let's create a full application with UI."

    show_command "make new TYPE=app NAME=demo-dashboard"
    make new TYPE=app NAME=demo-dashboard
    DEMO_ARTIFACTS+=("$REPO_ROOT/apps/demo-dashboard")

    narrate "Apps typically have more complex structure with frontend and backend."

    # Add metadata for the app
    cat > "$REPO_ROOT/apps/demo-dashboard/kamiwaza.json" <<EOF
{
  "name": "demo-dashboard",
  "version": "1.0.0",
  "description": "Demo dashboard application",
  "source_type": "kamiwaza",
  "visibility": "public",
  "risk_tier": 0,
  "verified": false,
  "services": {
    "frontend": {
      "image": "demo-dashboard-frontend:latest",
      "port": 3000
    },
    "backend": {
      "image": "demo-dashboard-backend:latest",
      "port": 8080
    }
  }
}
EOF

    show_command "cat apps/demo-dashboard/kamiwaza.json"
    cat apps/demo-dashboard/kamiwaza.json
    pause_for_discussion

    # Step 7: Docker Compose
    demo_step "7. Docker Compose Configuration"
    narrate "Extensions use Docker Compose for both local development and App Garden deployment."

    # Create a docker-compose.yml
    cat > "$REPO_ROOT/apps/demo-dashboard/docker-compose.yml" <<EOF
version: '3.9'
services:
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - API_URL=http://backend:8080
    depends_on:
      - backend

  backend:
    build: ./backend
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgres://user:pass@db:5432/demo
    depends_on:
      - db

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=demo
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
EOF

    show_command "cat apps/demo-dashboard/docker-compose.yml"
    cat apps/demo-dashboard/docker-compose.yml

    narrate "This compose file works for local development with build contexts and host ports."
    pause_for_discussion

    # Step 8: Sync for App Garden
    demo_step "8. Preparing for App Garden Deployment"
    narrate "App Garden has specific requirements. Let's sync our compose file."

    show_command "make sync-compose TYPE=app NAME=demo-dashboard"
    cd "$REPO_ROOT"
    python3 scripts/sync-compose.py --type app --name demo-dashboard || true

    if [[ -f "apps/demo-dashboard/docker-compose.appgarden.yml" ]]; then
        show_command "cat apps/demo-dashboard/docker-compose.appgarden.yml"
        cat apps/demo-dashboard/docker-compose.appgarden.yml

        narrate "Notice the transformations:"
        echo -e "  • ${YELLOW}Build contexts removed${NC} - App Garden uses pre-built images"
        echo -e "  • ${YELLOW}Port mappings changed${NC} - No host ports, only container ports"
        echo -e "  • ${YELLOW}Resource limits added${NC} - Required for multi-tenancy"
        echo -e "  • ${YELLOW}Bind mounts removed${NC} - Only named volumes allowed"
    fi
    pause_for_discussion

    # Step 9: External Extensions
    demo_step "9. External Extensions"
    narrate "External extensions reference third-party images without local source."

    show_command "make new-external TYPE=tool NAME=demo-external-tool"
    make new-external TYPE=tool NAME=demo-external-tool
    DEMO_ARTIFACTS+=("$REPO_ROOT/tools/demo-external-tool")

    # Create external metadata
    cat > "$REPO_ROOT/tools/demo-external-tool/kamiwaza.json" <<EOF
{
  "name": "demo-external-tool",
  "version": "1.0.0",
  "description": "External tool using third-party image",
  "source_type": "external",
  "visibility": "public",
  "risk_tier": 2,
  "verified": false,
  "external_source": {
    "repository": "https://github.com/example/tool",
    "image": "example/tool:v2.1.0"
  }
}
EOF

    show_command "cat tools/demo-external-tool/kamiwaza.json"
    cat tools/demo-external-tool/kamiwaza.json

    narrate "External extensions:"
    echo -e "  • ${YELLOW}Don't have local source code${NC}"
    echo -e "  • ${YELLOW}Reference existing Docker images${NC}"
    echo -e "  • ${YELLOW}Often have higher risk tier${NC}"
    echo -e "  • ${YELLOW}Include external_source metadata${NC}"
    pause_for_discussion

    # Step 10: Building Extensions
    demo_step "10. Building Extensions"
    narrate "For internal extensions, we need to build Docker images."

    # Create minimal Dockerfiles
    mkdir -p "$REPO_ROOT/tools/demo-search-tool"
    cat > "$REPO_ROOT/tools/demo-search-tool/Dockerfile" <<EOF
FROM python:3.11-slim
WORKDIR /app
CMD ["python", "-m", "http.server", "8000"]
EOF

    show_command "make build TYPE=tool NAME=demo-search-tool"
    cd "$REPO_ROOT"
    ./scripts/build-extension.sh tool demo-search-tool || true

    narrate "The build process:"
    echo -e "  • Validates the extension first"
    echo -e "  • Builds Docker images for internal extensions"
    echo -e "  • Verifies external images exist"
    echo -e "  • Tags images appropriately"
    pause_for_discussion

    # Step 11: Registry Generation
    demo_step "11. Extension Registry"
    narrate "Finally, we generate registry files for App Garden and Tool Shed."

    show_command "make build-registry"
    make build-registry

    show_command "cat build/garden/default/tools.json | jq '.tools[0]' | head -20"
    cat build/garden/default/tools.json 2>/dev/null | jq '.tools[0]' 2>/dev/null | head -20 || echo "Registry would contain all tool metadata"

    narrate "The registry files:"
    echo -e "  • ${GREEN}build/garden/default/apps.json${NC} - All App Garden applications"
    echo -e "  • ${GREEN}build/garden/default/tools.json${NC} - All Tool Shed tools"
    echo -e "  • Auto-generated from kamiwaza.json files"
    echo -e "  • Used by Kamiwaza platform for discovery"
    pause_for_discussion

    # Step 12: Complete Lifecycle
    demo_step "12. Complete Extension Lifecycle"
    narrate "Let's review the complete lifecycle we've demonstrated:"

    echo -e "\n${GREEN}1. Create${NC} - Scaffold new extension structure"
    echo -e "${GREEN}2. Configure${NC} - Add metadata and Docker configuration"
    echo -e "${GREEN}3. Validate${NC} - Ensure compliance with requirements"
    echo -e "${GREEN}4. Build${NC} - Create Docker images"
    echo -e "${GREEN}5. Test${NC} - Run locally with docker-compose"
    echo -e "${GREEN}6. Sync${NC} - Prepare for App Garden deployment"
    echo -e "${GREEN}7. Registry${NC} - Generate discovery metadata"
    echo -e "${GREEN}8. Deploy${NC} - Push to App Garden or Tool Shed"

    narrate "This lifecycle supports:"
    echo -e "  • ${CYAN}Rapid development${NC} with local testing"
    echo -e "  • ${CYAN}Multi-tenancy${NC} with resource limits"
    echo -e "  • ${CYAN}Security${NC} with risk tiers and verification"
    echo -e "  • ${CYAN}Flexibility${NC} with internal, external, and hybrid extensions"
    pause_for_discussion

    # Cleanup reminder
    demo_step "Demo Complete!"
    narrate "All demo artifacts will be cleaned up automatically."
    narrate "Thank you for exploring the Kamiwaza Extensions lifecycle!"
    echo -e "\n${CYAN}For more information, see:${NC}"
    echo -e "  • ${GREEN}README.md${NC} - General overview"
    echo -e "  • ${GREEN}DEVELOPERS.md${NC} - Technical details"
    echo -e "  • ${GREEN}CONTRIBUTING.md${NC} - Contribution guidelines"
}

# Run the demo
main
