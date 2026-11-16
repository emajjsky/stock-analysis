/* 0.4.0真实便携包：独立配置/端口/发行库，绝不修改正式用户数据。 */
const {_electron:electron}=require(process.env.WANGZHA_PLAYWRIGHT||'C:/ProgramData/anaconda3/Lib/site-packages/playwright/driver/package');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
async function until(check,timeout=90000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,250));}throw Error('验收等待超时');}
async function main(){
  const root=path.resolve(__dirname,'..'),binary=process.argv[2]||path.join(root,'release/Wangzha-0.4.0-win-x64/王炸.exe');
  const data=fs.mkdtempSync(path.join(root,'.runtime/ux-031/research-040-'));
  const out=path.join(root,'docs/evidence/research-workflow-20261116');fs.mkdirSync(out,{recursive:true});
  const options={executablePath:binary,args:['--user-data-dir='+path.join(data,'profile')],env:{...process.env,PATH:'C:\\Windows\\System32',WANGZHA_DATA_DIR:path.join(data,'data'),WANGZHA_PORT:'8778',WORKSTATION_AUTO_DATA:'0',HISTORY_WORKERS:'1',WANGZHA_TEST_HIDDEN:'0'},timeout:90000};
  let app;const checks=[],errors=[];
  async function enter(){
    app=await electron.launch(options);
    await until(()=>app.windows().some(w=>w.url().endsWith('/startup.html')));
    const startup=app.windows().find(w=>w.url().endsWith('/startup.html'));
    await startup.locator('#enter').waitFor();await until(()=>startup.locator('#enter').isEnabled());
    const coverage=(await startup.evaluate(()=>window.wangzhaStartup.status())).coverage;
    assert.equal(coverage.history_count,5223);assert.equal(coverage.rows,16805168);
    await startup.getByRole('button',{name:/进入/}).click();
    await until(()=>app.windows().some(w=>w.url().startsWith('http://127.0.0.1:8778/')));
    const page=app.windows().find(w=>w.url().startsWith('http://127.0.0.1:8778/'));
    page.on('pageerror',e=>errors.push(String(e)));return page;
  }
  async function finish(page,id){await until(async()=>await page.locator('.lab-result-summary').getAttribute('data-run-id').catch(()=>null)===id);}
  async function submit(page,name){const response=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/lab/jobs'));await page.getByRole('button',{name,exact:true}).click();const r=await response;assert.ok(r.ok(),await r.text());return (await r.json()).data;}
  try{
    let page=await enter();
    assert.deepEqual(await app.evaluate(({app})=>({packaged:app.isPackaged,version:app.getVersion()})),{packaged:true,version:'0.4.0'});
    await page.getByRole('button',{name:'开始选股',exact:true}).waitFor();
    let submits=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/lab/jobs'))submits++;});
    await page.getByLabel('批次名称（可选）').fill('全市场趋势核对');
    const first=await submit(page,'开始选股');
    await page.getByLabel('算法计算进度',{exact:true}).waitFor();
    assert.equal(await page.locator('progress[aria-label="算法计算进度"]').count(),1);
    await page.getByRole('button',{name:'数据与设置',exact:true}).click();
    assert.equal(await page.getByLabel('算法计算进度',{exact:true}).count(),0);
    assert.equal(await page.locator('.lab-persistent-progress,.lab-global-job').count(),0);
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({animations:'disabled',path:path.join(out,'away-no-global-progress.png'),timeout:60000});
    await page.getByRole('button',{name:'发现',exact:true}).click();
    await page.getByLabel('算法计算进度',{exact:true}).waitFor();
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({animations:'disabled',path:path.join(out,'algorithm-running.png'),timeout:60000});
    await page.reload();await page.getByLabel('算法计算进度',{exact:true}).waitFor();
    await finish(page,first.id);assert.equal(submits,1);
    assert.match(await page.locator('.lab-result-summary').innerText(),/计算 5223 只/);
    await page.getByLabel('算法计算进度',{exact:true}).waitFor({state:'hidden'});
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({animations:'disabled',path:path.join(out,'screen-results.png'),fullPage:true,timeout:60000});
    console.log('阶段通过');checks.push({check:'全市场运行中切设置无全局条，返回及刷新恢复同一任务，完成自动回显',job:first.id,post_count:submits,passed:true});
    // 真实UI生成另一批独立个股诊断。
    await page.getByRole('tab',{name:/个股分析/}).click();
    await page.getByLabel('搜索研究股票').fill('000001');
    await page.locator('.lab-search-results button').filter({hasText:'平安银行'}).first().click();
    await page.getByLabel('批次名称（可选）').fill('平安银行日线诊断');
    const stock=await submit(page,'生成个股诊断');await finish(page,stock.id);
    await page.locator('.diagnosis-grid strong').first().waitFor();
    assert.ok(await page.locator('.diagnosis-grid>div').count()>=6);
    await page.getByText('结合我的持仓核对（仅本机研究记录）',{exact:true}).click();
    await page.getByLabel('持仓成本',{exact:true}).fill('10');
    await page.getByLabel('持仓股数',{exact:true}).fill('1000');
    await page.getByLabel('当前可卖股数',{exact:true}).fill('500');
    assert.match(await page.locator('.stock-diagnosis').innerText(),/估算浮动盈亏/);
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({animations:'disabled',path:path.join(out,'stock-diagnosis.png'),fullPage:true,timeout:60000});
    await page.reload();await page.locator('.stock-diagnosis').waitFor();
    await page.getByText('结合我的持仓核对（仅本机研究记录）',{exact:true}).click();
    assert.equal(await page.getByLabel('持仓成本',{exact:true}).inputValue(),'10');
    await page.getByRole('button',{name:'打开完整K线与公司资料 →',exact:true}).click();
    await page.locator('.stock-algorithms').waitFor();
    assert.equal(await page.locator('.stock-algorithms .lab-result-summary').getAttribute('data-run-id'),stock.id);
    assert.equal(await page.locator('.stock-algorithms').getByRole('button',{name:'打开完整K线与公司资料 →',exact:true}).count(),0);
    await page.getByRole('button',{name:'发现',exact:true}).click();await finish(page,stock.id);
    console.log('阶段通过');checks.push({check:'个股独立诊断含趋势/位置/风险/持仓检查，刷新保留持仓，从结果进入K线沿用原依据',passed:true});
    // 历史批次命名、比较、过滤、JSON导出、原条件恢复。
    await page.getByRole('tab',{name:/历史批次/}).click();
    assert.equal(await page.locator('.batch-day').count(),1);
    const records=page.locator('.batch-day .lab-task');assert.equal(await records.count(),2);
    await records.first().getByRole('button',{name:'命名',exact:true}).click();
    await page.getByLabel('批次新名称').fill('盘后个股复核');await page.getByRole('button',{name:'保存名称',exact:true}).click();
    await until(async()=>await records.first().innerText().then(t=>t.includes('盘后个股复核')));
    await records.nth(0).getByRole('checkbox').check();await records.nth(1).getByRole('checkbox').check();
    await page.getByRole('button',{name:'比较已选两批',exact:true}).click();await page.locator('.batch-comparison').waitFor();
    assert.match(await page.locator('.batch-comparison').innerText(),/仅比较名单/);
    const exported=path.join(data,'export.json');
    await app.evaluate(({session},savePath)=>{session.defaultSession.once('will-download',(_,item)=>item.setSavePath(savePath));},exported);
    await records.first().getByRole('button',{name:'导出',exact:true}).click();
    await until(()=>fs.existsSync(exported)&&fs.statSync(exported).size>0,15000);
    assert.equal(JSON.parse(fs.readFileSync(exported,'utf8')).id,stock.id);
    await page.getByLabel('日期',{exact:true}).fill('2099-01-01');assert.equal(await records.count(),0);
    await page.getByLabel('日期',{exact:true}).fill('');
    await page.getByLabel('任务类型').selectOption('daily');
    await page.getByLabel('搜索名称 / 算法').fill('全市场趋势核对');assert.equal(await records.count(),1);
    await page.getByLabel('搜索名称 / 算法').fill('');
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({animations:'disabled',path:path.join(out,'batch-history-comparison.png'),fullPage:true,timeout:60000});
    await records.nth(1).getByRole('button',{name:'查看结果',exact:true}).click();await finish(page,first.id);
    assert.match(await page.locator('.lab-config-summary').innerText(),/均线趋势/);
    console.log('阶段通过');checks.push({check:'两批按日期归档、命名、过滤、比较配置差异、导出完整JSON、恢复原条件与结果',passed:true});
    // 分时输入不足有解释，不能作为没有机会。
    await page.getByRole('tab',{name:/个股分析/}).click();
    await page.getByRole('button',{name:'展开配置',exact:true}).click();
    await page.getByLabel('研究任务').selectOption('intraday');
    const intraday=await submit(page,'生成个股诊断');await finish(page,intraday.id);
    assert.match(await page.locator('.lab-input-coverage').innerText(),/没有完整且时效有效/);
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({animations:'disabled',path:path.join(out,'intraday-insufficient.png'),fullPage:true,timeout:60000});
    console.log('阶段通过');checks.push({check:'离线旧分时报价明确过期或缺失，不误报有效候选；本验收禁用上游网络，不代表实测在线下载',passed:true});
    // 390px溢出检查。
    await page.getByRole('tab',{name:/历史批次/}).click();await page.setViewportSize({width:390,height:844});
    await until(()=>page.locator('.app-sidebar').evaluate(e=>e.getBoundingClientRect().right<=0));
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.evaluate(()=>scrollTo(0,0));await page.screenshot({animations:'disabled',path:path.join(out,'history-mobile.png'),fullPage:true,timeout:60000});
    await page.setViewportSize({width:1440,height:1000});
    await page.getByRole('button',{name:'网页行情',exact:true}).click();
    for(const name of ['同花顺行情','东方财富行情','新浪财经','巨潮资讯'])assert.equal(await page.locator('.web-bookmarks').getByRole('button',{name,exact:true}).count(),1);
    assert.equal(await page.locator('.web-bookmarks').getByRole('button',{name:/新股/}).count(),0);
    // 受控站点cookie持久化；不使用或读取真实用户账号。
    await app.evaluate(async({session})=>{const s=session.fromPartition('persist:wangzha-external');await s.cookies.set({url:'https://example.com',name:'wangzha_qa',value:'persist-test',expirationDate:Date.now()/1000+3600});await s.cookies.flushStore();});
    await app.close();app=undefined;
    await until(async()=>{try{await fetch('http://127.0.0.1:8778/api/v1/session',{signal:AbortSignal.timeout(500)});return false;}catch{return true;}},15000);
    page=await enter();
    assert.equal(await app.evaluate(async({session})=>(await session.fromPartition('persist:wangzha-external').cookies.get({url:'https://example.com',name:'wangzha_qa'})).length),1);
    console.log('阶段通过');checks.push({check:'390px无横向溢出；行情快捷入口；独立外站会话受控cookie退出重开后保留（未登录第三方账号）',passed:true});
    assert.deepEqual(errors,[]);
  }finally{if(app)await app.close();}
  await until(async()=>{try{await fetch('http://127.0.0.1:8778/api/v1/session',{signal:AbortSignal.timeout(500)});return false;}catch{return true;}},15000);
  console.log('阶段通过');checks.push({check:'退出后8778服务关闭，无页面异常',errors,passed:true});
  fs.writeFileSync(path.join(out,'client-checks.json'),JSON.stringify(checks,null,2));console.log(JSON.stringify(checks));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
