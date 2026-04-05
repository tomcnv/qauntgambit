from quantgambit.market.orderbooks import OrderbookState


def test_orderbook_state_snapshot_and_delta():
    state = OrderbookState(symbol="BTC")
    state.apply_snapshot(bids=[[100, 1], [99, 2]], asks=[[101, 1]], seq=10)
    assert state.seq == 10
    state.apply_delta(bids=[[100, 0], [98, 3]], asks=[[101, 2]], seq=11)
    bids, asks = state.as_levels(depth=5)
    assert [98.0, 3.0] in bids
    assert [100.0, 1.0] not in bids
    assert asks[0][0] == 101.0
