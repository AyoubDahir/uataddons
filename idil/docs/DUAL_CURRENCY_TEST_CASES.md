# Dual Currency - Test Cases & Expected Results

## Pre-Test Setup

Before running any tests, ensure the following setup is complete:

### 1. Create Exchange Clearing Accounts

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to **Chart of Accounts** | Account list opens |
| 2 | Create new account: `Exchange Clearing Account` with **USD** currency | Account created |
| 3 | Create new account: `Exchange Clearing Account` with **SL** currency | Account created |

### 2. Set Up Exchange Rate

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Go to **Settings > Currencies** | Currency list opens |
| 2 | Select **SL (Somali Shilling)** | Currency form opens |
| 3 | Add rate: Date = Today, Rate = `571` | Rate saved |

### 3. Test Data Required

| Data Type | USD Version | SL Version |
|-----------|-------------|------------|
| Vendor | "USD Vendor" (USD payable account) | "SL Vendor" (SL payable account) |
| Item | "USD Item" (USD asset account, cost $10) | "SL Item" (SL asset account, cost 5,000 SL) |
| Cash Account | "USD Cash" (USD) | "SL Cash" (SL) |
| Product | "Test Product" (SL asset account) | - |

---

## Test Case 1: Mixed Currency BOM

**Objective**: Verify that BOMs can contain items with different currencies.

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Go to **Manufacturing > Bill of Materials** | - |
| 2 | Click **Create** | - |
| 3 | Enter BOM Name | `Mixed Currency BOM Test` |
| 4 | Select Product | `Test Product` |
| 5 | Add BOM Line 1 | Item: `USD Item`, Qty: 2 |
| 6 | Add BOM Line 2 | Item: `SL Item`, Qty: 3 |
| 7 | Click **Save** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| BOM saves successfully | No error, BOM record created | |
| `is_mixed_currency` field | Shows **True** | |
| `currency_id` field | Shows **Empty/False** (mixed) | |
| BOM Line 1 currency | Shows **USD** | |
| BOM Line 2 currency | Shows **SL** | |
| Total Cost calculated | Sum of line totals (in original currencies) | |

### Verification Query
```sql
SELECT name, is_mixed_currency, currency_id 
FROM idil_bom 
WHERE name = 'Mixed Currency BOM Test';
```

---

## Test Case 2: Manufacturing Order with Mixed BOM

**Objective**: Verify manufacturing orders correctly convert mixed-currency items.

### Prerequisites
- Complete Test Case 1 (Mixed Currency BOM exists)
- Exchange rate configured (571 SL/USD)

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Go to **Manufacturing > Manufacturing Orders** | - |
| 2 | Click **Create** | - |
| 3 | Select BOM | `Mixed Currency BOM Test` |
| 4 | Enter Quantity | `5` |
| 5 | Verify exchange rate is populated | Should show `571` |
| 6 | Click **Confirm** / **Start Production** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Order created | No error | |
| Transaction booking created | 1 booking record | |
| Booking lines for USD Item | 4 lines (DR product, CR clearing USD, DR clearing SL, CR item USD) | |
| Booking lines for SL Item | 4 lines (same pattern) | |
| USD Item conversion | $10 × 2 × 5 = $100 → converted to SL if product is SL | |
| SL Item | 5,000 × 3 × 5 = 75,000 SL (no conversion if product is SL) | |

### Verification - Transaction Booking Lines

Check the booking lines created:

| Account | Type | Amount | Currency |
|---------|------|--------|----------|
| Product Asset Account | DR | (converted total) | SL |
| Exchange Clearing Account | CR | (converted total) | SL |
| Exchange Clearing Account | DR | (original amount) | USD |
| USD Item Asset Account | CR | (original amount) | USD |

---

## Test Case 3: Cross-Currency Item Purchase (USD Item, SL Vendor)

**Objective**: Verify purchasing USD items from an SL vendor uses clearing accounts.

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Go to **Purchases > Purchase Orders** | - |
| 2 | Click **Create** | - |
| 3 | Select Vendor | `SL Vendor` (has SL payable account) |
| 4 | Verify exchange rate | Should auto-populate (571) |
| 5 | Add Order Line | Item: `USD Item`, Qty: 10, Cost: $10 |
| 6 | Click **Save** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Order saves | No "Currency mismatch" error | |
| Total amount | $100 (in item's currency) | |
| Transaction booking created | 1 booking | |
| Number of booking lines | **4 lines** (clearing pattern) | |

### Expected Booking Lines

| Line | Account | Type | Amount | Currency |
|------|---------|------|--------|----------|
| 1 | USD Item Asset | DR | $100.00 | USD |
| 2 | Exchange Clearing (USD) | CR | $100.00 | USD |
| 3 | Exchange Clearing (SL) | DR | 57,100.00 | SL |
| 4 | SL Vendor Payable | CR | 57,100.00 | SL |

### Verification Query
```sql
SELECT 
    tbl.description,
    ca.name as account_name,
    tbl.transaction_type,
    tbl.dr_amount,
    tbl.cr_amount,
    cur.name as currency
FROM idil_transaction_bookingline tbl
JOIN idil_chart_account ca ON tbl.account_number = ca.id
JOIN res_currency cur ON ca.currency_id = cur.id
WHERE tbl.transaction_booking_id = (
    SELECT id FROM idil_transaction_booking 
    WHERE reffno LIKE '%PO%' 
    ORDER BY id DESC LIMIT 1
);
```

---

## Test Case 4: Same-Currency Item Purchase (No Clearing)

**Objective**: Verify same-currency purchases use simple 2-line booking.

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Go to **Purchases > Purchase Orders** | - |
| 2 | Click **Create** | - |
| 3 | Select Vendor | `SL Vendor` (SL payable) |
| 4 | Add Order Line | Item: `SL Item`, Qty: 5, Cost: 5,000 SL |
| 5 | Click **Save** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Order saves | Success | |
| Number of booking lines | **2 lines** (simple pattern) | |

### Expected Booking Lines

| Line | Account | Type | Amount | Currency |
|------|---------|------|--------|----------|
| 1 | SL Item Asset | DR | 25,000.00 | SL |
| 2 | SL Vendor Payable | CR | 25,000.00 | SL |

---

## Test Case 5: Cross-Currency Product Purchase

**Objective**: Verify product purchases work with cross-currency clearing.

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Go to **Purchases > Product Purchase Orders** | - |
| 2 | Click **Create** | - |
| 3 | Select Vendor | `USD Vendor` (USD payable) |
| 4 | Verify exchange rate | Should show 571 |
| 5 | Add Line | Product: `Test Product` (SL asset), Qty: 2, Cost: 10,000 SL |
| 6 | Click **Save** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Order saves | No currency mismatch error | |
| Booking lines | **4 lines** (clearing pattern) | |
| Conversion | 20,000 SL ÷ 571 = $35.03 USD for vendor payable | |

---

## Test Case 6: Purchase Return (Currency Inheritance)

**Objective**: Verify purchase return inherits currency from original order.

### Prerequisites
- Complete Test Case 3 (Cross-currency purchase exists)

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Go to **Purchases > Purchase Returns** | - |
| 2 | Click **Create** | - |
| 3 | Select Vendor | `SL Vendor` |
| 4 | Select Original Order | (the PO from Test Case 3) |
| 5 | Observe **Currency** field | - |
| 6 | Add return line | Item: `USD Item`, Return Qty: 2 |
| 7 | Click **Confirm** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Currency field auto-populated | Shows **USD** (from original order) | |
| Currency field is readonly | Cannot change manually | |
| Exchange rate populated | Shows rate from original order | |
| Return confirmed | Transaction reversal created | |

---

## Test Case 7: Cross-Currency Vendor Payment

**Objective**: Verify paying a USD vendor from SL cash account uses clearing.

### Prerequisites
- A vendor transaction exists with pending balance (USD vendor)

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Go to **Purchases > Vendor Transactions** | - |
| 2 | Find pending transaction for `USD Vendor` | - |
| 3 | Click on the transaction | - |
| 4 | Select Cash Account | `SL Cash` (SL currency) |
| 5 | Enter Amount Paying | `$50` |
| 6 | Click **Pay** / **Register Payment** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Payment accepted | No currency mismatch error | |
| Booking lines created | **4 lines** (clearing pattern) | |

### Expected Booking Lines

| Line | Account | Type | Amount | Currency |
|------|---------|------|--------|----------|
| 1 | USD Vendor Payable | DR | $50.00 | USD |
| 2 | Exchange Clearing (USD) | CR | $50.00 | USD |
| 3 | Exchange Clearing (SL) | DR | 28,550.00 | SL |
| 4 | SL Cash | CR | 28,550.00 | SL |

---

## Test Case 8: Same-Currency Vendor Payment (No Clearing)

**Objective**: Verify same-currency payments use simple 2-line booking.

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Find pending transaction for `SL Vendor` | - |
| 2 | Select Cash Account | `SL Cash` |
| 3 | Enter Amount Paying | `10,000 SL` |
| 4 | Click **Pay** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Booking lines | **2 lines** (simple) | |
| Line 1 | DR SL Vendor Payable 10,000 SL | |
| Line 2 | CR SL Cash 10,000 SL | |

---

## Test Case 9: Trial Balance - Currency Filter

**Objective**: Verify trial balance shows accounts per selected currency.

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Go to **Reports > Trial Balance** | - |
| 2 | Select Currency | **USD** |
| 3 | Click **Generate** | - |
| 4 | Review results | - |
| 5 | Change Currency | **SL** |
| 6 | Click **Generate** again | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| USD Trial Balance | Shows only USD accounts | |
| USD accounts have balances | DR/CR totals match | |
| SL Trial Balance | Shows only SL accounts | |
| SL accounts have balances | DR/CR totals match | |
| Grand totals | DR total = CR total (balanced) | |

---

## Test Case 10: Error Handling - Missing Clearing Account

**Objective**: Verify proper error when clearing accounts are missing.

### Setup
- Temporarily delete or rename one Exchange Clearing Account

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Delete `Exchange Clearing Account (USD)` | - |
| 2 | Try to create cross-currency purchase | USD item, SL vendor |
| 3 | Click **Save** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Error message shown | "Exchange Clearing Accounts are required..." | |
| Order NOT saved | Transaction rolled back | |

### Cleanup
- Recreate the deleted Exchange Clearing Account

---

## Test Case 11: Error Handling - Missing Exchange Rate

**Objective**: Verify proper error when exchange rate is missing.

### Setup
- Delete all exchange rates for SL currency

### Steps

| Step | Action | Input |
|------|--------|-------|
| 1 | Delete SL currency rates | - |
| 2 | Try to create cross-currency purchase | - |
| 3 | Click **Save** | - |

### Expected Results

| Check | Expected Result | ✅/❌ |
|-------|-----------------|-------|
| Error message | "Exchange rate is required..." | |
| Order NOT saved | Transaction rolled back | |

### Cleanup
- Recreate exchange rate for SL

---

## Test Summary Checklist

| Test Case | Module | Status |
|-----------|--------|--------|
| TC1 | Mixed Currency BOM | ⬜ |
| TC2 | Manufacturing Order | ⬜ |
| TC3 | Cross-Currency Item Purchase | ⬜ |
| TC4 | Same-Currency Item Purchase | ⬜ |
| TC5 | Cross-Currency Product Purchase | ⬜ |
| TC6 | Purchase Return Currency Inheritance | ⬜ |
| TC7 | Cross-Currency Vendor Payment | ⬜ |
| TC8 | Same-Currency Vendor Payment | ⬜ |
| TC9 | Trial Balance Currency Filter | ⬜ |
| TC10 | Error - Missing Clearing Account | ⬜ |
| TC11 | Error - Missing Exchange Rate | ⬜ |

---

## Test Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Tester | | | |
| Developer | | | |
| Business Owner | | | |

---

*Document Version: 1.0*
*Created: December 2024*
