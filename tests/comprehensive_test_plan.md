# OpenAlgo Comprehensive Test Plan & Analysis

This document outlines a complete testing strategy for the OpenAlgo platform, ensuring it meets professional trading standards (benchmarked against Zerodha/Angel One).

## 1. Core Architecture & Standards Analysis

### Standard Broker Entities
*   **Order Book**: Must track all orders (Entry, Stop Loss, Target) with precise states (`OPEN`, `COMPLETE`, `CANCELLED`, `REJECTED`, `TRIGGER PENDING`).
*   **Trade Book**: Must record individual executions (fills). A single order can have multiple trades (partial fills), though for simplicity we often assume 1-to-1 in basic testing.
*   **Position Book**: Aggregated view of trades.
    *   `Net Quantity` = Buy Qty - Sell Qty
    *   `Avg Price` = weighted average of active holdings.
    *   `M2M (Unrealized P&L)` = (CMP - Avg Price) * Net Qty
    *   `Realized P&L` = Closed Qty * (Sell Avg - Buy Avg)

### Paper vs. Live Mode
*   **Live Mode**: Relies on `broker/` adapters. Truth is the Broker's API.
*   **Paper Mode**: Relies on `sandbox_service`. Truth is the internal database/memory state. Sandbox must realistically simulate fills, rejections, and margin checks.

## 2. High-Volume Automated Testing Strategy (Target: 4000+ Cases)

To achieve the "3-4k testcases" goal, we will employ **Property-Based Testing** using the `Hypothesis` library. This allows us to generate thousands of valid and invalid input combinations stochastically.

### A. Generator-Based Validator (`tests/test_scale_order_validation.py`)
*   **Input Space**:
    *   `Symbol`: [NIFTY, BANKNIFTY, RELIANCE, INVALID...]
    *   `Price`: [0.05, 100.0, 50000.0, -10.0, None]
    *   `Qty`: [1, 50, 10000, 0, -5]
    *   `Order Type`: [LIMIT, MARKET, SL-L, SL-M]
    *   `Product`: [MIS, NRML, CNC, CO]
    *   `Exchange`: [NSE, NFO, MCX, CDS]
*   **Scale**:
    *   `Validation Checks`: 1000 combinations to ensure `place_order` rejects invalid inputs and accepts valid ones.
    *   `P&L Calculation`: 1000 combinations of (Buy Price, Sell Price, Qty) to verify `(Sell - Buy) * Qty` match.
    *   `Broker Error Mapping`: 1000 variations of Broker Error Codes mapped to User Friendly messages.

### B. Unit Tests (Service Level)

#### 1. Signal Parsing & Classification
*   [ ] **Standard Signal**: Valid JSON input -> Correct `Signal` object.
*   [ ] **Invalid Signal**: Missing keys, wrong types -> Graceful Error.
*   [ ] **Duplicate Signal**: Same ID received twice -> Process once (Idempotency).
*   [ ] **Expiry Handling**: Signal for expired contract -> Reject.

#### 2. Order Management (`place_order_service`, `modify`, `cancel`)
*   [ ] **Limit Order**: Place LIMIT -> Verify params sent to Broker/Sandbox.
*   [ ] **Market Order**: Place MARKET -> Verify params.
*   [ ] **Stop Loss Order**: Place SL-L -> Verify `trigger_price` and `price`.
*   [ ] **Validation**: Qty > 0, valid Symbol, specific Product types (MIS/NRML).

#### 3. Position Logic (`position_monitor_service`)
*   [ ] **Add Position**: New entry -> Status `pending_open`.
*   [ ] **Update Status**: filled -> `active`.
*   [ ] **Update SL**: Modify SL -> Internal state update.
*   [ ] **Calculation**: Input Entry 100, CMP 110, Qty 50 -> P&L = 500.

### C. Integration Tests (End-to-End Workflows)

#### 1. The "Happy Path" (Long Trade)
1.  **Signal**: BUY NIFTY 1 Lot @ 100.
2.  **Order**: Entry Order placed (LIMIT/MARKET).
3.  **Fill**: Order `COMPLETE`.
4.  **Position**: Created in `active` state.
5.  **Hard SL**: SL Order placed at 90 (Stop-Limit).
6.  **Exit**: Target reached (120) -> SL Cancelled -> Exit Order Placed (LIMIT 120) -> Filled.
7.  **Final State**: Position Cleaned, Realized P&L recorded.

#### 2. The "Stop Loss Hit" (Hard SL)
1.  **Entry**: Buy @ 100. Position Active.
2.  **Hard SL**: SL Order @ 90 Active at Broker.
3.  **Trigger**: Price drops to 89. Broker fills SL.
4.  **Sync**: `PriceMonitor` detects SL Order `COMPLETE`.
5.  **Closure**: Position marked `closed` (Reason: SL Hit).

#### 3. Trailing Stop Loss
1.  **Entry**: Buy @ 100. SL @ 90. Target @ 120.
2.  **Move**: Price moves to 110 (Step 1).
3.  **Action**: Modify Hard SL Order -> New Price 100 (Cost).
4.  **Verify**: Broker API receives `modify_order` for SL ID.

#### 4. Order Rejection / Failure
1.  **Signal**: BUY @ 100.
2.  **Broker**: Reject (Insufficient Funds).
3.  **Handling**: Order Status `REJECTED`. Position NOT created/removed. Error Logged.

#### 5. Gap Opening (Exact Price Logic)
1.  **Context**: Overnight position or fast market.
2.  **Scenario**: Buy @ 100. SL @ 90. Market Gaps to 80.
3.  **Expectation**: SL Order (Stop-Limit) triggers. Broker fills at best available (or stuck if below limit in extreme cases, but typically triggers).
4.  **System**: Report Exit Price = Actual Fill Price (80), not theoretical SL (90).

### D. Live vs. Paper Verification

| Feature | Paper (Sandbox) | Live (Angel/Zerodha) |
| :--- | :--- | :--- |
| **Fills** | Immediate (if Price matches) or Stochastic | Real Market Matching |
| **Margins** | Simulated (Infinite or Configured) | Real Account Balance |
| **Latency** | Near Zero | Network + Broker processing |
| **Rejections**| Logic based (e.g. invalid symbol) | Broker specific (RMS rules) |

### E. UI/UX Standard Compliance (Trade/Order Book)

#### 1. Order Book Columns
*   **Time**: `HH:MM:SS`
*   **Type**: `BUY`/`SELL`
*   **Instrument**: Full Name
*   **Product**: `MIS`/`NRML`
*   **Qty**: `Filled` / `Total` (e.g. 50/50)
*   **Avg. Price**: Executed Price.
*   **Status**: Color Coded badge (`COMPLETE`=Green, `REJECTED`=Red, `OPEN`=Blue).

#### 2. Position Book Columns
*   **Instrument**: Symbol
*   **Net Qty**: Total holding.
*   **Avg. Price**: Break-even price.
*   **LTP**: Live from Websocket/Quote.
*   **P&L**: (LTP - Avg) * Qty. Color Coded (Green > 0, Red < 0).
*   **Actions**: "Exit", "Add" buttons.

## 3. Recommended Implementation

1.  **Expand `tests/`**: Creating dedicated test files:
    *   `tests/test_scale_order_validation.py` (Using Hypothesis for 3k+ checks)
    *   `tests/test_signal_flow.py`
    *   `tests/test_broker_adapter.py`
    *   `tests/test_ui_rendering.py` (using `client.get` and soup)
2.  **Mock Broker**: Enhance `sandbox_service` to strictly mimic Angel One's error codes and states.
3.  **UI Updates**: Audit `templates/orderbook.html` against the list above.

## 4. Execution Plan (Immediate)
1.  We have `test_order_sync.py` covering the complex "Hard SL" logic.
2.  Next: Create `tests/test_sandbox.py` to verify Paper Trading logic explicitly.
3.  Next: Create `tests/test_scale_order_validation.py` to generate the 3000+ test cases.
