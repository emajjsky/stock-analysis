const test=require('node:test'),assert=require('node:assert/strict');
const {verifyBackend,prepareFrontend,entryURL}=require('../delivery.cjs');
const response=(data,ok=true)=>({ok,json:async()=>({data})});
test('拒绝目录接口仍存在但没有进度接口的旧服务',async()=>{
  await assert.rejects(verifyBackend('http://127.0.0.1:8765','0.3.2',async url=>url.endsWith('/health')?response({version:'0.3.0'}):response(null,false)),/版本不匹配/);
  await assert.rejects(verifyBackend('http://127.0.0.1:8765','0.3.2',async url=>url.endsWith('/health')?response({version:'0.3.2'}):response(null,false)),/版本不匹配/);
  await verifyBackend('http://127.0.0.1:8766','0.3.2',async url=>url.endsWith('/health')?response({version:'0.3.2'}):response([]));
});
test('加载页面前清理HTTP缓存，入口带版本且不清用户存储',async()=>{
  const calls=[];await prepareFrontend({clearCache:async()=>calls.push('http-cache'),clearStorageData:()=>{throw Error('不得清用户配置');}});
  assert.deepEqual(calls,['http-cache']);assert.equal(entryURL('http://127.0.0.1:8766','0.3.2'),'http://127.0.0.1:8766/?client=0.3.2#/discover');
});
