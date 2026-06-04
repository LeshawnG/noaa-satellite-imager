#!/bin/bash

# =============================================================================
# SD Card Permission Fix Script
# =============================================================================
# This script helps fix SD card mounting issues for Python virtual environments
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Function to find SD card mount point
find_sd_mount() {
    # Common SD card mount patterns
    for pattern in "/media/$USER/WeatherImag" "/media/*/WeatherImag*" "/mnt/WeatherImag*"; do
        if ls $pattern 2>/dev/null; then
            echo $pattern
            return 0
        fi
    done
    return 1
}

# Function to check current mount options
check_mount_options() {
    local mountpoint="$1"
    print_status "Current mount options for $mountpoint:"
    mount | grep "$mountpoint" | head -1
}

# Function to remount with better options
remount_with_permissions() {
    local mountpoint="$1"
    local device=$(mount | grep "$mountpoint" | cut -d' ' -f1)
    
    print_status "Attempting to remount $device at $mountpoint with better permissions..."
    
    # Try to remount with options that support symlinks and proper permissions
    if sudo mount -o remount,uid=$(id -u),gid=$(id -g),fmask=0022,dmask=0022 "$mountpoint" 2>/dev/null; then
        print_success "Successfully remounted with improved permissions"
        return 0
    elif sudo mount -o remount,rw,exec,dev "$mountpoint" 2>/dev/null; then
        print_success "Successfully remounted with basic permissions"
        return 0
    else
        print_warning "Could not remount - filesystem may not support these options"
        return 1
    fi
}

# Main function
main() {
    print_status "SD Card Permission Fix Tool"
    print_status "============================="
    
    # Find the SD card mount point
    sd_mount=$(find_sd_mount)
    
    if [ -z "$sd_mount" ]; then
        print_error "Could not find SD card mount point"
        print_status "Please check that your SD card is mounted and try again"
        print_status "Common mount points: /media/$USER/WeatherImag or /mnt/WeatherImag"
        exit 1
    fi
    
    print_success "Found SD card at: $sd_mount"
    
    # Check current mount options
    check_mount_options "$sd_mount"
    
    # Test symlink support
    cd "$sd_mount" 2>/dev/null || {
        print_error "Cannot access SD card directory: $sd_mount"
        exit 1
    }
    
    test_file="__test_symlink_$$"
    test_link="__test_link_$$"
    
    echo "test" > "$test_file" 2>/dev/null
    if ln -s "$test_file" "$test_link" 2>/dev/null; then
        print_success "Filesystem supports symbolic links"
        rm -f "$test_file" "$test_link" 2>/dev/null
    else
        print_warning "Filesystem does not support symbolic links"
        rm -f "$test_file" "$test_link" 2>/dev/null
        
        # Try to remount with better options
        print_status "Attempting to fix mount options..."
        if remount_with_permissions "$sd_mount"; then
            # Test again
            echo "test" > "$test_file" 2>/dev/null
            if ln -s "$test_file" "$test_link" 2>/dev/null; then
                print_success "Filesystem now supports symbolic links!"
                rm -f "$test_file" "$test_link" 2>/dev/null
            else
                print_warning "Still cannot create symbolic links - will use --copies flag"
                rm -f "$test_file" "$test_link" 2>/dev/null
            fi
        fi
    fi
    
    print_status ""
    print_status "Recommendations:"
    print_status "1. Use the fixed deployment script: ./deploy_pi_fixed.sh"
    print_status "2. If you continue having issues, consider formatting the SD card as ext4"
    print_status "3. Alternatively, you can run the project from your home directory"
    print_status ""
    print_status "To format SD card as ext4 (WARNING: This will erase all data!):"
    print_status "  sudo mkfs.ext4 /dev/sdX1  # Replace sdX1 with your SD card device"
    print_status ""
}

main "$@" 