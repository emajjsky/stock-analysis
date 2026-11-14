# 王炸数据源选型核查：StockAPI、AKShare、Futu API、必盈与Level-2

核查日期：2026-11-09。范围为官方在线资料、指定GitHub源码、用户提供的富途SDK静态核查。本文是选型研究，不表示已接入新源、取得行情授权或完成盘中实测。

## 1. 结论

当前产品以A股为主。StockAPI和AKShare可以作为采集工具，Futu可以作为符合权限条件的个人实时LV1接入候选，必盈可以作为历史和批量行情的付费评测候选。这四者都不能直接确认为免费、稳定、可集中在服务器采集并向多个APP用户分发的A股Level-2方案。

免费/付费、是否需要API Key、是否推送、数据等级、再分发权限是不同维度。付费套餐不自动等于交易所Level-2或商业分发授权；API Key只是访问身份，不说明数据等级。

选股、日线趋势、波段和普通自选条件监测可先用校验后的历史数据与LV1，不需要等Level-2才开始。订单流、深度盘口、撤单或逐笔委托策略则必须另配相应数据，不能用五档快照或分钟线替代。

## 2. 对比

| 方案 | 实际性质 | 适合当前用途 | A股Level-2核查结果 | 主要边界 |
|---|---|---|---|---|
| zhangxiangliang/stock-api | MIT的TypeScript采集工具，腾讯/新浪/东方财富接口封装 | Node/MCP查询、公共接口备用实现参考 | 核查的源码/文档未提供正式A股L2服务 | 和现有腾讯/东方财富源高度重合，不构成独立授权行情供应商 |
| AKShare | 开源Python财经数据接口库 | 历史、财务、行业、ETF等补充采集与离线研究 | 文档中的实时行情/逐笔接口不能据此认定为授权L2流 | 不同接口来源、时效和单位不同；部分与现有源重合，可能限流或封IP |
| Futu API | SDK + OpenD网关 + 登录账号权限 | 符合条件账号的自选/当前个股实时LV1订阅和推送 | 官方A股仅列LV1、盘口5档；没有列A股LV2 | 订阅/历史额度，账号与登录IP条件；API权限和APP权限不完全一致 |
| 必盈API | licence访问的第三方HTTP数据服务 | 历史/财务和全市场批量报价候选 | 文档所列深度包是分钟K线和批量快照，不能认定为L2 | 免费配额很低；更新周期逐接口不同；商业分发/打包权限需单独确认 |

## 3. StockAPI指定项目

用户确认项目：https://github.com/zhangxiangliang/stock-api

- 核查分支main，固定源码commit：`bdab24063fbb7e317608bb5ea3e51f9319dd9d95`。
- README标注MIT；支持Node、浏览器、CLI、MCP；自动兜底顺序为腾讯→新浪→东方财富。
- 腾讯源码明确使用`qt.gtimg.cn`报价与`web.ifzq.gtimg.cn`K线；东方财富默认使用`push2delay.eastmoney.com`和`push2his.eastmoney.com`。这些和当前backend/providers.py、backend/boards.py来源有重合。
- 标准Stock接口主要统一名称、代码、现价、高低、涨跌比例、昨收及source；不能把它作为当前完整盘口、估值、历史归档和行情权限体系的直接替代。
- README明确不保证准确性、完整性、实时性或持续可用性，并要求商业/高频/生产使用前确认上游授权。
- 建议保留为实现参考或未来MCP查询候选，不为换一个封装库而替换现有已验证后端。

来源：

- https://github.com/zhangxiangliang/stock-api
- https://github.com/zhangxiangliang/stock-api/blob/bdab24063fbb7e317608bb5ea3e51f9319dd9d95/src/stocks/tencent/index.ts
- https://github.com/zhangxiangliang/stock-api/blob/bdab24063fbb7e317608bb5ea3e51f9319dd9d95/src/stocks/eastmoney/index.ts
- https://github.com/zhangxiangliang/stock-api/blob/bdab24063fbb7e317608bb5ea3e51f9319dd9d95/src/types/utils/stock.ts

## 4. AKShare

- 官网当前展示1.20.36文档，是数据接口库，不是自有交易所行情源或天然可用的全市场推送网关。
- `stock_zh_a_spot_em`文档称可返回沪深京A股报价；目标来源东方财富，与当前一部分来源重合。
- `stock_bid_ask_em`是东方财富行情报价接口；接口名称和有买卖盘口不等于Level-2。
- `stock_zh_a_hist`为日频历史，提供不复权、前复权、后复权；适合历史补数研究，仍需核对源修订与复权口径。
- 文档对新浪历史接口提醒多次获取容易封禁IP；官网FAQ还记录接口变更、网络、依赖和数据源异常。不能将接口库“免费”理解为大规模实时采集没有限制。
- 建议按接口引入，放后台独立采集任务，统一证券ID、源时间、股/手、元/万元、复权与修订记录。避免把AKShare与直接东方财富调用当作两条完全独立的容灾来源。
- 软件开源许可与上游数据的展示、保存和再分发许可分别核实。

来源：

- https://akshare.akfamily.xyz/
- https://akshare.akfamily.xyz/data/stock/stock_quote.html
- https://akshare.akfamily.xyz/faq.html
- https://github.com/akfamily/akshare

## 5. 富途与用户SDK

本地SDK：`examples/FTAPI4Python_10.12.7208/FTAPI4Python_10.12.7208`，VERSION.txt为10.12.7208，setup.py标注Apache License 2.0。

静态核查发现：

- `futu/examples/quote_push.py`包含报价、盘口、逐笔、经纪队列回调，但演示证券为港股。不能把示例支持的港股权限推广到A股。
- `OpenQuoteContext`可连接默认127.0.0.1:11111；SDK包含get_market_snapshot、subscribe、get_stock_quote、get_rt_ticker、get_order_book和历史K额度查询。
- OpenD是独立必需网关，可运行本机或服务器，需登录平台账号。SDK文件夹不等于已装好OpenD，也不赋予行情权限。
- 本次未发现默认11111端口监听，未登录账号、未订阅真实行情、未运行示例中的交易部分。

当前官方在线文档确认：

- A股：境内认证客户免费LV1，国际客户暂不支持；官方提示按OpenD登录IP区分相关客户类别，资格以实际账户和官方规则为准。
- 行情QA的A股摆盘档数为LV1五档，LV2/LV3/SF列均为不支持。API和APP权限不完全一致，购买APP行情卡不能推定OpenD也能获取。
- 港股存在符合条件免费LV2，美股有推广期行情权益；它们是其他市场规则，不能替代A股L2。
- 资产低于1万港币（含未开户）基础档为100订阅额度、100历史K线额度。每只证券每种订阅类型占1额度；例如报价+盘口+分时为3额度/证券。历史K额度按最近7天不同标的计，不是100根K线。
- 高等级额度提升也不是全A股无限订阅。个人档不适合作为全市场历史初始化和多用户共享行情总线的默认方案。
- 文档允许OpenD上云属于部署能力，不等于允许用一个个人账号把行情再分发给全部APP用户；需另核实对应协议/商业授权。

建议：如需自己验证自选实时推送，富途LV1值得优先做只读试接；如目标为统一服务器向用户提供行情，应先解决服务权限和规模条件，不默认复用个人权益。

来源：

- https://openapi.futunn.com/futu-api-doc/quote/overview.html
- https://openapi.futunn.com/futu-api-doc/intro/authority.html
- https://openapi.futunn.com/futu-api-doc/qa/quote.html
- https://openapi.futunn.com/futu-api-doc/opend/opend-intro.html
- https://openapi.futunn.com/futu-api-doc/quote/get-order-book.html
- https://openapi.futunn.com/futu-api-doc/quote/get-ticker.html

## 6. 必盈：逐接口看时效，深度包不等于Level-2

官网2026-11-09可见套餐信息（价格/配额可能调整，以下非采购确认）：

- 免费版：每日200次、期限3年，仍需licence。
- 包年版页面特惠688元/年；更高等级有不同限频。页面和旧文档的套餐名称/部分限频有差异，最终按证书实际权益及供应商确认。
- 深度行情包独立计费：页面现价158元/月、1088元/年，另有新客/老客折扣。免费证也可加购。
- 深度包核心为最新/历史1分钟K、完整历史分钟K、全市场批量报价；页面没有因此赋予十档/逐笔委托/订单队列L2能力。

具体接口：

| 数据 | 文档标注 | 影响 |
|---|---|---|
| 实时交易（公开） | 交易时段每1分钟更新 | 快照用途；每秒请求不意味着源每秒变化 |
| 实时交易（券商） | 实时 | 没有可量化时延保证，需盘中源时间对照 |
| 五档盘口 | 实时五档 | 不等于十档或逐笔委托Level-2 |
| 全市场批量报价 | 约3次/分钟；包年/白金或深度包等符合条件证书 | 有助服务端批量缓存；约20秒调用间隔不等于20秒源延迟上限 |
| 当天逐笔交易 | 盘中约60分钟更新，盘后定稿 | 不适合实时逐笔看盘或订单流信号 |
| 历史逐笔交易 | 2026-08-13起累积归档 | 不能据此承诺多年完整逐笔历史 |
| 完整历史分钟K | 按标的可采范围；本年度年片每月更新 | 最新部分需另用Pro接口补齐，不能承诺任意证券自上市分钟完整 |

4小时交易时段若每30秒1次请求，单一接口已需约480次/日，免费200次不足，尚未包括历史、详情、失败重试。多用户使用必须服务端共享采集与缓存，不能每个用户触发一次上游全市场下载。

商业边界：公开服务条款第6节仅列技术产品不可转让、非排他使用许可，并未明确授予本项目的行情APP转发、离线数据打包或算法非展示使用范围。不能因购买“企业版”就自行认定已经取得这些数据权利，也不据此断言供应商没有相关资质；需提供适用的明确协议。

建议：必盈列为低成本批量/历史候选，先测源时间、缺失、复权、单位、稳定性和授权范围，再决定是否替换当前来源。本次无licence，未调用鉴权行情接口，未购买套餐。

来源：

- https://www.biyingapi.com/licencelt
- https://www.biyingapi.com/doc_hs
- https://www.biyingapi.com/packs
- https://www.biyingapi.com/tk

## 7. 免费Level-2与正式APP的选择

五档快照、页面上的逐笔列表、按金额估算的资金流，均不能单凭名称认定为完整Level-2。上海官方Level-2产品列有十档价格/股数/委托笔数、第一档前50笔委托量、逐笔成交等能力；具体交易所及产品的数据集合不同，不能承诺每个L2套餐都包含全部逐笔委托与撤单。

本次没有找到同时满足A股、稳定实时、完整所需深度、服务器集中使用和多用户APP分发的免费L2方案。可能存在券商赠送的个人客户端权益、限时体验或研究样本，但必须逐项确认是否有API、何种市场、实际时效和使用范围。

上证所信息网络官方将Level-2展示与非展示许可分别列出。我们的行情页面展示、服务器算法计算、向用户分发历史数据包，都应在采购/合作范围内分别说明。StockAPI的MIT、Futu SDK的Apache或AKShare的开源许可，均不替代数据授权。

来源：

- https://www.sseinfo.com/services/assortment/level2/
- https://www.sseinfo.com/aboutus/authstatement/

## 8. 推荐落地顺序

1. 开发期保留现有缓存行情与历史机制，AKShare按需补资料；暂不因换封装库重写看盘页。
2. 个人实时验证优先试富途LV1；历史/全市场报价评测必盈。两者目的不同，不因某一路成功就认定满足商业分发。
3. 正式APP优先确定具备服务器使用、用户展示及所需历史保存/分发范围的LV1供应方案，再单独报价L2。基础选股算法可以先跑，不等待订单流数据。
4. 技术架构：供应商→独立采集适配器→统一校验/缓存/历史库→服务端算法和客户端推送；客户端本地数据包与增量更新继续保留。获准分发的数据只采集一次，按用户订阅分发，不把供应商密钥打进客户端。
5. 数据源权限与产品会员权限分开：超管只能把实际购得且允许对应使用的能力开放给用户，不能通过会员开关凭空产生L2权限。

待实测的关键项：沪深京/ETF/指数覆盖、源时间而非仅HTTP延迟、开盘/午休/收盘表现、断线补齐、批量缺失、历史起点、复权修订、字段单位、额度与用户数预算。数据接入完成标准必须同时覆盖代码、真实返回和页面呈现；本轮仅完成资料/静态选型核查。
