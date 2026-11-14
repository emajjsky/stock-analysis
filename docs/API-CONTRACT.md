# 前后端并行开发契约 v0.2

2026-10-29 行情首页与基础库增量接口见 [TERMINAL-CONTRACT.md](TERMINAL-CONTRACT.md)。该增量授权后台拉取证券目录、首页指数、自选与最近访问行情，替代下方旧版“仅手动同步”限制。现有导入、算法、Agent与模拟接口保持兼容，实际运行路径数在本轮发布后重新导出核对。

日期：2026-10-28。主任务维护本文件与共享类型；前后端改契约先报告主任务，禁止自行更名。本轮授权来自用户“补充后派生前后端再合并”，覆盖旧文档的“仅文档”阶段限制。最新源码契约为38路径；正式8765运行时仍为旧35路径，缺少腾讯行情同步、同步记录和研究资料同步3个新路由，状态核对见`docs/evidence/real-data-increment/formal-service-check.json`。

## 交付边界

交付本地可运行分析版：全导航可达，真实持久化自选、CSV历史导入、指标/推荐/信号、结构化Agent复核、结果验证、独立可配置资金模拟账户和订单/做T对照。无账户可看盘。所有外部数据与LLM未配置时明确不可用；可由用户点击载入固定的合成演示数据，不自动造假行情。实盘入口保留禁用说明，无实盘发单接口。Qlib训练、商业数据授权、同花顺原生文件、SDK实盘、桌面安装包为后续门槛，不能宣称完成。

## 真实数据接入增量（2026-10-27）

- `GET /data/providers`现有Provider数组新增`id="tencent"`，字段保留`name,status,source,capabilities,limitations`，增加`connected:boolean,last_updated_at:string|null,latest_data_at:string|null,error:string|null,warning:string|null,data_mode:"LIVE"`。Provider.status为`AVAILABLE`（尚无成功运行）、`SYNCED`（最近同步成功）、`PARTIAL`或`ERROR`；connected仅表示存在已缓存快照，不代表传输连接仍打开或持续订阅。GET只读缓存，不访问上游。公开接口可能延迟/改版，无SLA，不代表商业授权。
- `POST /data/providers/tencent/sync`请求`{security_ids:string[1..50],sync_daily:boolean=false}`。六位沪深A股代码或SH./SZ.规范ID。固定HTTPS域名，不接受任意URL。日线同步单次最多5只，快照最多50只。响应`{provider_id:"tencent",status:"SUCCEEDED"|"PARTIAL"|"FAILED",quotes_updated:number,daily_rows_saved:number,securities_processed:number,errors:string[],limitations:string[]}`；新证券保存为`LIVE.SH.600519`等稳定ID，不覆盖SH./SZ.导入证券或DEMO。接受已保存LIVE前缀ID以便再次同步。
- `GET /data/sync-runs`返回最近30条运行记录，包含上述结果和`id,started_at,finished_at`。上游失败保留缓存、记录中文原因，不返回mock。GET不触发上游请求，默认无自动刷新、不加入自选、不运行选股、不交易。
- 快照与日线分开保存。Quote新增`mode="LIVE",source_time,fetched_at,raw_hash,stale,is_realtime:false`；`as_of`为上游时间而非抓取时间。Quote的价格、昨收、涨跌幅、成交量、成交额及源时间均为可空字段，异常或缺失不可用0替代。历史`provider_bars`独立表保留source/received_at/raw_hash/adjustment，Bar.amount类型为`string|null`，上游无成交额时保持null，不用收盘价乘成交量推算。Bar仅有已完成日线；本轮保守排除当日，盘后最近报价与日线截点可能不同。真实证券的security_id使用`LIVE.SH.*`/`LIVE.SZ.*`，状态`LIVE_UNVERIFIED`，而非CSV原有的`SH.*`/`SZ.*`；没有公司行业资料时sector为“未接入行业资料”。
- Meta增加LIVE/LIVE_HISTORY来源模式，混合仍MIXED，不表示数据新鲜度。外部证券禁止当前DEMO/IMPORTED模拟成交。选股存在有历史的真实证券时排除DEMO，不混合真实与合成排名。历史数据基线尚未完成复权/公司行为处理，不宣称可投资性。

## 技术决策

### 公司与公告研究资料增量（2026-10-28，源码已实现）

- 关联REQ-05/19、P04/P05。已有真实或CSV证券可在个股页显式同步公司概况、财务摘要与公告目录。合成DEMO不调用外部源；浏览和GET接口只读缓存。先接固定HTTPS研究端点，不抓取公告正文、不运行新闻情感分类，不承诺商业授权或完整F10。
- `POST /securities/{id}/research/sync` 请求 `{sections?:["company","financials","announcements"]}`，默认三项。sections非空、最多3项、不得重复或包含未知值；非法证券或参数422、并发同步409。返回 `{id,security_id,provider_id:"eastmoney-research",status:"SUCCEEDED"|"PARTIAL"|"FAILED",started_at,finished_at,updated_sections:string[],errors:string[],limitations:string[]}`。每节独立保存，失败保留该节旧版本。同步不改变行情、自选、信号、复核、账户和订单。
- `GET /securities/{id}/profile` 保留原Profile，增加 `research:{supported:boolean,provider_id,status:"AVAILABLE"|"SYNCED"|"PARTIAL"|"ERROR",last_synced_at:string|null,error:string|null,sections:string[],limitations:string[]}`、`financials:FinancialSummary[]`、`evidence:ResearchEvidence[]`。无研究字段的旧后端必须由前端提示升级后再使用，不能误报同步成功。
- `FinancialSummary={period:YYYY-MM-DD,published_at:string|null,publication_precision:"DATE"|"TIME"|"UNKNOWN",total_revenue:string|null,parent_net_profit:string|null,currency:"CNY",unit:"元",source,received_at,available_at,raw_hash}`。金额从源JSON十进制解析；缺失保持null。收入及利润是源报表期内累计口径，不将半年度误标单季。日期级披露时间保留DATE标志，UTC转换不意味着获知精确到盘中；available_at用本机首次抓取时间。
- events保留标题、来源、链接；published_at可null，增加publication_precision、received_at及available_at。仅保存公告标题与元数据；summary不伪装为阅读正文的结论，不把目录无记录等同于没有风险。
- `ResearchEvidence={id,section:"company"|"financials"|"announcements",source,source_url,received_at,available_at,raw_hash}`。分节证据版本只追加，最新指针独立；失败不清空缓存，源内容修订保留原证据。raw_hash仅证明抓取内容身份，不表示保存了原文或取得分发权限。`GET /data/providers`增添`id="eastmoney-research",data_mode="RESEARCH"`的只读状态。
- 研究资料现在可进入复核Agent上下文，但仅限`available_at <= signal.confirmed_at`的已知版本；复核保存证据清单、研究版本hash和模型引用ID，资料修订或请求期间版本变化会使结果保持WAIT并要求重新复核。资料不会自动生成正负面、胜率或执行结论；实盘和自动交易保持原边界。

本轮Vue3+TypeScript+Vite前端，FastAPI+SQLite后端，使用lightweight-charts成熟图表组件。浏览器本地工作台先合并运行，不先做桌面安装壳。go-stock固定commit为59cfc64917476d21aeaeea921dad0ec0b0d01e62，LICENSE为GPLv3；不直接复制其源文件，独立实现必要业务并复用有各自许可的组件。其前端计算/本地设置、VIP运行门槛和直接OKX执行耦合不满足本项目服务端信号/独立A股账本边界，见ADR-001。

## 传输与安全

- API地址/api/v1；前端开发5173，后端8765。Vite proxy和生产同源部署，fetch credentials: same-origin。
- GET /session获取会话并设置HttpOnly SameSite=Strict cookie；所有写接口校验会话及Origin/Host，仅loopback；无跨域宽泛放行。读取不含密钥。配置密钥仅环境变量，UI不暴露。
- 成功统一 {data:T, meta:{request_id:string,mode:"EMPTY"|"DEMO"|"IMPORTED"|"MIXED"|"LIVE"|"LIVE_HISTORY",source:string,as_of:string|null,stale:boolean}}。
- 失败 {error:{code:string,message_zh:string,details:object},meta:{request_id:string}}，按400/401/403/404/409/422/503返回。
- 金额、价格与得分用十进制字符串；数量整数；UTC ISO时间；前端显示Asia/Shanghai。不把算法分数标百分比。所有证券code为字符串。
- 服务端所有变更持久化SQLite，前端不能以localStorage假装保存。布局偏好可本地存。

## 对象定义

Security={id,code,name,exchange,sector,status,quote:Quote|null}。
Quote={price:string|null,previous_close:string|null,change_pct:string|null,volume:number|null,amount:string|null,as_of:string|null,source:string,mode:string,source_time?:string|null,fetched_at?:string|null,raw_hash?:string,stale?:boolean,is_realtime?:boolean}。
Bar={time:string(YYYY-MM-DD或ISO),open:string,high:string,low:string,close:string,volume:number,amount:string|null}。
Profile={security_id,business:string|null,facts:Array<{label,value,period,source}>,events:Array<{id,title,published_at:string|null,publication_precision:"DATE"|"TIME"|"UNKNOWN",available_at,received_at,source,url:string|null,summary,raw_hash}>,financials:FinancialSummary[],evidence:ResearchEvidence[],research:ResearchStatus,limitations:string[]}。
ResearchStatus={supported:boolean,provider_id,status:"AVAILABLE"|"SYNCED"|"PARTIAL"|"ERROR",last_synced_at:string|null,error:string|null,sections:string[],limitations:string[]}。ResearchStatus缺失时表示旧后端，不得显示研究同步按钮已可用。
FinancialSummary={period:YYYY-MM-DD,published_at:string|null,publication_precision:"DATE"|"TIME"|"UNKNOWN",total_revenue:string|null,parent_net_profit:string|null,currency:"CNY",unit:"元",source,received_at,available_at,raw_hash}。
ResearchEvidence={id,section:"company"|"financials"|"announcements",source,source_url:string|null,received_at,available_at,raw_hash}。
WatchItem={id,security_id,group_name,tag,monitor_enabled:boolean,security:Security}。
Algorithm={id,name,kind,version,description,timeframe,status,parameters:object,limitations:string[]}。GET /algorithms返回注册表；所有SELECTION算法必须由POST /recommendations/run的algorithm_id实际选择执行。首批支持rank-momentum-v1与trend-stability-v1，空algorithm_id仍默认前者。
Recommendation={id,security:Security,algorithm_id,score:string,reasons:string[],risks:string[],horizon:string,created_at,review:Review|null}。score是所选算法在当前可计算股票池中的相对排序分，不是概率；不同算法的分数不可横向比较。reasons与risks说明各自采用的价格/波动依据和缺失的数据，不得命名为基本面质量、财务健康或胜率。
Signal={id,security:Security,algorithm_id,kind:"BUY"|"SELL"|"T_BUY"|"T_SELL"|"WATCH",status:"CONFIRMED"|"EXPIRED"|"INVALIDATED",confirmed_at,valid_until,price:string,conditions:Array<{label,value,operator,threshold,passed:boolean|null}>,reasons:string[],review:Review|null}。
Signal.decision可选兼容旧数据={agent_mode:"OFF"|"EXPLAIN"|"FILTER",status:string,label:string,gate_passed:boolean|null,reasons:string[],checks:Array<{id,label,passed:boolean|null,detail}>,execution_permission:"NOT_EVALUATED",execution_label:string,evaluated_at:string}。OFF/EXPLAIN不参与过滤为null；基础无效或FILTER无有效模型支持为false；只有同信号/版本/输入hash、有时效、无附加条件的LLM SUPPORT可为true，仍无账户执行许可。规则演示永不放行FILTER。
Recommendation可兼容增加algorithm_version/input_snapshot_hash/data_as_of；信号增加algorithm_version/parameters_snapshot。旧输入不可覆盖；参数或行情改变后旧信号展示INVALIDATED，新计算保留新记录。过期优先展示EXPIRED，同时decision检查给出输入改变等全部阻断原因。
Review={id,signal_id,verdict:"SUPPORT"|"CONDITIONAL"|"WAIT"|"REJECT",summary,supporting_evidence:string[],opposing_evidence:string[],unknowns:string[],conditions:string[],limitations:string[],model:string,mode:"UNAVAILABLE"|"RULE_DEMO"|"LLM",research_evidence_snapshot:Array<{id,section,source,source_url,available_at,received_at,raw_hash,included:boolean,exclusion_reason:string|null}>,research_revision_hash,research_binding_status:"CURRENT"|"STALE"|"UNBOUND",research_binding_label,model_request_attempted:boolean,model_latency_ms:number|null,model_error_code:string|null,cited_evidence_ids:string[],created_at,valid_until}。`model_error_code`只返回稳定错误分类，不含供应商原始异常或凭据；前端映射为中文状态。复核只可引用`included=true`且其`available_at`不晚于信号确认时刻的研究资料；清单同时保留被排除资料及原因。RULE_DEMO只在显式请求演示复核时允许，并始终标“规则演示，非AI”。
Monitor={id,security_id,algorithm_id,enabled:boolean,parameters:object,agent_mode:"OFF"|"EXPLAIN"|"FILTER",updated_at}。
Notification={id,signal_id:string|null,title,message,created_at,read:boolean}。
Account={id,name,initial_cash:string,cash:string,equity:string,market_value:string,total_pnl:string,today_pnl:string,environment:"SIM",mode:string,trade_date:string,created_at}。
Position={security:Security,quantity:number,sellable:number,today_bought:number,average_cost:string,market_value:string,unrealized_pnl:string}。
Order={id,account_id,security_id,side:"BUY"|"SELL",quantity:number,filled_quantity:number,price:string,fee:string,purpose:"BASE"|"T",status:string,reject_reason:string|null,trade_date,created_at,idempotency_key}。
Comparison={actual_equity:string,baseline_equity:string,t_increment:string,today_actual_pnl?:string,today_baseline_pnl?:string,today_t_increment?:string,status:"COMPARABLE"|"DIVERGED_CONSTRAINTS"|"MISSING_DATA",fees:string,open_t_quantity:number,explanation:string}。当日盈亏各以两账本上一估值日的收盘权益为日初基准；当日T增益=今日实际盈亏−今日不做T盈亏。累计增益与当日增益不得相加到账户盈亏。
Provider={id,name,status,capabilities:string[],source,limitations:string[],data_mode?:string,connected?:boolean,last_updated_at?:string|null,latest_data_at?:string|null,error?:string|null,warning?:string|null}。对腾讯公开源，status含AVAILABLE/SYNCED/PARTIAL/ERROR；connected表示有缓存，不代表持续连接。前端不得仅凭data_mode=LIVE或connected=true显示为实时行情流。
ImportPreview={id,filename,valid_rows:number,invalid_rows:number,errors:Array<{row:number,message:string}>,securities:string[],columns:string[],sample:object[],can_commit:boolean}。
Evaluation={id,name,type,sample_size:number,status,metrics:Array<{label,value:string,description:string}>,limitations:string[]}。

## 接口表（字段名精确）

### 自动监测增量契约（2026-10-27）

自动监测默认关闭、间隔默认60秒；只使用已保存的日线，在后端服务运行期间工作。停止服务不继续监测，重启读取已保存开关；不补跑停机期间每个周期。启用后立刻安排下一次检查；关闭阻止后续步骤，已开始的模型请求无法撤销费用，迟到结果保留WAIT。与自动模拟/实盘交易无连接，也不自动拉取行情。

- GET `/automation` → `{enabled:boolean,interval_seconds:number,auto_review:boolean,next_run_at:string|null,last_run_at:string|null,last_status:string,last_error:string|null,active_monitor_count:number,worker_running:boolean,limitations:string[]}`。所有路径仍在`/api/v1`下。
- PATCH `/automation` → 同对象。请求`{enabled?:boolean,interval_seconds?:integer(30..3600),auto_review?:boolean}`；默认auto_review=false。开启auto_review代表用户允许在模型已配置时发起有限模型调用，界面须明确可能产生费用。
- POST `/automation/run` `{}` → 单次运行记录。即使定时关闭也可显式单次检查；与定时共享互斥租约，运行冲突409，不排重复队列。同步返回、最多5次模型调用，每次沿用20秒超时；无重试。
- GET `/automation/runs` → 最近30条运行记录倒序。`Run={id,status:"RUNNING"|"SUCCEEDED"|"PARTIAL"|"FAILED"|"CANCELLED"|"INTERRUPTED",trigger:"MANUAL"|"SCHEDULED",started_at,finished_at:string|null,generated:number,reviewed:number,skipped:number,error:string|null,details:string[]}`。部分复核失败为PARTIAL；无新数据正常完成，不造信号。
- 持久化配置、运行、owner/lease/heartbeat和自动复核尝试。多进程只能一个运行；失去租约的执行者不得继续写终态。进程崩溃后旧运行标INTERRUPTED，再开始新检查；自动复核按信号/输入/Agent模式/模型绑定最多尝试一次，崩溃或失败由用户手动重试，避免重复扣费。每轮最多复核5条，其他顺延；OFF、WATCH、失效/过期、未配置不调用模型。不自动使用规则演示。
- 自选删除最后一条同证券记录时停用该证券监测；历史信号、意见和账本保留。
- 实际验收已使用独立数据库，通过浏览器验证默认关闭、手动运行、真实两轮30秒定时扫描、重复信号快照去重、表单轮询不覆盖未保存编辑、配置刷新保持、无模型时不调用Agent、停用持久化及1280视口。完整记录见`docs/evidence/automation-increment/`。仅单机单进程运行范围已验证；多个独立进程同时竞争同一个SQLite库尚不属于可部署保证。

### 现有接口

| Method/Path | 请求 | data |
|---|---|---|
| GET /session | 无 | {authenticated:true,api_version:"0.2"} |
| GET /health | 无 | {status,version,database,mode} |
| GET /dashboard | 无 | {security_count,watchlist_count,signal_count,pending_review_count,latest_data_at,indices:object[],notices:string[]} |
| POST /demo/seed | {}，显式用户点击 | {loaded:boolean,security_count:number,message:string}；幂等不清用户数据 |
| GET /securities?q= | 可空 | Security[] |
| GET /securities/{id} | 无 | Security |
| GET /securities/{id}/profile | 无 | Profile；research.section_status按公司、财务、公告分节返回status、last_attempt_at、last_updated_at、source、error；旧缓存更新失败时status=STALE并保留原资料 |
| GET /market/bars?security_id=&timeframe=1d | 首版1d/1w/1mo | {security_id,timeframe,bars:Bar[],indicators:{ma5:(string|null)[],ma20:(string|null)[],rsi14:(string|null)[],macd:(string|null)[],atr14:(string|null)[]},limitations:string[]} |
| GET /watchlists | 无 | WatchItem[] |
| POST /watchlists | {security_id,group_name?,tag?} | WatchItem（重复同组返回已有） |
| PATCH /watchlists/{id} | {group_name?,tag?,monitor_enabled?} | WatchItem |
| DELETE /watchlists/{id} | 无 | {deleted:true} |
| GET /algorithms | 无 | Algorithm[] |
| GET /monitors | 无 | Monitor[] |
| POST /monitors | {security_id,algorithm_id,enabled,parameters,agent_mode} | Monitor；同组合更新新参数并记录版本 |
| GET /recommendations | 无 | Recommendation[] |
| POST /recommendations/run | {algorithm_id?} | Recommendation[]；algorithm_id精确选择已注册SELECTION模型；同步历史基线，不假称训练模型 |
| GET /signals?security_id= | 可空 | Signal[] |
| POST /signals/run | {} | {generated:number,signals:Signal[]}；只使用保存的已完成行情 |
| POST /reviews | {signal_id,demo?:boolean} | Review；未配置LLM生成UNAVAILABLE/WAIT，非成功支持 |
| GET /reviews | 无 | Review[] |
| GET /notifications | 无 | Notification[] |
| PATCH /notifications/{id} | {read:true} | Notification |
| GET /data/providers | 无 | Provider[] |
| POST /securities/{id}/research/sync | `{sections?:["company","financials","announcements"]}` | 研究资料同步结果；仅用户显式触发，失败保留旧分节缓存，不改变行情、信号、复核或账户 |
| POST /data/providers/tencent/sync | {security_ids:string[1..50],sync_daily?:boolean}；日线最多5只 | {id,provider_id,status,started_at,finished_at,quotes_updated,daily_rows_saved,securities_processed,errors:string[],limitations:string[],requested_security_ids,sync_daily}；仅用户手动触发 |
| GET /data/sync-runs | 无 | 最近30条Provider同步结果，不触发网络请求 |
| POST /data/imports/preview | multipart file，CSV UTF8/GBK | ImportPreview；列security_id/code/name/date/open/high/low/close/volume/amount可映射，支持基本中文别名 |
| POST /data/imports/{id}/commit | {allow_partial?:boolean} | {imported_rows:number,security_count:number}；含坏行默认拒绝；partial须用户明确选择 |
| GET /data/imports | 无 | ImportPreview[] |
| GET /evaluations | 无 | Evaluation[]；无样本显示空/待验证 |
| POST /evaluations/run | {} | Evaluation；只评估成熟后验信号，绝不伪造收益/胜率 |
| GET /sim/accounts | 无 | Account[] |
| POST /sim/accounts | {name,initial_cash:string} | Account；正数并有合理上限，不内置100万 |
| GET /sim/accounts/{id} | 无 | {account:Account,positions:Position[],orders:Order[],comparison:Comparison} |
| POST /sim/accounts/{id}/orders | {security_id,side,quantity:number,purpose:"BASE"|"T",idempotency_key:string} | Order；市场模拟按已保存价，明确历史/演示撮合；T+1严格校验，不当成真实盘中成交 |
| POST /sim/accounts/{id}/advance-day | {} | Account；仅DEMO允许，演示交易日推进，不声称完整节假日日历 |
| GET /live/status | 无 | {enabled:false,status:"NOT_CONFIGURED",requirements:string[]} |
| GET /settings | 无 | {agent_configured:boolean,agent_model:string|null,mode,version,limitations:string[]}，不返回密钥 |

## 联调验收

### 数据集、报价与账本约束（开发复查补充）

- Security/Quote/Bar可增加dataset_id与source字段。证券唯一身份必须区分DEMO与IMPORTED，同代码的演示和导入数据不可相互覆盖；未知复权方式的数据可用于研究，不可默认为可交易的未复权价格。
- Account附带dataset_id、valuation_as_of；创建请求可选mode、dataset_id，未指定时只在唯一可用来源中选择。DEMO与IMPORTED账户只能使用各自固定数据集；来源模糊或混合时拒绝下单。DEMO的起始交易日期从已有数据中选择，明确是历史演示时间。
- Order附带quote_as_of、market_date、execution_basis。下单必须存在账户trade_date对应的非复权报价；不能拿最新历史价在未来交易日成交。仅DEMO允许advance-day，且只能推进到该数据集实际存在的下一交易日；两账本同时重新估值，无下一日返回409。
- 幂等键按账户隔离，同key同payload返回原订单，同key不同payload返回409。买卖、费用、库存、订单、对照账本在一个事务内提交。
- BASE操作先同时校验实际与不做T对照账本，任何一侧不足则均拒绝，或明确DIVERGED_CONSTRAINTS；不允许凭空补现金。T只影响实际账本。未完成的T腿按同一时点市值比较，不当成已实现利润，费用逐笔仅计一次。
- Signal附加version、input_snapshot_hash；Review附加signal_version、input_snapshot_hash，其valid_until不晚于信号有效期。过期、失效、版本或输入变化后不得沿用旧SUPPORT。未配置LLM和规则演示始终保留显式模式。
- 初始两个选股算法为20日动量横截面排序和20日趋势稳定性（20日动量百分数÷14日Wilder ATR占收盘百分数−最近21根收盘最大回撤百分数）。算法仅从完整历史OHLCV读数，不推断财务/新闻；得分只在同次同算法股票池内有序，不能当胜率或跨模型比较。单算法重复运行替换当前推荐快照，保留自选、信号、复核和账本。
- GET /session也校验Host为loopback；会话使用安全随机值、服务端期限，写请求缺失或不符Origin一律拒绝。开发允许127.0.0.1/localhost的5173同源代理，生产为8765；不接受任意端口/后缀的伪loopback地址。

1. 空库进入前端，无账户资产、无假推荐；可显式加载演示。
2. 演示标记全局可见；选股→加自选→规则保存→信号→复核→通知可持久化。
3. 导入真实CSV后图表/算法读入库数据，演示与导入来源不同，坏行不会静默覆盖。
4. 创建任意正金额模拟账户，初始值正确；同日买入不能卖，DEMO推进交易日后可卖；重复幂等键不重复成交。
5. 实际和不做T对照同起点、T操作不重复计收益；约束差异标不可比。
6. 无LLM返回WAIT和未配置；显式规则演示不标AI；实盘不能提交订单。
7. 前端构建、后端测试、API契约及浏览器端到端通过后合并。后续完整RPD未实现项目保留状态，不以“第一版”代替全完成。

### 2026-11-03 个股资料自动更新补充
`GET /securities/{key}/profile`新增可选`research.auto_refresh:{enabled:boolean,pending:boolean}`，读取缓存并登记有界后台研究需求，非阻塞上游读取。`research_sync_run.requested_sections`记录实际请求栏目，用于初始化失败和时效退避。company/financials/announcements时效7天/6小时/15分钟，失败15分钟退避；enabled受服务网络设置和全局行情自动更新开关约束。首次获知证据语义保持不变，手动同步端点保留。详细边界见TERMINAL-CONTRACT末节。

### 2026-11-03 数据核查补充

- Quote增加`quote_schema_version=2`、`pe_ttm/pe_dynamic/pe_static`、`total_shares/float_shares`、`buy_volume/sell_volume`，十进制字符串；股本及内外盘统一股，五档委托仍为手。旧错误PE映射读时纠正，不把未知动态PE填成TTM。
- Intraday.points增加`average_price/cumulative_amount`十进制字符串、`cumulative_volume`整数股，可为null；均价=累计额/累计股，非分钟价简单平均。Intraday.indicators提供MACD/RSI数组。
- `GET /market/bars`的`adjustment=none|qfq|hfq`独立序列；增加`history_updated_at:string|null`、`history_refresh_due:boolean`，复权检查时效6小时。指标数组与返回bars等长，预热缺失null；含主图及14种常规副图。
- `POST /securities/{key}/history/sync?adjustment=qfq|hfq`，body `{}`，返回口径、实际日期覆盖、count、received_at。来源完整修订先归档旧序列再原子更新；不完整修订422 INCOMPLETE_REVISION，同步互斥409 SYNC_BUSY。不改不复权或策略输入。
- Profile.financials增加`revenue_yoy/profit_yoy`百分数字符串，可空；financial schema2用于自动升级旧缓存，仍守失败退避。Profile.corporate_actions为独立展示目录，`items`含period、published_at、record_date、ex_date、plan、status，附source/source_url/received_at/error。缓存成功1天、失败15分钟；日期级值不伪造盘中时刻，不纳入Agent冻结证据。

### 2026-11-03 图表工作区修复补充

- Intraday 增加 `average_supported:boolean`（兼容旧股票缓存时可省略）。八指数为 false，points.average_price 一律 null，包括旧缓存读时清洗；股票仍按真实累计成交额/累计股数计算，不能把成分股平均股价画成指数点位均线。
- 会话中间件在业务执行前返回 401 SESSION_REQUIRED 时，前端共享一次会话恢复并至多重放一次；网络超时、其他401和业务拒绝不重放。未扩大权限或延长原会话期限。
- 首次打开新股遇当前批次历史回填时，在下一个历史请求前让出批次；下轮优先报价/最近三只分时，失败保留缓存并返回实际 error。无缓存失败也保存明确错误，不用空等待替代失败。
- 展示均线按当前返回口径及周期的收盘价计算，自定义周期1–500，预热不足 null；8个显示槽位和可见性仅保存为浏览器UI偏好，不修改服务端策略指标或账本。无新增HTTP路径。

### 2026-11-04 逐笔成交只读接口
`GET /market/trades?security_id=LIVE.SH.600519`返回`{security_id,trades:[{time:"HH:MM:SS",price:string,volume_lots:integer,side:"BUY"|"SELL"|"UNKNOWN"}],source,fetched_at}`。只接受合法沪深股票，校验上游证券代码和市场；手数必须为非负整数，价格为正。无可用源返回422 `TRADES_UNAVAILABLE`，不以空缓存伪装成功。方向只映射源代码1/2，其他值UNKNOWN。成交金额字段不返回；前端大单过滤按正价格×手数×100股计算。此只读公开源不是完整Level-2委托队列，也未承诺持续实时/商业授权。

### 2026-11-03 分时故障恢复

`POST /market/refresh`增加可选query `security_id`，需为已激活真实证券；提交目标优先刷新，异步返回原RefreshStatus，不保证排队时已取得新数据。手动请求可在自动刷新关闭时执行，仍不改变配置。`GET /market/intraday`成功备用源时增加可选`fallback:boolean`、`primary_error:string|null`、`previous_close:string|null`、`source_url:string`；error为null，整条序列来自单一标明来源，禁止逐点混合。双源失败时error包含两个源的失败原因，已有点保留。东方财富分钟量单位手转股（科创板同样乘100），不沿用腾讯科创板的股单位。

### 2026-11-06 板块看盘只读行情

- GET /market/boards?kind=industry|concept：返回rows/total/source、status/refreshing/stale/error/enabled/fetched_at。板块含code/name/price/change_pct/amount/net_inflow/net_ratio/advancing/declining/unchanged/source_time/leader。amount与net_inflow为元的十进制字符串；资金是东方财富估算。
- GET /market/boards/{code}/members：rows为已有Security与Quote结构，Quote补充net_inflow/net_ratio；total是源成分数，loaded是支持的沪深普通A股数，不把未支持证券当作加载失败或补假证券。
- GET /market/boards/{code}/chart?period=intraday|daily|funds：分别含points/bars/flows，单位股/元，日K未复权。按源代码、市场、日期序校验，不同板块不拼接。
- GET /market/boards/rotation?kind=industry|concept：days按倒序包含已归档源交易日date、Top10 rows和fetched_at，最多10日，无历史不补造。
- POST /market/boards/refresh?kind=industry|concept&code=BKxxxx&period=intraday|daily|funds，body {}：可选code必须已在目录中。异步请求当前分类及指定板块的成员、图表，返回queued/enabled，不改变自动刷新开关；同键至少5秒手动冷却，最多12个待处理键。板块接口meta的source/as_of来自本板块数据，不能借用全局腾讯报价时间。

## 2026-11-06 板块扩展API

新增GET /market/boards/concepts/latest、/market/boards/benchmark、/market/boards/rotation/history?kind=industry|concept、/market/boards/{code}/news、/market/boards/{code}/financial、/market/futures、/market/futures/{identity}/chart?period=daily|intraday、/market/etfs。缓存封装同BoardCache，数据为只读真实源。期货身份先从已缓存目录校验；财务返回metrics(value/count)、rows(code/name/period)、sample_size/covered；轮动返回days(date/rows)、covered/total/failed/progress；金额为十进制字符串，持仓/期货量为合约张。`/market/boards/concepts/latest`仍提供兼容数据，但当前市场页不再把它作为独立导航页。

POST /market/boards/refresh增加可选section及future_id/future_period，用于显式重试当前视图补充源，不修改设置。原字段保持兼容；未知section、kind、合约或周期返回422。最新概念保留THS身份，board_code仅完全同名映射；不向证券激活接口提交期货/ETF身份。OpenAPI已重新导出64条路径。


## 2026-11-07 ETF披露持仓候选接口

`GET /api/v1/market/etfs/holdings`：沿用板块缓存状态，返回`rows:[{code,name,report_date,stale,holdings:[{code,name,weight}],raw_hash}]`、`total`取样ETF数、`failed`与`failed_codes`及`scope_note`。单个weight为披露报告中的净值占比十进制字符串，不是当前板块的持仓占比。仅取主要主题成交额较高ETF的最新一期前十大六位股票，五位港股不补码；当前实际样本为21只，不代表全市场ETF持仓。24小时缓存，服从自动行情开关，手动刷新可重试；逐个间隔350ms，有源限流则停止。部分失败保留已缓存报告并标stale，全失败保留整个成功缓存。前端按当前板块成员代码交集补充候选，与名称/人工主题匹配分开标注；持仓候选至少3只重合且披露净值权重合计不低于20%，单只或低权重偶然重合不列入。持仓加载、失败与无可靠候选使用不同状态。当前接口路径数随新增债股联动接口更新。
# 2026-11-07 板块增仓只读接口增量

`GET /api/v1/market/boards/positions?kind=industry|concept` 返回标准封装。非法分类422；服从网络/自动更新开关；缓存优先，后台有界回填，不触发选股、监测或交易。

- `rows` 保留板块行情字段，并增加 `position_today/position_2d/position_3d`（百分数十进制字符串，未知null）、`rank_today/rank_2d/rank_3d`（只为有值板块生成，降序、同值同名次）。
- `covered/total` 为2日历史计算覆盖/当前分类总数；`progress` 为本进程回填进度，`failed` 为最近回填失败数；`source/formula/list_fetched_at` 保留口径和快照时间。
- 今日主力净额÷成交额；2/3日对齐连续交易日后以净额之和÷成交额之和计算；3日历史不足时保留原生3日字段。东方财富主力为超大单+大单，不是真实机构持仓或同花顺原数值。
- `POST /api/v1/market/boards/refresh?...&section=position` 手动重试，仍使用现有认证、去重、冷却和自动设置不变规则。
- 历史有界四个在途任务、共享并发信号量、600秒任务限额；增量持久化，429/514停止继续提交，失败保留旧历史，缺日或缺金额不补零、不跳日、不参与对应排名。

## 2026-11-07 债股联动只读行情

`GET /api/v1/market/bonds/convertible`返回标准缓存状态和`rows:[{id,code,name,price,change_pct,amount,source_time,stock_id,stock_code,stock_name,stock_price,stock_change_pct,stock_source_time,change_spread,listing_date,conversion_start,conversion_end,conversion_state,initial_conversion_price,issue_scale}]`。可转债行情来自东方财富`b:MK0354`公开延时快照；正股代码/名称、发行初始转股价及转股日期来自`RPT_BOND_CB_LIST`发行条款，再按交易所代码批量取同源正股快照。来源当前报价约317只、可按条款精确联接数量以响应`loaded/total/unmatched`为准；不保证固定覆盖数。

`change_spread`单位为百分点，公式=`bond.change_pct - stock.change_pct`；它只表示该快照中的日涨跌幅差，不是相关系数或交易信号。`conversion_state`按中国时区当前日期和条款转股起止日计算；`initial_conversion_price`只代表发行初始转股价。当前公开条款源的`TRANSFER_PRICE`/现行调整价和剩余规模为空，不能以初始价代替或推算转股价值/溢价率，缺失正股报价也保留null。周末/盘后可显示最近交易日行情时间；不承诺实时推送。

`POST /api/v1/market/boards/refresh?section=bond`手动重试债股数据，服从现有自动更新开关、认证与缓存策略；不会触发板块排行榜、股票激活、算法、Agent或交易。

当前本地OpenAPI包含66条路径；公开接口数量为工程状态，随后续路由增减更新。

