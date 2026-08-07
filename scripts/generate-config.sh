#!/bin/sh
set -eu

: "${MONITORING_IP:?}" "${PROXMOX_IP:?}" "${NEXTCLOUD_CT_IP:?}" "${DISCORD_VM_IP:?}" "${NEXTCLOUD_URL:?}"
: "${DISCORD_VM_ID:?}" "${NEXTCLOUD_CT_ID:?}"
: "${PVE_TOKEN_VALUE:?}"

sed \
  -e "s|MONITORING_IP|${MONITORING_IP}|g" \
  -e "s|PROXMOX_IP|${PROXMOX_IP}|g" \
  -e "s|NEXTCLOUD_CT_IP|${NEXTCLOUD_CT_IP}|g" \
  -e "s|DISCORD_VM_IP|${DISCORD_VM_IP}|g" \
  -e "s|NEXTCLOUD_URL|${NEXTCLOUD_URL}|g" \
  /templates/prometheus.yml.example > /output/prometheus/prometheus.yml

sed \
  -e "s|DISCORD_VM_ID|${DISCORD_VM_ID}|g" \
  -e "s|NEXTCLOUD_CT_ID|${NEXTCLOUD_CT_ID}|g" \
  /templates/homelab.yml.example > /output/rules/homelab.yml

sed \
  -e "s|PASTE_TOKEN_SECRET_HERE|${PVE_TOKEN_VALUE}|g" \
  /templates/pve.yml.example > /output/pve/pve.yml

echo "Generated prometheus.yml, rules/homelab.yml, pve.yml from .example templates"
