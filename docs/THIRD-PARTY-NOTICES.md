# 第三方组件与数据说明

本项目独立编写界面与领域服务，未复制go-stock、TradingAgents、Qlib、CZSC或AKShare算法源码。研究资料不等于已集成这些框架。

| 组件 | 本轮用途 | 许可/记录 |
|---|---|---|
| Electron 45.2.3 | Windows宿主、隔离外站网页 | MIT；发行目录附LICENSE和LICENSES.chromium.html，保留Chromium等完整第三方声明 |
| Vue 3、Vite、TypeScript | 前端 | MIT，精确版本见frontend/package-lock.json |
| lucide-vue-next | 图标 | ISC，锁文件记录版本 |
| lightweight-charts 5 | 原生日K与分时 | Apache-2.0；保留界面TradingView署名与项目说明，不关闭其归属标记 |
| FastAPI、Starlette、Uvicorn、HTTPX、pypinyin | 本机API和适配 | MIT/BSD，精确版本见backend/requirements-lock.txt |
| BaoStock 0.9.4 | 公开未复权完成日线 | PyPI元数据标为BSD License，作者baostock；官网https://www.baostock.com，元数据https://pypi.org/project/baostock/0.9.4/ |
| pandas、NumPy、python-dateutil、tzdata | BaoStock依赖 | BSD-3-Clause / Apache-2.0等，以发行包原始dist-info声明为准 |
| Python 3.12.3 | 冻结运行时 | PSF License，随冻结运行时保留许可 |
| PyInstaller 6.22.3 | 构建工具 | GPL-2.0-or-later及Bootloader例外，生成程序不因此要求整体GPL；构建锁见desktop/build-requirements.txt |
| rcedit 5.0.2 | 仅构建阶段写入输出副本的图标/版本资源 | MIT，锁定于desktop/package-lock.json，不作为运行时服务 |

公开数据来源包括新浪证券目录、腾讯财经行情和历史、BaoStock历史、东方财富研究与公告等。代码许可与数据权限分开；当前用于个人本机研究，没有声明获得交易所逐笔推送、商业转售或任意再分发授权。发行清单记录逐只覆盖、实际来源和质量限制。数据下载不包含付费登录凭据，不绕过数据源认证与验证码。

Jev为TypeSafe的远程服务适配，未分发模型权重，也不声明其开源。官方接口说明https://docs.typesafe.ai/；用户自行配置服务密钥，模型输出不构成执行授权。

打包脚本会附上可取得的Python依赖许可、元数据和Electron自带许可。examples中的富途第三方SDK压缩包/展开目录仅作本地参考，不纳入公开仓库或客户端。
