# ContestTrade 无人值守运行指南

项目采用“系统调度器每次启动一个受保护的单次任务”模式。与常驻 Python 循环相比，`launchd`、cron 或其他进程管理器可以在进程崩溃、机器重启后继续调度。

## 1. 初始化

```bash
cd /absolute/path/to/ContestTrade
uv sync --frozen
uv run contesttrade doctor
```

API 密钥放在项目根目录 `.env` 或调度器环境变量中，不要写入 plist、crontab 或源码：

```dotenv
DEEPSEEK_API_KEY=...
# 可选
SERP_API_KEY=...
BOCHA_API_KEY=...
```

先手动执行一次受保护任务：

```bash
uv run contesttrade run --market CN-Stock --silent --timeout-seconds 1800
```

## 2. macOS launchd（推荐）

模板默认在周一至周五 18:30（系统本地时区）运行。安装前可修改模板中的 Hour 和 Minute。

```bash
cd /absolute/path/to/ContestTrade
project_dir="$(pwd)"
launch_agent="$HOME/Library/LaunchAgents/com.contesttrade.daily.plist"
sed "s|__PROJECT_DIR__|$project_dir|g" \
  ops/com.contesttrade.daily.plist.example > "$launch_agent"
plutil -lint "$launch_agent"
launchctl bootstrap "gui/$(id -u)" "$launch_agent"
launchctl enable "gui/$(id -u)/com.contesttrade.daily"
```

立即试运行：

```bash
launchctl kickstart -k "gui/$(id -u)/com.contesttrade.daily"
```

查看或卸载：

```bash
launchctl print "gui/$(id -u)/com.contesttrade.daily"
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.contesttrade.daily.plist"
```

## 3. Linux systemd（推荐）

用户级 systemd 服务支持 Web 常驻、失败重启和开机启动。先确认用户已开启 linger：

```bash
loginctl show-user "$USER" -p Linger
# 如未开启，由管理员执行：sudo loginctl enable-linger "$USER"
```

安装服务（替换模板中的项目绝对路径）：

```bash
cd /absolute/path/to/ContestTrade
mkdir -p "$HOME/.config/systemd/user"
for unit in contesttrade-web.service contesttrade-run.service contesttrade-run.timer; do
  sed "s|__PROJECT_DIR__|$PWD|g" "ops/systemd/$unit.example" \
    > "$HOME/.config/systemd/user/$unit"
done
systemctl --user daemon-reload
systemctl --user enable --now contesttrade-web.service contesttrade-run.timer
```

如服务器需要固定代理，可创建仅当前用户可读的环境文件，两个服务会自动加载：

```bash
mkdir -p "$HOME/.config/contesttrade"
chmod 700 "$HOME/.config/contesttrade"
cat > "$HOME/.config/contesttrade/environment" <<'EOF'
HTTP_PROXY=http://proxy-host:port
HTTPS_PROXY=http://proxy-host:port
NO_PROXY=127.0.0.1,localhost
# Web 外部监听时必填；不要写入仓库
CONTESTTRADE_WEB_PASSWORD=replace-with-a-strong-password
EOF
chmod 600 "$HOME/.config/contesttrade/environment"
```

定时器在周一至周五 08:00（`Asia/Shanghai`）唤醒，运行脚本会再查询沪深交易日历，节假日正常跳过。`Persistent=true` 会在服务器错过触发时间后于下次启动时补跑。

检查状态：

```bash
systemctl --user status contesttrade-web.service
systemctl --user list-timers contesttrade-run.timer
journalctl --user -u contesttrade-web.service -u contesttrade-run.service
```

## 4. Linux cron（备选）

使用 `crontab -e` 增加以下一行，并替换绝对路径：

```cron
30 18 * * 1-5 /absolute/path/to/ContestTrade/scripts/run_scheduled.sh >> /tmp/contesttrade.cron.log 2>&1
```

服务器时区应设为 `Asia/Shanghai`，或在 crontab 中显式设置 `CRON_TZ=Asia/Shanghai`。

cron 只负责工作日唤醒，`run_scheduled.sh` 会在非交易日退出且不调用模型。

## 5. 运行语义

- 退出码 `0`：成功或部分 Agent 失败但报告已生成（`degraded`）。
- 退出码 `1`：配置错误、任务超时、全部关键 Agent 失败或报告生成失败。
- 退出码 `75`：已有任务运行，本次调度跳过，防止重叠执行。
- 默认总超时 1800 秒，可通过 `--timeout-seconds` 或 `CONTEST_TRADE_RUN_TIMEOUT_SECONDS` 调整。
- 日志按天轮转，默认保留 30 天。

关键运行文件：

- `contest_trade/agents_workspace/runtime/last_run.json`：最近一次运行状态、耗时、指标与报告路径。
- `contest_trade/agents_workspace/runtime/contesttrade.lock`：进程互斥锁。
- `contest_trade/agents_workspace/logs/scheduled_YYYY-MM-DD.log`：轮转日志。
- `contest_trade/agents_workspace/results/`：Markdown 和 JSON 报告。

## 6. 健康检查

```bash
uv run contesttrade doctor
uv run contesttrade doctor --strict --stale-after-hours 30
```

建议外部监控每小时执行严格检查。严格模式下，配置错误、最近运行失败、没有运行记录或状态超过指定时间都会返回非零退出码。

本机 Web 服务启动后也可读取不含密钥和绝对报告路径的健康接口：

```bash
curl --fail http://127.0.0.1:8765/api/health
```

`last_run.json` 的 `status` 有三种终态：

- `success`：所有 Agent 正常完成。
- `degraded`：部分 Agent 失败，但核心链路和报告完成。
- `failed`：没有有效数据、全部研究 Agent 失败、超时或出现未处理错误。

## 7. 日常维护

- 更新代码后执行 `uv sync --frozen` 和完整测试。
- 定期检查 `doctor --strict`、日志中的外部接口错误和报告是否持续生成。
- 不要并行配置多个相同任务；即使误配，文件锁也只允许一个任务运行。
- GitHub Actions 会在提交和拉取请求时验证 Python 3.10/3.13、包入口、编译与单元测试。
