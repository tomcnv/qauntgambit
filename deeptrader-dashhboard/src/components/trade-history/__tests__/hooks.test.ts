import { describe, expect, it } from 'vitest';

import { mapRawTrade } from '../hooks';

describe('mapRawTrade', () => {
  it('prefers explicit exit provenance fields for exitReason', () => {
    const trade = mapRawTrade({
      id: '1',
      symbol: 'BTCUSDT',
      side: 'sell',
      size: 1,
      pnl: 10,
      fees: 1,
      close_reason: 'invalidation_exit',
      reason: 'generic_reason',
    });
    expect(trade.exitReason).toBe('invalidation_exit');
  });

  it('falls back to closed_by when close_reason is absent', () => {
    const trade = mapRawTrade({
      id: '2',
      symbol: 'ETHUSDT',
      side: 'sell',
      size: 1,
      pnl: 8,
      fees: 1,
      closed_by: 'guardian_max_age_exceeded',
    });
    expect(trade.exitReason).toBe('guardian_max_age_exceeded');
  });

  it('uses backend net_pnl without subtracting fees twice', () => {
    const trade = mapRawTrade({
      id: '3',
      symbol: 'SOLUSDT',
      side: 'sell',
      size: 25.7,
      gross_pnl: -1.542,
      net_pnl: -2.78234625,
      total_fees_usd: 1.24034625,
    });
    expect(trade.realizedPnl).toBeCloseTo(-1.542, 6);
    expect(trade.fees).toBeCloseTo(1.24034625, 6);
    expect(trade.netPnl).toBeCloseTo(-2.78234625, 6);
  });
});
