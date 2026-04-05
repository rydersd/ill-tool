#!/usr/bin/env python3
"""
gen-pipl.py — Generate binary PiPL resource for Illustrator plugin.

Produces a raw .rsrc file containing the PiPL (Plug-in Property List) that
Illustrator's PICA/Sweet Pea loader uses to identify and load plugins.

Binary format (big-endian):
  [4] pipl_count          — number of PiPL objects (always 1 for us)
  For each PiPL:
    [4] version           — always 0
    [4] property_count    — number of properties
    For each property:
      [4] vendor          — ASCII fourcc (e.g. 'ADBE')
      [4] key             — ASCII fourcc (e.g. 'kind', 'ivrs', 'mi32', 'pinm', 'StsP')
      [4] id              — property ID (usually 0)
      [4] data_length     — byte length of value (padded to 4-byte alignment)
      [N] data            — value bytes

Usage:
  python3 gen-pipl.py [output_path]
  Default output: ../resources/pipl.rsrc
"""

import struct
import sys
import os


def pad4(data: bytes) -> bytes:
    """Pad byte string to next 4-byte boundary."""
    remainder = len(data) % 4
    if remainder:
        data += b'\x00' * (4 - remainder)
    return data


def write_property(buf: bytearray, vendor: str, key: str, value: bytes, pid: int = 0):
    """Append one PiPL property to the buffer."""
    buf += vendor.encode('ascii')           # 4 bytes: vendor
    buf += key.encode('ascii')              # 4 bytes: key
    buf += struct.pack('>I', pid)           # 4 bytes: property ID
    padded = pad4(value)
    buf += struct.pack('>I', len(padded))   # 4 bytes: data length
    buf += padded                           # N bytes: data


def generate_pipl(
    plugin_name: str = "IllTool Overlay",
    entry_point: str = "PluginMain",
    output_path: str = None,
):
    """Generate a binary PiPL .rsrc file."""

    if output_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, '..', 'resources', 'pipl.rsrc')

    buf = bytearray()

    # Resource count (always 1 — one PiPL in this file)
    buf += struct.pack('>I', 1)

    # PiPL header
    buf += struct.pack('>I', 0)  # version (always 0)
    buf += struct.pack('>I', 4)  # property count

    # Property 1: kind — identifies as a Sweet Pea (PICA) plugin
    write_property(buf, 'ADBE', 'kind', b'SPEA')

    # Property 2: ivrs — interface version (2 = current)
    write_property(buf, 'ADBE', 'ivrs', struct.pack('>I', 2))

    # Property 3: mi32 — macOS entry point (empty = resolve by symbol name)
    write_property(buf, 'ADBE', 'mi32', b'')

    # Property 4: pinm — plugin display name
    name_bytes = plugin_name.encode('ascii') + b'\x00'
    write_property(buf, 'ADBE', 'pinm', name_bytes)

    # Write output
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'wb') as f:
        f.write(buf)

    print(f"PiPL resource generated: {output_path} ({len(buf)} bytes)")
    return output_path


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else None
    generate_pipl(output_path=out)
