"""
Peeko MCP Server — expose peeko CLI as MCP tools for AI assistants.

Requires: Python >= 3.10, mcp SDK (pip install mcp)

Usage:
    python -m peeko.mcp_server              # stdio transport (Claude Desktop / Cursor)
    python -m peeko.mcp_server --sse 8080   # SSE transport (HTTP clients)
"""

from __future__ import annotations

import subprocess
import sys
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "peeko",
    instructions="Peeko: read/write MCU RAM variables by name over serial. "
                 "Call peeko_create first to generate symbols from ELF, "
                 "then peeko_open to connect, then peeko_get/peeko_set to interact.",
)

_PEEKO_CMD = [sys.executable, "-m", "peeko"]
_PEEKO_CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(*args: str, timeout: int = 30) -> str:
    """Run a peeko CLI command and return stdout."""
    try:
        result = subprocess.run(
            _PEEKO_CMD + list(args),
            capture_output=True, text=True, timeout=timeout,
            cwd=_PEEKO_CWD,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            err = result.stderr.strip() or output
            return f"Error: {err}"
        return output or "OK"
    except subprocess.TimeoutExpired:
        return "Error: command timed out"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def peeko_ports() -> str:
    """List available serial ports on this machine."""
    return _run("ports")


@mcp.tool()
def peeko_status() -> str:
    """Show current connection status (port, baud, symbols)."""
    return _run("status")


@mcp.tool()
def peeko_create(elf_file: str, output: str = "symbols.json") -> str:
    """Generate symbols.json from an ELF firmware file.

    Args:
        elf_file: Path to the ELF file (must contain DWARF debug info, compiled with -g).
        output: Output symbols file path. Defaults to "symbols.json".
    """
    return _run("create", elf_file, "-o", output)


@mcp.tool()
def peeko_open(port: str, baud: int = 115200, endian: str = "little") -> str:
    """Connect to MCU via serial port.

    Args:
        port: Serial port name, e.g. "COM3" or "/dev/ttyUSB0".
        baud: Baud rate. Defaults to 115200.
        endian: Byte order, "little" or "big". Defaults to "little".
    """
    return _run("open", "--name", port, "--baud", str(baud), "--endian", endian)


@mcp.tool()
def peeko_close() -> str:
    """Disconnect from MCU."""
    return _run("close")


@mcp.tool()
def peeko_get(variables: str, interval_ms: Optional[int] = None, count: Optional[int] = None) -> str:
    """Read one or more variables from MCU RAM.

    Args:
        variables: Variable name(s), comma-separated. Supports struct members
                   (sensor.temperature), array index (buffer[3]), file specifier
                   (counter@main.c).
        interval_ms: If set, read periodically at this interval in milliseconds.
        count: Number of reads. 0 means infinite (use with interval_ms). Defaults to 1 when interval_ms is set.
    """
    args = ["get", variables]
    if interval_ms is not None:
        args += ["-i", str(interval_ms)]
        if count is not None:
            args += ["-c", str(count)]
        else:
            args += ["-c", "1"]
    return _run(*args)


@mcp.tool()
def peeko_analyze(elf_file: str, top_n: int = 10) -> str:
    """Analyze firmware memory usage from ELF file.

    Returns section sizes (Flash/RAM), top variables by size, and per-file breakdown.

    Args:
        elf_file: Path to the ELF file (must contain DWARF debug info).
        top_n: Number of largest variables to show. Defaults to 10.
    """
    return _run("analyze", elf_file, "--top", str(top_n), "--json")


@mcp.tool()
def peeko_set(assignments: str, interval_ms: Optional[int] = None, count: Optional[int] = None) -> str:
    """Write one or more variables to MCU RAM.

    Args:
        assignments: Comma-separated var=value pairs, e.g. "motor_speed=1500"
                     or "speed=100,direction=1". Values support decimal, hex (0xFF),
                     binary (0b1010), float (3.14), bool (true/false).
        interval_ms: If set, write periodically at this interval in milliseconds.
        count: Number of writes. 0 means infinite. Defaults to 1 when interval_ms is set.
    """
    args = ["set", assignments]
    if interval_ms is not None:
        args += ["-i", str(interval_ms)]
        if count is not None:
            args += ["-c", str(count)]
        else:
            args += ["-c", "1"]
    return _run(*args)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Peeko MCP Server")
    parser.add_argument("--sse", type=int, metavar="PORT",
                        help="Run as SSE server on given port (default: stdio)")
    args = parser.parse_args()

    if args.sse:
        mcp.run(transport="sse", sse_params={"port": args.sse})
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
