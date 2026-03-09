# Peeko

**Read/write MCU RAM variables by name over serial — built for AI-assisted embedded development**

[中文](README.md)

## What It Does

AI coding assistants struggle with embedded development because they can't interact with real hardware. Peeko bridges this gap: it lets AI (or you) read/write MCU memory variables by name through a serial port.

```
AI generates code → compile → flash → Peeko reads/writes vars → feedback → iterate
```

## Quick Start

### MCU Side (3 lines to integrate)

Add `peeko.h` and `peeko.c` from `mcu_lib/` to your project:

```c
#include "peeko.h"

void UART_RX_IRQHandler(void) { pk_rx_byte(UART_DATA); }
void UART_TX_IRQHandler(void) { pk_tx_complete(); }

int main(void) {
    pk_init(uart_send_byte);   // pass your byte-send function
    while (1) { /* ... */ }
}
```

| Metric | Value |
|:---|:---|
| RAM | ~560 B (configurable) |
| Flash | ~1 KB |
| Requires | 1 UART only |

### PC Side

```bash
cd peeko
pip install -r requirements.txt
```

```bash
peeko create firmware.elf              # extract symbols from ELF
peeko open --name COM3 --baud 115200   # connect to MCU
peeko get temperature                  # read → temperature=25.5
peeko set motor_speed=1500             # write
peeko get uwTick -i 100 -c 0          # poll every 100ms
```

Interactive mode (REPL) with Tab completion:

```
$ peeko
peeko> uwTick                  # type name to read
uwTick=54321
peeko> motor.speed=2000        # assign to write
OK
peeko> /quit
```

Build standalone exe (no Python needed on target machine):

```bash
build.bat                      # → dist/peeko.exe
```

## CLI Reference

| Command | Description |
|:---|:---|
| `peeko create <elf> [-o file]` | Extract symbols from ELF/DWARF → symbols.json |
| `peeko open --name <port> [--baud N] [--endian little\|big]` | Connect to MCU |
| `peeko close` | Disconnect |
| `peeko get <vars> [-i ms] [-c N]` | Read variables (supports periodic) |
| `peeko set <var=val,...> [-i ms] [-c N]` | Write variables (supports periodic) |
| `peeko analyze <elf> [--top N] [--json]` | Analyze firmware memory usage (Flash/RAM/variable ranking) |
| `peeko ports` | List serial ports |
| `peeko status` | Show connection status |
| `peeko` (no subcommand) | Enter REPL mode |

**Variable syntax**: `sensor.temperature` (struct), `buffer[3]` (array), `counter@main.c` (file disambig)

**Value formats**: `100`, `0xFF`, `0b1010`, `3.14`, `true`/`false`

## AI Integration

Peeko is designed as a hardware interface for AI assistants. Output is machine-parseable:

```bash
peeko get sensor.temperature     # → sensor.temperature=25.5
peeko set button_pressed=1       # → OK
peeko get pid.output,pid.error   # → pid.output=0.85,pid.error=-0.02
```

Can be configured as an MCP (Model Context Protocol) tool for Claude / Cursor / Copilot.

## Architecture

```
+-----------+    Serial/UART    +-------------+
| PC: peeko | <===============> | MCU: peeko.c|
+-----------+                   +-------------+
      |                               |
 symbols.json                    RAM Variables
 (ELF/DWARF)                  (physical memory)
```

## Project Structure

```
├── mcu_lib/                  MCU C library
│   ├── inc/peeko.h           Protocol constants + public API
│   └── src/peeko.c           State machine RX + CRC + read/write
├── peeko/                    PC tool
│   ├── peeko/                Python package
│   │   ├── cli.py            CLI commands
│   │   ├── elf_parser.py     ELF/DWARF symbol extraction
│   │   ├── memory_analyzer.py Memory usage analysis
│   │   ├── protocol.py       Serial frame protocol
│   │   ├── symbol_resolver.py Name → address resolution
│   │   ├── variable_parser.py Syntax parsing
│   │   ├── type_converter.py  Type conversion
│   │   ├── serial_manager.py  Serial port management
│   │   ├── state_manager.py   State persistence
│   │   ├── config.py          Constants & config
│   │   └── repl/              Interactive mode
│   ├── setup.py
│   ├── requirements.txt
│   └── build.bat             Build script
├── README.md
├── README_EN.md
└── LICENSE
```

## Supported Platforms

**MCU**: STM32, Renesas RL78, Arduino, any UART-capable MCU

**ELF**: ARM Cortex-M (.elf/.axf), Renesas (.abs), Microchip PIC (.elf), GCC (.out)

## License

MIT — See [LICENSE](LICENSE)
