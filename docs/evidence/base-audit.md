# go-stock 底座源码审查证据

审查日期：2026-10-27。范围：固定源码、许可、架构耦合和本机构建前置检查。此文件不代表上游功能已成功运行，亦不证明算法收益。

## 1. 固定来源

- 上游：<https://github.com/ArvinLovegood/go-stock>
- 本地研究副本：`F:/教学案例/.research/go-stock`，使用 `git clone --depth 1` 创建。
- `git symbolic-ref refs/remotes/origin/HEAD` 返回 `refs/remotes/origin/dev`，实际默认分支为 `dev`。
- `git rev-parse HEAD` 返回 `59cfc64917476d21aeaeea921dad0ec0b0d01e62`。
- `git log -1 --format='%H%n%cd%n%s' --date=iso-strict` 返回提交时间 `2026-10-26T18:52:10+08:00`，标题 `feat(okx): 满仓换仓腾槽与反手开仓分数门槛`。
- 审查结束 `git status --short` 无输出；研究副本源码未修改。

所有下述行号对应此固定提交，不对应变化中的默认分支。可用以下固定链接核查：

<https://github.com/ArvinLovegood/go-stock/tree/59cfc64917476d21aeaeea921dad0ec0b0d01e62>

## 2. 许可证与实际技术栈

| 证据路径 | 直接观察 | 结论 |
|---|---|---|
| `LICENSE:1` | GNU GENERAL PUBLIC LICENSE, Version 3 | 根许可 GPL v3；源码复用需遵守其条件，不能用“开源”替代许可判断 |
| `go.mod:3` | `go 1.27.2` | Go 工具链要求至少 1.27.2 |
| `go.mod:49` | `github.com/wailsapp/wails/v2 v2.15.0` | Wails 2 桌面宿主 |
| `go.mod` | GORM、SQLite/modernc、Eino | 本地数据库、Go Agent 工具链 |
| `wails.json:1` | npm install/build/dev watcher，5173开发端口 | Wails 调用前端构建 |
| `frontend/package.json:27` | lightweight-charts `^5.2.0` | 成熟图表组件 |
| `frontend/package.json:33` | Vue `^3.5.33` | Vue 3 前端，JS/TS混合 |
| `frontend/package.json:52`、`:56` | Naive UI `^2.44.1`、Vite `^7.3.6` | 现成组件库与构建工具 |
| `.github/workflows/main.yml:78`、`:83`、`:84` | Go 1.27、Node 22.22.2、Wails v2.15.0 | 上游CI目标，不能代替本机构建通过 |

本轮独立实现不复制上述项目源文件；采用组件时单独记录组件许可。若未来选择 fork，需保留上游许可及对应来源，并重新评估发行要求。

## 3. 影响产品边界的源码证据

| 固定源码路径 | 观察到的行为 | 对本项目的影响 |
|---|---|---|
| `app_signal_monitor.go:14-22` | 注释明确买卖点算法保留在TS前端，Go cron仅通过Wails事件唤醒前端 | 后台独立监测不能假定已有；前端关闭、休眠及恢复需重新界定 |
| `frontend/src/components/kline/signalMonitor.ts:22-38` | 直接导入Wails runtime和App绑定 | 不是可独立HTTP运行的前端/后端契约 |
| `frontend/src/components/kline/signalMonitor.ts:47`、`:96`、`:183-191` | 监控池上限50，设置存localStorage | 服务端持久化监测及多页面一致性需单独设计 |
| `frontend/src/components/kline/signalMonitor.ts:226-253` | 信号监控校验VIP2等级 | README自述不能等同于已验证可用功能 |
| `app_signal_monitor.go:109-116` | 信号落库成功后直接调用`DispatchOKXSignalTrades` | 信号保存与交易副作用耦合，应拆开 |
| `backend/models/signal_trade_record.go:5` | 自动交易流水注释及字段针对OKX | 不等同于A股T+1、资金冻结、可卖库存及税费账本 |
| `main.go:108` | 启动`StartOKXTPSLMonitor` | 不能未经隔离运行整仓来验证纯A股功能 |
| `frontend/src/components/kline/calc.ts:1757` | 算法声称纯因果 | 尚未通过我们逐点回放测试，不据此认定无未来信息 |
| `frontend/src/components/kline/calc.ts:1843` | 箭头价格取当根low/high | 图形标记价格不能直接当可成交价格 |
| `backend/data/signal_record_api.go:235`、`:304` | 信号配对统计，并直接计算`(卖信号价-买信号价)/买信号价` | 不包含完整成交、费用、资金、T+1约束，不能当作账户收益 |

## 4. 可保留或参考的模块

- 图表：`frontend/src/components/StockLightweightKlineChart.vue`、`kline/calc.ts`、买卖点图形primitive。
- 行情/F10：`backend/data/tdx_kline_api.go:472`的K线、`:906`的F10，`stock_data_api.go:382`的报价，`f10_data_api.go:698`起的财务接口。
- 产品交互：自选、分组、推荐记录、信号去重、分页与通知。
- Agent：Eino、多模型适配、流式输出、工具调用、事实检查。用户需要的结构化信号复核仍应独立定义快照、时效、证据和权限。
- 独立建设：A股账户账本、T+1可卖库存、资金冻结、撮合、费用、做T与不做T对照，以及服务端统一信号生成。

## 5. 本机构建前置检查

在研究目录，仅执行工具版本查询与只读模块检查；没有执行上游发行exe、交易程序或联网测试，也没有读取凭据。

```text
go version
go version go1.27.1 windows/amd64

node --version
v24.19.0

npm --version
11.3.0

GOTOOLCHAIN=local go list -m
go: go.mod requires go >= 1.27.2 (running go 1.27.1; GOTOOLCHAIN=local)
```

最后一条在PowerShell当前进程设置`$env:GOTOOLCHAIN='local'`后执行，避免自动下载工具链。未升级Go、未安装Wails、未安装上游依赖、未运行完整前后端构建。故状态为“源码审查完成，完整构建未验证”，不是“上游不可构建”。

## 6. 本轮选择的依据与限制

不直接采用最新整仓作为交易核心，主要依据是前端信号运行、桌面绑定、VIP及OKX调度耦合，与本项目服务端信号、明确Agent复核、独立A股模拟账本边界不一致。

选择Vue/TypeScript前端及FastAPI/SQLite后端，是针对当前可交付闭环的独立实现决策，不是对两种路线工时的实测比较。本次没有完整运行上游，不能声称已证实fork成本必然更高。后续仍可在独立适配器中评估其数据与交互设计；复制代码前重新处理许可。
