#!/bin/bash
# Comprehensive API Test Suite
# Tests all backend APIs including Research & Backtesting

set -e

API_BASE="http://localhost:3001/api"
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}🧪 Comprehensive API Test Suite${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Check if server is running
echo -e "${BLUE}Checking if server is running...${NC}"
if ! curl -s "$API_BASE/health" > /dev/null; then
    echo -e "${RED}❌ Server is not running on port 3001${NC}"
    echo -e "${YELLOW}Please start the server first:${NC}"
    echo -e "  cd deeptrader-backend && node server.js"
    exit 1
fi
echo -e "${GREEN}✅ Server is running${NC}\n"

# Get auth token
echo -e "${BLUE}Authenticating...${NC}"
EMAIL="${TEST_EMAIL:-test@example.com}"
PASSWORD="${TEST_PASSWORD:-testpassword123}"

LOGIN_RESPONSE=$(curl -s -X POST "$API_BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")

TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"token":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo -e "${YELLOW}⚠️  Login failed, trying to register...${NC}"
    REGISTER_RESPONSE=$(curl -s -X POST "$API_BASE/auth/register" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"username\":\"testuser\"}")
    
    TOKEN=$(echo "$REGISTER_RESPONSE" | grep -o '"token":"[^"]*' | cut -d'"' -f4)
    
    if [ -z "$TOKEN" ]; then
        echo -e "${RED}❌ Authentication failed${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✅ Authenticated${NC}\n"

# Test function
test_endpoint() {
    local name=$1
    local method=$2
    local endpoint=$3
    local data=$4
    
    echo -e "${BLUE}Testing: $name${NC}"
    
    if [ "$method" = "GET" ]; then
        RESPONSE=$(curl -s -w "\n%{http_code}" -X GET "$API_BASE$endpoint" \
            -H "Authorization: Bearer $TOKEN")
    else
        RESPONSE=$(curl -s -w "\n%{http_code}" -X "$method" "$API_BASE$endpoint" \
            -H "Authorization: Bearer $TOKEN" \
            -H "Content-Type: application/json" \
            -d "$data")
    fi
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    
    if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
        echo -e "${GREEN}✅ PASSED (HTTP $HTTP_CODE)${NC}"
        return 0
    else
        echo -e "${RED}❌ FAILED (HTTP $HTTP_CODE)${NC}"
        echo -e "${YELLOW}Response: $BODY${NC}"
        return 1
    fi
}

# Test counters
PASSED=0
FAILED=0

# Research & Backtesting Tests
echo -e "\n${BLUE}=== Research & Backtesting APIs ===${NC}\n"

test_endpoint "List Backtests" "GET" "/research/backtests" && ((PASSED++)) || ((FAILED++))
test_endpoint "List Datasets" "GET" "/research/datasets" && ((PASSED++)) || ((FAILED++))

# Create a test backtest
END_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
START_DATE=$(date -u -v-7d +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -d "7 days ago" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

BACKTEST_DATA="{\"strategy_id\":\"amt_value_area_rejection_scalp\",\"symbol\":\"BTC-USDT-SWAP\",\"exchange\":\"okx\",\"start_date\":\"$START_DATE\",\"end_date\":\"$END_DATE\",\"initial_capital\":10000}"

test_endpoint "Create Backtest" "POST" "/research/backtests" "$BACKTEST_DATA" && ((PASSED++)) || ((FAILED++))

# Get backtest ID from list
BACKTEST_ID=$(curl -s -X GET "$API_BASE/research/backtests?limit=1" \
    -H "Authorization: Bearer $TOKEN" | grep -o '"id":"[^"]*' | head -1 | cut -d'"' -f4)

if [ ! -z "$BACKTEST_ID" ]; then
    test_endpoint "Get Backtest Detail" "GET" "/research/backtests/$BACKTEST_ID" && ((PASSED++)) || ((FAILED++))
fi

# Settings Tests
echo -e "\n${BLUE}=== Settings APIs ===${NC}\n"

test_endpoint "Get Trading Settings" "GET" "/settings/trading" && ((PASSED++)) || ((FAILED++))
test_endpoint "Get Order Types" "GET" "/settings/order-types" && ((PASSED++)) || ((FAILED++))
test_endpoint "Get Signal Config" "GET" "/settings/signal-config" && ((PASSED++)) || ((FAILED++))
test_endpoint "Get Allocator Config" "GET" "/settings/allocator" && ((PASSED++)) || ((FAILED++))

# Bot Config Tests
echo -e "\n${BLUE}=== Bot Config APIs ===${NC}\n"

test_endpoint "List Bot Profiles" "GET" "/bot-config/bots" && ((PASSED++)) || ((FAILED++))
test_endpoint "List Strategies" "GET" "/bot-config/strategies" && ((PASSED++)) || ((FAILED++))

# Dashboard Tests
echo -e "\n${BLUE}=== Dashboard APIs ===${NC}\n"

test_endpoint "Get Dashboard State" "GET" "/dashboard/state" && ((PASSED++)) || ((FAILED++))
test_endpoint "Get Trading Snapshot" "GET" "/dashboard/trading" && ((PASSED++)) || ((FAILED++))
test_endpoint "Get Signal Snapshot" "GET" "/dashboard/signals" && ((PASSED++)) || ((FAILED++))
test_endpoint "Get Market Context" "GET" "/dashboard/market-context" && ((PASSED++)) || ((FAILED++))

# Summary
echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}📊 Test Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Passed: $PASSED${NC}"
echo -e "${RED}❌ Failed: $FAILED${NC}"
echo -e "${BLUE}Total: $((PASSED + FAILED))${NC}"
echo -e "${BLUE}========================================${NC}\n"

if [ $FAILED -eq 0 ]; then
    exit 0
else
    exit 1
fi





