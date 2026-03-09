import os
import time
import click

from peeko import __version__
from peeko.config import DEFAULT_BAUD, NO_BITFIELD
from peeko.serial_manager import SerialManager, list_ports
from peeko.state_manager import StateManager
from peeko.protocol import Protocol, VarInfo, ProtocolError
from peeko.symbol_resolver import SymbolResolver, SymbolResolveError
from peeko.variable_parser import parse_variables, parse_assignments
from peeko.type_converter import TypeConverter


def _check_esc() -> bool:
    """Non-blocking ESC key detection on Windows."""
    try:
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch == b'\x1b':
                return True
    except ImportError:
        pass
    return False


def _connect_from_state(state_mgr: StateManager):
    """Re-establish connection from saved state. Returns (SerialManager, Protocol, endian) or raises."""
    state = state_mgr.load_state()
    if not state or not state.get("connected"):
        raise click.ClickException("Not connected. Use 'peeko open' first.")

    port = state["port"]
    baud = state.get("baud", DEFAULT_BAUD)
    endian = state.get("endian", "little")

    sm = SerialManager()
    try:
        sm.open(port, baud)
    except Exception as e:
        raise click.ClickException(f"Failed to open {port}: {e}")

    protocol = Protocol(sm.serial_port, little_endian=(endian == "little"))
    return sm, protocol, endian


def _load_symbols(state_mgr: StateManager) -> SymbolResolver:
    state = state_mgr.load_state()
    symbols_path = state.get("symbols_path", "")
    if not symbols_path or not os.path.isfile(symbols_path):
        raise click.ClickException(
            "No symbols loaded. Use 'peeko create <elf>' to generate symbols.json, "
            "then 'peeko open' to connect.")
    try:
        return SymbolResolver(symbols_path)
    except Exception as e:
        raise click.ClickException(f"Failed to load symbols: {e}")


def _resolve_and_build(var_paths, resolver: SymbolResolver):
    """Resolve variable paths to (var_infos, resolved_list)."""
    var_infos = []
    resolved_list = []
    for vp in var_paths:
        try:
            rv = resolver.resolve(vp)
        except SymbolResolveError as e:
            raise click.ClickException(str(e))
        var_infos.append(VarInfo(
            address=rv.address,
            size=rv.size,
            bit_offset=rv.bit_offset,
            bit_size=rv.bit_size,
        ))
        resolved_list.append(rv)
    return var_infos, resolved_list


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="peeko")
@click.pass_context
def cli(ctx):
    """Peeko - Serial-based MCU RAM read/write tool."""
    if ctx.invoked_subcommand is None:
        from peeko.repl.repl import start_repl
        start_repl()


@cli.command()
@click.option("--name", required=True, help="Serial port name (e.g. COM3)")
@click.option("--baud", default=DEFAULT_BAUD, type=int, help="Baud rate")
@click.option("--endian", default="little", type=click.Choice(["little", "big"]),
              help="Byte order")
def open(name, baud, endian):
    """Connect to MCU via serial port."""
    sm = SerialManager()
    try:
        sm.open(name, baud)
    except Exception as e:
        raise click.ClickException(f"Failed to open {name}: {e}")

    protocol = Protocol(sm.serial_port, little_endian=(endian == "little"))

    if protocol.ping():
        click.echo(f"Connected to {name} at {baud} baud ({endian}-endian)")
    else:
        click.echo(f"Connected to {name} at {baud} baud ({endian}-endian) "
                    f"(warning: no PONG response)")

    state_mgr = StateManager()
    state = state_mgr.load_state()
    symbols_path = state.get("symbols_path", "")
    state_mgr.save_state(name, baud, endian, symbols_path)
    sm.close()


@cli.command()
def close():
    """Disconnect from MCU."""
    state_mgr = StateManager()
    state = state_mgr.load_state()
    port = state.get("port", "")
    state_mgr.clear_state()
    if port:
        click.echo(f"Disconnected from {port}")
    else:
        click.echo("No active connection")


@cli.command()
@click.argument("elf_file", type=click.Path(exists=True))
@click.option("-o", "--output", default="symbols.json", help="Output file path")
def create(elf_file, output):
    """Generate symbols.json from ELF file."""
    from peeko.elf_parser import create_symbols_json
    try:
        count = create_symbols_json(elf_file, output)
    except Exception as e:
        raise click.ClickException(f"Failed to parse ELF: {e}")

    abs_output = os.path.abspath(output)
    click.echo(f"Symbol file created: {abs_output} ({count} symbols)")

    state_mgr = StateManager()
    state_mgr.update_state(symbols_path=abs_output)


@cli.command("get")
@click.argument("variables")
@click.option("-i", "--interval", type=int, default=None,
              help="Read interval in milliseconds")
@click.option("-c", "--count", type=int, default=None,
              help="Number of reads (0=infinite)")
def get_cmd(variables, interval, count):
    """Read variable(s) from MCU. Variables: comma-separated names."""
    state_mgr = StateManager()
    sm, protocol, endian = _connect_from_state(state_mgr)
    resolver = _load_symbols(state_mgr)
    converter = TypeConverter(little_endian=(endian == "little"))

    try:
        var_paths = parse_variables(variables)
    except ValueError as e:
        sm.close()
        raise click.ClickException(str(e))

    var_infos, resolved_list = _resolve_and_build(var_paths, resolver)

    try:
        if interval is None:
            # Single read
            _do_read(protocol, converter, var_paths, var_infos, resolved_list)
        else:
            # Periodic read
            iteration = 0
            target_count = count if count and count > 0 else 0
            click.echo("Press ESC to stop...", err=True)
            while True:
                _do_read(protocol, converter, var_paths, var_infos, resolved_list)
                iteration += 1
                if target_count and iteration >= target_count:
                    break
                if _check_esc():
                    click.echo("\nStopped by user (ESC)", err=True)
                    break
                time.sleep(interval / 1000.0)
    except ProtocolError as e:
        raise click.ClickException(str(e))
    finally:
        sm.close()


def _do_read(protocol, converter, var_paths, var_infos, resolved_list):
    """Execute one read and print results."""
    data_list = protocol.read_variables(var_infos)
    parts = []
    for vp, rv, data in zip(var_paths, resolved_list, data_list):
        value = converter.decode(data, rv.data_type)
        formatted = converter.format_value(value, rv.data_type)
        parts.append(f"{vp}={formatted}")
    click.echo(",".join(parts))


@cli.command("set")
@click.argument("assignments")
@click.option("-i", "--interval", type=int, default=None,
              help="Write interval in milliseconds")
@click.option("-c", "--count", type=int, default=None,
              help="Number of writes (0=infinite)")
def set_cmd(assignments, interval, count):
    """Write variable(s) to MCU. Assignments: comma-separated var=value pairs."""
    state_mgr = StateManager()
    sm, protocol, endian = _connect_from_state(state_mgr)
    resolver = _load_symbols(state_mgr)
    converter = TypeConverter(little_endian=(endian == "little"))

    try:
        pairs = parse_assignments(assignments)
    except ValueError as e:
        sm.close()
        raise click.ClickException(str(e))

    var_infos = []
    data_list = []
    for vp, value_str in pairs:
        try:
            rv = resolver.resolve(vp)
        except SymbolResolveError as e:
            sm.close()
            raise click.ClickException(str(e))

        vi = VarInfo(
            address=rv.address, size=rv.size,
            bit_offset=rv.bit_offset, bit_size=rv.bit_size,
        )
        var_infos.append(vi)

        parsed_val = converter.parse_value(value_str, rv.data_type)
        if rv.bit_offset != NO_BITFIELD:
            encoded = bytes([int(parsed_val) & 0xFF])
        else:
            encoded = converter.encode(parsed_val, rv.data_type, rv.size)
        data_list.append(encoded)

    try:
        if interval is None:
            protocol.write_variables(var_infos, data_list)
            click.echo("OK")
        else:
            iteration = 0
            target_count = count if count and count > 0 else 0
            click.echo("Press ESC to stop...", err=True)
            while True:
                protocol.write_variables(var_infos, data_list)
                click.echo("OK")
                iteration += 1
                if target_count and iteration >= target_count:
                    break
                if _check_esc():
                    click.echo("\nStopped by user (ESC)", err=True)
                    break
                time.sleep(interval / 1000.0)
    except ProtocolError as e:
        raise click.ClickException(str(e))
    finally:
        sm.close()


@cli.command()
@click.argument("elf_file", type=click.Path(exists=True))
@click.option("--top", default=10, type=int, help="Show top N largest variables")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def analyze(elf_file, top, as_json):
    """Analyze memory usage from ELF file."""
    from peeko.memory_analyzer import analyze as run_analyze, format_report
    import json as json_mod

    try:
        result = run_analyze(elf_file, top_n=top)
    except Exception as e:
        raise click.ClickException(f"Failed to analyze ELF: {e}")

    if as_json:
        click.echo(json_mod.dumps(result, indent=2, ensure_ascii=False))
    else:
        click.echo(format_report(result))


@cli.command()
def ports():
    """List available serial ports."""
    port_list = list_ports()
    if not port_list:
        click.echo("No serial ports found")
        return
    for device, desc in port_list:
        click.echo(f"{device}: {desc}")


@cli.command()
def status():
    """Show current connection status."""
    state_mgr = StateManager()
    state = state_mgr.load_state()
    if not state or not state.get("connected"):
        click.echo("Status: Not connected")
        return

    click.echo("Status: Connected")
    click.echo(f"  Port: {state.get('port', '?')}")
    click.echo(f"  Baud: {state.get('baud', '?')}")
    click.echo(f"  Endian: {state.get('endian', '?')}")
    symbols = state.get("symbols_path", "")
    if symbols:
        click.echo(f"  Symbols: {symbols}")
    else:
        click.echo("  Symbols: (none loaded)")
