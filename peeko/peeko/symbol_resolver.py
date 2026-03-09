import json
from dataclasses import dataclass
from peeko.config import NO_BITFIELD
from peeko.variable_parser import VarPath


@dataclass
class ResolvedVar:
    """A fully resolved variable with physical address and type info."""
    address: int
    size: int
    data_type: str
    bit_offset: int = NO_BITFIELD
    bit_size: int = NO_BITFIELD


class SymbolResolveError(Exception):
    pass


class SymbolResolver:
    """Loads symbols.json and resolves variable paths to addresses."""

    def __init__(self, json_path: str):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._symbols = data.get("symbols", [])
        self._by_name = {}  # name -> list of symbols (may have duplicates across files)
        for sym in self._symbols:
            name = sym["name"]
            self._by_name.setdefault(name, []).append(sym)

    def list_symbols(self, pattern: str = None) -> list:
        """List all symbol names, optionally filtered by substring pattern."""
        names = []
        for sym in self._symbols:
            name = sym["name"]
            if pattern is None or pattern.lower() in name.lower():
                names.append(name)
        return names

    def get_all_symbols(self) -> list:
        """Return the raw symbols list for completer usage."""
        return self._symbols

    def resolve(self, var_path: VarPath) -> ResolvedVar:
        """Resolve a VarPath to a ResolvedVar with address, size, type, bit info."""
        root_name = var_path.root_name
        candidates = self._by_name.get(root_name, [])

        if not candidates:
            raise SymbolResolveError(f"Variable not found: {root_name}")

        # Filter by file spec if provided
        if var_path.file_spec:
            filtered = [s for s in candidates
                        if var_path.file_spec in s.get("sourceFile", "")]
            if not filtered:
                raise SymbolResolveError(
                    f"Variable not found: {root_name}@{var_path.file_spec}")
            candidates = filtered

        if len(candidates) > 1 and not var_path.file_spec:
            files = [s.get("sourceFile", "?") for s in candidates]
            raise SymbolResolveError(
                f"Ambiguous variable '{root_name}' found in: {', '.join(files)}. "
                f"Use @filename to specify, e.g. {root_name}@{files[0].split('.')[0]}")

        sym = candidates[0]
        return self._resolve_path(sym, var_path.segments, 0)

    def _resolve_path(self, sym: dict, segments: list, seg_idx: int) -> ResolvedVar:
        """Recursively resolve segments into the symbol tree."""
        seg = segments[seg_idx]
        addr = _parse_addr(sym.get("memoryAddress", sym.get("address", "0")))
        size = sym.get("sizeInBytes", 0)
        data_type = sym.get("dataType", sym.get("baseDataType", ""))
        base_type = sym.get("baseDataType", data_type)
        bit_offset = NO_BITFIELD
        bit_size = NO_BITFIELD

        # Handle bitfield
        if "bitOffset" in sym:
            bit_offset = sym["bitOffset"]
            bit_size = sym.get("bitSize", 1)

        # Handle array index on current segment
        if seg.index >= 0:
            if sym.get("isArray"):
                elem_size = sym.get("elementSize", size)
                array_size = sym.get("arraySize", 0)
                if array_size and seg.index >= array_size:
                    raise SymbolResolveError(
                        f"Array index {seg.index} out of range "
                        f"(size={array_size}) for '{seg.name}'")
                addr += seg.index * elem_size
                size = elem_size
                # If array of structs, use element type info
                if "elementType" in sym:
                    data_type = sym["elementType"]
                    base_type = data_type
            else:
                # Treat as byte-offset array access
                elem_size = _guess_element_size(sym)
                addr += seg.index * elem_size
                size = elem_size

        # If there are more segments, dive into members
        next_idx = seg_idx + 1
        if next_idx < len(segments):
            next_seg = segments[next_idx]
            members = sym.get("members", [])
            if not members:
                raise SymbolResolveError(
                    f"'{seg.name}' has no members, cannot access '.{next_seg.name}'")

            member = None
            for m in members:
                if m.get("name") == next_seg.name:
                    member = m
                    break

            if member is None:
                available = [m.get("name", "?") for m in members]
                raise SymbolResolveError(
                    f"Member '{next_seg.name}' not found in '{seg.name}'. "
                    f"Available: {', '.join(available)}")

            # Member address: use memoryAddress if absolute, or base + memberOffset
            if "memoryAddress" in member:
                member_addr = _parse_addr(member["memoryAddress"])
            else:
                member_addr = addr + member.get("memberOffset", 0)

            member_with_addr = dict(member)
            member_with_addr["memoryAddress"] = hex(member_addr)

            return self._resolve_path(member_with_addr, segments, next_idx)

        return ResolvedVar(
            address=addr,
            size=size,
            data_type=data_type if data_type else base_type,
            bit_offset=bit_offset,
            bit_size=bit_size,
        )


def _parse_addr(addr) -> int:
    if isinstance(addr, int):
        return addr
    if isinstance(addr, str):
        return int(addr, 0)
    return 0


def _guess_element_size(sym: dict) -> int:
    """Guess element size from type info for simple arrays."""
    dt = sym.get("dataType", "").lower()
    size = sym.get("sizeInBytes", 1)
    if "8" in dt or "char" in dt or "bool" in dt:
        return 1
    if "16" in dt or "short" in dt:
        return 2
    if "64" in dt or "double" in dt or "long long" in dt:
        return 8
    if "32" in dt or "int" in dt or "float" in dt or "long" in dt:
        return 4
    return size
