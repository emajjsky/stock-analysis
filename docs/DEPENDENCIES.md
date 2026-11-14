# 本轮组件来源与固定版本

核查日期：2026-10-27。前端实际版本来自package-lock.json及已安装包的package.json；后端完整解析版本见backend/requirements-lock.txt。安装依赖所带的LICENSE须随其适用发行方式保留。

| 组件 | 本轮实际版本 | 许可 | 用途与来源 |
|---|---|---|---|
| Vue | 3.5.44 | MIT | 前端组件，https://github.com/vuejs/core |
| lightweight-charts | 5.2.1 | Apache-2.0 | K线、均线、量柱、十字线，https://github.com/tradingview/lightweight-charts |
| lucide-vue-next | 0.468.0 | ISC；部分Feather沿用MIT | 图标，https://github.com/lucide-icons/lucide |
| Vite | 6.4.5 | MIT | 开发与构建，https://github.com/vitejs/vite |
| TypeScript | 5.9.3 | Apache-2.0 | 类型检查，https://github.com/microsoft/TypeScript |
| vue-tsc | 2.2.12 | MIT | Vue类型检查，https://github.com/vuejs/language-tools |
| Vitest | 4.1.12 | MIT | 前端验证，https://github.com/vitest-dev/vitest |
| Prettier | 3.9.10 | MIT | 源码格式，https://github.com/prettier/prettier |
| FastAPI | 0.135.1 | MIT | API路由，https://github.com/fastapi/fastapi |
| Uvicorn | 0.41.0 | BSD-3-Clause | 本地HTTP服务，https://github.com/encode/uvicorn |
| HTTPX | 0.28.1 | BSD-3-Clause | 模型兼容HTTP入口及测试，https://github.com/encode/httpx |
| python-multipart | 0.0.22 | Apache-2.0 | CSV上传，https://github.com/Kludex/python-multipart |
| pytest | 9.0.2 | MIT | 后端与跨模块测试，https://github.com/pytest-dev/pytest |
| pypinyin | 0.55.0 | MIT | 本地证券名称全拼/首字母索引，https://github.com/mozillazg/python-pinyin |

2026-10-29 行情增量来源：新浪公开证券清单（沪深目录；下载时原始范围还包含北交所，过滤保留5222条沪深证券），腾讯公开八指数快照、分时、未复权日线；东方财富证券清单仅作后备。新浪下载完整性和来源见 `evidence/terminal-increment/catalog-source-check.json`，原始分页仅存本机 `.local/source-probe/`。公开接口实测可访问不等于SLA或商业分发授权。pypinyin新增固定依赖和许可副本，未复制go-stock源码。

TradingView官方v5.2.1 [NOTICE](https://github.com/tradingview/lightweight-charts/blob/v5.2.1/NOTICE)及核心运行组件许可副本位于docs/licenses/。用户可见图表保留TradingView署名与链接；lightweight-charts内部含tslib的BSD-0-Clause片段，遵循其原包声明。

上游go-stock研究快照固定为59cfc64917476d21aeaeea921dad0ec0b0d01e62，实际GPLv3；没有复制其源码或把研究克隆纳入本仓库。评估记录见ADR-001和evidence/base-audit.md。这份清单不授予第三方行情或新闻的保存、转发权限；真实供应商权限须接入时另验。

本轮未替用户决定自有业务源码的最终发行许可证，也没有发布软件包。未来发行须带上完整依赖许可与实际能力清单。

2026-11-03 分时故障补充：腾讯minute/query实测返回HTTP501拦截页；独立东方财富公开分时 `https://push2his.eastmoney.com/api/qt/stock/trends2/get` 实测688066/301015均返回241点。作为完整序列备用，不尝试绕过腾讯拦截。字段f51时间/f53收盘/f56分钟手数/f57成交额，f56统一乘100为股；均价以该源完整分钟量额累计计算，保留来源与主源失败原因。未复制第三方代码或新增依赖，不代表SLA或商业分发许可。

2026-11-06 板块增量：新增东方财富公开板块列表/成分股push2delay clist、板块分时/日K与历史资金push2his接口适配；源码为本项目实现，未复制同花顺私有代码，无新增依赖。板块资金f62/f184为来源估算，行情允许延迟，历史轮动只来自本机存档；公开访问不代表商业分发或SLA。板块轻量图复用lightweight-charts，页面底部提供TradingView可见署名链接，许可沿用现存副本。实测范围见evidence/boards/live-api.json。

2026-11-06 板块第二轮无新增软件依赖。新增只读来源：同花顺q.10jqka.com.cn/gn/公开HTML（概念日期/事件/源成员数）；东方财富search-api-web搜索JSONP（关键词资讯）；datacenter-web RPT_LICO_FN_CPD及RPT_DMSK_FN_BALANCE（最新业绩与同报告期资产负债）；push2delay国内期货/场内基金；push2his期货分时/日K、板块日K历史回填。普通公开请求，不绕过认证或反爬，不复制第三方代码；公开可访问不等于商用授权或SLA。新概念仅完全同名映射到东财行情，期股主题人工维护，ETF仅主题候选；同花顺专有增仓、净量等未接。测试及界面证据见evidence/boards-completion/coverage.md。


2026-11-07 无新增软件依赖。新增只读来源：`https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc`天天基金ETF股票投资明细，校验基金代码及报告期，只解析JSON字符串内的HTML，不执行JS。范围为主要主题ETF的最新披露前十大样本，非实时或完整持仓；限频时停止新请求，保留失败数量和已有报告。未改变交易、算法、账户或自动更新设置。布局与来源证据见evidence/boards-revision-20261107/coverage.md。
