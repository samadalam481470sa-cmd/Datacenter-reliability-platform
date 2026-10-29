# Live data-center connector — Redfish (read-only)

RackHelm can now collect measurements from servers and chassis implementing the **DMTF Redfish REST API**, including many Dell iDRAC, HPE iLO and Lenovo XClarity BMCs. This is a **read-only polling connector**: it does not reboot servers, change fan speeds, flash firmware, alter BIOS, or send Redfish POST/PATCH/DELETE commands.

## What you need

- Authorized access to the data center **management network** (VPN/bastion/segmented collector host).
- A **read-only** Redfish account for each BMC, TLS certificates trusted by the collector, and a documented asset-to-rack mapping.
- A RackHelm backend in **secure mode** with persistent storage and an operator ingestion key. Do **not** ingest real telemetry into the public synthetic demo.
- BMC firmware exposing `/redfish/v1/Chassis/.../Thermal` and `/Power` (paths vary by vendor; adjust the JSON configuration). Some vendors use newer `ThermalSubsystem`/`PowerSubsystem` resources, which require an adapter not yet implemented.

## Setup

```bash
python -m pip install -e '.[dev]'
cp config/redfish.example.json config/redfish.local.json
# Edit rack IDs, BMC HTTPS origins, vendor-specific resource paths and CA bundle.
export RACKHELM_REDFISH_USER_01='readonly-operator'
export RACKHELM_REDFISH_PASS_01='retrieve-from-your-secret-manager'
export RACKHELM_OPERATOR_KEY='a-private-random-value-at-least-32-characters'
export RACKHELM_MODE=secure
export RACKHELM_DB_PATH=/var/lib/rackhelm/rackhelm.db
uvicorn rackhelm.api:app --host 127.0.0.1 --port 8000
```

In a separate terminal with the Redfish credentials and ingestion key:

```bash
python scripts/poll_redfish.py --config config/redfish.local.json --dry-run
python scripts/poll_redfish.py --config config/redfish.local.json
python scripts/poll_redfish.py --config config/redfish.local.json --interval 60
```

For remote RackHelm deployments, configure `rackhelm_url` with an HTTPS origin and terminate TLS at a trusted reverse proxy. Store the config without credentials; credentials are resolved only from environment variables. Never commit local configs or credentials.

## Measurements and limitations

| Field | Redfish source | Notes |
|---|---|---|
| `inlet_c` | Thermal.Temperatures matching inlet/intake/ambient | Required; no fabricated reading |
| `outlet_c` | Thermal.Temperatures matching outlet/exhaust | Falls back to inlet if absent; not a measured outlet |
| `power_kw` | Power.PowerControl.PowerConsumedWatts | Required; converted from watts |
| `fan_rpm` | Thermal.Fans.Reading | Required and must explicitly report RPM |
| `gpu_util_pct` | Optional `Oem.RackHelm.GpuUtilizationPercent` | Defaults to zero if unavailable; not a measured GPU value |
| `ecc_errors` | Optional `Oem.RackHelm.EccErrors` | Defaults to zero if unavailable |
| `packet_loss_pct` | Optional `Oem.RackHelm.PacketLossPercent` | Defaults to zero if unavailable |

**Important:** This connector collects *one configured chassis per rack ID*, not automatically every machine in the rack. If the chassis is not a rack-level monitoring device, its readings must not be represented as the entire rack's thermal/power state. Vendor-specific mappings and aggregation need validation against physical equipment before operational use. Optional zero-filled GPU/network fields must not be interpreted as proof of healthy equipment. Redfish is not universally supported or consistent across BMC models.

## Security boundary

- Explicit BMC allowlist in JSON; no subnet scans or service discovery.
- HTTPS with certificate verification; no `verify=False` option.
- No redirects, no arbitrary URL ingestion, bounded 1 MB responses, 8-second request timeout.
- Credentials stay in environment variables and are never embedded in the JSON config.
- Connector prints generic error types rather than raw response bodies or secret-bearing URLs.
- **Redfish GET requests only**. RackHelm ingestion is a separate authenticated POST to the application, not to BMCs.
- Deploy behind a restricted management VLAN, apply firewall egress allowlists and DNS pinning, and use a secrets manager for production. DNS rebinding and compromised trusted BMCs require network-level controls; this code alone is not a complete SSRF defense.

**Status:** Connector implementation and unit tests are complete. **Not validated against a real BMC** because no authorized server credentials or live data-center network were provided.