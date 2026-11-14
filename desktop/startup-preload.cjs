const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('wangzhaStartup',{
  status:()=>ipcRenderer.invoke('startup:command','status'),
  start:()=>ipcRenderer.invoke('startup:command','start'),
  enter:()=>ipcRenderer.invoke('startup:command','enter'),
});
