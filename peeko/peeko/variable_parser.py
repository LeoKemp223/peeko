import re
from dataclasses import dataclass, field


@dataclass
class VarPathSegment:
    """A single segment in a variable path, e.g. 'name', 'name[3]'."""
    name: str
    index: int = -1  # -1 means no index

    def __repr__(self):
        if self.index >= 0:
            return f"{self.name}[{self.index}]"
        return self.name


@dataclass
class VarPath:
    """Parsed variable path like 'sensors[0].temperature@main'."""
    segments: list = field(default_factory=list)  # list of VarPathSegment
    file_spec: str = ""  # e.g. "main" from "counter@main"

    @property
    def root_name(self) -> str:
        return self.segments[0].name if self.segments else ""

    def __repr__(self):
        path = ".".join(str(s) for s in self.segments)
        if self.file_spec:
            path += f"@{self.file_spec}"
        return path


# Matches: name, name[index], name[index].member, name.member, etc.
_SEGMENT_RE = re.compile(r'([A-Za-z_]\w*)(?:\[(\d+)\])?')


def _parse_single(var_str: str) -> VarPath:
    """Parse a single variable expression like 'sensors[0].temperature@main'."""
    var_str = var_str.strip()
    if not var_str:
        raise ValueError("Empty variable name")

    file_spec = ""
    if "@" in var_str:
        var_str, file_spec = var_str.rsplit("@", 1)
        file_spec = file_spec.strip()

    segments = []
    for part in var_str.split("."):
        part = part.strip()
        if not part:
            raise ValueError(f"Invalid variable path: empty segment in '{var_str}'")

        # Handle chained indices like name[2][3]
        remaining = part
        first = True
        while remaining:
            m = _SEGMENT_RE.match(remaining)
            if not m:
                raise ValueError(f"Invalid variable syntax: '{part}'")

            name = m.group(1)
            idx = int(m.group(2)) if m.group(2) is not None else -1

            if first:
                segments.append(VarPathSegment(name=name, index=idx))
                first = False
            else:
                segments.append(VarPathSegment(name=name, index=idx))

            remaining = remaining[m.end():]
            # Handle additional [index] without name
            while remaining.startswith("["):
                idx_match = re.match(r'\[(\d+)\]', remaining)
                if not idx_match:
                    raise ValueError(f"Invalid index syntax in '{part}'")
                segments[-1] = VarPathSegment(
                    name=segments[-1].name, index=int(idx_match.group(1)))
                remaining = remaining[idx_match.end():]

    if not segments:
        raise ValueError(f"Invalid variable path: '{var_str}'")

    return VarPath(segments=segments, file_spec=file_spec)


def parse_variables(input_str: str) -> list:
    """Parse comma-separated variable expressions. Returns list of VarPath."""
    results = []
    for part in input_str.split(","):
        part = part.strip()
        if part:
            results.append(_parse_single(part))
    if not results:
        raise ValueError("No variables specified")
    return results


def parse_assignments(input_str: str) -> list:
    """Parse comma-separated 'var=value' pairs. Returns list of (VarPath, value_str)."""
    results = []
    for part in input_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Invalid assignment (missing '='): '{part}'")
        var_str, value_str = part.split("=", 1)
        vp = _parse_single(var_str)
        results.append((vp, value_str.strip()))
    if not results:
        raise ValueError("No assignments specified")
    return results
