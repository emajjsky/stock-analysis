/* 桌面实际加载与隔离验收。使用已安装的Playwright驱动，不改变用户自选。 */
const { _electron: electron } = require(process.env.WANGZHA_PLAYWRIGHT || 'C:/ProgramData/anaconda3/Lib/site-packages/playwright/driver/package');
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'docs/evidence/ipo-web');
async function main() {
  const app = await electron.launch({ executablePath:path.join(root,'desktop/node_modules/electron/dist/electron.exe'),
    args:[path.join(root,'desktop')], env:{...process.env, WANGZHA_TEST_HIDDEN:'1'}, timeout:30000 });
  const checks=[];
  try {
    let page;
    for(let i=0;i<100;i++){
      page=app.windows().find(p=>p.url().startsWith('http://127.0.0.1:8765/'));
      if(page)break;
      await new Promise(r=>setTimeout(r,250));
    }
    assert.ok(page,'本地工作台未启动');
    await page.waitForLoadState('networkidle');
    await page.locator('.web-tab').first().waitFor();
    const remoteReady = async () => app.evaluate(({webContents})=>webContents.getAllWebContents()
      .filter(w=>w.getURL().startsWith('https://q.10jqka.com.cn/')).map(w=>({id:w.id,url:w.getURL(),loading:w.isLoading()})));
    for(let i=0;i<80;i++) {
      const ready=await app.evaluate(async({webContents})=>{
        const wc=webContents.getAllWebContents().find(w=>w.getURL().startsWith('https://q.10jqka.com.cn/'));
        if(!wc)return false;
        try{return await wc.executeJavaScript('document.querySelectorAll("a").length>20');}catch{return false;}
      });
      if(ready)break;
      if(i===40)await page.getByRole('button',{name:'刷新网页',exact:true}).click();
      await new Promise(r=>setTimeout(r,500));
    }
    const loaded = await app.evaluate(async ({webContents})=>{
      const wc=webContents.getAllWebContents().find(w=>w.getURL().startsWith('https://q.10jqka.com.cn/'));
      return {url:wc.getURL(), prefs:wc.getLastWebPreferences(), info:await wc.executeJavaScript(`({title:document.title,text:document.body.innerText.slice(0,200),node:typeof process,bridge:typeof window.wangzhaBrowser,links:document.querySelectorAll('a').length})`)};
    });
    assert.equal(loaded.info.node,'undefined');assert.equal(loaded.info.bridge,'undefined');
    assert.ok(loaded.info.links>20, JSON.stringify(loaded.info));
    checks.push({check:'同花顺真实页面加载与隔离',url:loaded.url,info:loaded.info,nodeIntegration:loaded.prefs.nodeIntegration,sandbox:loaded.prefs.sandbox});
    await app.evaluate(async ({webContents})=>{
      const wc=webContents.getAllWebContents().find(w=>w.getURL().startsWith('https://q.10jqka.com.cn/'));
      await wc.executeJavaScript(`(() => {const link=[...document.querySelectorAll('a[target="_blank"]')].find(a=>a.href.startsWith('https://')&&a.href.includes('10jqka.com.cn'));if(!link)throw Error('没有新窗口链接');link.click();})()`);
    });
    await page.waitForFunction(()=>document.querySelectorAll('.web-tab').length===2);
    const windowCount=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().length);assert.equal(windowCount,1,'打开了产品外的新窗口');
    checks.push({check:'原站target=_blank链接进入内部第二标签',labels:await page.locator('.web-tab').allTextContents(),windows:windowCount});
    await page.locator('.web-close').last().click();
    await page.waitForFunction(()=>document.querySelectorAll('.web-tab').length===1);
    await page.getByRole('navigation',{name:'主要功能'}).getByRole('button',{name:'新股',exact:true}).click();
    await page.locator('.ipo-primary-table tbody tr').first().waitFor({timeout:20000});
    let views=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.map(v=>({visible:v.getVisible(),bounds:v.getBounds()})));
    assert.ok(views.filter(v=>v.visible).length<=1,JSON.stringify(views));
    await page.getByRole('navigation',{name:'主要功能'}).getByRole('button',{name:'网页行情',exact:true}).click();
    await page.locator('.web-tab').first().waitFor();
    const collapse=page.getByRole('button',{name:'收起侧边栏',exact:true});
    if(await collapse.count())await collapse.click();
    await page.waitForTimeout(300);
    views=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.map(v=>({visible:v.getVisible(),bounds:v.getBounds()})));
    const remote=views.find(v=>v.visible&&v.bounds.x>0);
    assert.ok(remote && remote.bounds.width>1000,JSON.stringify(views));
    checks.push({check:'切页保留标签且侧栏收缩后网页重新对齐',views});
    await page.getByRole('button',{name:'打开通知中心'}).click();
    await page.waitForTimeout(150);
    views=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.map(v=>({visible:v.getVisible(),bounds:v.getBounds()})));
    assert.ok(!views.some(v=>v.visible&&v.bounds.x>0),'网页覆盖了通知面板');
    await page.getByRole('button',{name:'关闭通知',exact:true}).click();
    await page.locator('.modal-scrim').waitFor({state:'detached'});
    await page.waitForTimeout(250);
    views=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.map(v=>({visible:v.getVisible(),bounds:v.getBounds()})));
    assert.ok(views.some(v=>v.visible&&v.bounds.x>0),'关闭通知后网页没有恢复');
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].show());
    await page.waitForTimeout(700);
    const capture=await app.evaluate(async ({BrowserWindow})=>(await BrowserWindow.getAllWindows()[0].capturePage()).toPNG().toString('base64'));
    // BrowserWindow.capturePage只捕获工作台层，原生WebContentsView另存，不能把前者当完整窗口截图。
    fs.writeFileSync(path.join(out,'desktop-shell.png'),Buffer.from(capture,'base64'));
    const remoteCapture=await app.evaluate(async({webContents})=>{
      const wc=webContents.getAllWebContents().find(w=>w.getURL().startsWith('https://q.10jqka.com.cn/'));
      return (await wc.capturePage()).toPNG().toString('base64');
    });
    fs.writeFileSync(path.join(out,'desktop-remote-page.png'),Buffer.from(remoteCapture,'base64'));
    const before=(await page.locator('.web-tab').allTextContents()).length;
    const blocked=await page.evaluate(async()=>{try{await window.wangzhaBrowser.command('open',{url:'http://127.0.0.1:8765/api/v1/watchlists'});return false;}catch{return true;}});
    assert.ok(blocked);assert.equal(await page.locator('.web-tab').count(),before);
    checks.push({check:'拒绝内嵌浏览器打开本地API',blocked});
    fs.writeFileSync(path.join(out,'desktop-checks.json'),JSON.stringify(checks,null,2));
    console.log(JSON.stringify({checks:checks.length,title:loaded.info.title}));
  } finally {await app.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
