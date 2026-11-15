/* 对真实0.3.1便携包验证运行中切页、刷新、完成结果和研究上下文。 */
const {_electron:electron}=require(process.env.WANGZHA_PLAYWRIGHT||'C:/ProgramData/anaconda3/Lib/site-packages/playwright/driver/package');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
async function waitUntil(check,timeout=60000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,250));}throw Error('等待验收条件超时');}
async function main(){
  const root=path.resolve(__dirname,'..'),binary=process.argv[2]||path.join(root,'release/Wangzha-0.3.1-win-x64/王炸.exe');
  const data=fs.mkdtempSync(path.join(root,'.runtime/ux-031/client-'));
  const out=path.join(root,'docs/evidence/lab-workspaces-20261115');fs.mkdirSync(out,{recursive:true});
  const app=await electron.launch({executablePath:binary,args:['--user-data-dir='+path.join(data,'profile')],env:{...process.env,PATH:'C:\\Windows\\System32',WANGZHA_DATA_DIR:path.join(data,'data'),WANGZHA_PORT:'8778',WORKSTATION_AUTO_DATA:'0',HISTORY_WORKERS:'1',WANGZHA_TEST_HIDDEN:'0'},timeout:90000});
  const checks=[];const errors=[];
  try{
    const identity=await app.evaluate(({app})=>({packaged:app.isPackaged,version:app.getVersion()}));assert.ok(identity.packaged);assert.equal(identity.version,'0.3.1');
    await waitUntil(()=>app.windows().some(w=>w.url().endsWith('/startup.html')));
    const startup=app.windows().find(w=>w.url().endsWith('/startup.html'));
    await startup.locator('#enter').waitFor();await waitUntil(()=>startup.locator('#enter').isEnabled());
    const coverage=(await startup.evaluate(()=>window.wangzhaStartup.status())).coverage;assert.equal(coverage.history_count,5223);assert.equal(coverage.rows,16805168);
    await startup.getByRole('button',{name:/进入/}).click();
    await waitUntil(()=>app.windows().some(w=>w.url().startsWith('http://127.0.0.1:8778/')));
    const page=app.windows().find(w=>w.url().startsWith('http://127.0.0.1:8778/'));page.on('pageerror',e=>errors.push(String(e)));
    await page.getByRole('button',{name:'开始选股',exact:true}).waitFor();
    let submits=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/lab/jobs'))submits++;});
    const accepted=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/lab/jobs'));
    await page.getByRole('button',{name:'开始选股',exact:true}).click();const job=(await (await accepted).json()).data;
    await page.getByLabel('算法计算进度',{exact:true}).waitFor();
    await page.getByRole('button',{name:'数据与设置',exact:true}).click();await page.getByRole('button',{name:'查看算法计算进度',exact:true}).waitFor();
    await page.screenshot({path:path.join(out,'client-running-away.png'),timeout:60000});
    await page.getByRole('button',{name:'发现',exact:true}).click();await page.getByLabel('算法计算进度',{exact:true}).waitFor();
    await page.reload();await page.getByLabel('算法计算进度',{exact:true}).waitFor();
    await waitUntil(async()=>await page.locator('.lab-result-summary').getAttribute('data-run-id').catch(()=>null)===job.id,90000);
    assert.equal(submits,1);assert.ok(await page.locator('.lab-result').count()>0);
    const result=await page.locator('.lab-result-summary').innerText();assert.match(result,/计算 5223 只/);
    await page.screenshot({path:path.join(out,'client-results.png'),timeout:60000});
    checks.push({check:'真实便携包全量选股运行中切设置返回并刷新，结果自动展示',...identity,job_id:job.id,submits,result,coverage});
    // 从候选进入K线页沿用同一份算法结果，返回后保留选股结果。
    const name=await page.locator('.lab-result .stock-link strong').first().innerText();
    await page.locator('.lab-result .stock-link').first().click();
    await page.locator('.stock-algorithms .lab-result-summary').waitFor();
    assert.equal(await page.locator('.stock-algorithms .lab-result-summary').getAttribute('data-run-id'),job.id);
    assert.equal(await page.locator('.stock-algorithms .lab-evidence-row').count(),2);
    await page.getByRole('button',{name:'发现',exact:true}).click();
    assert.equal(await page.locator('.lab-result-summary').getAttribute('data-run-id'),job.id);
    await page.getByRole('tab',{name:/运行记录/}).click();
    const record=page.locator('.lab-history .lab-task').first();await record.getByRole('button',{name:'查看结果',exact:true}).click();
    await waitUntil(async()=>await page.locator('.lab-result-summary').getAttribute('data-run-id').catch(()=>null)===job.id);
    assert.match(await page.locator('.lab-config-summary').innerText(),/均线趋势 \/ ATR/);
    checks.push({check:'候选带原始算法依据进入K线、返回及历史查看结果',stock:name,passed:true});
    assert.deepEqual(errors,[]);
  }finally{await app.close();}
  await waitUntil(async()=>{try{await fetch('http://127.0.0.1:8778/api/v1/session',{signal:AbortSignal.timeout(500)});return false;}catch{return true;}},15000);
  const log=fs.readFileSync(path.join(data,'data/backend.log'),'utf8');assert.ok(!/ModuleNotFoundError|ImportError|Traceback/.test(log),log.slice(-1500));
  checks.push({check:'退出后服务关闭，冻结运行时无缺包异常',page_errors:errors,passed:true});
  fs.writeFileSync(path.join(out,'client-checks.json'),JSON.stringify(checks,null,2));console.log(JSON.stringify(checks));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
