"""
Memory analyzer — ELF firmware memory usage analysis.

Parses ELF sections and DWARF symbols to produce a memory usage report:
  - Section sizes (Flash vs RAM classification)
  - Top N largest global variables
  - Per-source-file RAM usage breakdown
"""

import json
import os
from collections import defaultdict

from elftools.elf.elffile import ELFFile
from elftools.elf.constants import SH_FLAGS

from peeko.elf_parser import parse_elf


def _format_size(size_bytes):
    """Format byte count as human-readable string."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def _classify_section(name, flags, sec_type):
    """Classify a section as 'flash', 'ram', or None (skip)."""
    if not (flags & SH_FLAGS.SHF_ALLOC):
        return None

    is_write = bool(flags & SH_FLAGS.SHF_WRITE)
    is_exec = bool(flags & SH_FLAGS.SHF_EXECINSTR)

    ram_names = {".data", ".sdata", ".bss", ".sbss", ".common",
                 ".noinit", ".heap", ".stack"}
    flash_names = {".text", ".rodata", ".srodata", ".init", ".fini",
                   ".init_array", ".fini_array", ".ARM.exidx",
                   ".ARM.extab", ".isr_vector"}

    if name in flash_names:
        return "flash"
    if name in ram_names:
        return "ram"

    # ESP-IDF / vendor-specific naming conventions
    name_lower = name.lower()
    for kw in (".rodata", ".text", "flash", "iram", "vectors"):
        if kw in name_lower:
            return "flash"
    for kw in (".dram", ".bss", ".data", "rtc.data", ".noinit"):
        if kw in name_lower:
            return "ram"

    if is_exec:
        return "flash"
    if is_write:
        return "ram"
    return "flash"


def analyze_sections(elf_path):
    """Parse ELF sections and return classified section info.

    Returns dict with keys: sections (list), flash_total, ram_total.
    """
    sections = []
    flash_total = 0
    ram_total = 0

    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        for sec in elf.iter_sections():
            name = sec.name
            size = sec["sh_size"]
            addr = sec["sh_addr"]
            flags = sec["sh_flags"]
            sec_type = sec["sh_type"]

            if size == 0 or not name:
                continue

            category = _classify_section(name, flags, sec_type)
            if category is None:
                continue

            sections.append({
                "name": name,
                "address": f"0x{addr:08X}",
                "size": size,
                "category": category,
            })

            if category == "flash":
                flash_total += size
            else:
                ram_total += size

    sections.sort(key=lambda s: int(s["address"], 16))

    return {
        "sections": sections,
        "flash_total": flash_total,
        "ram_total": ram_total,
    }


def _analyze_symbols(symbols, top_n=10):
    """Analyze symbol list for variable ranking and per-file breakdown.

    Returns (top_variables_dict, by_file_dict).
    """
    total_size = sum(s.get("sizeInBytes", 0) for s in symbols)

    ranked = sorted(symbols, key=lambda s: s.get("sizeInBytes", 0), reverse=True)
    top = []
    for sym in ranked[:top_n]:
        top.append({
            "name": sym["name"],
            "size": sym.get("sizeInBytes", 0),
            "dataType": sym.get("dataType", "?"),
            "sourceFile": sym.get("sourceFile", "?"),
        })

    top_variables = {
        "variables": top,
        "total_count": len(symbols),
        "total_size": total_size,
    }

    by_file_map = defaultdict(lambda: {"count": 0, "total_size": 0})
    for sym in symbols:
        src = sym.get("sourceFile", "?")
        by_file_map[src]["count"] += 1
        by_file_map[src]["total_size"] += sym.get("sizeInBytes", 0)

    files = []
    for src, info in sorted(by_file_map.items(),
                            key=lambda x: x[1]["total_size"], reverse=True):
        files.append({
            "sourceFile": src,
            "variables": info["count"],
            "totalSize": info["total_size"],
        })

    by_file = {"files": files}

    return top_variables, by_file


def analyze(elf_path, top_n=10):
    """Run full memory analysis. Returns a structured dict.

    Parses the ELF only once for both section and symbol analysis.
    """
    sections = analyze_sections(elf_path)

    sym_data = parse_elf(elf_path)
    symbols = sym_data.get("symbols", [])
    top_variables, by_file = _analyze_symbols(symbols, top_n)

    return {
        "elfFile": os.path.basename(elf_path),
        "sections": sections,
        "topVariables": top_variables,
        "byFile": by_file,
    }


def format_report(analysis):
    """Format analysis dict as a human-readable text report."""
    lines = []

    sec = analysis["sections"]
    lines.append("=== Memory Sections ===")
    lines.append(f"{'Section':<20} {'Size':>10}    {'Address'}")
    for s in sec["sections"]:
        lines.append(
            f"{s['name']:<20} {_format_size(s['size']):>10}    {s['address']}"
        )
    lines.append("")
    lines.append(
        f"Flash: {_format_size(sec['flash_total'])}    "
        f"RAM: {_format_size(sec['ram_total'])}"
    )

    tv = analysis["topVariables"]
    n = len(tv["variables"])
    lines.append("")
    lines.append(f"=== Top {n} Variables by Size ===")
    lines.append(f"{'#':>3}  {'Name':<32} {'Size':>10}  {'Type':<20} {'Source'}")
    for i, v in enumerate(tv["variables"], 1):
        lines.append(
            f"{i:>3}  {v['name']:<32} {_format_size(v['size']):>10}  "
            f"{v['dataType']:<20} {v['sourceFile']}"
        )
    lines.append("")
    lines.append(
        f"Total: {tv['total_count']} variables, "
        f"{_format_size(tv['total_size'])}"
    )

    bf = analysis["byFile"]
    lines.append("")
    lines.append("=== RAM Usage by Source File ===")
    lines.append(f"{'Source File':<32} {'Vars':>6}   {'Total Size':>10}")
    for f in bf["files"]:
        lines.append(
            f"{f['sourceFile']:<32} {f['variables']:>6}   "
            f"{_format_size(f['totalSize']):>10}"
        )

    return "\n".join(lines)
