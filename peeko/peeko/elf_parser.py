"""
ELF/DWARF symbol extractor — pure Python replacement for elfsym.exe.

Parses DWARF debug info from ELF files and produces a symbols.json compatible
with the Peeko symbol format.
"""

import json
import os
from datetime import datetime, timezone

from elftools.elf.elffile import ELFFile


def _get_str(die, attr_name):
    attr = die.attributes.get(attr_name)
    if attr is None:
        return None
    val = attr.value
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def _get_int(die, attr_name, default=None):
    attr = die.attributes.get(attr_name)
    if attr is None:
        return default
    val = attr.value
    if hasattr(val, "value"):
        return val.value
    return int(val)


def _get_addr_from_location(loc_attr, addr_size=4):
    """Extract a fixed address from DW_AT_location (DW_OP_addr expression)."""
    if loc_attr is None:
        return None
    if loc_attr.form == "DW_FORM_exprloc":
        val = loc_attr.value
        if len(val) >= 1 + addr_size and val[0] == 0x03:  # DW_OP_addr
            return int.from_bytes(val[1:1 + addr_size], "little")
    return None


class _TypeResolver:
    """Resolves DWARF type DIEs into a flat dictionary description."""

    def __init__(self, die_map, cu_offset):
        self._die_map = die_map
        self._cu_offset = cu_offset

    def _abs(self, cu_relative_offset):
        return self._cu_offset + cu_relative_offset

    def resolve(self, type_attr, depth=0):
        if type_attr is None or depth > 30:
            return {}
        abs_off = self._abs(type_attr.value)
        die = self._die_map.get(abs_off)
        if die is None:
            return {}
        return self._resolve_die(die, depth)

    def _resolve_die(self, die, depth):
        tag = die.tag
        if tag == "DW_TAG_base_type":
            return self._base_type(die)
        if tag == "DW_TAG_typedef":
            return self._typedef(die, depth)
        if tag in ("DW_TAG_volatile_type", "DW_TAG_const_type",
                    "DW_TAG_restrict_type", "DW_TAG_atomic_type"):
            return self._qualifier(die, depth)
        if tag in ("DW_TAG_structure_type", "DW_TAG_union_type"):
            return self._struct_type(die, depth)
        if tag == "DW_TAG_array_type":
            return self._array_type(die, depth)
        if tag == "DW_TAG_enumeration_type":
            return self._enum_type(die, depth)
        if tag == "DW_TAG_pointer_type":
            return self._pointer_type(die)
        return {}

    def _base_type(self, die):
        name = _get_str(die, "DW_AT_name") or "?"
        return {
            "dataType": name,
            "baseDataType": name,
            "sizeInBytes": _get_int(die, "DW_AT_byte_size", 0),
        }

    def _typedef(self, die, depth):
        name = _get_str(die, "DW_AT_name") or "?"
        inner = self.resolve(die.attributes.get("DW_AT_type"), depth + 1)
        result = dict(inner)
        result["dataType"] = name
        if "baseDataType" not in result:
            result["baseDataType"] = name
        return result

    def _qualifier(self, die, depth):
        return self.resolve(die.attributes.get("DW_AT_type"), depth + 1)

    def _struct_type(self, die, depth):
        name = _get_str(die, "DW_AT_name") or "<struct>"
        size = _get_int(die, "DW_AT_byte_size", 0)
        members = []
        for child in die.iter_children():
            if child.tag != "DW_TAG_member":
                continue
            m = self._parse_member(child, depth)
            if m:
                members.append(m)
        result = {
            "dataType": name,
            "baseDataType": "<struct>",
            "sizeInBytes": size,
            "isStruct": True,
            "members": members,
        }
        return result

    def _parse_member(self, die, depth):
        m = {"name": _get_str(die, "DW_AT_name") or "?"}

        # Member offset
        off_attr = die.attributes.get("DW_AT_data_member_location")
        if off_attr is not None:
            val = off_attr.value
            if isinstance(val, list):
                # DWARF expression — typically [DW_OP_plus_uconst, N]
                if len(val) >= 2 and val[0] == 0x23:
                    m["memberOffset"] = val[1]
                else:
                    m["memberOffset"] = 0
            else:
                m["memberOffset"] = int(val)
        else:
            m["memberOffset"] = 0

        # Bit fields (DWARF 2/3 style)
        bit_size = _get_int(die, "DW_AT_bit_size")
        if bit_size is not None:
            m["bitSize"] = bit_size
            bit_offset = _get_int(die, "DW_AT_bit_offset")
            data_bit_offset = _get_int(die, "DW_AT_data_bit_offset")
            if data_bit_offset is not None:
                m["bitOffset"] = data_bit_offset
            elif bit_offset is not None:
                byte_size = _get_int(die, "DW_AT_byte_size", 1)
                m["bitOffset"] = (byte_size * 8) - bit_offset - bit_size

        # Member type
        type_info = self.resolve(die.attributes.get("DW_AT_type"), depth + 1)
        m["dataType"] = type_info.get("dataType", "?")
        m["sizeInBytes"] = type_info.get("sizeInBytes", 0)
        if type_info.get("isStruct"):
            m["isStruct"] = True
            m["members"] = type_info.get("members", [])
        if type_info.get("isArray"):
            m["isArray"] = True
            for k in ("arraySize", "elementSize", "elementType"):
                if k in type_info:
                    m[k] = type_info[k]
        return m

    def _array_type(self, die, depth):
        elem_info = self.resolve(die.attributes.get("DW_AT_type"), depth + 1)
        result = {"isArray": True}
        result["dataType"] = elem_info.get("dataType", "?")
        result["baseDataType"] = elem_info.get("baseDataType", "?")
        result["elementSize"] = elem_info.get("sizeInBytes", 0)
        if elem_info.get("isStruct"):
            result["elementType"] = elem_info.get("dataType", "?")
            result["members"] = elem_info.get("members", [])

        # Array dimensions
        for child in die.iter_children():
            if child.tag == "DW_TAG_subrange_type":
                upper = _get_int(child, "DW_AT_upper_bound")
                count = _get_int(child, "DW_AT_count")
                if upper is not None:
                    result["arraySize"] = upper + 1
                elif count is not None:
                    result["arraySize"] = count

        if "elementSize" in result and "arraySize" in result:
            result["sizeInBytes"] = result["elementSize"] * result["arraySize"]
        return result

    def _enum_type(self, die, depth):
        name = _get_str(die, "DW_AT_name") or "<enum>"
        size = _get_int(die, "DW_AT_byte_size", 4)
        return {
            "dataType": name,
            "baseDataType": "<enum>",
            "sizeInBytes": size,
        }

    def _pointer_type(self, die):
        size = _get_int(die, "DW_AT_byte_size", 4)
        return {
            "dataType": "pointer",
            "baseDataType": "pointer",
            "sizeInBytes": size,
        }


def parse_elf(elf_path: str) -> dict:
    """
    Parse an ELF file and extract global variable symbols.

    Returns a dict in the Peeko symbols.json format.
    """
    with open(elf_path, "rb") as f:
        elf = ELFFile(f)
        if not elf.has_dwarf_info():
            raise ValueError(f"No DWARF debug info in {elf_path}. "
                             "Compile with -g flag.")

        addr_size = 4 if elf.elfclass == 32 else 8
        dwarf = elf.get_dwarf_info()
        symbols = []

        for cu in dwarf.iter_CUs():
            top_die = cu.get_top_DIE()
            cu_file = _get_str(top_die, "DW_AT_name") or "?"
            # Simplify path to just filename
            source_file = os.path.basename(cu_file)

            # Build offset -> DIE map for this CU
            die_map = {}
            for die in cu.iter_DIEs():
                die_map[die.offset] = die

            resolver = _TypeResolver(die_map, cu.cu_offset)

            # Scan for global variables with fixed addresses
            for die in die_map.values():
                if die.tag != "DW_TAG_variable":
                    continue

                loc_attr = die.attributes.get("DW_AT_location")
                addr = _get_addr_from_location(loc_attr, addr_size)
                if addr is None:
                    continue

                name = _get_str(die, "DW_AT_name")
                type_attr = die.attributes.get("DW_AT_type")

                # Follow DW_AT_specification for name/type
                spec_attr = die.attributes.get("DW_AT_specification")
                if spec_attr is not None:
                    abs_off = cu.cu_offset + spec_attr.value
                    spec_die = die_map.get(abs_off)
                    if spec_die:
                        if name is None:
                            name = _get_str(spec_die, "DW_AT_name")
                        if type_attr is None:
                            type_attr = spec_die.attributes.get("DW_AT_type")

                if name is None:
                    continue

                type_info = resolver.resolve(type_attr)
                if not type_info:
                    continue

                sym = {
                    "name": name,
                    "dataType": type_info.get("dataType", "?"),
                    "baseDataType": type_info.get("baseDataType",
                                                  type_info.get("dataType", "?")),
                    "sizeInBytes": type_info.get("sizeInBytes", 0),
                    "memoryAddress": f"0x{addr:08X}",
                    "sourceFile": source_file,
                }

                if type_info.get("isStruct"):
                    sym["isStruct"] = True
                    members = type_info.get("members", [])
                    _fill_member_addresses(members, addr)
                    sym["members"] = members

                if type_info.get("isArray"):
                    sym["isArray"] = True
                    for k in ("arraySize", "elementSize", "elementType"):
                        if k in type_info:
                            sym[k] = type_info[k]
                    if type_info.get("members"):
                        sym["members"] = type_info["members"]

                symbols.append(sym)

    result = {
        "schemaVersion": "1.0",
        "toolVersion": "peeko-pyelftools",
        "exportTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sourceElfFile": os.path.basename(elf_path),
        "totalSymbols": len(symbols),
        "symbols": symbols,
    }
    return result


def _fill_member_addresses(members, base_addr):
    """Compute absolute memoryAddress for each struct member."""
    for m in members:
        offset = m.get("memberOffset", 0)
        m["memoryAddress"] = f"0x{base_addr + offset:08X}"
        if "members" in m:
            _fill_member_addresses(m["members"], base_addr + offset)


def create_symbols_json(elf_path: str, output_path: str) -> int:
    """Parse ELF and write symbols.json. Returns symbol count."""
    data = parse_elf(elf_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data["totalSymbols"]
