#!/usr/bin/env python3
"""
HTTPS server for Kamiwaza Extensions Registry
Serves registry files over HTTPS with self-signed certificate
"""

import argparse
import os
import ssl
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path


class CORSRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with CORS headers."""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()


def create_ssl_context(cert_dir):
    """Create SSL context with self-signed certificate."""
    cert_file = cert_dir / "server.pem"
    key_file = cert_dir / "server.key"

    # If certificates don't exist, create them
    if not cert_file.exists() or not key_file.exists():
        print(f"Certificate files not found in {cert_dir}")
        print("Creating self-signed certificate...")

        cert_dir.mkdir(parents=True, exist_ok=True)

        # Generate self-signed certificate using openssl
        import subprocess

        result = subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-x509",
                "-keyout",
                str(key_file),
                "-out",
                str(cert_file),
                "-days",
                "365",
                "-nodes",
                "-subj",
                "/C=US/ST=State/L=City/O=Kamiwaza/CN=localhost",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Failed to create certificate: {result.stderr}")
            print("Falling back to HTTP mode")
            return None

        print(f"Created self-signed certificate in {cert_dir}")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)

    return context


def detect_garden_dir(package_root: Path) -> str:
    env_candidate = os.getenv("KAMIWAZA_REGISTRY_GARDEN_DIR")
    if env_candidate:
        env_path = package_root / "garden" / env_candidate
        if (env_path / "apps.json").exists() or (env_path / "tools.json").exists():
            return env_candidate

    repo_version_file = package_root / ".repo-version"
    if repo_version_file.exists():
        repo_version = repo_version_file.read_text().strip()
        if repo_version:
            candidate = "default" if repo_version == "1" else f"v{repo_version}"
            candidate_path = package_root / "garden" / candidate
            if (candidate_path / "apps.json").exists() or (candidate_path / "tools.json").exists():
                return candidate

    garden_root = package_root / "garden"
    if garden_root.exists():
        for candidate in sorted(garden_root.iterdir()):
            if candidate.is_dir() and ((candidate / "apps.json").exists() or (candidate / "tools.json").exists()):
                return candidate.name

    return "default"


def main():
    parser = argparse.ArgumentParser(description="Serve Kamiwaza Extensions Registry")
    parser.add_argument("--port", type=int, default=58888, help="Port to serve on (default: 58888)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--http", action="store_true", help="Use HTTP instead of HTTPS")
    args = parser.parse_args()

    # Get package root directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)
    garden_dir = detect_garden_dir(script_dir)

    # Create and configure server
    server_address = (args.host, args.port)
    httpd = HTTPServer(server_address, CORSRequestHandler)

    if not args.http:
        # Try to set up SSL
        cert_dir = script_dir / ".certs"
        ssl_context = create_ssl_context(cert_dir)

        if ssl_context:
            httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)
            protocol = "HTTPS"
            url_prefix = "https://"
        else:
            protocol = "HTTP"
            url_prefix = "http://"
    else:
        protocol = "HTTP"
        url_prefix = "http://"

    print(f"Serving Kamiwaza Extensions Registry over {protocol}")
    print(f"Server running at {url_prefix}localhost:{args.port}")
    print("")
    print("Registry URLs:")
    print(f"  Apps:  {url_prefix}localhost:{args.port}/garden/{garden_dir}/apps.json")
    print(f"  Tools: {url_prefix}localhost:{args.port}/garden/{garden_dir}/tools.json")
    print("")
    if protocol == "HTTPS":
        print("Note: This uses a self-signed certificate. Clients may need to accept it.")
    print("Press Ctrl+C to stop the server")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.shutdown()


if __name__ == "__main__":
    main()
