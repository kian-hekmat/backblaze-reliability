"""Render the raw-file section of docs/DATA_DICTIONARY.md from the observed column profile.

Null rates come from results/profiling/<quarter>/column_profile.csv (computed, not estimated).
SMART attribute names are the conventional ATA names; meanings of raw values are vendor-specific.

Usage: uv run python scripts/build_raw_dictionary.py Q2_2026 > docs/_raw_columns.md
"""

import sys

import pandas as pd

SMART_NAMES = {
    1: "Read Error Rate", 2: "Throughput Performance", 3: "Spin-Up Time", 4: "Start/Stop Count",
    5: "Reallocated Sectors Count", 7: "Seek Error Rate", 8: "Seek Time Performance",
    9: "Power-On Hours", 10: "Spin Retry Count", 11: "Calibration Retry Count",
    12: "Power Cycle Count", 13: "Soft Read Error Rate", 15: "(vendor-specific)",
    16: "(vendor-specific)", 17: "(vendor-specific)", 18: "Head Health (Seagate)",
    22: "Current Helium Level (HGST/WDC)", 23: "Helium Condition Lower (Toshiba)",
    24: "Helium Condition Upper (Toshiba)", 27: "(vendor-specific)", 71: "(vendor-specific, WDC)",
    82: "(vendor-specific)", 90: "(vendor-specific, WDC)",
    160: "Uncorrectable Sector Count (SSD)", 161: "Valid Spare Blocks (SSD)",
    163: "Initial Invalid Blocks (SSD)", 164: "Total Erase Count (SSD)",
    165: "Max Erase Count (SSD)", 166: "Min Erase Count (SSD)", 167: "Average Erase Count (SSD)",
    168: "SATA PHY Error Count (SSD)", 169: "Remaining Life / Bad Block Rate (SSD)",
    170: "Available Reserved Space (SSD)", 171: "Program Fail Count (SSD)",
    172: "Erase Fail Count (SSD)", 173: "Wear Leveling Count (SSD)",
    174: "Unexpected Power Loss Count (SSD)", 175: "Power Loss Protection Failure (SSD)",
    176: "Erase Fail Count (SSD)", 177: "Wear Range Delta (SSD)", 178: "Used Reserved Block Count (SSD)",
    179: "Used Reserved Block Count Total (SSD)", 180: "Unused Reserved Block Count Total (SSD)",
    181: "Program Fail Count Total", 182: "Erase Fail Count Total (SSD)",
    183: "SATA Downshift Error Count / Runtime Bad Block", 184: "End-to-End Error",
    187: "Reported Uncorrectable Errors", 188: "Command Timeout",
    189: "High Fly Writes", 190: "Airflow Temperature", 191: "G-Sense Error Rate",
    192: "Power-off Retract Count", 193: "Load/Unload Cycle Count", 194: "Temperature (Celsius)",
    195: "Hardware ECC Recovered", 196: "Reallocation Event Count",
    197: "Current Pending Sector Count", 198: "Offline Uncorrectable Sector Count",
    199: "UltraDMA CRC Error Count", 200: "Multi-Zone Error Rate / Write Error Rate",
    201: "Soft Read Error Rate", 202: "Data Address Mark Errors / Percent Lifetime Remaining (SSD)",
    206: "Flying Height", 210: "(vendor-specific)", 211: "(vendor-specific)",
    212: "(vendor-specific)", 218: "CRC Error Count (SSD)", 220: "Disk Shift",
    222: "Loaded Hours", 223: "Load/Unload Retry Count", 224: "Load Friction",
    225: "Load/Unload Cycle Count", 226: "Load-in Time", 230: "GMR Head Amplitude / Drive Life Protection (SSD)",
    231: "Life Left (SSD) / Temperature", 232: "Endurance Remaining / Available Reserved Space (SSD)",
    233: "Media Wearout Indicator (SSD) / Power-On Hours", 234: "Average/Max Erase Count (SSD)",
    235: "Good Block Count / Power-Fail Count (SSD)", 240: "Head Flying Hours",
    241: "Total LBAs Written", 242: "Total LBAs Read", 244: "Average Erase Count (SSD)",
    245: "Max Erase Count (SSD)", 246: "Total Erase Count / Cumulative Host Sectors Written (SSD)",
    247: "Host Program Page Count (SSD)", 248: "FTL Program Page Count (SSD)",
    250: "Read Error Retry Rate", 251: "Minimum Spares Remaining (SSD)",
    252: "Newly Added Bad Flash Block (SSD)", 254: "Free Fall Protection",
    255: "(vendor-specific)",
}

BASE = {
    "date": ("DATE (yyyy-mm-dd string)", "Day of the snapshot. Equals the CSV file name for every row (checked)."),
    "serial_number": ("STRING", "Manufacturer-assigned drive serial number; the drive identifier."),
    "model": ("STRING", "Manufacturer-assigned model. Prefix conventions are inconsistent (see DECISIONS: model normalization)."),
    "capacity_bytes": ("BIGINT", "Drive capacity in bytes."),
    "failure": ("INT 0/1", "1 on the drive's last day in service when it was removed as failed; 0 otherwise. A failed drive does not appear after its failure row (checked)."),
    "datacenter": ("STRING", "Backblaze data center code (e.g. phx1, sac0, iad1, ams5)."),
    "cluster_id": ("STRING (numeric)", "Cluster identifier within the data center."),
    "vault_id": ("STRING (numeric)", "Backblaze Vault identifier (group of 20 pods)."),
    "pod_id": ("STRING (numeric)", "Storage Pod position within the vault."),
    "pod_slot_num": ("STRING (numeric)", "Drive slot within the pod; null for some drives."),
    "is_legacy_format": ("BOOLEAN", "Whether the row uses Backblaze's legacy format; 'false' for every row observed."),
}


def main(quarter: str) -> None:
    prof = pd.read_csv(f"results/profiling/{quarter}/column_profile.csv")
    print(f"| Column | Type | Null rate ({quarter}) | Meaning |")
    print("|---|---|---|---|")
    for r in prof.itertuples():
        if r.column in BASE:
            typ, meaning = BASE[r.column]
        else:
            _, num, kind = r.column.split("_")
            name = SMART_NAMES.get(int(num), "(vendor-specific)")
            typ = "INT" if kind == "normalized" else "BIGINT"
            meaning = (f"SMART {num} {name}: vendor-normalized health value (typically 1-253, higher is healthier)"
                       if kind == "normalized" else f"SMART {num} {name}: raw counter/value (encoding is vendor-specific)")
        print(f"| `{r.column}` | {typ} | {r.null_rate:.4f} | {meaning} |")


if __name__ == "__main__":
    main(sys.argv[1])
