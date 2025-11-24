# Product Profitability Report - Implementation Guide

## Overview

This document explains the **currency-aware profitability calculation** approach used to generate accurate product profitability reports in a multi-currency environment (USD costs, Shilling sales).

## Problem Statement

### Initial Challenge
The original Product Profitability report had a **critical currency mismatch**:

```
Revenue:    182,548,000 Shillings  ← Sales in local currency
Cost:            6,135 USD         ← Product costs in USD
Profit:    182,541,865 ???         ← MEANINGLESS (mixing currencies!)
Margin:           100%             ← WRONG!
```

### The Math Was Broken

**Before Fix:**
```python
net_profit = SUM(quantity * price_in_shillings) - SUM(quantity * cost_in_usd)
           = 182,548,000 - 6,135
           = 182,541,865 (comparing apples to oranges!)
```

**Result:** Every product showed 100% margin because the USD cost was a tiny number compared to Shilling revenue.

## Solution Architecture

### Currency Standardization to USD

The solution converts **all revenue to USD** using the exchange rate stored at the time of each sale.

**Why USD?**
1. ✅ Product costs are already in USD
2. ✅ Each sale order has its exchange rate (`so.rate`)
3. ✅ Historically accurate (uses rate from transaction date)
4. ✅ Consistent with system's base currency

### The Fix

**After Fix:**
```python
revenue_usd = SUM(quantity * price_in_shillings / exchange_rate)
cost_usd = SUM(quantity * cost_in_usd)
net_profit_usd = revenue_usd - cost_usd
margin_percentage = (net_profit_usd / revenue_usd) * 100
```

**Result:** Accurate margins in USD, both revenue and cost in same currency.

## Implementation Details

### SQL Query Modifications

#### Before (WRONG):
```sql
SELECT
    p.name AS product_name,
    SUM(sol.quantity) AS sold_qty,
    AVG(sol.price_unit) AS avg_price,                          -- In Shillings
    SUM(sol.quantity * sol.price_unit) AS total_revenue,       -- In Shillings
    p.cost AS unit_cost,                                        -- In USD
    SUM(sol.quantity * p.cost) AS total_cost,                  -- In USD
    (SUM(sol.quantity * sol.price_unit) - SUM(sol.quantity * p.cost)) AS net_profit  -- MIXED!
```

#### After (CORRECT):
```sql
SELECT
    p.name AS product_name,
    SUM(sol.quantity) AS sold_qty,
    AVG(sol.price_unit / NULLIF(so.rate, 0)) AS avg_price,                                    -- USD
    SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) AS total_revenue,                 -- USD
    p.cost AS unit_cost,                                                                        -- USD
    SUM(sol.quantity * p.cost) AS total_cost,                                                  -- USD
    (SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) - SUM(sol.quantity * p.cost)) AS net_profit  -- USD
FROM idil_sale_order_line sol
JOIN idil_sale_order so ON sol.order_id = so.id  -- ← GET THE EXCHANGE RATE
JOIN my_product_product p ON sol.product_id = p.id
```

**Key Changes:**
1. Added `JOIN idil_sale_order so` to access exchange rate
2. Divided all price calculations by `so.rate`
3. Used `NULLIF(so.rate, 0)` to prevent division by zero

### Report Display Updates

**Title:**
```python
# Before
Paragraph("<b>Product Profitability Analysis</b>", subtitle_style)

# After
Paragraph("<b>Product Profitability Analysis (USD)</b>", subtitle_style)
```

**Column Headers:**
```python
# Before
headers = ["Product", "Sold Qty", "Avg Price", "Revenue", "Unit Cost", ...]

# After
headers = ["Product", "Sold Qty", "Avg Price (USD)", "Revenue (USD)", "Unit Cost (USD)", ...]
```

## Examples

### Example 1: Rodhi dhaadheer (Bakery Product)

**Sales Data:**
- Quantity Sold: 91,274 units
- Sell Price: 2,000 Shillings per unit
- Exchange Rate: 1 USD = 1,000 Shillings
- Product Cost: $0.07 USD per unit

**Before (WRONG):**
```
Revenue:    182,548,000 Shillings
Cost:             6,135 USD
Profit:     182,541,865 ???
Margin:          100.0%          ← WRONG!
```

**After (CORRECT):**
```
Revenue:    $182,548 USD  (182,548,000 ÷ 1,000)
Cost:         $6,135 USD
Profit:     $176,413 USD
Margin:         96.5%            ← CORRECT!
```

### Example 2: Multi-Currency Sales

**Product sold at different exchange rates:**
- Day 1: 100 units @ 2,000 Shillings, Rate = 950 → Revenue = $210.53 USD
- Day 2: 100 units @ 2,000 Shillings, Rate = 1,050 → Revenue = $190.48 USD
- Cost: $0.07/unit × 200 = $14 USD

**Calculation:**
```sql
-- Each sale uses its own rate
SUM(100 * 2000 / 950 + 100 * 2000 / 1050) = $401.01 USD
```

**Result:**
```
Revenue:  $401.01 USD
Cost:      $14.00 USD
Profit:   $387.01 USD
Margin:     96.5%
```

## Real-World Scenarios

### Scenario 1: High Margin (Correct)

If your raw materials truly cost $0.07 and you sell for $2.00:
```
Cost:    $0.07 (flour, water, yeast)
Price:   $2.00 (finished bread)
Margin:  96.5%  ← LEGITIMATE!
```

This is **normal for bakery products** where raw materials are cheap but value is added through processing.

### Scenario 2: Currency Fluctuation

**Month 1:** Exchange rate weakens (1 USD = 900 Shillings)
- Sell at 2,000 Shillings → $2.22 USD revenue
- Cost: $0.07 USD
- Margin: 96.8% (slightly higher in USD)

**Month 2:** Exchange rate strengthens (1 USD = 1,100 Shillings)
- Sell at 2,000 Shillings → $1.82 USD revenue
- Cost: $0.07 USD
- Margin: 96.2% (slightly lower in USD)

**The report accounts for this automatically** using historical rates.

## Data Flow

```
User Input (Wizard)
    ↓
┌─────────────────────────────────────────┐
│ ProductProfitabilityReportWizard        │
│ - start_date, end_date, company_id      │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ SQL Query Execution                     │
│                                         │
│ FOR EACH sale_order_line:              │
│   revenue_usd = quantity * price / rate │
│   cost_usd = quantity * product.cost    │
│                                         │
│ GROUP BY product:                       │
│   SUM(revenue_usd)                      │
│   SUM(cost_usd)                         │
│   Calculate margin %                    │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ PDF Generation                          │
│ - Format as table                       │
│ - Add totals row                        │
│ - Show all values in USD                │
└─────────────────────────────────────────┘
    ↓
PDF Output (All USD)
```

## Important Fields

### From `idil.sale.order`
- `rate`: Exchange rate at time of sale (e.g., 1 USD = 975.5 Shillings)
- `order_date`: Used for date range filtering
- `state`: Must be 'confirmed'

### From `idil.sale.order.line`
- `quantity`: Units sold
- `price_unit`: Price per unit **in Shillings**

### From `my_product.product`
- `cost`: Product cost **in USD** (Weighted Average Cost)

## Formulas Reference

### Per Product
```python
sold_qty = SUM(line.quantity)

avg_price_usd = AVG(line.price_unit / order.rate)

total_revenue_usd = SUM(line.quantity * line.price_unit / order.rate)

total_cost_usd = SUM(line.quantity * product.cost)

net_profit_usd = total_revenue_usd - total_cost_usd

margin_percentage = (net_profit_usd / total_revenue_usd) * 100
```

### Totals Row
```python
grand_total_revenue = SUM(all_products.total_revenue_usd)
grand_total_cost = SUM(all_products.total_cost_usd)
grand_total_profit = grand_total_revenue - grand_total_cost
overall_margin = (grand_total_profit / grand_total_revenue) * 100
```

## Validation Steps

### 1. Verify Exchange Rates Exist
```sql
SELECT 
    so.name,
    so.order_date,
    so.rate
FROM idil_sale_order so
WHERE so.state = 'confirmed'
  AND (so.rate IS NULL OR so.rate = 0);
```

**Expected:** Zero rows (all orders have valid rates)

### 2. Compare with Manual Calculation
```sql
-- Pick one product
SELECT 
    sol.quantity,
    sol.price_unit AS price_shillings,
    so.rate,
    (sol.price_unit / so.rate) AS price_usd,
    p.cost AS cost_usd,
    ((sol.price_unit / so.rate) - p.cost) AS profit_per_unit_usd
FROM idil_sale_order_line sol
JOIN idil_sale_order so ON sol.order_id = so.id
JOIN my_product_product p ON sol.product_id = p.id
WHERE p.name = 'Rodhi dhaadheer'
  AND so.state = 'confirmed'
LIMIT 5;
```

Manually verify the calculations match.

### 3. Check Report Total
```sql
-- Run report for period
-- Then verify total matches:
SELECT 
    SUM(sol.quantity * sol.price_unit / NULLIF(so.rate, 0)) AS expected_total_revenue_usd
FROM idil_sale_order_line sol
JOIN idil_sale_order so ON sol.order_id = so.id
WHERE so.state = 'confirmed'
  AND so.order_date BETWEEN '2025-01-01' AND '2025-12-31';
```

## Troubleshooting

### Issue: Division by Zero Error

**Symptom:** Report crashes with "division by zero"

**Cause:** Some sales orders have `rate = 0` or `rate IS NULL`

**Solution:** The query uses `NULLIF(so.rate, 0)` which returns `NULL` if rate is 0, preventing division errors. However, those rows will be excluded.

**Fix broken rates:**
```sql
UPDATE idil_sale_order
SET rate = 1000  -- Set to default rate
WHERE rate IS NULL OR rate = 0;
```

### Issue: Margins Still Look Wrong

**Symptom:** Margins are still 100% or unrealistic

**Possible Causes:**
1. **Product costs are wrong**: Check `p.cost` vs actual purchase prices
2. **Exchange rates are wrong**: Verify `so.rate` values are realistic
3. **Currency field confusion**: Ensure prices are in Shillings, costs in USD

**Debug Query:**
```sql
SELECT 
    p.name,
    p.cost AS product_cost_usd,
    AVG(pol.price_unit) AS avg_purchase_price
FROM my_product_product p
LEFT JOIN idil_purchase_order_line pol ON pol.product_id = p.id
GROUP BY p.name, p.cost
HAVING p.cost < 0.50  -- Flag suspiciously low costs
ORDER BY p.cost;
```

### Issue: Different Results from Previous Report

**Symptom:** Margins changed significantly after the fix

**Explanation:** This is **expected and correct**!
- **Before:** Compared Shillings to USD (wrong)
- **After:** Compares USD to USD (correct)

The new numbers are the **accurate** ones.

## Best Practices

1. **Regular Exchange Rate Updates**: Ensure `rate` is set on every sale order
2. **Cost Maintenance**: Keep product costs updated in USD
3. **Currency Consistency**: Always use USD for costs, local currency for prices
4. **Report Period Selection**: Use fiscal periods for meaningful analysis
5. **Margin Benchmarks**: Establish acceptable margin ranges per product category

## File Locations

```
idil/
├── models/
│   └── report_productprofitability.py   # Main report logic
└── views/
    └── report_productprofitability.xml  # Wizard and menu
```

## Version History

- **v1.0** (Initial): Single-currency calculation (broken)
- **v2.0** (2025-11-24): Multi-currency support with exchange rate conversion
  - Added `so.rate` to query
  - Converted all revenue to USD
  - Updated report title and headers
  - Added `NULLIF` protection

## Related Documentation

- **Cash Flow Statement**: See `CASHFLOW_README.md`
- **Exchange Rate Management**: See `models/sales.py`
- **Product Cost Calculation**: See `models/products.py`

---

**Author**: Antigravity AI  
**Last Updated**: 2025-11-24  
**Module**: idil (BizCore ERP)
