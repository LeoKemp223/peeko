# Peeko

**让 AI 真正理解硬件 —— 串口桥接 PC 与 MCU，实时读写 RAM 变量**

[English](README_EN.md)

## 它能做什么？

AI 辅助编程在 Web 领域已非常成熟，但在嵌入式开发中，AI 无法与真实硬件交互。Peeko 通过串口让 AI（或开发者）直接按变量名读写 MCU 内存，打通自动化闭环：

```
AI 代码生成 → 编译 → 烧录 → Peeko 读写变量 → 反馈给 AI → 迭代优化
```

## 快速开始

### MCU 端（3 行代码接入）

将 `mcu_lib/` 下的 `peeko.h` 和 `peeko.c` 加入你的工程：

```c
#include "peeko.h"

void UART_RX_IRQHandler(void) { pk_rx_byte(UART_DATA); }
void UART_TX_IRQHandler(void) { pk_tx_complete(); }

int main(void) {
    pk_init(uart_send_byte);   // 传入你的单字节发送函数
    while (1) { /* ... */ }
}
```

| 指标 | 数值 |
|:---|:---|
| RAM | ~560 B（可配置） |
| Flash | ~1 KB |
| 依赖 | 仅 1 个 UART |

### PC 端

```bash
cd peeko
pip install -r requirements.txt
```

```bash
peeko create firmware.elf              # 从 ELF 提取变量符号
peeko open --name COM3 --baud 115200   # 连接 MCU
peeko get temperature                  # 读变量 → temperature=25.5
peeko set motor_speed=1500             # 写变量
peeko get uwTick -i 100 -c 0          # 每 100ms 持续读取
```

也可以进入交互模式（REPL），支持 Tab 补全和命令历史：

```
$ peeko
peeko> uwTick                  # 输入变量名直接读
uwTick=54321
peeko> motor.speed=2000        # 赋值直接写
OK
peeko> /quit
```

打包为独立 exe（目标机无需 Python）：

```bash
build.bat                      # → dist/peeko.exe
```

## CLI 命令一览

| 命令 | 说明 |
|:---|:---|
| `peeko create <elf> [-o file]` | 从 ELF/DWARF 提取符号生成 symbols.json |
| `peeko open --name <port> [--baud N] [--endian little\|big]` | 连接 MCU |
| `peeko close` | 断开连接 |
| `peeko get <vars> [-i ms] [-c N]` | 读变量（支持周期读取） |
| `peeko set <var=val,...> [-i ms] [-c N]` | 写变量（支持周期写入） |
| `peeko analyze <elf> [--top N] [--json]` | 分析固件内存使用（Flash/RAM/变量排名） |
| `peeko ports` | 列出可用串口 |
| `peeko status` | 查看当前连接状态 |
| `peeko` (无子命令) | 进入 REPL 交互模式 |

**变量语法**：`sensor.temperature`（结构体）、`buffer[3]`（数组）、`counter@main.c`（源文件消歧）

**值格式**：`100`、`0xFF`、`0b1010`、`3.14`、`true`/`false`

## 与 AI 集成

Peeko 设计为 AI 编程助手的硬件接口，CLI 输出格式便于机器解析：

```bash
peeko get sensor.temperature     # → sensor.temperature=25.5
peeko set button_pressed=1       # → OK
peeko get pid.output,pid.error   # → pid.output=0.85,pid.error=-0.02
```

支持配置为 MCP (Model Context Protocol) 工具，让 Claude / Cursor / Copilot 直接操作硬件。

## 架构

```
+-----------+    Serial/UART    +-------------+
| PC: peeko | <===============> | MCU: peeko.c|
+-----------+                   +-------------+
      |                               |
 symbols.json                    RAM Variables
 (ELF/DWARF)                   (物理内存地址)
```

## 项目结构

```
├── mcu_lib/                  MCU 端 C 库
│   ├── inc/peeko.h           协议常量 + 公开 API
│   └── src/peeko.c           状态机接收 + CRC + 读写处理
├── peeko/                    PC 端工具
│   ├── peeko/                Python 包
│   │   ├── cli.py            CLI 命令层
│   │   ├── elf_parser.py     ELF/DWARF 符号提取
│   │   ├── memory_analyzer.py 内存使用分析
│   │   ├── protocol.py       串口帧协议
│   │   ├── symbol_resolver.py 变量名 → 地址
│   │   ├── variable_parser.py 语法解析
│   │   ├── type_converter.py  类型转换
│   │   ├── serial_manager.py  串口管理
│   │   ├── state_manager.py   状态持久化
│   │   ├── config.py          常量配置
│   │   └── repl/              交互模式
│   ├── setup.py
│   ├── requirements.txt
│   └── build.bat             打包脚本
├── README.md
├── README_EN.md
└── LICENSE
```

## 支持的平台

**MCU**：STM32、Renesas RL78、Arduino、任何有 UART 的 MCU

**ELF**：ARM Cortex-M (.elf/.axf)、Renesas (.abs)、Microchip PIC (.elf)、GCC (.out)

## 许可证

MIT — 详见 [LICENSE](LICENSE)
