"""将纯公开行情快照写入发行库并生成可核查覆盖清单。"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path


TABLES=('documents','bars','provider_bars','provider_adjusted_bars','schema_version','security_catalog')
PUBLIC_KINDS=('index_daily','history_coverage','market_history','history_release')


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda:file.read(8*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def export(database,destination,manifest,allow_partial=False):
    source=sqlite3.connect(f'file:{Path(database).resolve().as_posix()}?mode=ro',uri=True)
    source.execute('BEGIN')
    states={row[0]:json.loads(row[1]) for row in source.execute("SELECT id,payload FROM documents WHERE kind='history_coverage'")}
    catalog=[(row[0],row[1],row[2]) for row in source.execute('SELECT id,code,name FROM security_catalog ORDER BY code')]
    target=max((s.get('target','') for s in states.values()),default='')
    def verified(sid):
        state=states.get(sid,{})
        return state.get('status')=='READY' and state.get('target')==target and (state.get('provider_id')!='baostock' or state.get('pagination_verified') or state.get('last_date')==target)
    missing=[{'id':sid,'code':code,'name':name} for sid,code,name in catalog if not verified(sid)]
    if not catalog or (missing and not allow_partial):raise ValueError(f'发行覆盖未完成：{len(missing)}/{len(catalog)}，未生成正式数据包')
    path=Path(destination);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise ValueError('发行目标已存在，请使用新文件；不覆盖已有用户库')
    dest=sqlite3.connect(path)
    with dest:
        for table in TABLES:
            sql=source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if sql:dest.execute(sql[0])
        dest.executemany('INSERT INTO security_catalog VALUES(?,?,?,?,?,?)',source.execute('SELECT * FROM security_catalog'))
        dest.executemany('INSERT INTO provider_bars VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',source.execute("SELECT b.* FROM provider_bars b JOIN security_catalog c ON b.security_id=c.id LEFT JOIN documents d ON d.kind='history_coverage' AND d.id=b.security_id WHERE b.provider_id=coalesce(json_extract(d.payload,'$.provider_id'),'tencent')"))
        for kind in PUBLIC_KINDS:
            query='SELECT * FROM documents WHERE kind=?'
            if kind in {'history_coverage','market_history'}:query+=' AND id IN (SELECT id FROM security_catalog)'
            dest.executemany('INSERT INTO documents VALUES(?,?,?)',source.execute(query,(kind,)))
        dest.execute('INSERT INTO schema_version VALUES(1)')
        dest.execute('CREATE INDEX provider_bars_security_time ON provider_bars(security_id,time)')
        counts={sid:(n,first,last) for sid,n,first,last in dest.execute('SELECT security_id,count(*),min(time),max(time) FROM provider_bars GROUP BY security_id')}
        for sid,payload in dest.execute("SELECT id,payload FROM documents WHERE kind='history_coverage'").fetchall():
            if sid not in counts:continue
            state=json.loads(payload);n,first,last=counts[sid];state.update(row_count=n,first_date=first,last_date=last)
            dest.execute("UPDATE documents SET payload=? WHERE kind='history_coverage' AND id=?",(json.dumps(state,ensure_ascii=False),sid))
        for sid,(n,first,last) in counts.items():
            if sid not in states:
                dest.execute('INSERT INTO documents VALUES(?,?,?)',('history_coverage',sid,json.dumps({'id':sid,'status':'PARTIAL','full':False,'row_count':n,'first_date':first,'last_date':last})))
        dest.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?)',('history_release','latest',json.dumps({'id':'latest','target_trade_date':target,'metadata_counts':True})))
        dest.execute('PRAGMA user_version=1')
    summary=dest.execute('SELECT count(*),count(distinct security_id),min(time),max(time) FROM provider_bars').fetchone()
    quality=[{'id':sid,'excluded_dates':s.get('excluded_dates',[]),'diagnostics':s.get('diagnostics',[])} for sid,s in states.items() if s.get('diagnostics')]
    kinds=dict(dest.execute('SELECT kind,count(*) FROM documents GROUP BY kind'))
    assert not set(kinds)-set(PUBLIC_KINDS)
    if dest.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('发行库完整性检查失败')
    dest.close();source.close()
    stats=sqlite3.connect(path);sources=dict(stats.execute('SELECT provider_id,count(*) FROM provider_bars GROUP BY provider_id'));stats.close()
    result={'version':'0.3.0','generated_at':datetime.now(timezone.utc).isoformat(),'target_trade_date':target,
            'scope':'当前目录沪深在市证券 / 来源可提供的未复权完成日线',
            'catalog_count':len(catalog),'history_count':summary[1],'completed_check_count':len(catalog)-len(missing),
            'row_count':summary[0],'first_date':summary[2],'last_date':summary[3],
            'status':'PARTIAL' if missing else 'COMPLETE_WITH_DIAGNOSTICS' if quality else 'COMPLETE',
            'missing':missing,'quality':quality,'document_kinds':kinds,
            'sources':sources,
            'privacy':'仅目录/行情/公开覆盖元数据；无自选、账户、任务、模型设置或私人研究记录',
            'limitations':['不含北交所、全退市样本、完整分钟/逐笔历史','停牌不补造日线；来源无效行剔除并在quality中记录','公开接口不代表取得商业行情转售授权'],
            'database_bytes':path.stat().st_size,'database_sha256':sha256(path)}
    Path(manifest).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'quality','missing'}},ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database',required=True);parser.add_argument('--destination',required=True)
    parser.add_argument('--manifest',required=True);parser.add_argument('--allow-partial',action='store_true');args=parser.parse_args()
    export(args.database,args.destination,args.manifest,args.allow_partial)
