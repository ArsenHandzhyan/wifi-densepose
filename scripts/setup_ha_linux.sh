#!/bin/bash
#
# Setup Home Assistant on Linux VM for full FP2 integration
# This script creates a Linux VM using QEMU (built-in on macOS)
#

set -e

VM_NAME="ha-fp2"
VM_DIR="$HOME/.ha-vm"
VM_DISK="$VM_DIR/ubuntu.qcow2"
VM_SIZE="20G"
VM_MEM="4096"
VM_CPUS="2"
UBUNTU_IMG="https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"

echo "=========================================="
echo "Home Assistant Linux VM Setup"
echo "=========================================="
echo ""

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "This script is for macOS only"
    exit 1
fi

# Create VM directory
mkdir -p "$VM_DIR"

# Download Ubuntu cloud image if not exists
if [ ! -f "$VM_DISK" ]; then
    echo "Downloading Ubuntu 22.04 cloud image..."
    curl -L "$UBUNTU_IMG" -o "$VM_DIR/ubuntu-base.img"
    
    echo "Creating VM disk ($VM_SIZE)..."
    qemu-img create -f qcow2 -b "$VM_DIR/ubuntu-base.img" -F qcow2 "$VM_DISK" "$VM_SIZE"
fi

# Create cloud-init config
cat > "$VM_DIR/user-data" << 'EOF'
#cloud-config
hostname: ha-fp2
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC... # Will be replaced
package_update: true
packages:
  - docker.io
  - docker-compose
  - avahi-daemon
  - net-tools
runcmd:
  - systemctl enable docker
  - systemctl start docker
  - usermod -aG docker ubuntu
  - |
    # Install Home Assistant Container
    docker run -d \
      --name homeassistant \
      --privileged \
      --restart=unless-stopped \
      -e TZ=Europe/Moscow \
      -v /home/ubuntu/ha-config:/config \
      --network=host \
      ghcr.io/home-assistant/home-assistant:stable
EOF

cat > "$VM_DIR/meta-data" << 'EOF'
instance-id: ha-fp2
local-hostname: ha-fp2
EOF

# Create ISO for cloud-init
echo "Creating cloud-init ISO..."
hdiutil makehybrid -o "$VM_DIR/cloud-init.iso" "$VM_DIR" -iso -default-volume-name cidata 2>/dev/null || \
    mkisofs -output "$VM_DIR/cloud-init.iso" -volid cidata -joliet -rock "$VM_DIR/user-data" "$VM_DIR/meta-data" 2>/dev/null || \
    echo "Please install cdrtools: brew install cdrtools"

echo ""
echo "=========================================="
echo "VM Setup Complete"
echo "=========================================="
echo ""
echo "To start the VM, run:"
echo "  qemu-system-x86_64 \\"
echo "    -name $VM_NAME \\"
echo "    -m $VM_MEM \\"
echo "    -smp $VM_CPUS \\"
echo "    -hda $VM_DISK \\"
echo "    -cdrom $VM_DIR/cloud-init.iso \\"
echo "    -netdev user,id=net0,hostfwd=tcp::8123-:8123 \\"
echo "    -device e1000,netdev=net0 \\"
echo "    -nographic"
echo ""
echo "Or use the start script:"
echo "  ./scripts/start_ha_vm.sh"
