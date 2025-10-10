#!/bin/bash
# ============================================================================
# MeshCore to MQTT - Interactive Installer
# ============================================================================
set -e

SCRIPT_VERSION="1.0.0"
DEFAULT_REPO="michaelhart/meshcoretomqtt"
DEFAULT_BRANCH="main"

# Parse command line arguments
CONFIG_URL=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG_URL="$2"
            shift 2
            ;;
        --repo)
            DEFAULT_REPO="$2"
            shift 2
            ;;
        --branch)
            DEFAULT_BRANCH="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--config URL] [--repo owner/repo] [--branch branch-name]"
            exit 1
            ;;
    esac
done

# Use environment variables if set, otherwise use defaults/args
REPO="${INSTALL_REPO:-$DEFAULT_REPO}"
BRANCH="${INSTALL_BRANCH:-$DEFAULT_BRANCH}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

prompt_yes_no() {
    local prompt="$1"
    local default="${2:-n}"
    local response
    
    if [ "$default" = "y" ]; then
        prompt="$prompt [Y/n]: "
    else
        prompt="$prompt [y/N]: "
    fi
    
    # Read from /dev/tty to work when stdin is piped
    read -p "$prompt" response </dev/tty
    response=${response:-$default}
    
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

prompt_input() {
    local prompt="$1"
    local default="$2"
    local response
    
    # Read from /dev/tty to work when stdin is piped
    if [ -n "$default" ]; then
        read -p "$prompt [$default]: " response </dev/tty
        echo "${response:-$default}"
    else
        read -p "$prompt: " response </dev/tty
        echo "$response"
    fi
}

# Configure MQTT brokers (smart - offers LetsMesh by default)
configure_mqtt_brokers() {
    ENV_LOCAL="$INSTALL_DIR/.env.local"
    
    # Ensure .env.local exists with update source info
    if [ ! -f "$ENV_LOCAL" ]; then
        cat > "$ENV_LOCAL" << EOF
# MeshCore to MQTT Configuration
# This file contains your local overrides to the defaults in .env

# Update source (configured by installer)
UPDATE_REPO=$REPO
UPDATE_BRANCH=$BRANCH

# Serial Configuration
SERIAL_PORTS=/dev/ttyACM0

# Location Code
IATA=XXX
EOF
    fi
    
    # Get IATA from existing config
    IATA=$(grep "^IATA=" "$ENV_LOCAL" 2>/dev/null | cut -d'=' -f2)
    
    # Always prompt for IATA if it's XXX or empty
    if [ -z "$IATA" ] || [ "$IATA" = "XXX" ]; then
        echo ""
        print_info "IATA code is a 3-letter airport code identifying your geographic region"
        print_info "Example: SEA (Seattle), LAX (Los Angeles), NYC (New York), LON (London)"
        echo ""
        
        while [ -z "$IATA" ] || [ "$IATA" = "XXX" ]; do
            IATA=$(prompt_input "Enter your IATA code (3 letters)" "")
            IATA=$(echo "$IATA" | tr '[:lower:]' '[:upper:]' | tr -d ' ')
            
            if [ -z "$IATA" ]; then
                print_error "IATA code cannot be empty"
            elif [ "$IATA" = "XXX" ]; then
                print_error "Please enter your actual IATA code, not XXX"
            elif [ ${#IATA} -ne 3 ]; then
                print_warning "IATA code should be 3 letters, you entered: $IATA"
                if ! prompt_yes_no "Use '$IATA' anyway?" "n"; then
                    IATA="XXX"  # Reset to force re-prompt
                fi
            fi
        done
        
        # Update IATA in config
        sed -i.bak "s/^IATA=.*/IATA=$IATA/" "$ENV_LOCAL"
        rm -f "$ENV_LOCAL.bak"
        echo ""
        print_success "IATA code set to: $IATA"
        echo ""
    fi
    
    echo ""
    print_header "MQTT Broker Configuration"
    echo ""
    print_info "Enable the LetsMesh.net Packet Analyzer (mqtt-us-v1.letsmesh.net) broker?"
    echo "  • Real-time packet analysis and visualization"
    echo "  • Network health monitoring"
    echo "  • Requires meshcore-decoder for authentication"
    echo ""
    
    if [ "$DECODER_AVAILABLE" = true ]; then
        if prompt_yes_no "Enable LetsMesh Packet Analyzer?" "y"; then
            cat >> "$ENV_LOCAL" << EOF

# MQTT Broker 1 - LetsMesh.net Packet Analyzer
MQTT1_ENABLED=true
MQTT1_SERVER=mqtt-us-v1.letsmesh.net
MQTT1_PORT=443
MQTT1_TRANSPORT=websockets
MQTT1_USE_TLS=true
MQTT1_USE_AUTH_TOKEN=true
MQTT1_TOKEN_AUDIENCE=mqtt-us-v1.letsmesh.net
EOF
            print_success "LetsMesh Packet Analyzer enabled"
            
            if prompt_yes_no "Would you like to configure additional MQTT brokers?" "n"; then
                configure_additional_brokers
            fi
        else
            # User declined LetsMesh, ask if they want to configure a custom broker
            if prompt_yes_no "Would you like to configure a custom MQTT broker?" "y"; then
                configure_custom_broker 1
                
                if prompt_yes_no "Would you like to configure additional MQTT brokers?" "n"; then
                    configure_additional_brokers
                fi
            else
                print_warning "No MQTT brokers configured - you'll need to edit .env.local manually"
            fi
        fi
    else
        # No decoder available, can't use LetsMesh
        print_warning "meshcore-decoder not available - cannot use LetsMesh auth token authentication"
        
        if prompt_yes_no "Would you like to configure a custom MQTT broker with username/password?" "y"; then
            configure_custom_broker 1
            
            if prompt_yes_no "Would you like to configure additional MQTT brokers?" "n"; then
                configure_additional_brokers
            fi
        else
            print_warning "No MQTT brokers configured - you'll need to edit .env.local manually"
        fi
    fi
}

# Configure additional brokers (starting from MQTT2)
configure_additional_brokers() {
    # Find next available broker number
    NEXT_BROKER=2
    while grep -q "^MQTT${NEXT_BROKER}_ENABLED=" "$INSTALL_DIR/.env.local" 2>/dev/null; do
        NEXT_BROKER=$((NEXT_BROKER + 1))
    done
    
    NUM_ADDITIONAL=$(prompt_input "How many additional brokers?" "1")
    
    for i in $(seq 1 $NUM_ADDITIONAL); do
        BROKER_NUM=$((NEXT_BROKER + i - 1))
        configure_custom_broker $BROKER_NUM
    done
}

# Configure a single custom MQTT broker
configure_custom_broker() {
    local BROKER_NUM=$1
    ENV_LOCAL="$INSTALL_DIR/.env.local"
    
    echo ""
    print_header "Configuring MQTT Broker $BROKER_NUM"
    
    SERVER=$(prompt_input "Server hostname/IP")
    if [ -z "$SERVER" ]; then
        print_warning "Server hostname required - skipping broker $BROKER_NUM"
        return
    fi
    
    echo "" >> "$ENV_LOCAL"
    echo "# MQTT Broker $BROKER_NUM" >> "$ENV_LOCAL"
    echo "MQTT${BROKER_NUM}_ENABLED=true" >> "$ENV_LOCAL"
    echo "MQTT${BROKER_NUM}_SERVER=$SERVER" >> "$ENV_LOCAL"
    
    PORT=$(prompt_input "Port" "1883")
    echo "MQTT${BROKER_NUM}_PORT=$PORT" >> "$ENV_LOCAL"
    
    # Transport
    if prompt_yes_no "Use WebSockets transport?" "n"; then
        echo "MQTT${BROKER_NUM}_TRANSPORT=websockets" >> "$ENV_LOCAL"
    fi
    
    # TLS
    if prompt_yes_no "Use TLS/SSL encryption?" "n"; then
        echo "MQTT${BROKER_NUM}_USE_TLS=true" >> "$ENV_LOCAL"
        
        if ! prompt_yes_no "Verify TLS certificates?" "y"; then
            echo "MQTT${BROKER_NUM}_TLS_VERIFY=false" >> "$ENV_LOCAL"
        fi
    fi
    
    # Authentication
    echo ""
    print_info "Authentication method:"
    echo "  1) Username/Password"
    echo "  2) MeshCore Auth Token (requires meshcore-decoder)"
    echo "  3) None (anonymous)"
    AUTH_TYPE=$(prompt_input "Choose authentication method [1-3]" "1")
    
    if [ "$AUTH_TYPE" = "2" ]; then
        if [ "$DECODER_AVAILABLE" = false ]; then
            print_error "meshcore-decoder not available - using username/password instead"
            AUTH_TYPE=1
        else
            echo "MQTT${BROKER_NUM}_USE_AUTH_TOKEN=true" >> "$ENV_LOCAL"
            TOKEN_AUDIENCE=$(prompt_input "Token audience (optional)" "")
            if [ -n "$TOKEN_AUDIENCE" ]; then
                echo "MQTT${BROKER_NUM}_TOKEN_AUDIENCE=$TOKEN_AUDIENCE" >> "$ENV_LOCAL"
            fi
        fi
    fi
    
    if [ "$AUTH_TYPE" = "1" ]; then
        USERNAME=$(prompt_input "Username" "")
        if [ -n "$USERNAME" ]; then
            echo "MQTT${BROKER_NUM}_USERNAME=$USERNAME" >> "$ENV_LOCAL"
            PASSWORD=$(prompt_input "Password" "")
            if [ -n "$PASSWORD" ]; then
                echo "MQTT${BROKER_NUM}_PASSWORD=$PASSWORD" >> "$ENV_LOCAL"
            fi
        fi
    fi
    
    print_success "Broker $BROKER_NUM configured"
}

# Check for old installations
check_old_installation() {
    # Only check for old systemd service - simple and non-blocking
    if [ -f /etc/systemd/system/mctomqtt.service ]; then
        local working_dir=$(grep "WorkingDirectory=" /etc/systemd/system/mctomqtt.service 2>/dev/null | cut -d'=' -f2)
        
        if [ -n "$working_dir" ] && [ "$working_dir" != "$HOME/.meshcoretomqtt" ]; then
            echo ""
            print_warning "Old mctomqtt systemd service detected at: $working_dir"
            echo ""
            
            if prompt_yes_no "Would you like to stop and remove the old service?" "y"; then
                if sudo systemctl stop mctomqtt.service && sudo systemctl disable mctomqtt.service && sudo rm -f /etc/systemd/system/mctomqtt.service && sudo systemctl daemon-reload; then
                    print_success "Old service removed"
                else
                    print_error "Failed to remove old service - please remove manually"
                fi
            else
                print_warning "Old service left in place - may conflict with new installation"
            fi
            echo ""
        fi
    fi
    
    # Check for launchd on macOS
    if [ "$(uname)" = "Darwin" ]; then
        local plist_file="$HOME/Library/LaunchAgents/com.meshcore.mctomqtt.plist"
        if [ -f "$plist_file" ] && ! grep -q "$HOME/.meshcoretomqtt" "$plist_file" 2>/dev/null; then
            echo ""
            print_warning "Old mctomqtt launchd service detected"
            echo ""
            
            if prompt_yes_no "Would you like to unload and remove the old service?" "y"; then
                launchctl unload "$plist_file" 2>/dev/null || true
                rm -f "$plist_file"
                print_success "Old service removed"
            else
                print_warning "Old service left in place - may conflict with new installation"
            fi
            echo ""
        fi
    fi
}

# Main installation function
main() {
    print_header "MeshCore to MQTT Installer v${SCRIPT_VERSION}"
    
    echo "This installer will help you set up MeshCore to MQTT relay."
    echo ""
    
    # Check for old installations and offer to clean up
    check_old_installation
    
    # Determine installation directory
    DEFAULT_INSTALL_DIR="$HOME/.meshcoretomqtt"
    INSTALL_DIR=$(prompt_input "Installation directory" "$DEFAULT_INSTALL_DIR")
    INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"  # Expand tilde
    
    print_info "Installation directory: $INSTALL_DIR"
    
    # Check if directory exists
    UPDATING_EXISTING=false
    if [ -d "$INSTALL_DIR" ]; then
        if prompt_yes_no "Directory already exists. Reinstall/update?" "n"; then
            print_info "Updating existing installation..."
            UPDATING_EXISTING=true
        else
            print_error "Installation cancelled."
            exit 1
        fi
    fi
    
    # Create installation directory
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    
    # Download or copy files
    print_header "Installing Files"
    
    if [ -n "${LOCAL_INSTALL}" ]; then
        # Local install for testing
        print_info "Installing from local directory: ${LOCAL_INSTALL}"
        cp "${LOCAL_INSTALL}/mctomqtt.py" "$INSTALL_DIR/"
        cp "${LOCAL_INSTALL}/auth_token.py" "$INSTALL_DIR/"
        cp "${LOCAL_INSTALL}/.env" "$INSTALL_DIR/"
        if [ -f "${LOCAL_INSTALL}/.env.local" ]; then
            print_warning ".env.local found in source - copying as .env.local.example"
            cp "${LOCAL_INSTALL}/.env.local" "$INSTALL_DIR/.env.local.example"
        fi
        chmod +x "$INSTALL_DIR/mctomqtt.py"
        print_success "Files copied from local directory"
    else
        # Download from GitHub
        print_info "Downloading from GitHub ($REPO @ $BRANCH)..."
        
        BASE_URL="https://raw.githubusercontent.com/$REPO/$BRANCH"
        
        # Download to temp directory first for verification
        TMP_DIR=$(mktemp -d)
        trap "rm -rf $TMP_DIR" EXIT
        
        print_info "Downloading mctomqtt.py..."
        if ! curl -fsSL --retry 3 --retry-delay 2 "$BASE_URL/mctomqtt.py" -o "$TMP_DIR/mctomqtt.py"; then
            print_error "Failed to download mctomqtt.py from $REPO/$BRANCH"
            print_error "Please verify the repository and branch exist"
            exit 1
        fi
        
        print_info "Downloading auth_token.py..."
        if ! curl -fsSL --retry 3 --retry-delay 2 "$BASE_URL/auth_token.py" -o "$TMP_DIR/auth_token.py"; then
            print_error "Failed to download auth_token.py"
            exit 1
        fi
        
        print_info "Downloading .env..."
        if ! curl -fsSL --retry 3 --retry-delay 2 "$BASE_URL/.env" -o "$TMP_DIR/.env"; then
            print_error "Failed to download .env"
            exit 1
        fi
        
        # Verify Python syntax before installing
        print_info "Verifying Python syntax..."
        if ! python3 -m py_compile "$TMP_DIR/mctomqtt.py" 2>/dev/null; then
            print_error "Downloaded Python file has syntax errors"
            print_error "The repository may be in an inconsistent state"
            exit 1
        fi
        
        # All downloads successful and verified, now install
        mv "$TMP_DIR/mctomqtt.py" "$INSTALL_DIR/mctomqtt.py"
        mv "$TMP_DIR/auth_token.py" "$INSTALL_DIR/auth_token.py"
        mv "$TMP_DIR/.env" "$INSTALL_DIR/.env"
        
        chmod +x "$INSTALL_DIR/mctomqtt.py"
        print_success "Files downloaded and verified"
    fi
    
    # Update source will be added by configure_mqtt_brokers if needed
    
    # Check Python
    print_header "Checking Dependencies"
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed. Please install Python 3 and try again."
        exit 1
    fi
    print_success "Python 3 found: $(python3 --version)"
    
    # Set up virtual environment
    print_info "Setting up Python virtual environment..."
    if [ ! -d "$INSTALL_DIR/venv" ]; then
        python3 -m venv "$INSTALL_DIR/venv"
        print_success "Virtual environment created"
    else
        print_success "Using existing virtual environment"
    fi
    
    # Install Python dependencies
    print_info "Installing Python dependencies..."
    source "$INSTALL_DIR/venv/bin/activate"
    pip install --quiet --upgrade pip
    pip install --quiet pyserial paho-mqtt
    print_success "Python dependencies installed"
    
    # Check for meshcore-decoder (optional)
    if command -v meshcore-decoder &> /dev/null; then
        print_success "meshcore-decoder found: $(which meshcore-decoder)"
        DECODER_AVAILABLE=true
    else
        print_warning "meshcore-decoder not found (required for auth token authentication)"
        if prompt_yes_no "Would you like instructions to install it now?" "y"; then
            echo ""
            echo "To install meshcore-decoder, run:"
            echo "  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash"
            echo "  # Restart your shell or run: source ~/.bashrc (or ~/.zshrc)"
            echo "  nvm install --lts"
            echo "  npm install -g @michaelhart/meshcore-decoder"
            echo ""
            if prompt_yes_no "Continue without meshcore-decoder (you can install it later)?" "y"; then
                DECODER_AVAILABLE=false
            else
                exit 1
            fi
        else
            DECODER_AVAILABLE=false
        fi
    fi
    
    # Configuration
    print_header "Configuration"
    
    # Check if config URL was provided
    if [ -n "$CONFIG_URL" ]; then
        print_info "Downloading configuration from: $CONFIG_URL"
        if curl -fsSL "$CONFIG_URL" -o "$INSTALL_DIR/.env.local"; then
            print_success "Configuration downloaded successfully"
            
            # Show what was downloaded
            echo ""
            print_info "Downloaded configuration:"
            cat "$INSTALL_DIR/.env.local" | grep -v '^#' | grep -v '^$' | head -20
            if [ $(cat "$INSTALL_DIR/.env.local" | grep -v '^#' | grep -v '^$' | wc -l) -gt 20 ]; then
                echo "..."
            fi
            echo ""
            
            if prompt_yes_no "Use this configuration?" "y"; then
                print_success "Using downloaded configuration"
                
                # Always prompt for IATA
                echo ""
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                print_warning "IATA CODE REQUIRED"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo ""
                print_info "IATA code is a 3-letter airport code and should match an airport near the reporting location"
                print_info "Example: SEA (Seattle), LAX (Los Angeles), NYC (New York), LON (London)"
                echo ""
                
                # Try to extract existing IATA from config
                EXISTING_IATA=$(grep "^IATA=" "$INSTALL_DIR/.env.local" 2>/dev/null | cut -d'=' -f2)
                
                IATA=""
                while [ -z "$IATA" ] || [ "$IATA" = "XXX" ]; do
                    if [ -n "$EXISTING_IATA" ] && [ "$EXISTING_IATA" != "XXX" ]; then
                        IATA=$(prompt_input "Enter your IATA code" "$EXISTING_IATA")
                    else
                        IATA=$(prompt_input "Enter your IATA code (3 letters)" "")
                    fi
                    IATA=$(echo "$IATA" | tr '[:lower:]' '[:upper:]' | tr -d ' ')
                    
                    if [ -z "$IATA" ]; then
                        print_error "IATA code cannot be empty"
                    elif [ "$IATA" = "XXX" ]; then
                        print_error "Please enter your actual IATA code, not XXX"
                    elif [ ${#IATA} -ne 3 ]; then
                        print_warning "IATA code should be 3 letters, you entered: $IATA"
                        if ! prompt_yes_no "Use '$IATA' anyway?" "n"; then
                            IATA=""
                        fi
                    fi
                done
                
                # Update IATA in config
                if grep -q "^IATA=" "$INSTALL_DIR/.env.local"; then
                    sed -i.bak "s/^IATA=.*/IATA=$IATA/" "$INSTALL_DIR/.env.local"
                    rm -f "$INSTALL_DIR/.env.local.bak"
                else
                    echo "IATA=$IATA" >> "$INSTALL_DIR/.env.local"
                fi
                echo ""
                print_success "IATA code set to: $IATA"
                echo ""
                
                # Check if MQTT1 is already configured and offer additional brokers
                if grep -q "^MQTT1_ENABLED=true" "$INSTALL_DIR/.env.local" 2>/dev/null; then
                    MQTT1_SERVER=$(grep "^MQTT1_SERVER=" "$INSTALL_DIR/.env.local" 2>/dev/null | cut -d'=' -f2)
                    echo ""
                    print_success "MQTT Broker 1 already configured: $MQTT1_SERVER"
                    
                    if prompt_yes_no "Would you like to configure additional MQTT brokers?" "n"; then
                        configure_additional_brokers
                    fi
                else
                    # No MQTT configured, offer options
                    configure_mqtt_brokers
                fi
            else
                rm -f "$INSTALL_DIR/.env.local"
                configure_mqtt_brokers
            fi
        else
            print_error "Failed to download configuration from URL"
            if prompt_yes_no "Continue with interactive configuration?" "y"; then
                configure_mqtt_brokers
            else
                exit 1
            fi
        fi
    elif [ "$UPDATING_EXISTING" = true ] && [ -f "$INSTALL_DIR/.env.local" ]; then
        if prompt_yes_no "Existing configuration found. Reconfigure?" "n"; then
            # Back up existing config before reconfiguring
            cp "$INSTALL_DIR/.env.local" "$INSTALL_DIR/.env.local.backup-$(date +%Y%m%d-%H%M%S)"
            rm -f "$INSTALL_DIR/.env.local"
            configure_mqtt_brokers
        else
            print_info "Keeping existing configuration"
        fi
    elif [ ! -f "$INSTALL_DIR/.env.local" ]; then
        configure_mqtt_brokers
    fi
    
    # Service installation
    print_header "Service Installation"
    
    SYSTEM_TYPE=$(detect_system_type)
    print_info "Detected system type: $SYSTEM_TYPE"
    
    if prompt_yes_no "Would you like to install as a system service?" "y"; then
        install_service "$SYSTEM_TYPE"
    else
        print_info "Skipping service installation"
        print_info "To run manually: cd $INSTALL_DIR && ./venv/bin/python3 mctomqtt.py"
    fi
    
    # Final summary
    print_header "Installation Complete!"
    echo "Installation directory: $INSTALL_DIR"
    echo ""
    echo "Configuration file: $INSTALL_DIR/.env.local"
    echo ""
    
    if [ "$SERVICE_INSTALLED" = true ]; then
        case "$SYSTEM_TYPE" in
            systemd)
                echo "Service management:"
                echo "  Start:   sudo systemctl start mctomqtt"
                echo "  Stop:    sudo systemctl stop mctomqtt"
                echo "  Status:  sudo systemctl status mctomqtt"
                echo "  Logs:    sudo journalctl -u mctomqtt -f"
                ;;
            launchd)
                echo "Service management:"
                echo "  Start:   launchctl start com.meshcore.mctomqtt"
                echo "  Stop:    launchctl stop com.meshcore.mctomqtt"
                echo "  Status:  launchctl list | grep mctomqtt"
                echo "  Logs:    tail -f ~/Library/Logs/mctomqtt.log"
                ;;
        esac
    else
        echo "Manual run: cd $INSTALL_DIR && ./venv/bin/python3 mctomqtt.py"
    fi
    
    echo ""
    print_success "Installation complete!"
}

# Detect system type
detect_system_type() {
    if command -v systemctl &> /dev/null; then
        echo "systemd"
    elif [ "$(uname)" = "Darwin" ]; then
        echo "launchd"
    else
        echo "unknown"
    fi
}

# Install service
install_service() {
    local system_type="$1"
    
    case "$system_type" in
        systemd)
            install_systemd_service
            ;;
        launchd)
            install_launchd_service
            ;;
        *)
            print_error "Unsupported system type: $system_type"
            print_info "You'll need to manually configure the service"
            SERVICE_INSTALLED=false
            return 1
            ;;
    esac
}

# Install systemd service (Linux)
install_systemd_service() {
    print_info "Installing systemd service..."
    
    local service_file="/tmp/mctomqtt.service"
    local current_user=$(whoami)
    
    # Build PATH with meshcore-decoder if available
    local service_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    if command -v meshcore-decoder &> /dev/null; then
        local decoder_dir=$(dirname "$(which meshcore-decoder)")
        service_path="${decoder_dir}:${service_path}"
    fi
    
    cat > "$service_file" << EOF
[Unit]
Description=MeshCore to MQTT Relay
After=network.target

[Service]
User=$current_user
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$service_path"
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/mctomqtt.py
KillMode=process
Restart=on-failure
RestartSec=10
Type=exec

[Install]
WantedBy=multi-user.target
EOF
    
    print_info "Service file created. Installing (requires sudo)..."
    
    if sudo cp "$service_file" /etc/systemd/system/mctomqtt.service; then
        sudo systemctl daemon-reload
        
        if prompt_yes_no "Enable service to start on boot?" "y"; then
            sudo systemctl enable mctomqtt.service
            print_success "Service enabled"
        fi
        
        if prompt_yes_no "Start service now?" "y"; then
            sudo systemctl start mctomqtt.service
            
            print_info "Waiting for service to start..."
            sleep 3
            
            # Check if service is actually running and connected
            print_info "Checking service health..."
            sleep 2
            
            if sudo systemctl is-active --quiet mctomqtt.service; then
                # Check logs for successful MQTT connection
                if sudo journalctl -u mctomqtt.service --since "10 seconds ago" | grep -q "Connected to.*MQTT broker"; then
                    print_success "Service started and connected to MQTT successfully"
                    echo ""
                    print_info "Recent logs:"
                    sudo journalctl -u mctomqtt.service -n 10 --no-pager
                else
                    print_warning "Service started but may not be connected to MQTT yet"
                    echo ""
                    print_info "Recent logs:"
                    sudo journalctl -u mctomqtt.service -n 15 --no-pager
                    echo ""
                    print_warning "Check logs with: sudo journalctl -u mctomqtt -f"
                fi
            else
                print_error "Service failed to start"
                echo ""
                sudo systemctl status mctomqtt.service --no-pager || true
            fi
        fi
        
        SERVICE_INSTALLED=true
        print_success "Systemd service installed"
    else
        print_error "Failed to install service (sudo required)"
        SERVICE_INSTALLED=false
    fi
    
    rm -f "$service_file"
}

# Install launchd service (macOS)
install_launchd_service() {
    print_info "Installing launchd service..."
    
    local plist_file="$HOME/Library/LaunchAgents/com.meshcore.mctomqtt.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    
    # Build PATH with meshcore-decoder if available
    local service_path="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    if command -v meshcore-decoder &> /dev/null; then
        local decoder_dir=$(dirname "$(which meshcore-decoder)")
        service_path="${decoder_dir}:${service_path}"
    fi
    
    cat > "$plist_file" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.meshcore.mctomqtt</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/venv/bin/python3</string>
        <string>$INSTALL_DIR/mctomqtt.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$service_path</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/mctomqtt.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/mctomqtt-error.log</string>
</dict>
</plist>
EOF
    
    if prompt_yes_no "Load service now?" "y"; then
        launchctl load "$plist_file"
        print_success "Service loaded"
    fi
    
    SERVICE_INSTALLED=true
    print_success "Launchd service installed"
}

# Run main
main "$@"

