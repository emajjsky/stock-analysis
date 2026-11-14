/* 复现原生网页遮挡提示：验证提示在最上层，网页保持可见，悬停/键盘退出后消失。 */
const {_electron:electron}=require(process.env.WANGZHA_PLAYWRIGHT||'C:/ProgramData/anaconda3/Lib/site-packages/playwright/driver/package');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const os=require('node:os');
const root=path.resolve(__dirname,'..');
async function main(){
  const app=await electron.launch({executablePath:path.join(root,'desktop/node_modules/electron/dist/electron.exe'),
    args:[path.join(root,'desktop'),'--user-data-dir='+fs.mkdtempSync(path.join(os.tmpdir(),'wangzha-tooltip-'))],timeout:30000});
  try{
    // WebContentsView也可能被驱动列为page；明确选本地工作台主框架。
    let page;
    for(let i=0;i<60;i++){
      page=app.windows().find(p=>p.url().startsWith('http://127.0.0.1:8765/'));
      if(page)break;
      await new Promise(r=>setTimeout(r,250));
    }
    assert.ok(page,'没有本地工作台');
    await page.locator('.web-tab').first().waitFor();
    if(await page.getByRole('button',{name:'收起侧边栏',exact:true}).count())
      await page.getByRole('button',{name:'收起侧边栏',exact:true}).click();
    let remoteReady=false;
    for(let i=0;i<100;i++){
      remoteReady=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.some(v=>v.getVisible()&&v.webContents?.getURL().startsWith('https://')));
      if(remoteReady)break;
      await page.waitForTimeout(250);
    }
    assert.ok(remoteReady,'网页尚未进入可见原生视图，不能验证遮挡');
    const labels=['首页','发现','市场','自选','新股','网页行情','信号','验证','交易','算法与规则','数据与设置'];
    const checks=[];
    for(const label of labels){
      const button=page.locator('.app-sidebar').getByRole('button',{name:label,exact:true});
      await button.hover();
      await page.waitForFunction(label=>document.getElementById('sidebar-tooltip')?.textContent===label,label);
      let result;
      for(let i=0;i<30;i++){
        result=await app.evaluate(async({BrowserWindow})=>{
          const children=BrowserWindow.getAllWindows()[0].contentView.children;
          const tip=children.find(v=>v.webContents?.getURL().endsWith('/tooltip.html'));
          return {visible:tip.getVisible(),top:children.at(-1)===tip,bounds:tip.getBounds(),
            text:await tip.webContents.executeJavaScript('document.getElementById("label").textContent'),
            remoteVisible:children.some(v=>v!==tip&&v.getVisible()&&v.webContents?.getURL().startsWith('https://'))};
        });
        if(result.visible&&result.text===label)break;
        await page.waitForTimeout(50);
      }
      assert.ok(result.visible&&result.top&&result.remoteVisible,JSON.stringify(result));
      assert.equal(result.text,label);
      checks.push({label,...result});
      await page.locator('.breadcrumb').hover();
      await page.waitForTimeout(50);
      assert.equal(await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.find(v=>v.webContents?.getURL().endsWith('/tooltip.html')).getVisible()),false);
    }
    await page.locator('.app-sidebar').getByRole('button',{name:'自选',exact:true}).focus();
    await page.waitForTimeout(100);
    assert.equal(await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.find(v=>v.webContents?.getURL().endsWith('/tooltip.html')).getVisible()),true);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(100);
    assert.equal(await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].contentView.children.find(v=>v.webContents?.getURL().endsWith('/tooltip.html')).getVisible()),false);
    const out=path.join(root,'docs/evidence/ipo-web/desktop-tooltips.json');
    fs.writeFileSync(out,JSON.stringify({checks,keyboardEscape:true},null,2));
    console.log(JSON.stringify({labels:checks.length,keyboardEscape:true,remoteRemainsVisible:true}));
  }finally{await app.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
