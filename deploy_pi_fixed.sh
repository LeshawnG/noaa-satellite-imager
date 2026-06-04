#!/bin/bash

# =============================================================================
# Satellite Weather Imager - Raspberry Pi Deployment Script (SD Card Fixed)
# =============================================================================
# This script sets up and runs the Satellite Weather Looping System
# for continuous monitoring of GOES-19 satellite imagery over Trinidad & Tobago
# 
# FIXES FOR SD CARD DEPLOYMENT:
# - Handles permission issues with external storage
# - Provides fallback options for virtual environment creation
# - Supports different filesystem types
# - MANUAL STARTUP ONLY - No systemd service
# =============================================================================

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
VENV_DIR="venv"
APP_NAME="Satellite Weather Imager"
PORT=5000
FORCE_RECREATE_VENV=false

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}"
    echo "============================================================================="
    echo "  $1"
    echo "============================================================================="
    echo -e "${NC}"
}

# Function to check if we're on external storage
check_external_storage() {
    current_path=$(pwd)
    if [[ "$current_path" == /media/* ]] || [[ "$current_path" == /mnt/* ]]; then
        return 0  # We are on external storage
    else
        return 1  # We are on internal storage
    fi
}

# Function to check filesystem type
get_filesystem_type() {
    current_path=$(pwd)
    df -T "$current_path" | tail -1 | awk '{print $2}'
}

# Function to check if filesystem supports symlinks
test_symlink_support() {
    test_file="__test_symlink_$$"
    test_link="__test_link_$$"
    
    # Create a test file
    echo "test" > "$test_file" 2>/dev/null || return 1
    
    # Try to create a symlink
    if ln -s "$test_file" "$test_link" 2>/dev/null; then
        # Cleanup
        rm -f "$test_file" "$test_link" 2>/dev/null
        return 0  # Symlinks supported
    else
        # Cleanup
        rm -f "$test_file" "$test_link" 2>/dev/null
        return 1  # Symlinks not supported
    fi
}

# Function to check Python installation
check_python() {
    print_status "Checking Python installation..."
    
    if ! command -v python3 >/dev/null 2>&1; then
        print_error "Python 3 is not installed. Installing..."
        sudo apt update
        sudo apt install -y python3 python3-pip python3-venv
    fi
    
    python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
    print_success "Found Python $python_version"
}

# Function to create virtual environment with fallback options
setup_venv_with_fallback() {
    print_status "Setting up virtual environment with SD card compatibility..."
    
    # Check current environment
    filesystem_type=$(get_filesystem_type)
    print_status "Current filesystem: $filesystem_type"
    
    if check_external_storage; then
        print_warning "Detected external storage mount - checking for compatibility issues..."
        
        if ! test_symlink_support; then
            print_warning "Filesystem doesn't support symbolic links - using alternative approach"
            setup_venv_no_symlinks
            return $?
        else
            print_success "Filesystem supports symbolic links"
        fi
    fi
    
    # Try standard venv creation first
    if setup_venv_standard; then
        return 0
    else
        print_warning "Standard virtual environment creation failed - trying alternatives..."
        setup_venv_no_symlinks
        return $?
    fi
}

# Function to create standard virtual environment
setup_venv_standard() {
    print_status "Attempting standard virtual environment creation..."
    
    # Remove existing venv if needed
    if [ "$FORCE_RECREATE_VENV" = true ] || ! check_venv_functional; then
        if [ -d "$VENV_DIR" ]; then
            print_status "Removing existing virtual environment..."
            rm -rf "$VENV_DIR"
        fi
        
        # Create new virtual environment
        print_status "Creating virtual environment..."
        if python3 -m venv "$VENV_DIR" 2>/dev/null; then
            print_success "Standard virtual environment created successfully"
            
            # Activate and upgrade pip
            source "$VENV_DIR/bin/activate"
            pip install --upgrade pip
            return 0
        else
            print_warning "Standard virtual environment creation failed"
            return 1
        fi
    else
        print_success "Existing virtual environment is functional"
        source "$VENV_DIR/bin/activate"
        return 0
    fi
}

# Function to create virtual environment without symlinks
setup_venv_no_symlinks() {
    print_status "Creating virtual environment with --copies flag (no symlinks)..."
    
    # Remove existing venv if it exists
    if [ -d "$VENV_DIR" ]; then
        print_status "Removing existing virtual environment..."
        rm -rf "$VENV_DIR"
    fi
    
    # Create virtual environment with --copies flag
    if python3 -m venv --copies "$VENV_DIR" 2>/dev/null; then
        print_success "Virtual environment created with --copies flag"
        
        # Activate and upgrade pip
        source "$VENV_DIR/bin/activate"
        pip install --upgrade pip
        return 0
    else
        print_error "Failed to create virtual environment with --copies flag"
        setup_venv_in_home
        return $?
    fi
}

# Function to create venv in home directory as last resort
setup_venv_in_home() {
    print_warning "Creating virtual environment in home directory as fallback..."
    
    home_venv="$HOME/.satellite_weather_venv"
    
    # Remove existing home venv if it exists
    if [ -d "$home_venv" ]; then
        print_status "Removing existing home virtual environment..."
        rm -rf "$home_venv"
    fi
    
    # Create virtual environment in home directory
    if python3 -m venv "$home_venv"; then
        print_success "Virtual environment created in home directory: $home_venv"
        
        # Create a symlink or script to activate it from project directory
        if test_symlink_support; then
            ln -sf "$home_venv" "$VENV_DIR"
            print_success "Created symlink to home virtual environment"
        else
            # Create activation script
            cat > "activate_venv.sh" << EOF
#!/bin/bash
source "$home_venv/bin/activate"
export VIRTUAL_ENV="$home_venv"
echo "Activated virtual environment from: $home_venv"
EOF
            chmod +x "activate_venv.sh"
            print_success "Created activation script: activate_venv.sh"
        fi
        
        # Activate and upgrade pip
        source "$home_venv/bin/activate"
        pip install --upgrade pip
        return 0
    else
        print_error "Failed to create virtual environment in home directory"
        return 1
    fi
}

# Function to check if virtual environment is functional
check_venv_functional() {
    if [ -f "activate_venv.sh" ]; then
        # Using home directory venv
        home_venv="$HOME/.satellite_weather_venv"
        if [ -d "$home_venv" ] && [ -f "$home_venv/bin/activate" ]; then
            source "$home_venv/bin/activate"
            python3 -c "import sys; print('Python OK')" >/dev/null 2>&1
            return $?
        fi
        return 1
    elif [ ! -d "$VENV_DIR" ]; then
        return 1  # No venv directory
    elif [ ! -f "$VENV_DIR/bin/activate" ]; then
        return 1  # No activation script
    else
        # Try to activate and check Python
        if source "$VENV_DIR/bin/activate" 2>/dev/null; then
            python3 -c "import sys; print('Python OK')" >/dev/null 2>&1
            return $?
        fi
        return 1
    fi
}

# Function to activate virtual environment (handles both standard and home venv)
activate_venv() {
    if [ -f "activate_venv.sh" ]; then
        source "./activate_venv.sh"
    else
        source "$VENV_DIR/bin/activate"
    fi
}

# Function to check if key dependencies are installed
check_dependencies_installed() {
    print_status "Checking if required dependencies are installed..."
    
    if [ ! -f "requirements.txt" ]; then
        print_error "requirements.txt not found"
        return 1
    fi
    
    # Activate virtual environment
    activate_venv
    
    # Check key imports
    python3 -c "
try:
    import flask
    import requests
    import PIL
    import numpy
    import astral
    import schedule
    import psutil
    print('Key dependencies available')
except ImportError as e:
    print(f'Missing dependency: {e}')
    exit(1)
" >/dev/null 2>&1
    
    return $?
}

# Function to install Python dependencies
install_dependencies() {
    print_status "Installing/updating Python dependencies..."
    
    if [ ! -f "requirements.txt" ]; then
        print_error "requirements.txt not found in current directory"
        exit 1
    fi
    
    # Activate virtual environment
    activate_venv
    
    # Check if we need to install/update dependencies
    if check_dependencies_installed && [ "$FORCE_RECREATE_VENV" != true ]; then
        print_success "Dependencies are already up to date"
        return 0
    fi
    
    # Install/update requirements
    print_status "Installing requirements from requirements.txt..."
    pip install -r requirements.txt
    
    print_success "All dependencies installed/updated successfully"
}

# Function to create required directories
create_directories() {
    print_status "Creating required directories..."
    
    # Base images directory
    mkdir -p images
    
    # Create band-specific directories
    declare -a bands=("GeoColor" "Sandwich RGB" "Band 2 (Red-Visible - 0.64 um)" 
                     "Band 13 (Clean Longwave IR - 10.3 um)" 
                     "Band 10 (Lower-level Water Vapor - 7.3 um)"
                     "Band 9 (Mid-Level Water Vapour - 6.9 um)"
                     "Band 8 (Upper-Level Water Vapor - 6.2 um)")
    
    for band in "${bands[@]}"; do
        band_dir="images/$band"
        mkdir -p "$band_dir/raw_images"
        mkdir -p "$band_dir/Zoom/Zoom1"
        mkdir -p "$band_dir/Zoom/Zoom2"
        mkdir -p "$band_dir/Zoom/Zoom3"
        print_status "Created directories for: $band"
    done
    
    # Create static and templates directories if they don't exist
    mkdir -p static
    mkdir -p templates
    
    print_success "All required directories created"
}

# Function to check system requirements
check_system_requirements() {
    print_status "Checking system requirements..."
    
    # Check available disk space (need at least 5GB for image storage)
    available_space=$(df . | tail -1 | awk '{print $4}')
    available_gb=$((available_space / 1024 / 1024))
    
    if [ $available_gb -lt 5 ]; then
        print_warning "Available disk space: ${available_gb}GB. Recommend at least 5GB for image storage."
    else
        print_success "Available disk space: ${available_gb}GB"
    fi
    
    # Check memory
    total_memory=$(free -m | grep '^Mem:' | awk '{print $2}')
    if [ $total_memory -lt 1024 ]; then
        print_warning "Available memory: ${total_memory}MB. Recommend at least 1GB for optimal performance."
    else
        print_success "Available memory: ${total_memory}MB"
    fi
}

# Function to verify installation
verify_installation() {
    print_status "Verifying installation..."
    
    # Check if main files exist
    required_files=("app.py" "config.py" "requirements.txt" "image_downloader.py" 
                   "image_processor.py" "storage_manager.py" "sun_calculator.py")
    
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            print_error "Required file missing: $file"
            exit 1
        fi
    done
    
    print_success "All required files are present"
    
    # Verify virtual environment state
    print_status "Verifying virtual environment state..."
    if check_venv_functional; then
        print_success "Virtual environment is functional"
        
        # Get venv Python version
        activate_venv
        venv_python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
        print_success "Virtual environment Python version: $venv_python_version"
        
        # Check dependencies in detail
        if check_dependencies_installed; then
            print_success "All required dependencies are installed"
            
            # Show some key package versions
            print_status "Key package versions:"
            python3 -c "
import pkg_resources
packages = ['flask', 'requests', 'Pillow', 'numpy', 'astral', 'schedule', 'psutil']
for pkg in packages:
    try:
        version = pkg_resources.get_distribution(pkg).version
        print(f'  • {pkg}: {version}')
    except:
        print(f'  • {pkg}: not found')
"
        else
            print_warning "Some dependencies may be missing (will be installed/updated)"
        fi
    else
        print_error "Virtual environment verification failed"
        exit 1
    fi
    
    print_success "Installation verification complete"
}

# Function to create startup script
create_startup_script() {
    print_status "Creating startup script..."
    
    # Create a convenient startup script
    if [ -f "activate_venv.sh" ]; then
        # Using home directory venv
        cat > "start_app.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source ./activate_venv.sh
echo "Starting Satellite Weather Imager..."
python3 app.py
EOF
    else
        # Using local venv
        cat > "start_app.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
echo "Starting Satellite Weather Imager..."
python3 app.py
EOF
    fi
    
    chmod +x "start_app.sh"
    print_success "Created startup script: start_app.sh"
}

# Function to show usage information
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --force-recreate-venv    Force recreation of virtual environment"
    echo "  --help                   Show this help message"
    echo ""
    echo "This script will:"
    echo "  1. Check system requirements"
    echo "  2. Set up virtual environment (with SD card compatibility)"
    echo "  3. Install Python dependencies"
    echo "  4. Create required directories"
    echo "  5. Verify installation"
    echo "  6. Create startup script for manual execution"
    echo ""
    echo "NOTE: This script does NOT create a systemd service."
    echo "The application must be started manually."
    echo ""
}

# Main execution
main() {
    print_header "$APP_NAME - Raspberry Pi Deployment (SD Card Compatible - Manual Startup)"
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force-recreate-venv)
                FORCE_RECREATE_VENV=true
                shift
                ;;
            --help)
                show_usage
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # Check if running as root
    if [ "$EUID" -eq 0 ]; then
        print_error "Please do not run this script as root"
        exit 1
    fi
    
    # Main deployment steps
    check_python
    check_system_requirements
    setup_venv_with_fallback
    install_dependencies
    create_directories
    verify_installation
    create_startup_script
    
    print_header "Deployment Complete!"
    
    print_success "Satellite Weather Imager has been successfully deployed!"
    print_status ""
    print_status "🚀 To start the application manually:"
    print_status "   ./start_app.sh"
    print_status ""
    print_status "💡 Alternative startup methods:"
    if [ -f "activate_venv.sh" ]; then
        print_status "   source ./activate_venv.sh && python3 app.py"
    else
        print_status "   source venv/bin/activate && python3 app.py"
    fi
    print_status ""
    print_status "🌐 Web interface will be available at: http://localhost:$PORT"
    print_status ""
    print_status "⚠️  NOTE: This is a manual startup configuration."
    print_status "   The application will stop when you close the terminal."
    print_status "   To run in background, use: nohup ./start_app.sh &"
    print_status ""
}

# Run main function
main "$@" 