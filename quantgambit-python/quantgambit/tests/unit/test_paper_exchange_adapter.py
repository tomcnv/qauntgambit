import asyncio

from quantgambit.execution.paper import PaperExchangeAdapter, PaperFillEngine, PaperTradingConfig


def test_paper_exchange_records_fill():
    engine = PaperFillEngine()
    adapter = PaperExchangeAdapter(
        engine,
        config=PaperTradingConfig(enable_latency=False, slippage_bps=10.0),
    )

    result = asyncio.run(
        adapter.place_order("BTC", "buy", 1.0, "market", price=100.0, reduce_only=False)
    )

    assert result.success is True
    assert len(engine.fills) == 1
    assert engine.fills[0].symbol == "BTC"
    assert engine.fills[0].fill_price == 100.1
    assert engine.fills[0].fee_usd is not None
