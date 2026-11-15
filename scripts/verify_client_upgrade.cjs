/* 旧缓存升级回归：同一Chromium配置先缓存旧入口，再启动真实发行包。 */
const {_electron:electron}=require(process.env.WANGZHA_PLAYWRIGHT||'C:/ProgramData/anaconda3/Lib/site-packages/playwright/driver/package');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
async function until(check,timeout=90000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,200));}throw Error('等待升级验收超时');}
async function main(){
  const root=path.resolve(__dirname,'..'),binary=process.argv[2]||path.join(root,'release/Wangzha-0.3.2-win-x64/王炸.exe');
  const data=fs.mkdtempSync(path.join(root,'.runtime/ux-031/upgrade-')),profile=path.join(data,'profile'),warm=path.join(data,'warm');fs.mkdirSync(warm);
  const output=path.join(root,'docs/evidence/client-upgrade-20261115');fs.mkdirSync(output,{recursive:true});
  const checks=[],errors=[];let networkRequests=0;
  const server=http.createServer((req,res)=>{networkRequests++;res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'public, max-age=31536000'});res.end('<html><body><h1>旧版选股页面</h1><button>运行一次</button><script>localStorage.setItem("upgrade-keep-preference","保留原配置")</script></body></html>');});
  await new Promise(resolve=>server.listen(8778,'127.0.0.1',resolve));
  fs.writeFileSync(path.join(warm,'package.json'),JSON.stringify({name:'wangzha-desktop',main:'main.cjs'}));
  fs.writeFileSync(path.join(warm,'main.cjs'),`const {app,BrowserWindow}=require('electron');app.whenReady().then(()=>{const w=new BrowserWindow();w.loadURL('http://127.0.0.1:8778/#/discover');});app.on('window-all-closed',()=>app.quit());`);
  let warmed;
  try{
    warmed=await electron.launch({executablePath:path.join(root,'desktop/node_modules/electron/dist/electron.exe'),args:[warm,'--user-data-dir='+profile]});
    const page=await warmed.firstWindow();await page.getByRole('heading',{name:'旧版选股页面'}).waitFor();
    assert.equal(await page.evaluate(()=>localStorage.getItem('upgrade-keep-preference')),'保留原配置');
    const before=networkRequests;await page.goto('about:blank');await page.goto('http://127.0.0.1:8778/#/discover');
    await page.getByRole('heading',{name:'旧版选股页面'}).waitFor();
    assert.equal(networkRequests,before,'预置旧入口必须确实由HTTP缓存复用');
    checks.push({check:'升级前同一配置目录确实复用旧版入口HTTP缓存',passed:true});
  }finally{if(warmed)await warmed.close();await new Promise(resolve=>server.close(resolve));}
  const app=await electron.launch({executablePath:binary,args:['--user-data-dir='+profile],env:{...process.env,PATH:'C:\\Windows\\System32',WANGZHA_DATA_DIR:path.join(data,'data'),WANGZHA_PORT:'8778',WORKSTATION_AUTO_DATA:'0',WANGZHA_TEST_HIDDEN:'0'},timeout:90000});
  try{
    assert.deepEqual(await app.evaluate(({app})=>({version:app.getVersion(),packaged:app.isPackaged})),{version:'0.3.2',packaged:true});
    await until(()=>app.windows().some(w=>w.url().endsWith('/startup.html')));
    const startup=app.windows().find(w=>w.url().endsWith('/startup.html'));await startup.locator('#enter').waitFor();await until(()=>startup.locator('#enter').isEnabled());
    await startup.locator('#enter').click();await until(()=>app.windows().some(w=>w.url().startsWith('http://127.0.0.1:8778/')));
    const page=app.windows().find(w=>w.url().startsWith('http://127.0.0.1:8778/'));page.on('pageerror',e=>errors.push(String(e)));
    await page.getByRole('heading',{name:'算法选股与监测',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>localStorage.getItem('upgrade-keep-preference')),'保留原配置');
    assert.ok(page.url().includes('client=0.3.2'));
    const html=await page.request.get('http://127.0.0.1:8778/');assert.equal(html.headers()['cache-control'],'no-store');
    assert.equal(html.headers()['x-wangzha-version'],'0.3.2');
    checks.push({check:'真实包升级后刷新旧缓存，保留原本地配置，入口与服务版本一致',version:'0.3.2',passed:true});
    let submits=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/lab/jobs'))submits++;});
    const accepted=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/lab/jobs'));
    await page.getByRole('button',{name:'开始选股',exact:true}).click();const job=(await (await accepted).json()).data;
    const bar=page.locator('.lab-persistent-progress');await bar.waitFor();assert.equal(await bar.getAttribute('data-job-id'),job.id);
    await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
    await until(async()=>{const b=await bar.boundingBox();return b&&b.y>=0&&b.y<100;});
    await page.screenshot({path:path.join(output,'running-scrolled.png')});
    const initial=Number(await page.getByLabel('全局算法筛查进度',{exact:true}).getAttribute('value'));
    await until(async()=>Number(await page.getByLabel('全局算法筛查进度',{exact:true}).getAttribute('value'))>initial);
    await page.getByRole('button',{name:'数据与设置',exact:true}).click();assert.equal(await bar.getAttribute('data-job-id'),job.id);
    await page.screenshot({path:path.join(output,'running-settings.png')});
    await page.getByRole('button',{name:'发现',exact:true}).click();assert.equal(await bar.getAttribute('data-job-id'),job.id);
    await page.reload();await bar.waitFor();assert.equal(await bar.getAttribute('data-job-id'),job.id);
    await page.screenshot({path:path.join(output,'running-restored.png')});
    await until(async()=>await page.locator('.lab-result-summary').getAttribute('data-run-id').catch(()=>null)===job.id);
    assert.equal(submits,1);assert.ok(await page.locator('.lab-result').count()>0);assert.equal(await bar.count(),0);
    await page.locator('.lab-result-summary').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'completed-results.png')});
    checks.push({check:'5223只全量筛查真实进度递增、滚动可见、切页返回刷新保持同一任务、完成自动显示本次结果',job_id:job.id,submits,result:await page.locator('.lab-result-summary').innerText(),passed:true});
    assert.deepEqual(errors,[]);
  }finally{await app.close();}
  await until(async()=>{try{await fetch('http://127.0.0.1:8778/api/v1/health',{signal:AbortSignal.timeout(500)});return false;}catch{return true;}},15000);
  checks.push({check:'没有页面异常，客户端退出后自有服务关闭',page_errors:errors,passed:true});
  fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify(checks,null,2));console.log(JSON.stringify(checks));
}
main().catch(e=>{console.error(e);process.exitCode=1});
