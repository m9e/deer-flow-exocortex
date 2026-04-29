# Kamiwaza Extensions Registry Package

This package contains a complete offline distribution of the Kamiwaza Extensions Registry, including all extension metadata and optionally Docker images for offline deployment.

## Package Contents

`<garden-dir>` below is the active registry directory for this package:
- `default` for repo version 1
- `v2` for repo version 2
- `v3` for repo version 3
- `package-setup.sh` and `serve-registry.py` auto-detect it

When extracted, all files are contained within the `kamiwaza-extension-registry/` directory:

```
kamiwaza-extension-registry/
├── garden/
│   └── <garden-dir>/
│       ├── apps.json               # Application registry
│       ├── tools.json              # Tools registry
│       ├── app-garden-images/      # Preview images for extensions
│       └── docker-images/          # Exported Docker images (if included)
│           ├── *.tar               # Docker image archives
│           ├── manifest.json       # Image manifest with checksums
│           └── import-images.sh    # Script to import all images
├── package-setup.sh                # Setup and configuration script
├── serve-registry.py               # HTTPS server for registry
├── kamiwaza-registry.env.template  # Environment configuration template
└── README.md                       # This file
```

## Quick Start

### 1. Extract and Enter Directory

```bash
tar -xzf kamiwaza-registry-*.tar.gz
cd kamiwaza-extension-registry
```

### 2. Run Setup Script

```bash
./package-setup.sh
```

This interactive script will:
- Verify Docker installation
- Check registry integrity
- Optionally load Docker images locally
- Configure environment variables
- Optionally start an HTTPS server

### 2. Configure Kamiwaza

The registry can be used in two modes:

#### Option 1: HTTPS Server (Recommended for Teams)

```bash
# Set environment variables
export KAMIWAZA_EXTENSION_STAGE=LOCAL
export KAMIWAZA_EXTENSION_LOCAL_STAGE_URL=https://your-server:58888

# Start HTTPS server (if not started by setup script)
python3 serve-registry.py --port 58888
```

The server uses a self-signed certificate. Clients may need to accept the certificate or disable TLS verification.

#### Option 2: Local File System (Single Machine)

```bash
# Set environment variables
export KAMIWAZA_EXTENSION_STAGE=LOCAL
export KAMIWAZA_EXTENSION_LOCAL_STAGE_URL=file:///path/to/package

# Or source the generated env file
source kamiwaza-registry.env
```

## Manual Docker Image Import

If you didn't load images during setup, you can import them manually:

```bash
cd garden/<garden-dir>/docker-images
./import-images.sh
```

Or import individual images:

```bash
docker load -i garden/<garden-dir>/docker-images/image_name.tar
```

## Registry Structure

### apps.json
Contains metadata for all applications including:
- Name, version, description
- Environment variables and defaults
- Docker compose configuration
- Resource requirements
- Docker image references

### tools.json
Contains metadata for all MCP tools including:
- Name, version, description
- Tool capabilities
- Docker configuration
- Resource requirements

### Docker Images
If included, the package contains all Docker images referenced by the extensions:
- Images are stored as tar archives
- SHA256 checksums in manifest.json
- Can be imported for offline use

## Environment Variables

### Required for Local Stage
- `KAMIWAZA_EXTENSION_STAGE=LOCAL` - Enables local extension loading
- `KAMIWAZA_EXTENSION_LOCAL_STAGE_URL` - Registry location (https:// or file://)

### Optional Registry Paths
- `KAMIWAZA_REGISTRY_APPS` - Path to apps.json
- `KAMIWAZA_REGISTRY_TOOLS` - Path to tools.json

## Serving the Registry

### Using the Provided HTTPS Server

The package includes a Python HTTPS server with self-signed certificate:

```bash
cd kamiwaza-extension-registry

# Default port 58888
python3 serve-registry.py

# Custom port
python3 serve-registry.py --port 8443
```

### Using Your Own Server

Any static file server can serve the registry. Ensure:
1. CORS headers are configured if needed
2. The `/garden/<garden-dir>/` path structure is preserved
3. JSON files are served with correct content-type

Example with nginx:

```nginx
server {
    listen 443 ssl;
    server_name registry.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    root /path/to/package;

    location / {
        add_header Access-Control-Allow-Origin *;
        try_files $uri $uri/ =404;
    }
}
```

## Verification

### Check Registry Files

```bash
# Count extensions
jq '. | length' garden/<garden-dir>/apps.json
jq '. | length' garden/<garden-dir>/tools.json

# List app names
jq '.[].name' garden/<garden-dir>/apps.json

# List tool names
jq '.[].name' garden/<garden-dir>/tools.json
```

### Check Docker Images

```bash
# List available tar files
ls -lh garden/<garden-dir>/docker-images/*.tar

# Verify manifest
jq . garden/<garden-dir>/docker-images/manifest.json

# Check if images are loaded
docker images | grep 'ghcr.io/.*/images/'
```

## Troubleshooting

### Certificate Issues

If you encounter TLS/SSL certificate errors:

1. **For development**: Set `NODE_TLS_REJECT_UNAUTHORIZED=0` (not for production)
2. **For production**: Use a proper certificate from a trusted CA
3. **For self-signed**: Add certificate to trusted store or configure client to accept

### Docker Image Loading

If image loading fails:
1. Ensure Docker daemon is running
2. Check available disk space
3. Verify tar file integrity using SHA256 from manifest.json

### Registry Access

If Kamiwaza cannot access the registry:
1. Verify `KAMIWAZA_EXTENSION_STAGE=LOCAL` is set
2. Check `KAMIWAZA_EXTENSION_LOCAL_STAGE_URL` format
   - For HTTPS: `https://server:port` (no trailing slash)
   - For file: `file:///absolute/path` (three slashes)
3. Test access: `curl https://server:port/garden/<garden-dir>/apps.json`

## Security Notes

- The self-signed certificate is for development/testing only
- For production, use certificates from a trusted CA
- Docker images may contain sensitive data - handle accordingly
- Review extension permissions before deployment

## Support

For issues or questions:
- GitHub: https://github.com/kamiwaza-ai/kamiwaza-extensions
- Documentation: https://docs.kamiwaza.ai

## Version

Package generated on: [TIMESTAMP]
Registry format version: 1.0.0
