/* 构建阶段修改当前输出副本的Windows资源，不修改Electron原始安装。 */
const path=require('node:path');
async function main(){
  const {rcedit}=await import('rcedit');
  const binary=path.resolve(process.argv[2]),version=process.argv[3]||'0.3.0';
  await rcedit(binary,{icon:path.join(__dirname,'icon.ico'),'file-version':version,'product-version':version,
    'version-string':{ProductName:'王炸',FileDescription:'王炸股票研究客户端',OriginalFilename:'王炸.exe'}});
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
