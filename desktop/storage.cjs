const fs=require('node:fs');
function ensureSeed(database,seed){
  if(fs.existsSync(database))return false;
  const temporary=database+'.initializing';
  try{
    fs.copyFileSync(seed,temporary);
    const fd=fs.openSync(temporary,'r+');
    try{fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
    if(fs.existsSync(database)){fs.unlinkSync(temporary);return false;}
    fs.renameSync(temporary,database);
    return true;
  }catch(error){
    try{if(fs.existsSync(temporary))fs.unlinkSync(temporary);}catch{}
    throw error;
  }
}
module.exports={ensureSeed};
