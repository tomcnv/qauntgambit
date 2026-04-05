#!/bin/bash
# Compare all strategies over a time period

API_BASE="http://localhost:3002/api/research"
TENANT_ID="11111111-1111-1111-1111-111111111111"

STRATEGIES=(
    "amt_value_area_rejection_scalp"
    "poc_magnet_scalp"
    "breakout_scalp"
    "mean_reversion_fade"
    "trend_pullback"
    "opening_range_breakout"
    "asia_range_scalp"
    "europe_open_vol"
    "us_open_momentum"
    "overnight_thin"
    "high_vol_breakout"
    "low_vol_grind"
    "vol_expansion"
    "liquidity_hunt"
    "order_flow_imbalance"
    "spread_compression"
    "vwap_reversion"
    "volume_profile_cluster"
)

declare -A RUN_IDS

echo "Submitting backtests for all strategies..."
for strategy in "${STRATEGIES[@]}"; do
    result=$(curl -s -X POST "$API_BASE/backtests" \
        -H "Content-Type: application/json" \
        -H "X-Tenant-ID: $TENANT_ID" \
        -d "{
            \"name\": \"Strategy Comparison - $strategy\",
            \"strategy_id\": \"$strategy\",
            \"symbol\": \"BTCUSDT\",
            \"start_date\": \"2026-01-13\",
            \"end_date\": \"2026-01-14\",
            \"initial_capital\": 10000,
            \"config\": {
                \"maker_fee_bps\": 2,
                \"taker_fee_bps\": 5.5,
                \"slippage_model\": \"fixed\",
                \"slippage_bps\": 5
            }
        }")
    
    run_id=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('run_id',''))")
    RUN_IDS[$strategy]=$run_id
    echo "  ✓ $strategy: $run_id"
done

echo ""
echo "Waiting for backtests to complete (this may take a few minutes)..."
sleep 60

echo ""
echo "Collecting results..."
echo ""

# Collect results
RESULTS=""
for strategy in "${STRATEGIES[@]}"; do
    run_id=${RUN_IDS[$strategy]}
    if [ -n "$run_id" ]; then
        result=$(curl -s "$API_BASE/backtests/$run_id" -H "X-Tenant-ID: $TENANT_ID")
        metrics=$(echo "$result" | python3 -c "
import sys,json
d = json.load(sys.stdin)
m = d.get('metrics', {})
print(f\"{m.get('total_return_pct',0):.2f},{m.get('total_trades',0)},{m.get('win_rate',0):.1f},{m.get('profit_factor',0):.2f},{m.get('max_drawdown_pct',0):.2f},{m.get('sharpe_ratio',0):.2f}\")
" 2>/dev/null)
        RESULTS="$RESULTS$strategy,$metrics\n"
    fi
done

echo "============================================================================================================"
echo "STRATEGY COMPARISON RESULTS"
echo "============================================================================================================"
printf "%-35s %10s %8s %8s %8s %8s %8s\n" "Strategy" "Return" "Trades" "Win%" "PF" "DD%" "Sharpe"
echo "------------------------------------------------------------------------------------------------------------"

# Sort by return and display
echo -e "$RESULTS" | sort -t',' -k2 -rn | while IFS=',' read -r strategy ret trades win pf dd sharpe; do
    if [ -n "$strategy" ]; then
        printf "%-35s %9s%% %8s %7s%% %8s %7s%% %8s\n" "$strategy" "$ret" "$trades" "$win" "$pf" "$dd" "$sharpe"
    fi
done

echo "============================================================================================================"
