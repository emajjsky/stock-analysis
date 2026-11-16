const { app, BrowserWindow, WebContentsView, ipcMain, session, Notification } = require('electron');
const { spawn, execFileSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const http = require('node:http');
const { pathToFileURL } = require('node:url');
// 发行客户端使用自己的端口和数据目录，避免误复用开发库。
if(!process.env.WANGZHA_PORT)process.env.WANGZHA_PORT=app.isPackaged?'8766':'8765';
const { publicURL, trustedSender, LOCAL_ORIGIN } = require('./url-policy.cjs');
const {ensureSeed}=require('./storage.cjs');
const {verifyBackend,prepareFrontend,entryURL}=require('./delivery.cjs');
const root = path.resolve(__dirname, '..');
let window, child, browserSession, active, visible = false, bounds;
let nextId = 0;
const tabs = new Map();
let tooltipView, tooltipRevision = 0;
let noticeTimer;

function hideTooltip() {
  tooltipRevision++;
  tooltipView?.setVisible(false);
}
async function showTooltip(args) {
  const revision = ++tooltipRevision;
  tooltipView.setVisible(false);
  if (typeof args.label !== 'string' || !args.label || args.label.length > 40 ||
      !Number.isFinite(args.x) || !Number.isFinite(args.y)) return;
  // 仅本地静态提示视图，文字作为字符串赋值，不插入HTML或载入外站。
  const width = await tooltipView.webContents.executeJavaScript(`(() => {
    const label = document.getElementById('label');
    label.textContent = ${JSON.stringify(args.label)};
    return Math.ceil(label.getBoundingClientRect().width) + 6;
  })()`);
  if (revision !== tooltipRevision || window.isDestroyed()) return;
  const size = window.getContentBounds();
  tooltipView.setBounds({x:Math.max(0, Math.min(Math.round(args.x),size.width-width)),
    y:Math.max(0,Math.min(Math.round(args.y),size.height-36)),width,height:36});
  // 原生网页始终在主DOM之上，提示也需位于原生视图栈顶。
  window.contentView.removeChildView(tooltipView);
  window.contentView.addChildView(tooltipView);
  tooltipView.setVisible(true);
}

function available() {
  return new Promise(resolve => {
    const req = http.get(LOCAL_ORIGIN + '/api/v1/session', r => { r.resume(); resolve(r.statusCode === 200); });
    req.on('error', () => resolve(false));
    req.setTimeout(1000, () => { req.destroy(); resolve(false); });
  });
}
async function ensureBackend() {
  if (await available()) {
    if(app.isPackaged)throw new Error('客户端端口已被占用。请关闭已有王炸客户端，或在启动配置中指定其他 WANGZHA_PORT。');
    await verifyBackend(LOCAL_ORIGIN,app.getVersion());
    return;
  }
  const bundled=path.join(process.resourcesPath,'backend','wangzha-backend.exe');
  if(app.isPackaged&&!fs.existsSync(bundled))throw new Error('缺少内置数据服务，请完整解压客户端并核对发行校验值。');
  if(app.isPackaged&&fs.existsSync(bundled)) {
    const userRoot=process.env.WANGZHA_DATA_DIR||path.join(app.getPath('userData'),'data');
    fs.mkdirSync(userRoot,{recursive:true});
    const database=path.join(userRoot,'workstation.db'),seed=path.join(process.resourcesPath,'seed.db');
    if(!fs.existsSync(database)&&fs.existsSync(seed))ensureSeed(database,seed);
    const log=fs.openSync(path.join(userRoot,'backend.log'),'a');
    child=spawn(bundled,[],{cwd:path.dirname(bundled),windowsHide:true,stdio:['ignore',log,log],env:{...process.env,WORKSTATION_DB:database}});
    child.on('error',()=>{});
    for(let i=0;i<90;i++){if(await available()){await verifyBackend(LOCAL_ORIGIN,app.getVersion());return;}await new Promise(r=>setTimeout(r,500));}
    throw new Error('内置数据服务未就绪，请检查数据目录中的 backend.log。');
  }
  const venvPython = path.join(root, '.venv', 'Scripts', 'python.exe');
  child = spawn(process.env.WANGZHA_PYTHON || (fs.existsSync(venvPython) ? venvPython : 'python'), ['-X', 'utf8', 'run.py'], {
    cwd: root, windowsHide: true, stdio: 'ignore', env: { ...process.env },
  });
  let failed = false;
  child.on('error', () => { failed = true; });
  child.on('exit', () => { failed = true; });
  for (let i = 0; i < 60; i++) {
    if (await available()) {await verifyBackend(LOCAL_ORIGIN,app.getVersion());return;}
    if (failed) break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error('本地服务未启动。请先运行 python run.py，或设置 WANGZHA_PYTHON 为已有环境的 Python 路径。');
}
function snapshot() {
  return { active, tabs: [...tabs.values()].map(t => ({ id: t.id, url: t.url, title: t.title,
    loading: t.loading, error: t.error,
    back: t.view.webContents.navigationHistory.canGoBack(),
    forward: t.view.webContents.navigationHistory.canGoForward() })) };
}
function publish() {
  if (window && !window.isDestroyed()) window.webContents.send('browser:state', snapshot());
}
function layout() {
  for (const t of tabs.values()) {
    const show = visible && t.id === active && !!bounds;
    t.view.setVisible(show);
    if (show) {
      const size = window.getContentBounds();
      const x = Math.max(0, Math.min(size.width, Math.round(bounds.x)));
      const y = Math.max(0, Math.min(size.height, Math.round(bounds.y)));
      t.view.setBounds({ x, y, width: Math.max(1, Math.min(Math.round(bounds.width), size.width - x)),
        height: Math.max(1, Math.min(Math.round(bounds.height), size.height - y)) });
    }
  }
}
function openTab(value, referrer) {
  hideTooltip();
  const url = publicURL(value);
  if (!url) throw new Error('仅支持公开的 HTTP / HTTPS 网页');
  if (tabs.size >= 20) throw new Error('最多打开20个网页，请先关闭不用的标签');
  const view = new WebContentsView({ webPreferences: {
    session: browserSession, nodeIntegration: false, contextIsolation: true, sandbox: true,
    webSecurity: true, allowRunningInsecureContent: false,
  } });
  view.setBackgroundColor('#fffef9');
  const t = { id: String(++nextId), view, url, title: '正在打开…', loading: true, error: null };
  tabs.set(t.id, t);
  window.contentView.addChildView(view);
  const wc = view.webContents;
  wc.setWindowOpenHandler(details => {
    if (publicURL(details.url)) {
      try { openTab(details.url, details.referrer); } catch (e) { t.error = e.message; publish(); }
    }
    return { action: 'deny' };
  });
  wc.on('will-navigate', (e, value) => { if (!publicURL(value)) e.preventDefault(); });
  wc.on('will-redirect', (e, value) => { if (!publicURL(value)) e.preventDefault(); });
  wc.on('did-start-loading', () => { t.loading = true; t.error = null; publish(); });
  wc.on('did-stop-loading', () => { t.loading = false; publish(); });
  wc.on('page-title-updated', (_, title) => { t.title = title; publish(); });
  const navigated = (_, value) => { t.url = value; publish(); };
  wc.on('did-navigate', navigated);
  wc.on('did-navigate-in-page', navigated);
  wc.on('did-fail-load', (_, code, description, validatedURL, isMainFrame) => {
    if (isMainFrame && code !== -3) { t.error = '网页加载失败：' + description; t.loading = false; publish(); }
  });
  wc.on('render-process-gone', () => { t.error = '网页进程已退出，可点击刷新重新加载'; t.loading = false; publish(); });
  active = t.id;
  layout(); publish();
  wc.loadURL(url, referrer ? { httpReferrer: referrer } : {}).catch(() => {});
  return t.id;
}
const single=app.requestSingleInstanceLock();
if(!single)app.quit();
app.on('second-instance',()=>{const target=window&&!window.isDestroyed()?window:BrowserWindow.getAllWindows()[0];if(target){if(target.isMinimized())target.restore();target.show();target.focus();}});
app.whenReady().then(async () => {
  if(!single)return;
  await ensureBackend();
  await prepareFrontend(session.defaultSession);
  app.setAppUserModelId('Stock.Wangzha');
  browserSession = session.fromPartition('persist:wangzha-external');
  browserSession.setPermissionRequestHandler((_, __, callback) => callback(false));
  browserSession.setPermissionCheckHandler(() => false);
  browserSession.webRequest.onBeforeRequest((details, callback) => {
    let check = details.url.replace(/^wss:/, 'https:').replace(/^ws:/, 'http:');
    // data/blob资源不具备本地网络访问权；所有网络请求均检查目的地址。
    callback({ cancel: /^(https?|wss?):/.test(details.url) && !publicURL(check) });
  });
  window = new BrowserWindow({ width: 1560, height: 980, minWidth: 1050, minHeight: 700,
    icon:path.join(__dirname,'icon.ico'),
    show: false,
    title: '王炸', backgroundColor: '#fff8e7', autoHideMenuBar: true,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true } });
  tooltipView = new WebContentsView({webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
  tooltipView.setBackgroundColor('#00000000');
  tooltipView.setVisible(false);
  window.contentView.addChildView(tooltipView);
  await tooltipView.webContents.loadFile(path.join(__dirname,'tooltip.html'));
  window.on('blur',hideTooltip);
  window.on('resize',hideTooltip);
  window.webContents.setWindowOpenHandler(details => {
    if (publicURL(details.url)) { openTab(details.url); window.webContents.executeJavaScript("window.dispatchEvent(new CustomEvent('wangzha-open-browser'))"); }
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (e, value) => {
    if (new URL(value).origin !== LOCAL_ORIGIN) {
      e.preventDefault();
      if (publicURL(value)) openTab(value);
    }
  });
  window.on('resize', layout);
  window.webContents.on('did-start-navigation', (_, __, ___, mainFrame) => {
    if (mainFrame) { hideTooltip(); visible = false; layout(); }
  });
  window.on('closed', () => { tooltipRevision++; tooltipView.webContents.close(); for (const t of tabs.values()) t.view.webContents.close(); tabs.clear(); });
  ipcMain.handle('browser:command', (event, command, args = {}) => {
    if (!trustedSender(event, window.webContents)) throw new Error('无权访问桌面浏览器');
    switch (command) {
      case 'state': break;
      case 'tooltip':
        if (args.visible === true) return showTooltip(args).then(snapshot);
        hideTooltip();
        break;
      case 'open': openTab(args.url); break;
      case 'active': if (tabs.has(args.id)) active = args.id; break;
      case 'close': {
        const t = tabs.get(args.id);
        if (t) { window.contentView.removeChildView(t.view); t.view.webContents.close(); tabs.delete(args.id); }
        if (active === args.id) active = [...tabs.keys()].at(-1);
        break;
      }
      case 'viewport':
        visible = args.visible === true;
        if (!visible) hideTooltip();
        if (['x', 'y', 'width', 'height'].every(k => Number.isFinite(args[k]))) bounds = args;
        break;
      case 'navigate': {
        const url = publicURL(args.url);
        if (!url) throw new Error('请输入公开网页地址');
        if (!tabs.has(active)) openTab(url);
        else tabs.get(active).view.webContents.loadURL(url).catch(() => {});
        break;
      }
      case 'back': if (tabs.get(active)?.view.webContents.navigationHistory.canGoBack()) tabs.get(active).view.webContents.navigationHistory.goBack(); break;
      case 'forward': if (tabs.get(active)?.view.webContents.navigationHistory.canGoForward()) tabs.get(active).view.webContents.navigationHistory.goForward(); break;
      case 'reload': tabs.get(active)?.view.webContents.reload(); break;
      default: throw new Error('未知浏览器操作');
    }
    layout(); publish(); return snapshot();
  });
  const startup=new BrowserWindow({width:920,height:760,icon:path.join(__dirname,'icon.ico'),title:'王炸 · 准备行情',autoHideMenuBar:true,show:process.env.WANGZHA_TEST_HIDDEN!=='1',webPreferences:{preload:path.join(__dirname,'startup-preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true}});
  window.hide();
  const startupURL=pathToFileURL(path.join(__dirname,'startup.html')).href;
  let entering=false;
  ipcMain.handle('startup:command',async(event,command)=>{
    if(event.sender!==startup.webContents||event.senderFrame!==event.sender.mainFrame||event.senderFrame.url!==startupURL)throw new Error('无权访问启动服务');
    if(command==='enter'){
      if(entering)return;entering=true;
      await window.loadURL(entryURL(LOCAL_ORIGIN,app.getVersion()),{extraHeaders:'Cache-Control: no-cache\n'});if(process.env.WANGZHA_TEST_HIDDEN!=='1')window.show();startup.close();return;
    }
    if(command==='status')return (await fetch(LOCAL_ORIGIN+'/api/v1/history/status')).json().then(x=>x.data);
    if(command==='start'){
      const session=await fetch(LOCAL_ORIGIN+'/api/v1/session');const cookie=session.headers.get('set-cookie')?.split(';')[0];
      const response=await fetch(LOCAL_ORIGIN+'/api/v1/history/start',{method:'POST',headers:{'Origin':LOCAL_ORIGIN,'Cookie':cookie||'','Content-Type':'application/json'},body:'{}'});
      if(!response.ok)throw new Error('启动补数失败，请重试');return (await response.json()).data;
    }
    throw new Error('未知启动操作');
  });
  startup.on('closed',()=>{if(!entering)app.quit();});
  await startup.loadFile(path.join(__dirname,'startup.html'));
  let seenNotices;
  try{seenNotices=new Set((await (await fetch(LOCAL_ORIGIN+'/api/v1/notifications',{signal:AbortSignal.timeout(5000)})).json()).data.map(n=>n.id));}catch{}
  noticeTimer=setInterval(async()=>{
    try{
      const rows=(await (await fetch(LOCAL_ORIGIN+'/api/v1/notifications',{signal:AbortSignal.timeout(5000)})).json()).data;
      const next=new Set(rows.map(n=>n.id));
      if(seenNotices&&Notification.isSupported()&&process.env.WANGZHA_TEST_HIDDEN!=='1'){
        const fresh=rows.filter(n=>n.kind==='ALGORITHM'&&!n.read&&!seenNotices.has(n.id));
        for(const n of fresh.slice(0,5)){
          const notice=new Notification({title:n.title,body:n.message});
          notice.on('click',()=>{if(window&&!window.isDestroyed()){window.show();window.focus();window.loadURL(LOCAL_ORIGIN+'/#/stock/'+encodeURIComponent(n.security_id));}});
          notice.show();
        }
      }
      seenNotices=next;
    }catch{}
  },10000);
}).catch(error => {
  const { dialog } = require('electron');
  dialog.showErrorBox('王炸启动失败', error.message); app.quit();
});
app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => {
  clearInterval(noticeTimer);
  browserSession?.flushStorageData();
  if(child&&child.pid){
    // 只结束本次客户端创建的服务树，包含历史下载子进程。
    if(process.platform==='win32'){
      try{execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{windowsHide:true,stdio:'ignore',timeout:5000});}catch{}
    }else child.kill();
  }
});
