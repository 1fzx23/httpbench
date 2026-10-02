# HttpBench

> L7 · 宗师 — 每两周一个小工具系列

轻量级 HTTP 性能测试工具，纯 Python 标准库实现，零外部依赖。

## 功能

- **并发压测** — 多线程并发发送 HTTP 请求
- **双模式运行** — 按请求数 (`-n`) 或按持续时间 (`-d`)
- **完整统计** — Min / Mean / Median / StdDev / Max / P50 / P75 / P90 / P95 / P99 / P99.9
- **错误分析** — 自动分类连接错误、超时、HTTP 异常码
- **多种输出** — 终端表格（含 ASCII 直方图）、JSON、自包含 HTML 报告
- **HTTP 方法** — 支持 GET / POST / PUT / DELETE / PATCH 等
- **Keep-Alive** — 默认复用连接，可关闭以模拟真实场景

## 安装

```bash
# 直接运行（推荐）
python httpbench.py https://example.com -n 1000 -c 50

# 或作为模块运行
python -m httpbench https://example.com -n 1000 -c 50

# 或 pip 安装
pip install .
httpbench https://example.com -n 1000 -c 50
```

## 使用方法

### 基本压测

```bash
# 发送 100 个请求，1 个并发（默认）
python httpbench.py https://example.com

# 发送 1000 个请求，50 并发
python httpbench.py https://example.com -n 1000 -c 50

# 持续压测 30 秒，10 并发
python httpbench.py https://example.com -d 30 -c 10
```

### POST 请求

```bash
python httpbench.py https://api.example.com/login \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  --data '{"username":"admin","password":"secret"}' \
  -n 500 -c 20
```

### 输出格式

```bash
# JSON 输出（便于管道处理）
python httpbench.py https://example.com -n 100 -o json

# HTML 报告
python httpbench.py https://example.com -n 1000 --report report.html

# 同时输出终端报告并保存 HTML
python httpbench.py https://example.com -n 1000 --report report.html
```

### 其他选项

```bash
# 禁用 Keep-Alive（每个请求新建连接）
python httpbench.py https://example.com -n 100 --no-keepalive

# 自定义超时
python httpbench.py https://example.com -n 100 -t 10

# 从文件读取请求体
python httpbench.py https://api.example.com/upload -X POST --data-file payload.json

# 静默模式（无进度条）
python httpbench.py https://example.com -n 10000 -q
```

## CLI 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `url` | 目标 URL | — |
| `-n, --requests` | 总请求数 | 100 |
| `-c, --concurrency` | 并发连接数 | 1 |
| `-d, --duration` | 持续秒数（覆盖 `-n`） | — |
| `-X, --method` | HTTP 方法 | GET |
| `-H, --header` | 请求头（可多次使用） | — |
| `--data` | 请求体字符串 | — |
| `--data-file` | 从文件读取请求体 | — |
| `-t, --timeout` | 单次请求超时（秒） | 30 |
| `--no-keepalive` | 禁用连接复用 | — |
| `-o, --output` | 输出格式: terminal/json/html | terminal |
| `--report` | 保存 HTML 报告到文件 | — |
| `-q, --quiet` | 隐藏进度条 | — |
| `--version` | 显示版本 | — |

## 示例输出

```
Benchmarking https://httpbin.org/get ...
  10 concurrent connection(s)
  Requests: 1000

  URL:       https://httpbin.org/get
  Method:    GET
  Duration:  4.832s
  Requests:  1000 total  |  1000 success  |  0 failed
  RPS:       206.96
  Data:      1.847 MB received

  Latency Distribution
  ────────────────────────────────────────────
    Min          23.45 ms
    Mean         48.23 ms
    Median       45.12 ms
    StdDev       12.56 ms
    Max         112.34 ms
  ────────────────────────────────────────────
    P50          45.12 ms
    P75          54.78 ms
    P90          65.34 ms
    P95          78.91 ms
    P99          98.45 ms
    P99.9       110.23 ms

  Latency Histogram
  ────────────────────────────────────────────
        23.4-    34.5 ms  ████████░░░░░░░░░░░░  142
        34.5-    45.6 ms  ██████████████░░░░░░  298
        45.6-    56.7 ms  ███████████░░░░░░░░░  231
        56.7-    67.8 ms  ██████░░░░░░░░░░░░░░  128
        67.8-    78.9 ms  ███░░░░░░░░░░░░░░░░░   65
        78.9-    90.0 ms  ██░░░░░░░░░░░░░░░░░░   42
        90.0-   101.1 ms  █░░░░░░░░░░░░░░░░░░░   18
       101.1-   112.3 ms  █░░░░░░░░░░░░░░░░░░░    8

  Status Codes
  ────────────────────────────────────────────
    HTTP 200: 1000
```

## 技术栈

- Python 3.9+
- 零外部依赖（仅标准库）

## 协议

MIT License
