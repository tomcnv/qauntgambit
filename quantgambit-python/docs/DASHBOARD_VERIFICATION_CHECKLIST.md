# Dashboard Verification Checklist

This document provides a comprehensive manual testing checklist for verifying the backtesting dashboard functionality. Use this checklist to ensure all dashboard features work correctly after deployment or code changes.

## Prerequisites

Before starting verification:

1. **Services Running**:
   - [ ] Bot API server running on port 3002 (`python -m quantgambit.api.main`)
   - [ ] TimescaleDB running and accessible
   - [ ] Redis running and accessible
   - [ ] Dashboard running on port 3000 (`npm run dev` in deeptrader-dashboard)

2. **Test Data**:
   - [ ] At least one completed backtest exists in the database
   - [ ] At least one failed backtest exists (for error state testing)
   - [ ] Historical market data available for backtesting

3. **Browser**:
   - [ ] Use Chrome, Firefox, or Edge (latest version)
   - [ ] Open browser developer tools (F12) to monitor network requests

---

## Requirement 6.1: Backtest List Display

**Validates**: WHEN the backtesting page loads THEN the Dashboard SHALL display a list of available backtests

### Test Steps

1. **Navigate to Backtesting Page**
   - [ ] Open the dashboard at `http://localhost:3000`
   - [ ] Navigate to the Backtesting page from the sidebar

2. **Verify Initial Load**
   - [ ] Loading spinner appears while fetching data
   - [ ] Network request to `/api/research/backtests` is visible in DevTools
   - [ ] Request completes with 200 status

3. **Verify Backtest List Display**
   - [ ] Backtest runs table is displayed
   - [ ] Each row shows:
     - [ ] Run name/ID
     - [ ] Strategy name
     - [ ] Symbol (e.g., BTC-USDT)
     - [ ] Date period (start - end)
     - [ ] Status badge (completed/running/pending/failed)
     - [ ] PnL value (colored green/red)
     - [ ] Return percentage
     - [ ] Max Drawdown
     - [ ] Sharpe Ratio
     - [ ] Profit Factor
     - [ ] Total Trades
     - [ ] Realism indicators (F for fees, S for slippage)

4. **Verify Filtering**
   - [ ] Search box filters runs by name/strategy
   - [ ] Status dropdown filters by status
   - [ ] Symbol dropdown filters by symbol
   - [ ] "Clear filters" button resets all filters

### Expected Behavior

| Scenario | Expected Result |
|----------|-----------------|
| Page loads with backtests | Table displays all backtest runs |
| Search for "scalp" | Only runs with "scalp" in name/strategy shown |
| Filter by "completed" | Only completed runs shown |
| Filter by symbol | Only runs for selected symbol shown |

### Troubleshooting

- **Table not loading**: Check if Bot API is running on port 3002
- **Empty table with data in DB**: Check CORS headers in API response
- **Slow loading**: Check database connection and query performance

---

## Requirement 6.2: Equity Curve Chart Display

**Validates**: WHEN a backtest is selected THEN the Dashboard SHALL display the equity curve chart

### Test Steps

1. **Select a Completed Backtest**
   - [ ] Click on a row with "completed" status
   - [ ] Detail drawer slides in from the right

2. **Verify Equity Curve Loading**
   - [ ] Loading indicator appears in chart area
   - [ ] Network request to `/api/research/backtests/{id}` is visible
   - [ ] Request includes equity curve data

3. **Verify Chart Display**
   - [ ] Equity curve line chart is rendered
   - [ ] X-axis shows time/date labels
   - [ ] Y-axis shows equity values
   - [ ] Drawdown area is displayed (red shaded area)
   - [ ] Chart tooltip shows values on hover
   - [ ] Legend shows "Equity" and "Drawdown %" labels

4. **Verify Chart Interactivity**
   - [ ] Hovering over chart shows tooltip with exact values
   - [ ] Chart is responsive (resizes with drawer)

### Expected Behavior

| Scenario | Expected Result |
|----------|-----------------|
| Select completed backtest | Equity curve chart renders with data |
| Hover over chart | Tooltip shows date, equity, and drawdown values |
| Resize drawer | Chart resizes proportionally |

### Troubleshooting

- **Chart not rendering**: Check if equity curve data is in API response
- **Empty chart**: Verify `backtest_equity_curve` table has data for this run
- **Chart shows wrong data**: Check backtest ID in API request

---

## Requirement 6.3: Trades Table Display

**Validates**: WHEN a backtest is selected THEN the Dashboard SHALL display the trades table

### Test Steps

1. **Open Backtest Detail**
   - [ ] Click on a completed backtest row
   - [ ] Detail drawer opens

2. **Navigate to Trades Tab**
   - [ ] Click on "Trades" tab in the detail drawer
   - [ ] Loading indicator appears while fetching trades

3. **Verify Trades Table Display**
   - [ ] Trades table is rendered
   - [ ] Table headers show: Time, Side, Entry, Exit, Size, PnL
   - [ ] Each trade row displays:
     - [ ] Entry timestamp
     - [ ] Side badge (BUY in green, SELL in red)
     - [ ] Entry price
     - [ ] Exit price
     - [ ] Position size
     - [ ] PnL (colored green for profit, red for loss)

4. **Verify Trade Data Accuracy**
   - [ ] Trade count matches "Total Trades" in KPI strip
   - [ ] Sum of PnL values approximately matches "Realized PnL"
   - [ ] Timestamps are in chronological order

### Expected Behavior

| Scenario | Expected Result |
|----------|-----------------|
| Open Trades tab | Table displays all trades for the backtest |
| Backtest with 50+ trades | Table shows first 100 trades |
| Trade with profit | PnL shown in green with + prefix |
| Trade with loss | PnL shown in red |

### Troubleshooting

- **Trades not loading**: Check if `backtest_trades` table has data
- **Missing columns**: Verify API response includes all trade fields
- **Wrong PnL values**: Check fee and slippage calculations

---

## Requirement 6.4: Empty State Display

**Validates**: WHEN no backtests exist THEN the Dashboard SHALL display an empty state message

### Test Steps

1. **Prepare Empty State**
   - [ ] Ensure no backtests exist in database (or use a fresh tenant)
   - [ ] Or apply filters that match no results

2. **Verify Empty State Display**
   - [ ] Empty state container is centered
   - [ ] Flask/beaker icon is displayed
   - [ ] Message reads "No backtest runs found"
   - [ ] Subtext reads "Create your first backtest to get started."

3. **Verify Filtered Empty State**
   - [ ] Apply filters that match no results
   - [ ] Different empty state appears: "No runs match your filters"
   - [ ] "Clear filters" button is displayed

### Expected Behavior

| Scenario | Expected Result |
|----------|-----------------|
| No backtests in database | Empty state with "No backtest runs found" |
| Filters match nothing | Empty state with "No runs match your filters" |
| Click "Clear filters" | Filters reset, all runs shown |

### Troubleshooting

- **Empty state not showing**: Check if API returns empty array
- **Wrong message**: Verify filter state vs. data state logic

---

## Requirement 6.5: Error State with Retry

**Validates**: WHEN a backtest fails to load THEN the Dashboard SHALL display an error message with retry option

### Test Steps

1. **Simulate API Error (List)**
   - [ ] Stop the Bot API server
   - [ ] Refresh the backtesting page
   - [ ] Verify error state appears

2. **Verify Error State Display (List)**
   - [ ] Red alert icon is displayed
   - [ ] Message reads "Failed to load backtest runs"
   - [ ] Error details are shown (e.g., "Network Error")
   - [ ] "Retry" button is visible

3. **Test Retry Functionality (List)**
   - [ ] Start the Bot API server
   - [ ] Click "Retry" button
   - [ ] Loading state appears
   - [ ] Data loads successfully

4. **Simulate API Error (Detail)**
   - [ ] Select a backtest to open detail drawer
   - [ ] Stop the Bot API server
   - [ ] Verify error states in:
     - [ ] Equity curve section
     - [ ] Trades table section

5. **Verify Error State Display (Detail)**
   - [ ] Red alert icon in equity curve area
   - [ ] Message "Failed to load equity curve"
   - [ ] "Retry" button available
   - [ ] Similar error state in Trades tab

6. **Test Retry Functionality (Detail)**
   - [ ] Start the Bot API server
   - [ ] Click "Retry" button in equity curve section
   - [ ] Chart loads successfully
   - [ ] Click "Retry" in Trades tab
   - [ ] Trades table loads successfully

### Expected Behavior

| Scenario | Expected Result |
|----------|-----------------|
| API unavailable | Error message with retry button |
| Click Retry (API still down) | Error persists, can retry again |
| Click Retry (API restored) | Data loads successfully |
| Network timeout | Error message shows timeout info |

### Troubleshooting

- **Retry not working**: Check if refetch function is called
- **Error not showing**: Verify error handling in useQuery hooks
- **Infinite loading**: Check for unhandled promise rejections

---

## Requirement 6.6: Loading Indicator

**Validates**: WHEN the equity curve data is loading THEN the Dashboard SHALL display a loading indicator

### Test Steps

1. **Verify List Loading State**
   - [ ] Refresh the backtesting page
   - [ ] Observe loading spinner during data fetch
   - [ ] Message "Loading backtest runs..." is displayed

2. **Verify Detail Loading State**
   - [ ] Click on a backtest row
   - [ ] Observe loading state in detail drawer:
     - [ ] Equity curve shows spinner with "Loading equity curve..."
     - [ ] Trades tab shows spinner with "Loading trades..."

3. **Verify Loading Indicator Styling**
   - [ ] Spinner is animated (rotating)
   - [ ] Loading text is muted/gray
   - [ ] Loading state is centered in container

4. **Verify Loading Transitions**
   - [ ] Loading state transitions smoothly to data display
   - [ ] No flash of empty state before data appears
   - [ ] Loading state transitions to error state on failure

### Expected Behavior

| Scenario | Expected Result |
|----------|-----------------|
| Initial page load | Spinner with "Loading backtest runs..." |
| Open backtest detail | Spinner in equity curve area |
| Switch to Trades tab | Spinner while trades load |
| Fast network | Brief loading state, then data |
| Slow network | Loading state persists until data arrives |

### Troubleshooting

- **No loading indicator**: Check isLoading state in component
- **Loading never ends**: Check for stuck promises or missing data
- **Flash of content**: Add loading state check before rendering

---

## Additional Verification Items

### Live State Card (Warm Start)

1. **Verify Live State Display**
   - [ ] Live State Card appears above backtest list
   - [ ] Shows current positions (if any)
   - [ ] Shows account state (equity, balance, margin)
   - [ ] Shows snapshot age

2. **Verify Staleness Warning**
   - [ ] If state is stale (>5 min), amber warning appears
   - [ ] Warning shows age in minutes
   - [ ] Refresh button is available

3. **Verify Error State**
   - [ ] If live state fails to load, error card appears
   - [ ] "Retry" button is available

### Backtest Detail Actions

1. **Verify Action Buttons**
   - [ ] "Rerun" button is enabled for completed/failed backtests
   - [ ] "Clone" button opens new backtest form with same settings
   - [ ] "Add to Compare" button adds to comparison selection
   - [ ] "Export" button triggers download
   - [ ] "Delete" button shows confirmation dialog

2. **Verify Failed Backtest Display**
   - [ ] Error message banner appears for failed backtests
   - [ ] "Rerun with Force" button is available
   - [ ] Error details are displayed

### KPI Strip Verification

1. **Verify KPI Values**
   - [ ] Realized PnL matches sum of trade PnLs
   - [ ] Return % is calculated correctly
   - [ ] Max Drawdown matches equity curve
   - [ ] Sharpe Ratio is reasonable (typically -3 to +3)
   - [ ] Profit Factor > 0 for profitable backtests
   - [ ] Win Rate matches winning/total trades ratio

---

## Sign-Off

| Requirement | Verified By | Date | Status |
|-------------|-------------|------|--------|
| 6.1 Backtest List Display | | | ☐ Pass / ☐ Fail |
| 6.2 Equity Curve Chart | | | ☐ Pass / ☐ Fail |
| 6.3 Trades Table | | | ☐ Pass / ☐ Fail |
| 6.4 Empty State | | | ☐ Pass / ☐ Fail |
| 6.5 Error State with Retry | | | ☐ Pass / ☐ Fail |
| 6.6 Loading Indicator | | | ☐ Pass / ☐ Fail |

**Overall Status**: ☐ All Requirements Verified / ☐ Issues Found

**Notes**:
_Document any issues, observations, or deviations from expected behavior here._

---

## Appendix: API Endpoints Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/research/backtests` | GET | List all backtests |
| `/api/research/backtests/{id}` | GET | Get backtest detail with equity curve and trades |
| `/api/research/backtests` | POST | Create new backtest |
| `/api/research/backtests/{id}/rerun` | POST | Rerun a backtest |
| `/api/research/backtests/{id}` | DELETE | Delete a backtest |
| `/api/research/warm-start` | GET | Get current live state for warm start |

## Appendix: Common Issues and Solutions

| Issue | Possible Cause | Solution |
|-------|----------------|----------|
| CORS errors in console | API CORS not configured | Check `allow_origins` in FastAPI CORS middleware |
| 404 on API requests | Wrong API URL | Verify `VITE_BOT_API_URL` in dashboard `.env` |
| Empty equity curve | No data in DB | Run a backtest to completion |
| Stale data | Caching | Hard refresh (Ctrl+Shift+R) or clear React Query cache |
| Slow loading | Large dataset | Check database indexes on backtest tables |
