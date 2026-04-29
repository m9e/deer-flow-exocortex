#!/bin/bash
# =============================================================================
# Kamiwaza Extension Entrypoint
# =============================================================================
#
# Shared entrypoint script for Kamiwaza extensions that need to trust
# Kamiwaza's internal TLS certificates (e.g., for ToolShed MCP connections).
#
# WHY THIS EXISTS:
# - Kamiwaza's Traefik uses self-signed certs for *.default.deployment.kamiwaza.ai
# - Containers connect via host.docker.internal which doesn't match the cert
# - This script fetches the cert at runtime and installs it to the system CA store
# - This preserves SSL security for external connections while trusting internal ones
#
# USAGE:
# 1. Copy this script into your Docker image:
#      COPY scripts/kamiwaza-entrypoint.sh /kamiwaza-entrypoint.sh
#      RUN chmod +x /kamiwaza-entrypoint.sh
#
# 2. Use as ENTRYPOINT (recommended):
#      ENTRYPOINT ["/kamiwaza-entrypoint.sh"]
#      CMD ["your-actual-command", "arg1", "arg2"]
#
# 3. Or source it in your own entrypoint:
#      source /kamiwaza-entrypoint.sh
#      kamiwaza_setup_ssl  # Call the setup function
#      exec your-command "$@"
#
# ENVIRONMENT VARIABLES:
#   KAMIWAZA_TRUST_TRAEFIK_CERT - Set to "true" to enable (default: false)
#   KAMIWAZA_TRAEFIK_HOST       - Host to connect to for cert (default: host.docker.internal)
#   KAMIWAZA_TRAEFIK_PORT       - Port to fetch cert from (default: 443)
#   KAMIWAZA_TRAEFIK_SNI        - SNI hostname for cert request (default: toolshed.default.deployment.kamiwaza.ai)
#                                 This must match the certificate's CN/SAN
#
# REQUIREMENTS:
#   - openssl (for fetching certificate)
#   - ca-certificates package (for update-ca-certificates)
#   - Root permissions (for installing certs)
#
# =============================================================================

set -e

# Configuration with defaults
KAMIWAZA_TRAEFIK_HOST="${KAMIWAZA_TRAEFIK_HOST:-host.docker.internal}"
KAMIWAZA_TRAEFIK_PORT="${KAMIWAZA_TRAEFIK_PORT:-443}"
# SNI hostname must match the certificate's wildcard (*.default.deployment.kamiwaza.ai)
KAMIWAZA_TRAEFIK_SNI="${KAMIWAZA_TRAEFIK_SNI:-toolshed.default.deployment.kamiwaza.ai}"
KAMIWAZA_CERT_PATH="/usr/local/share/ca-certificates/kamiwaza-traefik.crt"

_kamiwaza_log() {
    echo "[kamiwaza-entrypoint] $1"
}

# Setup DNS entries for Kamiwaza internal hostnames
# This maps *.default.deployment.kamiwaza.ai to the Docker gateway
kamiwaza_setup_dns() {
    local gateway_ip=""

    # Check if entry already exists (idempotency for container restarts)
    if grep -q "toolshed.default.deployment.kamiwaza.ai" /etc/hosts 2>/dev/null; then
        _kamiwaza_log "Hosts entry for toolshed.default.deployment.kamiwaza.ai already exists, skipping"
        return 0
    fi

    # Get the IPv4 address that host.docker.internal resolves to
    # Use ahostsv4 to force IPv4 resolution (avoid IPv6 which may not route correctly)
    # Guard for getent which may not exist on Alpine/minimal images
    if command -v getent >/dev/null 2>&1; then
        gateway_ip=$(getent ahostsv4 host.docker.internal 2>/dev/null | awk '{print $1}' | head -1)

        # Fallback to regular hosts lookup if ahostsv4 fails
        if [ -z "$gateway_ip" ]; then
            gateway_ip=$(getent hosts host.docker.internal 2>/dev/null | grep -E '^[0-9]+\.' | awk '{print $1}' | head -1)
        fi
    fi

    # Final fallback: try reading /etc/hosts directly (works on Alpine)
    if [ -z "$gateway_ip" ]; then
        gateway_ip=$(grep -E "host\.docker\.internal" /etc/hosts 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    fi

    if [ -n "$gateway_ip" ]; then
        # Add entry for toolshed.default.deployment.kamiwaza.ai pointing to the gateway
        # This hostname matches the Traefik certificate's wildcard
        if echo "$gateway_ip toolshed.default.deployment.kamiwaza.ai" >> /etc/hosts 2>/dev/null; then
            _kamiwaza_log "Added hosts entry: $gateway_ip -> toolshed.default.deployment.kamiwaza.ai"
        else
            _kamiwaza_log "WARNING: Could not write to /etc/hosts (may need root permissions)"
        fi
    else
        _kamiwaza_log "WARNING: Could not resolve host.docker.internal to IPv4, skipping hosts entry"
    fi
}

# Fetch and install Traefik's TLS certificate
kamiwaza_install_cert() {
    _kamiwaza_log "Fetching TLS certificate from ${KAMIWAZA_TRAEFIK_HOST}:${KAMIWAZA_TRAEFIK_PORT} (SNI: ${KAMIWAZA_TRAEFIK_SNI})..."

    local temp_cert
    temp_cert=$(mktemp)

    # Fetch certificate from Traefik using openssl
    # Use SNI hostname to request the correct wildcard certificate
    if echo | openssl s_client -connect "${KAMIWAZA_TRAEFIK_HOST}:${KAMIWAZA_TRAEFIK_PORT}" \
        -servername "${KAMIWAZA_TRAEFIK_SNI}" 2>/dev/null | \
        openssl x509 > "$temp_cert" 2>/dev/null; then

        # Validate we got a real certificate
        if [ -s "$temp_cert" ] && grep -q "BEGIN CERTIFICATE" "$temp_cert"; then
            _kamiwaza_log "Certificate fetched successfully"

            # Install cert to system CA store (requires root)
            if cp "$temp_cert" "$KAMIWAZA_CERT_PATH" 2>/dev/null; then
                _kamiwaza_log "Certificate installed to $KAMIWAZA_CERT_PATH"

                # Update system CA bundle
                if update-ca-certificates 2>/dev/null; then
                    _kamiwaza_log "CA certificate store updated successfully"

                    # Export SSL env vars to ensure Python/httpx use the updated bundle
                    # Critical for PyInstaller binaries that bundle their own certifi
                    export SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt"
                    export REQUESTS_CA_BUNDLE="/etc/ssl/certs/ca-certificates.crt"
                    _kamiwaza_log "Set SSL_CERT_FILE and REQUESTS_CA_BUNDLE to use system CA bundle"
                else
                    _kamiwaza_log "WARNING: update-ca-certificates failed (may need root permissions)"
                fi
            else
                _kamiwaza_log "WARNING: Could not install certificate (may need root permissions)"
            fi
        else
            _kamiwaza_log "WARNING: Failed to extract valid certificate from ${KAMIWAZA_TRAEFIK_HOST}:${KAMIWAZA_TRAEFIK_PORT}"
        fi
    else
        _kamiwaza_log "WARNING: Could not connect to ${KAMIWAZA_TRAEFIK_HOST}:${KAMIWAZA_TRAEFIK_PORT}"
    fi

    rm -f "$temp_cert"
}

# Main setup function - call this to run all Kamiwaza SSL setup
kamiwaza_setup_ssl() {
    # Always setup DNS for toolshed hostname resolution
    # This is needed regardless of SSL strategy (cert trust vs SSL bypass)
    kamiwaza_setup_dns

    # Only install certs if explicitly requested
    if [ "${KAMIWAZA_TRUST_TRAEFIK_CERT:-false}" = "true" ]; then
        _kamiwaza_log "KAMIWAZA_TRUST_TRAEFIK_CERT is enabled, installing certificate"
        kamiwaza_install_cert
    else
        _kamiwaza_log "KAMIWAZA_TRUST_TRAEFIK_CERT not set, skipping certificate installation (using SSL bypass)"
    fi
}

# =============================================================================
# ENTRYPOINT MODE
# =============================================================================
# When this script is used as ENTRYPOINT, it runs setup then execs to CMD
# If sourced by another script, the functions above are available to call

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    # Script is being executed directly (ENTRYPOINT mode)
    kamiwaza_setup_ssl

    # Exec to the command passed as arguments (from CMD or docker run)
    if [ $# -gt 0 ]; then
        _kamiwaza_log "Starting: $*"
        exec "$@"
    else
        _kamiwaza_log "WARNING: No command provided. Use CMD in Dockerfile or pass command to docker run."
        exit 1
    fi
fi
