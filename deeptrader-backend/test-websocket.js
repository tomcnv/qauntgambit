import WebSocket from 'ws';

console.log('🧪 Testing Binance WebSocket connection...');

const ws = new WebSocket('wss://stream.binance.com:9443/ws/btcusdt@ticker');

ws.on('open', () => {
  console.log('✅ WebSocket connected successfully');
});

ws.on('message', (data) => {
  try {
    const tickerData = JSON.parse(data.toString());
    console.log('📨 Received data:', {
      eventType: tickerData.e,
      symbol: tickerData.s,
      price: tickerData.c,
      priceChange: tickerData.P,
      volume: tickerData.v
    });

    // Close after first message
    ws.close();
    console.log('✅ Test completed successfully');
  } catch (error) {
    console.error('❌ Error parsing data:', error);
  }
});

ws.on('error', (error) => {
  console.error('❌ WebSocket error:', error);
});

ws.on('close', () => {
  console.log('🔌 WebSocket closed');
});

// Timeout after 10 seconds
setTimeout(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.close();
    console.log('⏰ Test timed out');
  }
}, 10000);
