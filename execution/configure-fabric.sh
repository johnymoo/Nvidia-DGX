#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Usage: sudo $0 INTERFACE LOCAL_CIDR PEER_IP" >&2
  exit 1
fi

interface="$1"
local_cidr="$2"
peer_ip="$3"
connection="gb10-ds4-fabric-$interface"

if [ "$(id -u)" -ne 0 ]; then
  echo "This command requires root." >&2
  exit 1
fi

if [ ! -d "/sys/class/net/$interface" ]; then
  echo "Unknown interface: $interface" >&2
  exit 1
fi

if [ "$(cat "/sys/class/net/$interface/carrier" 2>/dev/null || echo 0)" != "1" ]; then
  echo "$interface has no physical carrier; connect the fabric before applying config." >&2
  exit 2
fi

if nmcli -g NAME connection show | grep -Fxq "$connection"; then
  nmcli connection modify "$connection" \
    connection.interface-name "$interface" \
    ipv4.method manual ipv4.addresses "$local_cidr" \
    ipv4.never-default yes ipv6.method disabled ethernet.mtu 9000
else
  nmcli connection add type ethernet ifname "$interface" con-name "$connection" \
    ipv4.method manual ipv4.addresses "$local_cidr" \
    ipv4.never-default yes ipv6.method disabled ethernet.mtu 9000
fi

nmcli connection up "$connection"
ip -br address show dev "$interface"
rdma link show
show_gids || true
ping -c 3 -W 2 "$peer_ip"
