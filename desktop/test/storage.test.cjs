const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {ensureSeed}=require('../storage.cjs');
test('发行库仅首次复制，已有用户库保持原样',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'wangzha-storage-')),seed=path.join(dir,'seed.db'),db=path.join(dir,'user.db');
  fs.writeFileSync(seed,'public history');assert.equal(ensureSeed(db,seed),true);
  assert.equal(fs.readFileSync(db,'utf8'),'public history');assert.equal(fs.existsSync(db+'.initializing'),false);
  fs.writeFileSync(db,'private user records');assert.equal(ensureSeed(db,seed),false);
  assert.equal(fs.readFileSync(db,'utf8'),'private user records');
});
test('中断复制不会留下假完成的用户库，可安全重试',()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'wangzha-interrupt-')),seed=path.join(dir,'seed.db'),db=path.join(dir,'user.db');
  fs.writeFileSync(seed,'complete seed');fs.writeFileSync(db+'.initializing','incomplete prior attempt');
  assert.equal(ensureSeed(db,seed),true);assert.equal(fs.readFileSync(db,'utf8'),'complete seed');
  assert.equal(fs.existsSync(db+'.initializing'),false);
  const missing=path.join(dir,'new.db');assert.throws(()=>ensureSeed(missing,path.join(dir,'absent.db')));
  assert.equal(fs.existsSync(missing),false);
});
