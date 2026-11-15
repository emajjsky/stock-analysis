// 升级核验只刷新HTTP缓存，保留登录、本地偏好和用户业务数据。
async function verifyBackend(origin,version,fetcher=fetch) {
  const options={cache:'no-store',signal:AbortSignal.timeout(5000)};
  const [health,jobs]=await Promise.all([
    fetcher(origin+'/api/v1/health',options),fetcher(origin+'/api/v1/lab/jobs',options),
  ]);
  const actual=health.ok?(await health.json()).data?.version:undefined;
  if(actual!==version||!jobs.ok||!Array.isArray((await jobs.json()).data))
    throw new Error(`数据服务版本不匹配（客户端 ${version}，服务 ${actual||'未知'}），请关闭旧服务后重新启动客户端。`);
}
async function prepareFrontend(browserSession) {
  await browserSession.clearCache();
}
function entryURL(origin,version) {return origin+'/?client='+encodeURIComponent(version)+'#/discover';}
module.exports={verifyBackend,prepareFrontend,entryURL};
