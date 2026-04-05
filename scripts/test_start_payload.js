// Test script to verify is_demo is included in start_bot payload
const http = require('http');

const data = JSON.stringify({
  type: 'start_bot',
  botId: 'bf167763-fee1-4f11-ab9a-6fddadf125de',
  tenantId: '11111111-1111-1111-1111-111111111111',
  exchangeAccountId: 'fb213790-5ba6-4637-bccc-25e3d68d4c0c'
});

const options = {
  hostname: 'localhost',
  port: 3001,
  path: '/api/control/command',
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Content-Length': data.length,
    'x-user-id': '11111111-1111-1111-1111-111111111111'  // Dev mode auth
  }
};

const req = http.request(options, (res) => {
  let body = '';
  res.on('data', chunk => body += chunk);
  res.on('end', () => {
    console.log('Status:', res.statusCode);
    console.log('Response:', body);
  });
});

req.on('error', (e) => console.error('Error:', e.message));
req.write(data);
req.end();
