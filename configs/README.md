# Regional Configuration Templates

This directory contains pre-configured templates for various regions and mesh networks.

## Usage

Use the `--config` flag with the installer to use a regional configuration:

```bash
curl -fsSL https://raw.githubusercontent.com/Cisien/meshcoretomqtt/main/install.sh | \
  bash -s -- --config https://raw.githubusercontent.com/Cisien/meshcoretomqtt/main/configs/.env.pugetmesh
```

## Available Configurations

### PugetMesh (Seattle, WA)
**IATA Code:** SEA  
**File:** `.env.pugetmesh`

Pre-configured for the Puget Sound region with connection to the public observer network.

```bash
--config https://raw.githubusercontent.com/Cisien/meshcoretomqtt/main/configs/.env.pugetmesh
```

### SoCalMesh (Los Angeles, CA)
**IATA Code:** LAX  
**File:** `.env.socalmesh`

Pre-configured for the Southern California region with connection to the public observer network.

```bash
--config https://raw.githubusercontent.com/Cisien/meshcoretomqtt/main/configs/.env.socalmesh
```

## Creating Your Own Configuration

You can host your own configuration file anywhere (GitHub Gist, your repo, etc.):

1. Copy `.env.local.example` as a template
2. Configure for your region/network
3. Host it publicly (Gist, repo, etc.)
4. Use the URL with `--config`

### Example: GitHub Gist

```bash
# Create a Gist with your config
# Get the raw URL, then:

curl -fsSL https://raw.githubusercontent.com/Cisien/meshcoretomqtt/main/install.sh | \
  bash -s -- --config https://gist.githubusercontent.com/username/abc123/raw/my-config.env
```

### Example: Your Own Repository

If you're maintaining a fork or custom branch:

```bash
curl -fsSL https://raw.githubusercontent.com/yourusername/meshcoretomqtt/yourbranch/install.sh | \
  bash -s -- \
    --config https://raw.githubusercontent.com/yourusername/meshcoretomqtt/yourbranch/configs/.env.yourregion \
    --repo yourusername/meshcoretomqtt \
    --branch yourbranch
```

## Configuration Format

Regional configs should be in `.env` format:

```bash
# Location
IATA=XXX

# Serial ports
SERIAL_PORTS=/dev/ttyACM0

# MQTT Brokers
MQTT1_ENABLED=true
MQTT1_SERVER=mqtt.example.com
# ... etc
```

See `.env.local.example` in the root directory for all available options.

## Contributing

To add a regional configuration:

1. Fork the repository
2. Create your config in `configs/yourregion.env`
3. Update this README
4. Submit a pull request

Regional configs should:
- Use appropriate IATA codes
- Include commonly used brokers for that region
- Be well-commented
- Follow the `.env` format

