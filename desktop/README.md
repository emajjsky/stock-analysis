# 王炸桌面客户端 v0.3.0

发行便携包：完整解压后运行“王炸.exe”，包含冻结服务和独立行情seed。首次复制到用户目录，启动窗口检查并补缺失日线，联网失败保留缓存；进入后使用原有行情轮询。历史范围、实际覆盖、缺失与质量警告见同目录history-manifest.json。默认8766，与开发8765隔离；关闭客户端停止本机监测。原有用户库不会被seed覆盖。

Jev环境变量：TYPESAFE_API_KEY（兼容JEV_API_KEY）、JEV_MODEL（可选，默认jev-latest）；Agent：AGENT_API_BASE（含/v1）、AGENT_MODEL、AGENT_API_KEY。可复制发行包中的“配置模型示例.cmd”到本地填写后启动。密钥不会写进发行包。模型调用可能计费；自动调用只在新事件发生且勾选时运行，每任务每小时最多4组。Jev未配置状态与失败关闭、官方协议替身测试已覆盖，未进行付费接口调用。

源码构建（PowerShell）：在frontend和desktop分别npm ci；安装backend/requirements-lock.txt和desktop/build-requirements.txt；执行`python -m scripts.build_history_seed --download`准备独立发行库，完成后执行`pwsh -File scripts/build_desktop.ps1`。脚本拒绝覆盖已有输出目录，并在正式导出时拒绝未完成覆盖；历史数据库不提交Git。当前Windows未签名，未验证自动升级和干净机器安装。

以下为开发宿主说明：

从项目根目录双击 `启动王炸.cmd`，或在本目录执行 `npm start`。

首次开发安装：`npm ci`。前端仍在 `frontend` 执行 `npm run build`，Python环境沿用根目录 `.venv`。桌面启动会优先复用8765服务；未运行才使用已有 `.venv` 启动，不另开第二套。也可设置 `WANGZHA_PYTHON` 指定Python。

- “网页行情”默认打开 https://q.10jqka.com.cn/ ，支持20个内部网页标签、关闭、地址栏、前后退和刷新。原站的 `_blank`/`window.open(网页地址)` 转为内部标签。
- 网站登录会话保存在独立外站分区，不交给本地工作台或算法。网站需要的账号、行情权限、验证码仍由原站处理。先 `window.open('about:blank')` 再用脚本控制弹出窗口的特殊登录流程不保证兼容。
- 外站没有Node和本地桥；关闭摄像头/麦克风等权限，本地回环和常见私网网络地址被拦截。不移除CSP、不绕过证书错误，也不改写同花顺页面。
- 普通浏览器版有可选iframe预览和打开原站入口。iframe不具备跨域拦截新窗口的能力；多标签完整体验在此桌面宿主中。
- 便携包包含运行时和历史数据；代码签名、自动升级与干净机器验证尚未实施。

桌面依赖：Electron 45.2.3（MIT；Chromium等第三方许可见Electron发行目录的LICENSE/LICENSES.chromium.html），锁定于package-lock.json。Vue等前端依赖仍归frontend独立管理；未引入或复制AKShare源码。
