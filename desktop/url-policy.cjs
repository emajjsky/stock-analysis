const configuredPort=Number(process.env.WANGZHA_PORT||8765);
if(!Number.isInteger(configuredPort)||configuredPort<1024||configuredPort>65535)throw new Error('本机端口配置无效');
const LOCAL_ORIGIN = 'http://127.0.0.1:'+configuredPort;
function publicURL(value) {
  if (typeof value !== 'string' || value.length > 8192) return null;
  try {
    const url = new URL(value);
    const h = url.hostname.toLowerCase().replace(/^\[|\]$/g, '');
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return null;
    if (!h || h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.local') || !h.includes('.')) return null;
    if (/^(0|10|127)\./.test(h) || /^169\.254\./.test(h) || /^192\.168\./.test(h) || /^172\.(1[6-9]|2\d|3[01])\./.test(h) || /^2(2[4-9]|[3-5]\d)\./.test(h)) return null;
    if (h.includes(':')) return null;
    return url.href;
  } catch { return null; }
}
function trustedSender(event, webContents) {
  return event.sender === webContents && event.senderFrame === webContents.mainFrame &&
    new URL(event.senderFrame.url).origin === LOCAL_ORIGIN;
}
module.exports = { publicURL, trustedSender, LOCAL_ORIGIN };
