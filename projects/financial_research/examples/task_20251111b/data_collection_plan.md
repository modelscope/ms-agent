# Data Collection Plan

## Objective
Collect financial and macroeconomic data required to analyze the profitability-cash flow matching of Midea Group (000333.SZ), Gree Electric (000651.SZ), and Haier Smart Home (600690.SH) over the past four quarters, in conjunction with China's monetary environment.

## Data Requirements & Tool Mapping

### 1. Quarterly Financial Statements (Profit & Cash Flow)
- **Entities**: 
  - Midea Group: `sz.000333`
  - Gree Electric: `sz.000651`
  - Haier Smart Home: `sh.600690`
- **Time Range**: Past 4 quarters → Q3 2024, Q2 2024, Q1 2024, Q4 2023
- **Data Types**:
  - `profit`: for net profit
  - `cash_flow`: for net cash from operating activities
- **Tool**: `financial_data_fetcher---get_financial_data`

### 2. Macroeconomic Indicators
- **Indicators**:
  - `money_supply_year`: Annual M2 data (will extract quarterly values)
  - `loan_rate`: Benchmark loan rate (proxy for interest rate environment)
- **Time Range**: 2023-10-01 to 2024-09-30 (covers past 4 quarters)
- **Tool**: `financial_data_fetcher---get_macro_data`

### 3. Optional Operational Metrics
- **Data Type**: `operation` (includes receivables/inventory turnover)
- **Scope**: Same companies and quarters as above
- **Note**: Will collect if easily available; not critical for core analysis

## Out-of-Scope Data
- Public sentiment data (not supported by current tools)
- Forward-looking forecasts beyond historical data
- Real-time news or media commentary

## Execution Strategy
- Fetch all 3 companies × 4 quarters × 2 data types (profit + cash_flow) = 24 tool calls
- Fetch macro data in one call
- Validate each response for non-empty `example_data`; retry once if empty
- Save all outputs automatically via tool; no manual file handling needed