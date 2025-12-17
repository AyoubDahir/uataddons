# Dual Currency Support (USD & Somali Shilling)

## Overview

This document describes the dual currency implementation in the IDIL ERP system, enabling support for both **US Dollar (USD)** and **Somali Shilling (SL)** across all modules.

## Table of Contents

1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Modified Modules](#modified-modules)
4. [The Clearing Account Pattern](#the-clearing-account-pattern)
5. [Module-Specific Changes](#module-specific-changes)
6. [Usage Examples](#usage-examples)
7. [Technical Reference](#technical-reference)
8. [Troubleshooting](#troubleshooting)

---

## Introduction

### Problem Statement

Previously, the system operated with currency constraints:
- Purchase Orders were restricted to single-currency transactions
- Bills of Materials (BOMs) required all items to have the same currency
- Manufacturing Orders assumed all raw materials were in USD
- Vendor payments required matching currencies between cash and payable accounts

### Solution

The dual currency implementation allows:
- **Mixed-currency BOMs**: Products can be manufactured from USD and SL raw materials
- **Cross-currency purchases**: Buy USD items from SL vendors (or vice versa)
- **Cross-currency payments**: Pay USD vendors from SL cash accounts (or vice versa)
- **Automatic currency conversion**: Using exchange rates and clearing accounts

---

## Prerequisites

### 1. Exchange Clearing Accounts

Before using dual currency features, create these accounts in your Chart of Accounts:

| Account Name | Currency | Account Type | Required |
|--------------|----------|--------------|----------|
| `Exchange Clearing Account` | **USD** | Clearing | ✅ Yes |
| `Exchange Clearing Account` | **SL** | Clearing | ✅ Yes |

> **Important**: The account name must be exactly `Exchange Clearing Account` (case-sensitive).

### 2. Exchange Rates

Ensure exchange rates are configured in **Settings > Currencies > Currency Rates**:

| Currency | Rate (SL per 1 USD) | Example |
|----------|---------------------|---------|
| SL | 571.00 | 1 USD = 571 SL |

> Exchange rates should be updated regularly to reflect current market rates.

### 3. Module Update

After deployment, update the IDIL module:

```bash
# Restart Odoo and update the module
./odoo-bin -u idil -d your_database
```

---

## Modified Modules

| Module | File | Change Type |
|--------|------|-------------|
| Bill of Materials | `BOM.py` | Constraint removed |
| Manufacturing Order | `ManufacturingOrder.py` | Logic updated |
| Purchase Order (Items) | `purchases.py` | Clearing logic added |
| Purchase Order (Products) | `Purchaseproduct.py` | Clearing logic added |
| Purchase Return (Items) | `purchase_return.py` | Currency inheritance |
| Purchase Return (Products) | `product_purchase_return.py` | Currency inheritance |
| Vendor Transaction | `VendorTransaction.py` | Cross-currency payments |

### Modules Already Supporting Dual Currency (No Changes Needed)

| Module | File | Status |
|--------|------|--------|
| Chart of Accounts | `chart_of_accounts.py` | ✅ Already supports |
| Trial Balance | `TrialBalance.py` | ✅ Already supports |
| Item Opening Balance | `item_opening_balance.py` | ✅ Already supports |
| Vendor Opening Balance | `vendor_opening_balance.py` | ✅ Already supports |
| Product Opening Balance | `product_opening_balance.py` | ✅ Already supports |
| Sales Order | `sales.py` | ✅ Already supports |
| Stock Adjustment | `StockAdjustment.py` | ✅ Already supports |

---

## The Clearing Account Pattern

### What is the Clearing Account Pattern?

When a transaction involves two different currencies, the system uses a **4-line booking pattern** with clearing accounts to maintain accounting integrity.

### How It Works

**Example**: Purchasing a USD item ($100) from an SL vendor (rate: 571 SL/USD)

```
Line 1: DR  Item Asset Account (USD)           $100.00
Line 2: CR  Exchange Clearing Account (USD)    $100.00
Line 3: DR  Exchange Clearing Account (SL)     57,100.00 SL
Line 4: CR  Vendor Payable Account (SL)        57,100.00 SL
```

### Visual Diagram

```
┌─────────────────────┐          ┌─────────────────────┐
│  Item Asset (USD)   │          │ Vendor Payable (SL) │
│      DR $100        │          │    CR 57,100 SL     │
└─────────────────────┘          └─────────────────────┘
         │                                  ▲
         │                                  │
         ▼                                  │
┌─────────────────────┐          ┌─────────────────────┐
│ Clearing Acct (USD) │ ──────▶  │ Clearing Acct (SL)  │
│      CR $100        │ Exchange │    DR 57,100 SL     │
│                     │   Rate   │                     │
└─────────────────────┘  571:1   └─────────────────────┘
```

### Why Clearing Accounts?

1. **Maintains double-entry integrity**: Each currency's books remain balanced
2. **Audit trail**: Clear record of currency conversion
3. **Exchange rate tracking**: Rate is stored on each transaction
4. **Reconciliation**: Clearing accounts should net to zero over time

---

## Module-Specific Changes

### 1. Bill of Materials (BOM.py)

**Change**: Removed the uniform currency constraint

**Before**:
```python
@api.constrains("bom_line_ids")
def _check_uniform_currency(self):
    # Raised ValidationError if currencies didn't match
```

**After**:
- Constraint removed
- New `is_mixed_currency` computed field added
- BOM can now contain items with different currencies

**New Field**:
```python
is_mixed_currency = fields.Boolean(
    string="Mixed Currency BOM",
    compute="_compute_is_mixed_currency",
    store=True,
)
```

---

### 2. Manufacturing Order (ManufacturingOrder.py)

**Change**: Per-line currency conversion instead of assuming all items are USD

**Before**:
```python
cost_amount_usd = line.cost_price * line.quantity
cost_amount_sos = cost_amount_usd * order.rate  # Always multiplied
```

**After**:
```python
item_currency = line.item_id.asset_account_id.currency_id
product_currency = order.product_id.asset_account_id.currency_id

if item_currency.id == product_currency.id:
    cost_amount_product = cost_amount_item  # No conversion
elif item_currency.name == "USD" and product_currency.name == "SL":
    cost_amount_product = cost_amount_item * order.rate
elif item_currency.name == "SL" and product_currency.name == "USD":
    cost_amount_product = cost_amount_item / order.rate
```

---

### 3. Purchase Order - Items (purchases.py)

**Change**: Added clearing account logic for cross-currency purchases

**Before**:
```python
if stock_currency.id != payment_currency.id:
    raise ValidationError("Currency mismatch detected...")
```

**After**:
- Same currency: 2-line booking (DR Asset, CR Payable)
- Different currencies: 4-line clearing pattern

---

### 4. Purchase Order - Products (Purchaseproduct.py)

**Change**: Same as Item Purchase Order - added clearing account logic

---

### 5. Purchase Return - Items (purchase_return.py)

**Change**: Currency now inherited from original order

**Before**:
```python
currency_id = fields.Many2one(
    "res.currency",
    default=lambda self: self.env["res.currency"].search([("name", "=", "SL")], limit=1),
    readonly=True,
)
```

**After**:
```python
currency_id = fields.Many2one(
    "res.currency",
    compute="_compute_currency_from_order",
    store=True,
)

@api.depends("original_order_id", "original_order_id.currency_id")
def _compute_currency_from_order(self):
    for record in self:
        if record.original_order_id:
            record.currency_id = record.original_order_id.currency_id
```

---

### 6. Purchase Return - Products (product_purchase_return.py)

**Change**: Same as Item Purchase Return - currency inherited from original order

---

### 7. Vendor Transaction (VendorTransaction.py)

**Change**: Cross-currency payments now allowed with clearing accounts

**Before**:
```python
if account_payable.currency_id != self.cash_account_id.currency_id:
    raise ValidationError("Currency mismatch...")
```

**After**:
- Same currency: 2-line booking (DR Payable, CR Cash)
- Different currencies: 4-line clearing pattern

---

## Usage Examples

### Example 1: Mixed Currency BOM

**Scenario**: Creating a product from USD and SL raw materials

1. Create BOM with:
   - Item A (USD): $50 × 2 = $100
   - Item B (SL): 10,000 SL × 3 = 30,000 SL

2. Manufacturing Order will:
   - Convert each item to product's currency
   - Use clearing accounts for conversion
   - Calculate total cost in product's currency

---

### Example 2: Cross-Currency Purchase

**Scenario**: Buying USD items from an SL vendor

1. Create Purchase Order:
   - Vendor: ABC Supplies (SL payable account)
   - Item: Widget (USD asset account)
   - Quantity: 10 @ $25 = $250
   - Exchange Rate: 571

2. System creates 4-line booking:
   ```
   DR  Widget Asset (USD)              $250.00
   CR  Exchange Clearing (USD)         $250.00
   DR  Exchange Clearing (SL)      142,750.00 SL
   CR  ABC Supplies Payable (SL)   142,750.00 SL
   ```

---

### Example 3: Cross-Currency Vendor Payment

**Scenario**: Paying a USD vendor from an SL bank account

1. Create Vendor Payment:
   - Vendor: XYZ Corp (USD payable)
   - Amount: $500
   - Pay from: Main Bank (SL)
   - Exchange Rate: 571

2. System creates 4-line booking:
   ```
   DR  XYZ Corp Payable (USD)          $500.00
   CR  Exchange Clearing (USD)         $500.00
   DR  Exchange Clearing (SL)      285,500.00 SL
   CR  Main Bank (SL)              285,500.00 SL
   ```

---

## Technical Reference

### Currency Conversion Formula

| From | To | Formula |
|------|----|---------|
| USD | SL | `amount_sl = amount_usd × rate` |
| SL | USD | `amount_usd = amount_sl ÷ rate` |

Where `rate` = SL per 1 USD (e.g., 571)

### Exchange Rate Storage

Exchange rates are stored in `res.currency.rate`:
- `currency_id`: The foreign currency (SL)
- `name`: Date of the rate
- `rate`: Value (e.g., 571.00)
- `company_id`: Optional company filter

### Key Model Fields

| Model | Field | Purpose |
|-------|-------|---------|
| `idil.purchase_order` | `rate` | Exchange rate at transaction date |
| `idil.purchase_order` | `currency_id` | Order currency |
| `idil.bom` | `is_mixed_currency` | Flag for mixed BOM |
| `idil.chart.account` | `currency_id` | Account's currency |

---

## Troubleshooting

### Error: "Exchange Clearing Accounts are required"

**Cause**: Missing clearing accounts for one or both currencies.

**Solution**:
1. Go to Chart of Accounts
2. Create account named `Exchange Clearing Account` for USD
3. Create account named `Exchange Clearing Account` for SL

---

### Error: "Exchange rate is required for cross-currency"

**Cause**: No exchange rate defined for the transaction date.

**Solution**:
1. Go to Settings > Currencies > Currency Rates
2. Add a rate for SL currency on or before the transaction date

---

### Error: "Unhandled currency conversion"

**Cause**: Currency pair not supported (only USD↔SL implemented).

**Solution**: Contact system administrator to add support for additional currencies.

---

### Trial Balance Shows Wrong Totals

**Cause**: Viewing trial balance with wrong currency filter.

**Solution**: In Trial Balance wizard, select the correct currency to view accounts in that currency only.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Dec 2024 | Initial dual currency implementation |

---

## Support

For technical support or questions about the dual currency implementation, contact your system administrator.

---

*Document generated: December 2024*
*IDIL ERP System - Dual Currency Module*
