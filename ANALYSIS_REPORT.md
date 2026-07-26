# ContestTrade 稳定性修复汇总报告

> 项目：`/Users/tomcat/earn/ContestTrade`
> 日期：2026-07-26
> 范围：A 股模块的启动、数据采集、Agent 工作流、信号聚合、报告输出、缓存安全、Web 查看器与依赖

## 1. 结论

项目已从“研究 Agent 输出直接当最终结果”改为可校验、可去重、可排序的确定性输出链路，并完成了一次真实端到端运行。当部分数据接口或 Agent 失败时，其他并行 Agent 可继续完成，失败信息会进入结果统计和报告。

2026-07-26 的端到端验证结果：

- 总耗时：106.69 秒。
- 数据 Agent：4 个有效因子。
- 研究 Agent：9 条原始信号。
- 信号聚合：7 个唯一标的，合并 2 条重复提案。
- 输出：研究 Markdown、结构化 JSON、数据 Markdown 三份报告均成功生成。

## 2. 已修复问题

### 2.1 最终信号不可靠

- 新增确定性信号聚合器。
- 严格校验 A 股代码、动作、概率、证据和证据时间。
- 按股票代码合并重复提案，过滤买卖意见严重分裂的标的。
- 按概率、动作一致度、证据完整度和多 Agent 覆盖度评分，支持最低分、最低共识和 Top N。
- Markdown/JSON 报告展示聚合分数、来源 Agent、去重数和排除原因。

### 2.2 配置与启动失败过晚

- 每个 LLM/VLM 配置独立指定 `api_key_env`，取消未知 Provider 偷偷套用其他密钥的回退链。
- `YOUR_*` 占位符不再被当作真实密钥。
- 运行前校验主 LLM 密钥、模型名、数据 Agent、研究工具和 belief 文件，错误时直接给出可操作提示。
- 数据源与研究工具动态导入改为 fail-fast，不再静默忽略配置拼写错误。
- 删除永远不会成立的 `SimpleTradeCompany is None` 分支。

### 2.3 缓存安全与数据完整性

- 移除所有数据源缓存的 pickle 读写，消除可写缓存目录下的任意代码执行风险。
- 替换为 gzip JSON，DataFrame 使用 pandas table schema。
- 缓存写入使用临时文件 + `os.replace`，避免并发读取到半写文件。
- 损坏缓存会记录警告并重新获取，旧 `.pkl` 不再反序列化。

### 2.4 数据源与模型降级

- 删除分时数据的本地占位路径，对不可用能力返回明确降级说明。
- 新浪新闻端点由 HTTP 切换到已验证可用的 HTTPS，增加状态码检查、3 次有界重试和退避。
- Google/Serper 搜索增加 10 秒请求超时。
- 没有 SERP/Bocha 密钥时，`search_web` 不会注册给研究 Agent，避免无效工具循环。
- 将 LongCat-2.0 显式标记为不支持图片，价格分析改走主 LLM 文本分支，避免传图后长时间空响应。

### 2.5 Agent 容错与工具调度

- 数据 Agent 和研究 Agent 并发执行采用异常隔离，单 Agent 失败不再中断全部流程。
- 失败 Agent 数量与原因写入 `step_results`、Markdown 和 JSON。
- 工具注册失败会终止初始化；工具运行失败返回统一的 `success: false` 结构。
- 工具选择 JSON 连续解析失败后转入最终报告，不再无计数循环。
- Research Agent 的结构化 `parsed_signals` 进入正式输出，主工作流不再对 JSON 重复解析；XML 仅作旧报告兼容回退。

### 2.6 报告与 CLI

- 交互与静默模式共用同一个报告生成入口，同时生成研究 Markdown、结构化 JSON 和可用的数据 Markdown。
- JSON 报告失败不再被当成整体成功；静默模式会返回非零退出。
- 去掉分析完成后多余的 `input()` 阻塞。
- 接通中英文文本选择，支持 `CONTEST_TRADE_LANGUAGE`。
- 统一版本为 1.1.0，CLI 从安装包元数据读取版本。

### 2.7 Web 报告服务

- 默认从 `0.0.0.0` 改为 `127.0.0.1`，仅本机可访问。
- 如需外部监听，必须显式设置 `CONTESTTRADE_WEB_HOST`，启动时会警告需要 TLS 和访问控制。
- 改用 `ThreadingHTTPServer`，增加 CSP、`X-Frame-Options`、`nosniff`、`no-referrer`、`no-store` 等响应头。
- 恢复 HTTP 请求日志，并在退出时关闭 server socket。

### 2.8 依赖

- `pyproject.toml` 与 `requirements.txt` 已对齐；删除主流程未使用的 Tushare、LightGBM 和 joblib，保留 python-dotenv 与 prompt-toolkit 约束。
- 新增 PEP 621 CLI 入口，更新 `uv.lock`。
- 项目已按当前需求移除 Docker 构建与运行入口，仅保留本地 Python/uv/pip 运行方式。

### 2.9 冗余清理

- 删除无法导入且未接入主流程的旧 `contest_trade/contest` 训练、预测与竞赛实现；确定性聚合器是当前唯一信号优选路径。
- 删除旧 Tushare 数据源、Provider、选股与摘要工具；市场元数据统一使用离线缓存和 AKShare。
- 删除仓库中提交的历史 `.pkl` 运行缓存与 LightGBM 模型二进制，运行产物不再混入源码。
- 删除重复的 `cli/setup.py`、调试型 `__main__` 入口和未使用的报告包装函数。
- CLI 交互查看与落盘报告共用同一个模板构建入口，避免两套 Markdown 字段逐渐不一致。

## 3. 验证记录

| 验证项 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 17/17 通过 |
| 全项目 `compileall` | 通过 |
| `git diff --check` | 通过 |
| CLI `config` / `version` | 通过，版本 1.1.0 |
| 4 个数据 Agent + 2 个研究 Agent 初始化 | 通过 |
| 工具元数据 | 通过；无搜索密钥时每个研究 Agent 注册 6 个可用工具 |
| 新浪 HTTPS 单页抓取 | 通过，50 条 |
| 同花顺 API 单页抓取 | 通过，5 条（限制参数后） |
| Web `/api/reports` | HTTP 200，安全头齐全 |
| 真实端到端静默运行 | 通过，三份报告落盘 |
| 删除旧模块后的公司初始化 | 通过，4 个数据 Agent + 2 个研究 Agent |
| 离线报告回放 | 通过，Markdown/JSON 文件名与内容可解析 |
| `uv lock --check` / `uv pip check` | 通过，锁文件一致且依赖兼容 |

## 4. 已知剩余风险

1. 外部数据接口仍可能限流、断连或改变返回结构。当前已实现单 Agent/单子数据源降级，但无法保证第三方服务可用性。
2. 未配置 `SERP_API_KEY` 或 `BOCHA_API_KEY` 时，项目可稳定运行，但研究 Agent 没有通用 Web 搜索能力。
3. 当前没有历史收益驱动的 Agent 权重机制；如未来恢复该能力，需要基于现有聚合接口重新设计，旧实验代码可从 Git 历史查阅。
4. XML 信号解析仍作为旧报告兼容回退，新输出已优先使用 JSON。

## 5. 建议的下一阶段

- 先累积至少一个可比较窗口的信号与后续收益，再接入历史业绩 Agent 权重。
- 增加 CI：单元测试、编译检查和不含凭据的离线报告回放。
- 对外部数据源增加持久化健康指标：请求成功率、延迟、空数据率和最后成功时间。
