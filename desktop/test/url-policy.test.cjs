const test = require('node:test');
const assert = require('node:assert/strict');
const { publicURL, trustedSender } = require('../url-policy.cjs');
test('外站只允许公开网页，拒绝本地API、私网、凭据和可执行协议', () => {
  for (const value of ['javascript:alert(1)', 'file:///C:/test', 'data:text/html,test', 'https://user:password@example.com/',
    'http://127.0.0.1:8765/api/v1/watchlists', 'http://2130706433:8765/', 'http://0x7f000001/',
    'http://10.0.0.1/', 'http://192.168.1.2/', 'http://172.31.1.1/', 'http://[::1]/', 'http://localhost/', 'http://host.local/'])
    assert.equal(publicURL(value), null, value);
  assert.equal(publicURL('https://q.10jqka.com.cn/'), 'https://q.10jqka.com.cn/');
  assert.equal(publicURL('https://data.eastmoney.com/xg/'), 'https://data.eastmoney.com/xg/');
});
test('桌面桥仅接受本地工作台主框架', () => {
  const frame = { url: 'http://127.0.0.1:8765/#/web' }, wc = { mainFrame: frame };
  assert.equal(trustedSender({ sender: wc, senderFrame: frame }, wc), true);
  assert.equal(trustedSender({ sender: {}, senderFrame: frame }, wc), false);
  assert.equal(trustedSender({ sender: wc, senderFrame: { url: frame.url } }, wc), false);
});
