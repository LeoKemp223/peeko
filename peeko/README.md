# peeko — MCU RAM 变量读写工具

通过串口与 MCU 通信，实时读取/写入 RAM 中的变量。支持 CLI 单次命令和 REPL 交互两种模式。

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

```bash
# 1. 从 ELF 固件生成符号文件
python -m peeko create firmware.elf

# 2. 连接 MCU
python -m peeko open --name COM3

# 3. 读取变量
python -m peeko get uwTick

# 4. 写入变量
python -m peeko set counter=100
```

## CLI 命令

### 查看版本

```bash
python -m peeko --version
```

### 列出串口

```bash
python -m peeko ports
```

### 生成符号文件

从 ELF 固件中提取全局变量信息，输出 `symbols.json`。

```bash
python -m peeko create <elf_file> [-o output.json]
```

| 参数 | 说明 |
|------|------|
| `elf_file` | ELF 固件路径（需含 DWARF 调试信息，编译时加 `-g`） |
| `-o, --output` | 输出文件路径，默认 `symbols.json` |

示例：

```bash
python -m peeko create firmware.elf
python -m peeko create firmware.elf -o my_symbols.json
```

### 连接 MCU

```bash
python -m peeko open --name <port> [--baud <rate>] [--endian little|big]
```

| 参数 | 说明 |
|------|------|
| `--name` | 串口名称，如 `COM3`、`/dev/ttyUSB0` |
| `--baud` | 波特率，默认 `9600` |
| `--endian` | 字节序，`little`（默认）或 `big` |

示例：

```bash
python -m peeko open --name COM3
python -m peeko open --name COM5 --baud 115200 --endian big
```

### 断开连接

```bash
python -m peeko close
```

### 查看连接状态

```bash
python -m peeko status
```

### 读取变量

```bash
python -m peeko get <variables> [-i interval_ms] [-c count]
```

| 参数 | 说明 |
|------|------|
| `variables` | 变量名，多个用逗号分隔 |
| `-i, --interval` | 周期读取间隔（毫秒） |
| `-c, --count` | 读取次数，`0` 为无限循环 |

示例：

```bash
# 单次读取
python -m peeko get uwTick
python -m peeko get uwTick,SystemCoreClock

# 每 100ms 读一次，共 10 次
python -m peeko get uwTick -i 100 -c 10

# 持续读取直到按 ESC 键
python -m peeko get uwTick -i 200 -c 0

# 读取结构体成员
python -m peeko get sensor.temperature

# 读取数组元素
python -m peeko get buffer[0]

# 指定源文件（同名变量消歧）
python -m peeko get counter@main.c
```

### 写入变量

```bash
python -m peeko set <assignments> [-i interval_ms] [-c count]
```

| 参数 | 说明 |
|------|------|
| `assignments` | 赋值表达式，格式 `var=value`，多个用逗号分隔 |
| `-i, --interval` | 周期写入间隔（毫秒） |
| `-c, --count` | 写入次数，`0` 为无限循环 |

支持的值格式：十进制 `100`、十六进制 `0xFF`、二进制 `0b1010`、浮点 `3.14`、布尔 `true/false`

示例：

```bash
python -m peeko set counter=0
python -m peeko set counter=0xFF
python -m peeko set sensor.enable=true,motor.speed=1500
python -m peeko set pwm_duty=50 -i 500 -c 0
```

## REPL 交互模式

直接运行 `python -m peeko`（不带子命令）进入交互模式：

```bash
python -m peeko
```

### REPL 命令

所有命令以 `/` 开头：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/quit` 或 `/exit` | 退出（保留连接状态） |
| `/quit -f` | 强制退出（清除状态） |
| `/ports` | 列出串口 |
| `/status` | 查看连接状态 |
| `/open --name COM3 [--baud 115200] [--endian little]` | 连接 MCU |
| `/close` | 断开连接 |
| `/create firmware.elf [-o symbols.json]` | 从 ELF 生成符号文件 |
| `/load symbols.json` | 加载已有的符号文件 |
| `/get <vars> [-i ms] [-c count]` | 读取变量 |
| `/set <var=val,...> [-i ms] [-c count]` | 写入变量 |

### REPL 快捷语法

连接并加载符号后，可直接输入变量名进行操作，无需 `/get`、`/set` 前缀：

```
peeko> uwTick                   # 等价于 /get uwTick
uwTick=123456

peeko> counter=100              # 等价于 /set counter=100
OK

peeko> a,b,c                    # 等价于 /get a,b,c
a=1,b=2,c=3
```

### REPL 补全

支持 Tab 键自动补全：
- `/` 开头补全命令名
- 变量名补全（含结构体成员展开）

## 典型工作流

```bash
# 1. 编译固件（确保带调试信息）
arm-none-eabi-gcc -g -o firmware.elf ...

# 2. 生成符号文件
python -m peeko create firmware.elf

# 3. 进入交互模式
python -m peeko

# 4. 在 REPL 中操作
peeko> /open COM3 --baud 115200
Connected to COM3 at 115200 baud (little-endian)

peeko> uwTick
uwTick=54321

peeko> motor.speed=2000
OK

peeko> /quit
```

## 打包为独立 exe

```bash
build.bat
```

输出 `dist/peeko.exe`，可脱离 Python 环境直接使用。

## 状态持久化

连接信息和符号文件路径保存在 `~/.peeko/state.json`，关闭后重新打开 REPL 会自动恢复上次的连接配置。命令历史保存在 `~/.peeko/history`。
