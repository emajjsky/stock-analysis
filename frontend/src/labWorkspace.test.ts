import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {nextTick} from 'vue';
const mock=vi.hoisted(()=>({api:vi.fn(),post:vi.fn()}));
vi.mock('./api',()=>mock);
const selection=[{id:'ma-trend',parameters:{fast:5,slow:20}},{id:'atr-risk',parameters:{period:14,max_pct:5}}];
function result(id='run-1',workspace='screen'){
  return {id,workspace,mode:'daily',scope:'all',combination:'all',selections:selection,total:5223,matched:11,skipped:2,status:'SUCCEEDED',started_at:'2026-11-15T13:00:00Z',finished_at:'2026-11-15T13:00:35Z',rows:[]};
}
function job(status='RUNNING'){
  return {id:'run-1',run_id:'run-1',workspace:'screen',config:{mode:'daily',scope:'all',combination:'all',selections:selection,security_ids:[],workspace:'screen'},status,total:5223,completed:100,matched:1,skipped:0,started_at:'2026-11-15T13:00:00Z'};
}
let storage:Map<string,string>;
beforeEach(()=>{vi.resetModules();mock.api.mockReset();mock.post.mockReset();storage=new Map();vi.stubGlobal('localStorage',{getItem:(k:string)=>storage.get(k)??null,setItem:(k:string,v:string)=>storage.set(k,v)});});
afterEach(()=>vi.unstubAllGlobals());
describe('发现工作区的跨页面任务与结果',()=>{
  it('三个场景及不同周期的条件独立，刷新后恢复草稿',async()=>{
    const m=await import('./labWorkspace');
    m.labWorkspace.drafts.screen.selectionsByMode.daily.push({id:'rsi',parameters:{period:14,lower:30,upper:70}});
    m.labWorkspace.drafts.stock.chosen=[{id:'LIVE.SH.600519',name:'贵州茅台',code:'600519'}];
    m.labWorkspace.tab='stock';await nextTick();
    expect(m.draftConfig('screen').selections).toHaveLength(3);
    expect(m.draftConfig('stock').selections).toHaveLength(2);
    m.labWorkspace.drafts.screen.mode='intraday';expect(m.draftConfig('screen').selections[0].id).toBe('price-change');
    m.labWorkspace.drafts.screen.mode='daily';expect(m.draftConfig('screen').selections).toHaveLength(3);
    await nextTick();vi.resetModules();const restored=await import('./labWorkspace');
    expect(restored.labWorkspace.tab).toBe('stock');expect(restored.draftConfig('stock').security_ids).toEqual(['LIVE.SH.600519']);expect(restored.draftConfig('screen').selections).toHaveLength(3);
  });
  it('离开选股场景后完成仍写回选股工作区，监测草稿不被覆盖',async()=>{
    let status='RUNNING';
    mock.api.mockImplementation(async(path:string)=>({data:path==='/lab/jobs'?[job(status)]:path==='/lab/runs'?(status==='SUCCEEDED'?[result()]:[]):result()}));
    const m=await import('./labWorkspace');await m.refreshLabWorkspace();
    expect(m.activeLabJob.value?.completed).toBe(100);m.labWorkspace.tab='monitor';
    m.labWorkspace.drafts.monitor.taskName='我的独立监测';status='SUCCEEDED';await m.refreshLabWorkspace();
    expect(m.labWorkspace.tab).toBe('monitor');expect(m.labWorkspace.drafts.monitor.taskName).toBe('我的独立监测');expect(m.labResults.screen?.matched).toBe(11);expect(m.labResults.monitor).toBeUndefined();
  });
  it('请求响应丢失后由任务查询恢复，点击不重复提交',async()=>{
    mock.post.mockRejectedValue(new TypeError('Failed to fetch'));
    mock.api.mockImplementation(async(path:string)=>({data:path==='/lab/jobs'?[job()]:[]}));
    const m=await import('./labWorkspace');await m.startCalculation('screen');await m.refreshLabWorkspace();await m.startCalculation('screen');
    expect(mock.post).toHaveBeenCalledTimes(1);expect(m.activeLabJob.value?.id).toBe('run-1');
  });
  it('历史记录恢复所属场景和原始配置，轮询不会悄悄换成最新结果',async()=>{
    const old={...result('old','stock'),scope:'custom',total:1,security_ids:['LIVE.SH.600519'],rows:[{security:{id:'LIVE.SH.600519',name:'贵州茅台',code:'600519'}}]};
    mock.api.mockImplementation(async(path:string)=>({data:path==='/lab/jobs'?[job('SUCCEEDED')]:path==='/lab/runs'?[result(),old]:path.endsWith('/old')?old:result()}));
    const m=await import('./labWorkspace');await m.openRun('old');await m.refreshLabWorkspace();
    expect(m.labWorkspace.tab).toBe('stock');expect(m.labResults.stock?.id).toBe('old');expect(m.sameConfig(old as any,'stock')).toBe(true);
    expect(m.labWorkspace.drafts.stock.paramsOpen).toBe(false);
  });
  it('取消或失败保留上一份结果，网络失败保留已知任务进度',async()=>{
    let fail=false;
    mock.api.mockImplementation(async(path:string)=>{if(fail)throw new Error('暂时断网');return {data:path==='/lab/jobs'?[job('CANCELLED')]:path==='/lab/runs'?[result('previous')]:result('previous')};});
    const m=await import('./labWorkspace');await m.refreshLabWorkspace();expect(m.labResults.screen?.id).toBe('previous');
    fail=true;await m.refreshLabWorkspace();expect(m.labWorkspace.connectionError).toContain('暂时断网');expect(m.labResults.screen?.id).toBe('previous');
  });
});
