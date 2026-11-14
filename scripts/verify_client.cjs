/* 对真实便携包测试：独立端口/数据目录，绝不复用8765正式库。 */
const {_electron:electron}=require(process.env.WANGZHA_PLAYWRIGHT||'C:/ProgramData/anaconda3/Lib/site-packages/playwright/driver/package');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),os=require('node:os');
const {execFileSync}=require('node:child_process');
const root=path.resolve(__dirname,'..');
async function main(){
  const binary=process.argv[2]||path.join(root,'.runtime/release/client-qa-01/王炸.exe');
  const data=fs.mkdtempSync(path.join(os.tmpdir(),'wangzha-packaged-'));
  const out=path.join(root,'docs/evidence/algorithm-lab-20261115');
  let repair;
  if(process.argv.includes('--repair-probe')){
    // 仅修改本脚本创建的临时发行副本，模拟漏掉最后一个交易日；绝不写发行seed或用户库。
    const database=path.join(data,'data/workstation.db');fs.mkdirSync(path.dirname(database),{recursive:true});
    fs.copyFileSync(path.join(path.dirname(binary),'resources/seed.db'),database);
    const code=`import sqlite3,json,sys
c=sqlite3.connect(sys.argv[1])
sid,payload=c.execute("SELECT id,payload FROM documents WHERE kind='history_coverage' AND json_extract(payload,'$.provider_id')='baostock' AND json_extract(payload,'$.last_date')=json_extract(payload,'$.target') ORDER BY id LIMIT 1").fetchone()
s=json.loads(payload);target=s['target'];before=s['row_count']
with c:
 c.execute("DELETE FROM provider_bars WHERE provider_id='baostock' AND security_id=? AND time=?",(sid,target))
 previous=c.execute("SELECT max(time) FROM provider_bars WHERE provider_id='baostock' AND security_id=?",(sid,)).fetchone()[0]
 s.update(last_date=previous,target=previous,row_count=before-1)
 c.execute("UPDATE documents SET payload=? WHERE kind='history_coverage' AND id=?",(json.dumps(s),sid))
print(json.dumps(dict(sid=sid,target=target,before=before)))
`;
    repair=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-X','utf8','-c',code,database],{encoding:'utf8'}));
  }
  const app=await electron.launch({executablePath:binary,args:['--user-data-dir='+path.join(data,'profile')],
    env:{...process.env,PATH:'C:\\Windows\\System32',WANGZHA_DATA_DIR:path.join(data,'data'),WANGZHA_PORT:'8778',WORKSTATION_AUTO_DATA:'0',HISTORY_WORKERS:'1',WANGZHA_TEST_HIDDEN:process.env.WANGZHA_QA_SHOW==='1'?'0':'1'},timeout:60000});
  const checks=[];let backendPid;
  try{
    const identity=await app.evaluate(({app})=>({packaged:app.isPackaged,version:app.getVersion(),appPath:app.getAppPath()}));
    assert.equal(identity.packaged,true);assert.equal(identity.version,'0.3.0');
    let startup;
    for(let i=0;i<120;i++){
      startup=app.windows().find(p=>p.url().endsWith('/startup.html'));if(startup)break;
      await new Promise(r=>setTimeout(r,250));
    }
    assert.ok(startup,'启动补数窗口未出现');
    await startup.locator('#enter').waitFor();
    for(let i=0;i<120&&!(await startup.locator('#enter').isEnabled());i++)await new Promise(r=>setTimeout(r,250));
    assert.ok(await startup.locator('#enter').isEnabled(),'启动窗口未启用进入操作');
    const status=await startup.evaluate(()=>window.wangzhaStartup.status());
    assert.ok(status.coverage.catalog_count>0);assert.ok(fs.existsSync(path.join(data,'data/workstation.db')));
    await startup.screenshot({path:path.join(out,'packaged-startup.png')});
    checks.push({check:repair?'真实发行库临时副本缺少末日后启动内置服务':'真实便携包复制发行库并启动内置服务',...identity,coverage:status.coverage,status:status.status,...(repair?{repair_probe:repair}:{})});
    await startup.getByRole('button',{name:/进入/}).click();
    let mainWindow;
    for(let i=0;i<80;i++){
      mainWindow=app.windows().find(p=>p.url().startsWith('http://127.0.0.1:8778/'));
      if(mainWindow)break;await new Promise(r=>setTimeout(r,100));
    }
    assert.ok(mainWindow,'本地发现工作台未出现');
    await mainWindow.waitForURL('http://127.0.0.1:8778/#/discover');
    await mainWindow.getByRole('tab',{name:'选股工作台',exact:true}).waitFor();
    const errors=[];mainWindow.on('pageerror',e=>errors.push(String(e)));
    const denied=await mainWindow.evaluate(async()=>{try{await window.wangzhaBrowser.command('open',{url:'http://127.0.0.1:8778/api/v1/session'});return false;}catch{return true;}});
    assert.ok(denied);
    await mainWindow.getByRole('button',{name:'运行一次',exact:true}).click();
    await mainWindow.locator('.lab-result-summary').waitFor({timeout:60000});
    await mainWindow.screenshot({path:path.join(out,'packaged-discover.png'),timeout:60000});
    assert.deepEqual(errors,[]);
    checks.push({check:'缓存进入发现页、真实算法计算、桌面桥拒绝本地外站',result:await mainWindow.locator('.lab-result-summary').innerText(),page_errors:errors});
    let progress;
    for(let i=0;i<180;i++){
      progress=await mainWindow.evaluate(async()=>(await (await fetch('/api/v1/history/status')).json()).data);
      if(progress.completed>0&&progress.target_date&&progress.downloaded>0)break;
      if(['FAILED','PARTIAL'].includes(progress.status))throw new Error('内置历史下载失败：'+JSON.stringify(progress.errors));
      await new Promise(r=>setTimeout(r,1000));
    }
    assert.ok(progress.completed>0&&progress.target_date&&progress.downloaded>0,'冻结后的历史下载没有新增数据：'+JSON.stringify(progress));
    if(repair){
      const code=`import sqlite3,json,sys
c=sqlite3.connect(sys.argv[1]);s=json.loads(c.execute("SELECT payload FROM documents WHERE kind='history_coverage' AND id=?",(sys.argv[2],)).fetchone()[0]);print(json.dumps(dict(target=s['target'],rows=s['row_count'],last=s['last_date'])))`;
      const restored=JSON.parse(execFileSync(path.join(root,'.venv/Scripts/python.exe'),['-X','utf8','-c',code,path.join(data,'data/workstation.db'),repair.sid],{encoding:'utf8'}));
      assert.equal(restored.target,repair.target);assert.equal(restored.last,repair.target);assert.equal(restored.rows,repair.before);
      checks.push({check:'启动补齐临时副本缺失末日并保留已有日线',...restored,passed:true});
    }
    checks.push({check:'冻结服务真实历史补数及独立下载子进程',completed:progress.completed,target:progress.target_date,downloaded:progress.downloaded});
    // 记录创建的服务进程，退出后检查独立端口是否关闭。
    await mainWindow.evaluate(async()=>{await fetch('/api/v1/session');await fetch('/api/v1/history/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});});
  }finally{await app.close();}
  for(let i=0;i<40;i++){
    let live=false;try{await fetch('http://127.0.0.1:8778/api/v1/session',{signal:AbortSignal.timeout(500)});live=true;}catch{}
    if(!live){checks.push({check:'退出后内置服务端口关闭',passed:true});break;}
    if(i===39)throw new Error('退出后服务仍运行');await new Promise(r=>setTimeout(r,250));
  }
  const log=fs.readFileSync(path.join(data,'data/backend.log'),'utf8');
  assert.ok(!/ModuleNotFoundError|ImportError|Traceback/.test(log),log.slice(-2000));
  checks.push({check:'冻结后端无缺包异常',passed:true});
  fs.writeFileSync(path.join(out,'packaged-checks.json'),JSON.stringify(checks,null,2));
  console.log(JSON.stringify(checks));
}
main().catch(e=>{console.error(e);process.exitCode=1;});
