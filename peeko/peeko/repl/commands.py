import os
import time
import shlex

from peeko.config import NO_BITFIELD, DEFAULT_BAUD
from peeko.protocol import VarInfo, ProtocolError
from peeko.symbol_resolver import SymbolResolveError
from peeko.variable_parser import parse_variables, parse_assignments
from peeko.serial_manager import list_ports


def _check_esc() -> bool:
    try:
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch == b'\x1b':
                return True
    except ImportError:
        pass
    return False


def handle_command(session, line: str) -> str:
    """Dispatch a /command. Returns output string or None to quit."""
    line = line.strip()
    if not line:
        return ""

    if line.startswith("/"):
        parts = line[1:].split(None, 1)
        cmd = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        return _dispatch_slash(session, cmd, args)

    # Shortcut: var=value → write
    if "=" in line and not line.startswith("/"):
        return _shortcut_set(session, line)

    # Shortcut: variable names → read
    return _shortcut_get(session, line)


def _dispatch_slash(session, cmd: str, args: str) -> str:
    handlers = {
        "help": _cmd_help,
        "quit": lambda s, a: _cmd_quit(s, a),
        "exit": lambda s, a: _cmd_quit(s, a),
        "ports": _cmd_ports,
        "status": _cmd_status,
        "open": _cmd_open,
        "close": _cmd_close,
        "create": _cmd_create,
        "load": _cmd_load,
        "get": _cmd_get,
        "set": _cmd_set,
    }

    handler = handlers.get(cmd)
    if handler is None:
        return f"Unknown command: /{cmd}. Type /help for available commands."
    return handler(session, args)


def _cmd_help(session, args):
    return (
        "Commands:\n"
        "  /help              Show this help\n"
        "  /quit, /exit       Exit (state preserved)\n"
        "  /quit -f           Force exit (clear state)\n"
        "  /ports             List serial ports\n"
        "  /status            Show connection status\n"
        "  /open --name PORT [--baud BAUD] [--endian little|big]\n"
        "  /close             Close connection\n"
        "  /create <elf>      Generate symbols.json from ELF\n"
        "  /load <file>       Load symbols file\n"
        "  /get <vars> [-i ms] [-c count]\n"
        "  /set <var=val,...> [-i ms] [-c count]\n"
        "\n"
        "Shortcuts:\n"
        "  counter            Read variable (= /get counter)\n"
        "  counter=100        Write variable (= /set counter=100)\n"
        "  a,b,c              Read multiple (= /get a,b,c)"
    )


def _cmd_quit(session, args):
    if args.strip() == "-f":
        session.close_and_clear()
        return "__QUIT_FORCE__"
    session.save_state()
    return "__QUIT__"


def _cmd_ports(session, args):
    port_list = list_ports()
    if not port_list:
        return "No serial ports found"
    return "\n".join(f"{d}: {desc}" for d, desc in port_list)


def _cmd_status(session, args):
    if not session.is_connected:
        lines = ["Status: Not connected"]
    else:
        lines = [
            "Status: Connected",
            f"  Port: {session.serial_mgr.port_name}",
            f"  Baud: {session.serial_mgr.baud_rate}",
            f"  Endian: {session.endian}",
        ]
    state = session.state_mgr.load_state()
    sp = state.get("symbols_path", "")
    lines.append(f"  Symbols: {sp if sp else '(none)'}")
    if session.resolver:
        lines.append(f"  Symbol count: {len(session.resolver.list_symbols())}")
    return "\n".join(lines)


def _cmd_open(session, args):
    # Parse --name PORT --baud BAUD --endian little|big
    try:
        tokens = shlex.split(args)
    except ValueError:
        tokens = args.split()

    port = None
    baud = DEFAULT_BAUD
    endian = "little"

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "--name" and i + 1 < len(tokens):
            port = tokens[i + 1]
            i += 2
        elif t == "--baud" and i + 1 < len(tokens):
            baud = int(tokens[i + 1])
            i += 2
        elif t == "--endian" and i + 1 < len(tokens):
            endian = tokens[i + 1]
            i += 2
        else:
            if port is None:
                port = t
            i += 1

    if not port:
        return "Usage: /open --name PORT [--baud BAUD] [--endian little|big]"

    try:
        pong = session.connect(port, baud, endian)
        msg = f"Connected to {port} at {baud} baud ({endian}-endian)"
        if not pong:
            msg += " (warning: no PONG response)"
        return msg
    except Exception as e:
        return f"Failed to open {port}: {e}"


def _cmd_close(session, args):
    port = session.disconnect()
    if port:
        return f"Disconnected from {port}"
    return "No active connection"


def _cmd_create(session, args):
    args = args.strip()
    if not args:
        return "Usage: /create <elf_file>"

    parts = args.split()
    elf_file = parts[0]
    output = "symbols.json"

    for i, p in enumerate(parts):
        if p in ("-o", "--output") and i + 1 < len(parts):
            output = parts[i + 1]

    if not os.path.isfile(elf_file):
        return f"ELF file not found: {elf_file}"

    from peeko.elf_parser import create_symbols_json
    try:
        sym_count = create_symbols_json(elf_file, output)
    except Exception as e:
        return f"Failed to parse ELF: {e}"

    abs_output = os.path.abspath(output)
    session.state_mgr.update_state(symbols_path=abs_output)
    try:
        count = session.load_symbols(abs_output)
        return f"Symbol file created: {abs_output}\nLoaded {count} symbols"
    except Exception as e:
        return f"Symbol file created: {abs_output} ({sym_count} symbols)\nWarning: failed to load: {e}"


def _cmd_load(session, args):
    path = args.strip()
    if not path:
        return "Usage: /load <symbols.json>"
    if not os.path.isfile(path):
        return f"File not found: {path}"
    try:
        count = session.load_symbols(os.path.abspath(path))
        return f"Loaded {count} symbols from {path}"
    except Exception as e:
        return f"Failed to load symbols: {e}"


def _cmd_get(session, args):
    if not session.is_connected:
        return "Not connected. Use /open first."
    if not session.resolver:
        return "No symbols loaded. Use /load or /create first."

    # Parse -i/--interval and -c/--count from args
    tokens = args.split()
    interval = None
    count = None
    var_str_parts = []

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("-i", "--interval") and i + 1 < len(tokens):
            interval = int(tokens[i + 1])
            i += 2
        elif t in ("-c", "--count") and i + 1 < len(tokens):
            count = int(tokens[i + 1])
            i += 2
        else:
            var_str_parts.append(t)
            i += 1

    var_str = " ".join(var_str_parts).strip()
    if not var_str:
        return "Usage: /get <variables> [-i interval_ms] [-c count]"

    return _execute_read(session, var_str, interval, count)


def _cmd_set(session, args):
    if not session.is_connected:
        return "Not connected. Use /open first."
    if not session.resolver:
        return "No symbols loaded. Use /load or /create first."

    tokens = args.split()
    interval = None
    count = None
    assign_parts = []

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("-i", "--interval") and i + 1 < len(tokens):
            interval = int(tokens[i + 1])
            i += 2
        elif t in ("-c", "--count") and i + 1 < len(tokens):
            count = int(tokens[i + 1])
            i += 2
        else:
            assign_parts.append(t)
            i += 1

    assign_str = " ".join(assign_parts).strip()
    if not assign_str:
        return "Usage: /set <var=value,...> [-i interval_ms] [-c count]"

    return _execute_write(session, assign_str, interval, count)


def _shortcut_get(session, line):
    if not session.is_connected:
        return "Not connected. Use /open first."
    if not session.resolver:
        return "No symbols loaded. Use /load or /create first."
    return _execute_read(session, line, None, None)


def _shortcut_set(session, line):
    if not session.is_connected:
        return "Not connected. Use /open first."
    if not session.resolver:
        return "No symbols loaded. Use /load or /create first."
    return _execute_write(session, line, None, None)


def _execute_read(session, var_str, interval, count):
    try:
        var_paths = parse_variables(var_str)
    except ValueError as e:
        return str(e)

    var_infos = []
    resolved_list = []
    for vp in var_paths:
        try:
            rv = session.resolver.resolve(vp)
        except SymbolResolveError as e:
            return str(e)
        var_infos.append(VarInfo(
            address=rv.address, size=rv.size,
            bit_offset=rv.bit_offset, bit_size=rv.bit_size))
        resolved_list.append(rv)

    try:
        if interval is None:
            data_list = session.protocol.read_variables(var_infos)
            return _format_read(session, var_paths, resolved_list, data_list)
        else:
            lines = []
            iteration = 0
            target = count if count and count > 0 else 0
            lines.append("Press ESC to stop...")
            while True:
                data_list = session.protocol.read_variables(var_infos)
                lines.append(_format_read(session, var_paths, resolved_list, data_list))
                iteration += 1
                if target and iteration >= target:
                    break
                if _check_esc():
                    lines.append("\nStopped by user (ESC)")
                    break
                time.sleep(interval / 1000.0)
            return "\n".join(lines)
    except ProtocolError as e:
        return f"Error: {e}"


def _execute_write(session, assign_str, interval, count):
    try:
        pairs = parse_assignments(assign_str)
    except ValueError as e:
        return str(e)

    var_infos = []
    data_list = []
    for vp, value_str in pairs:
        try:
            rv = session.resolver.resolve(vp)
        except SymbolResolveError as e:
            return str(e)

        vi = VarInfo(address=rv.address, size=rv.size,
                     bit_offset=rv.bit_offset, bit_size=rv.bit_size)
        var_infos.append(vi)

        parsed_val = session.converter.parse_value(value_str, rv.data_type)
        if rv.bit_offset != NO_BITFIELD:
            encoded = bytes([int(parsed_val) & 0xFF])
        else:
            encoded = session.converter.encode(parsed_val, rv.data_type, rv.size)
        data_list.append(encoded)

    try:
        if interval is None:
            session.protocol.write_variables(var_infos, data_list)
            return "OK"
        else:
            lines = ["Press ESC to stop..."]
            iteration = 0
            target = count if count and count > 0 else 0
            while True:
                session.protocol.write_variables(var_infos, data_list)
                lines.append("OK")
                iteration += 1
                if target and iteration >= target:
                    break
                if _check_esc():
                    lines.append("\nStopped by user (ESC)")
                    break
                time.sleep(interval / 1000.0)
            return "\n".join(lines)
    except ProtocolError as e:
        return f"Error: {e}"


def _format_read(session, var_paths, resolved_list, data_list):
    parts = []
    for vp, rv, data in zip(var_paths, resolved_list, data_list):
        value = session.converter.decode(data, rv.data_type)
        formatted = session.converter.format_value(value, rv.data_type)
        parts.append(f"{vp}={formatted}")
    return ",".join(parts)
