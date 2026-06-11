# Personalized Research Dashboard Scheduler

这个项目现在提供一个手动启动、可自启动的后台调度命令：

```bash
uv run python -m nlp_arxiv_daily run-scheduler
```

## 行为规则

调度器的行为与要求对齐：

- 用户需要手动启动调度器进程
- 也可以把这个命令挂到系统自启动
- 调度器启动后会先检查“今天是否已经有 pipeline 运行记录”
- 如果今天还没有生成 `runs/YYYY-MM-DD.json`，就立即运行当天的 `run-personalized`
- 调度器常驻后会持续存活，并在跨过本地时间的 `00:00` 后检查当天是否已有运行记录
- 如果跨过午夜时上一条 pipeline 还在运行，不会并发启动；会等上一条结束，再检查新的一天是否缺记录，缺则补跑

当前“是否已经运行过”的判定标准是：

- `docs/personalized/runs/YYYY-MM-DD.json` 存在
- 且其中 `pipeline == "run-personalized"`

这意味着：

- 只要当天已经生成过运行记录，调度器就不会重复启动当天 pipeline
- 当前策略更偏保守，优先避免重复跑

## 手动启动

```bash
uv run python -m nlp_arxiv_daily run-scheduler
```

也可以自定义轮询周期：

```bash
uv run python -m nlp_arxiv_daily run-scheduler --poll-seconds 15
```

默认轮询周期来自配置：

- `scheduler_poll_seconds`
- `scheduler_lock_path`

## 配置项

当前默认值由 `load_config()` 注入：

```yaml
scheduler_poll_seconds: 30
scheduler_lock_path: "./docs/personalized/runs/scheduler.lock"
```

其中：

- `scheduler_poll_seconds`
  调度器检查日期切换和待执行任务的周期
- `scheduler_lock_path`
  用于保证同一时刻只有一个 scheduler 进程在跑

## Linux: systemd 自启动

示例 unit：

```ini
[Unit]
Description=Personalized Research Dashboard scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/nlp-arxiv-daily
ExecStart=/path/to/uv run python -m nlp_arxiv_daily run-scheduler
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

保存到：

```text
/etc/systemd/system/nlp-arxiv-daily-scheduler.service
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable nlp-arxiv-daily-scheduler
sudo systemctl start nlp-arxiv-daily-scheduler
sudo systemctl status nlp-arxiv-daily-scheduler
```

## macOS: launchd 自启动

示例 `plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>io.josephjoycz.nlp-arxiv-daily.scheduler</string>

    <key>ProgramArguments</key>
    <array>
      <string>/path/to/uv</string>
      <string>run</string>
      <string>python</string>
      <string>-m</string>
      <string>nlp_arxiv_daily</string>
      <string>run-scheduler</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/path/to/nlp-arxiv-daily</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/tmp/nlp-arxiv-daily-scheduler.out</string>

    <key>StandardErrorPath</key>
    <string>/tmp/nlp-arxiv-daily-scheduler.err</string>
  </dict>
</plist>
```

保存到：

```text
~/Library/LaunchAgents/io.josephjoycz.nlp-arxiv-daily.scheduler.plist
```

启用：

```bash
launchctl load ~/Library/LaunchAgents/io.josephjoycz.nlp-arxiv-daily.scheduler.plist
launchctl start io.josephjoycz.nlp-arxiv-daily.scheduler
```

## Windows: 任务计划程序自启动

最简单的是“登录时启动”或“开机时启动”。

命令示例：

```powershell
uv run python -m nlp_arxiv_daily run-scheduler
```

在“任务计划程序”里新建任务：

1. `常规`
   填写任务名，例如 `nlp-arxiv-daily-scheduler`
2. `触发器`
   选择“登录时”或“启动时”
3. `操作`
   选择“启动程序”
4. `程序或脚本`
   填 `uv`
5. `添加参数`
   填 `run python -m nlp_arxiv_daily run-scheduler`
6. `起始于`
   填仓库目录，例如 `C:\Users\josep\nlp-arxiv-daily`

如果 `uv` 不在系统 PATH 里，也可以直接填它的绝对路径。

## 适合的使用方式

推荐的运行模式是：

- 平时让 scheduler 常驻
- 每天自动补当天的 personalized pipeline
- 如果机器或服务中途停掉，之后用户手动重新启动 scheduler 时，会再次检查当天是否已有记录，没有则补跑

## 注意事项

- 调度器当前按“本地系统时间”判断午夜
- 当前按“是否已有 run record 文件”判断是否已经跑过当天任务
- 如果你希望“失败记录也自动重试”，这是另一种策略，需要单独定义
- 当前实现优先保证不重复运行，而不是自动重试失败日
