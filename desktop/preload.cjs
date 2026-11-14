const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('wangzhaBrowser', {
  nativeTooltips: true,
  command: (command, args) => ipcRenderer.invoke('browser:command', command, args),
  onState: (callback) => {
    const listener = (_, state) => callback(state);
    ipcRenderer.on('browser:state', listener);
    return () => ipcRenderer.removeListener('browser:state', listener);
  },
});
