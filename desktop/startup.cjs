const $=id=>document.getElementById(id);
let running=false;
async function refresh(){
  try{const data=await window.wangzhaStartup.status();const c=data.coverage;
    $('coverage').textContent=c.history_count.toLocaleString()+' / '+c.catalog_count.toLocaleString();$('rows').textContent=c.rows.toLocaleString();$('date').textContent=c.last_date||'尚未下载';
    running=data.status==='RUNNING';$('fill').style.width=(data.total?100*data.completed/data.total:0)+'%';
    $('current').textContent=running?`${data.current} · 已检查 ${data.completed}/${data.total}，新增 ${data.downloaded.toLocaleString()} 根，失败 ${data.failed} 只`:data.status==='SUCCEEDED'?'历史检查完成，可以进入工作台。':`补数${data.status==='IDLE'?'尚未开始':'未全部完成'}，已有缓存保留。`;
    $('errors').textContent=(data.errors||[]).slice(-5).join('\n');$('retry').hidden=running||data.status==='SUCCEEDED';
    $('enter').disabled=false;$('enter').textContent=data.status==='SUCCEEDED'?'进入发现工作台':running?'使用已有缓存进入，后台继续补数':'使用已有缓存进入';
  }catch(e){$('current').textContent='连接数据服务失败：'+e.message;$('retry').hidden=false;}
}
$('retry').addEventListener('click',async()=>{await window.wangzhaStartup.start();await refresh();});
$('enter').addEventListener('click',()=>window.wangzhaStartup.enter());
window.wangzhaStartup.start().then(refresh).catch(e=>{$('current').textContent=e.message;});
setInterval(refresh,1500);
