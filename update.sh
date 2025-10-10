#!/bin/bash
# ============================================================================
# MeshCore to MQTT - Updater
# ============================================================================
set -e

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
    
    read -p "$prompt" response
    response=${response:-$default}
    
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# Load configuration to get update source
load_update_source() {
    local script_dir=$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")
    
    # Try to read from .env.local first, then .env
    local env_local="$script_dir/.env.local"
    local env_file="$script_dir/.env"
    
    UPDATE_REPO=""
    UPDATE_BRANCH=""
    
    # Parse .env files for UPDATE_REPO and UPDATE_BRANCH
    for file in "$env_local" "$env_file"; do
        if [ -f "$file" ]; then
            while IFS='=' read -r key value; do
                # Skip comments and empty lines
                [[ "$key" =~ ^#.*$ ]] && continue
                [[ -z "$key" ]] && continue
                
                # Remove quotes from value
                value=$(echo "$value" | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")
                
                case "$key" in
                    UPDATE_REPO)
                        [ -z "$UPDATE_REPO" ] && UPDATE_REPO="$value"
                        ;;
                    UPDATE_BRANCH)
                        [ -z "$UPDATE_BRANCH" ] && UPDATE_BRANCH="$value"
                        ;;
                esac
            done < "$file"
        fi
    done
    
    # Set defaults if not found
    UPDATE_REPO="${UPDATE_REPO:-michaelhart/meshcoretomqtt}"
    UPDATE_BRANCH="${UPDATE_BRANCH:-main-with-upstream}"
    
    echo "$UPDATE_REPO|$UPDATE_BRANCH"
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

# Stop service
stop_service() {
    local system_type="$1"
    
    case "$system_type" in
        systemd)
            if systemctl is-active --quiet mctomqtt.service 2>/dev/null; then
                print_info "Stopping service..."
                sudo systemctl stop mctomqtt.service
                print_success "Service stopped"
                return 0
            fi
            ;;
        launchd)
            if launchctl list | grep -q com.meshcore.mctomqtt 2>/dev/null; then
                print_info "Stopping service..."
                launchctl stop com.meshcore.mctomqtt
                print_success "Service stopped"
                return 0
            fi
            ;;
    esac
    
    print_info "No running service found"
    return 1
}

# Start service
start_service() {
    local system_type="$1"
    local was_running="$2"
    
    if [ "$was_running" != "true" ]; then
        return 0
    fi
    
    case "$system_type" in
        systemd)
            print_info "Starting service..."
            sudo systemctl start mctomqtt.service
            print_success "Service started"
            ;;
        launchd)
            print_info "Starting service..."
            launchctl start com.meshcore.mctomqtt
            print_success "Service started"
            ;;
    esac
}

# Main update function
main() {
    print_header "MeshCore to MQTT Updater"
    
    # Determine installation directory
    SCRIPT_DIR=$(dirname "$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")")
    INSTALL_DIR="$SCRIPT_DIR"
    
    print_info "Installation directory: $INSTALL_DIR"
    
    # Load update source
    UPDATE_INFO=$(load_update_source)
    UPDATE_REPO=$(echo "$UPDATE_INFO" | cut -d'|' -f1)
    UPDATE_BRANCH=$(echo "$UPDATE_INFO" | cut -d'|' -f2)
    
    print_info "Update source: $UPDATE_REPO @ $UPDATE_BRANCH"
    
    # Confirm update
    echo ""
    if ! prompt_yes_no "Update from $UPDATE_REPO/$UPDATE_BRANCH?" "y"; then
        print_info "Update cancelled"
        exit 0
    fi
    
    # Detect system and stop service if running
    SYSTEM_TYPE=$(detect_system_type)
    SERVICE_WAS_RUNNING=false
    
    if stop_service "$SYSTEM_TYPE"; then
        SERVICE_WAS_RUNNING=true
        sleep 2
    fi
    
    # Backup current .env.local
    print_header "Backing Up Configuration"
    
    if [ -f "$INSTALL_DIR/.env.local" ]; then
        BACKUP_FILE="$INSTALL_DIR/.env.local.backup-$(date +%Y%m%d-%H%M%S)"
        cp "$INSTALL_DIR/.env.local" "$BACKUP_FILE"
        print_success "Configuration backed up to: $(basename $BACKUP_FILE)"
    fi
    
    # Download updated files
    print_header "Downloading Updates"
    
    BASE_URL="https://raw.githubusercontent.com/$UPDATE_REPO/$UPDATE_BRANCH"
    
    print_info "Fetching from: $BASE_URL"
    
    # Create temporary directory for downloads
    TMP_DIR=$(mktemp -d)
    trap "rm -rf $TMP_DIR" EXIT
    
    # Note: Using GitHub raw URLs automatically handles force-pushes
    # GitHub serves the latest content at the branch ref, no git history needed
    
    print_info "Downloading mctomqtt.py..."
    if ! curl -fsSL --retry 3 --retry-delay 2 "$BASE_URL/mctomqtt.py" -o "$TMP_DIR/mctomqtt.py"; then
        print_error "Failed to download mctomqtt.py from $UPDATE_REPO/$UPDATE_BRANCH"
        print_error "Please verify the repository and branch still exist"
        start_service "$SYSTEM_TYPE" "$SERVICE_WAS_RUNNING"
        exit 1
    fi
    
    print_info "Downloading auth_token.py..."
    if ! curl -fsSL --retry 3 --retry-delay 2 "$BASE_URL/auth_token.py" -o "$TMP_DIR/auth_token.py"; then
        print_error "Failed to download auth_token.py"
        start_service "$SYSTEM_TYPE" "$SERVICE_WAS_RUNNING"
        exit 1
    fi
    
    print_info "Downloading .env (defaults)..."
    if ! curl -fsSL --retry 3 --retry-delay 2 "$BASE_URL/.env" -o "$TMP_DIR/.env"; then
        print_error "Failed to download .env"
        start_service "$SYSTEM_TYPE" "$SERVICE_WAS_RUNNING"
        exit 1
    fi
    
    print_success "All files downloaded"
    
    # Verify Python syntax
    print_info "Verifying Python syntax..."
    if ! python3 -m py_compile "$TMP_DIR/mctomqtt.py" 2>/dev/null; then
        print_error "Downloaded Python file has syntax errors"
        start_service "$SYSTEM_TYPE" "$SERVICE_WAS_RUNNING"
        exit 1
    fi
    print_success "Syntax check passed"
    
    # Install updated files
    print_header "Installing Updates"
    
    mv "$TMP_DIR/mctomqtt.py" "$INSTALL_DIR/mctomqtt.py"
    mv "$TMP_DIR/auth_token.py" "$INSTALL_DIR/auth_token.py"
    mv "$TMP_DIR/.env" "$INSTALL_DIR/.env"
    
    chmod +x "$INSTALL_DIR/mctomqtt.py"
    
    print_success "Files updated"
    
    # Restore .env.local (in case it was overwritten)
    if [ -f "$BACKUP_FILE" ] && [ ! -f "$INSTALL_DIR/.env.local" ]; then
        cp "$BACKUP_FILE" "$INSTALL_DIR/.env.local"
        print_info "Configuration restored"
    fi
    
    # Check for Python dependency updates
    print_header "Checking Dependencies"
    
    if [ -d "$INSTALL_DIR/venv" ]; then
        print_info "Updating Python dependencies..."
        source "$INSTALL_DIR/venv/bin/activate"
        pip install --quiet --upgrade pip pyserial paho-mqtt
        print_success "Dependencies updated"
    fi
    
    # Restart service if it was running
    if [ "$SERVICE_WAS_RUNNING" = "true" ]; then
        print_header "Restarting Service"
        start_service "$SYSTEM_TYPE" "$SERVICE_WAS_RUNNING"
        
        sleep 2
        
        # Show status
        case "$SYSTEM_TYPE" in
            systemd)
                sudo systemctl status mctomqtt.service --no-pager || true
                ;;
            launchd)
                if launchctl list | grep -q com.meshcore.mctomqtt; then
                    print_success "Service is running"
                else
                    print_warning "Service may not be running - check logs"
                fi
                ;;
        esac
    fi
    
    # Final message
    print_header "Update Complete!"
    
    echo "Updated to: $UPDATE_REPO @ $UPDATE_BRANCH"
    echo "Installation directory: $INSTALL_DIR"
    
    if [ -f "$BACKUP_FILE" ]; then
        echo "Configuration backup: $BACKUP_FILE"
    fi
    
    echo ""
    print_success "Update complete!"
}

# Run main
main "$@"

