#!/bin/bash
# Generate systemd service file for mctomqtt

set -e

# Get current directory (where mctomqtt.py is)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Verify mctomqtt.py exists
if [ ! -f "$SCRIPT_DIR/mctomqtt.py" ]; then
    echo "Error: mctomqtt.py not found in $SCRIPT_DIR"
    exit 1
fi

# Find Python in venv
PYTHON_PATH="$SCRIPT_DIR/mctomqtt/bin/python3"
if [ ! -f "$PYTHON_PATH" ]; then
    echo "Error: Python venv not found at $PYTHON_PATH"
    echo "Please create venv first: python3 -m venv mctomqtt"
    exit 1
fi

# Find meshcore-decoder
DECODER_PATH=$(which meshcore-decoder 2>/dev/null || true)
if [ -z "$DECODER_PATH" ]; then
    echo "Warning: meshcore-decoder not found in PATH"
    echo "Auth token authentication will not work"
    echo "Install with: npm install -g @michaelhart/meshcore-decoder"
    DECODER_DIR=""
else
    # Get the directory containing meshcore-decoder
    DECODER_DIR=$(dirname "$DECODER_PATH")
    echo "Found meshcore-decoder at: $DECODER_PATH"
fi

# Get current username
CURRENT_USER=$(whoami)

# Build PATH environment variable
if [ -n "$DECODER_DIR" ]; then
    # Include decoder directory plus standard paths
    SERVICE_PATH="$DECODER_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
else
    # Just standard paths
    SERVICE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
fi

# Generate the service file
cat > "$SCRIPT_DIR/mctomqtt.service" << EOF
[Unit]
Description=MeshCore to MQTT Relay
After=network.target

[Service]
# Run as the user who installed npm packages, NOT root
User=$CURRENT_USER
WorkingDirectory=$SCRIPT_DIR
Environment="PATH=$SERVICE_PATH"
ExecStart=$PYTHON_PATH $SCRIPT_DIR/mctomqtt.py
KillMode=process
Restart=on-failure
Type=exec

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "✓ Generated mctomqtt.service"
echo ""
echo "Service configuration:"
echo "  User: $CURRENT_USER"
echo "  WorkingDirectory: $SCRIPT_DIR"
echo "  Python: $PYTHON_PATH"
echo "  PATH: $SERVICE_PATH"
echo ""
echo "To install the service, run:"
echo "  sudo cp $SCRIPT_DIR/mctomqtt.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable mctomqtt.service"
echo "  sudo systemctl start mctomqtt.service"
echo ""
