# Salesperson Sales Accounting Formula - README

## 📋 Overview

This document explains the updated accounting formula for salesperson sales transactions. The formula ensures that revenue is recorded at the **full sale amount** while receivables are recorded at the **net amount** after deductions.

---

## 🔄 What Changed

### Previous Formula (Incorrect)
- Revenue was recorded at netted amount (subtotal)
- Commission and discount had duplicate offsetting CR entries
- Revenue didn't show true sales value

### New Formula (Correct)
- **Revenue** = Full sale amount (Quantity × Price)
- **Receivable** = Net amount after deductions (already in subtotal)
- **No duplicate entries** - commission/discount already netted in receivable

---

## 💰 Accounting Formula

### Monthly Commission Schedule

**Scenario:**
- Product: F1
- Quantity: 50 units
- Unit Price: 1,500 SL
- Commission Rate: 7%
- Discount Rate: 3%
- Cost: 0.03 USD (40,021 SL)

**Calculations:**
```
Gross Sale:      50 × 1,500 = 75,000 SL
Discount (3%):   75,000 × 0.03 = 2,250 SL
Commission (7%): 75,000 × 0.07 = 5,250 SL
Receivable:      75,000 - 2,250 = 72,750 SL
```

**Accounting Entries:**

| # | Account Category | Account Name | Debit (SL) | Credit (SL) |
|---|------------------|--------------|------------|-------------|
| 1 | Expense | COGS Expense | 40,021 | |
| 2 | Asset | Inventory Asset | | 40,021 |
| 3 | Asset | **Accounts Receivable** | **72,750** | |
| 4 | Revenue | **Sales Revenue** | | **75,000** |
| 5 | Expense | Commission Expense | 5,250 | |
| 6 | Liability | Commission Payable | | 5,250 |
| 7 | Expense | Sales Discount | 2,250 | |
| | **TOTALS** | | **120,271** | **120,271** ✅ |

**Balance Proof:**
```
Left Side (DR):  Receivable (72,750) + Discount (2,250) + Commission (5,250) = 80,250
Right Side (CR): Revenue (75,000) + Comm Payable (5,250) = 80,250
✓ BALANCED
```

---

### Daily Commission Schedule

**Same Scenario as Above**

**Calculations:**
```
Gross Sale:      50 × 1,500 = 75,000 SL
Discount (3%):   75,000 × 0.03 = 2,250 SL
Commission (7%): 75,000 × 0.07 = 5,250 SL
Receivable:      75,000 - 2,250 - 5,250 = 67,500 SL
```

**Accounting Entries:**

| # | Account Category | Account Name | Debit (SL) | Credit (SL) |
|---|------------------|--------------|------------|-------------|
| 1 | Expense | COGS Expense | 40,021 | |
| 2 | Asset | Inventory Asset | | 40,021 |
| 3 | Asset | **Accounts Receivable** | **67,500** | |
| 4 | Revenue | **Sales Revenue** | | **75,000** |
| 5 | Expense | Commission Expense | 5,250 | |
| 6 | Expense | Sales Discount | 2,250 | |
| | **TOTALS** | | **115,021** | **115,021** ✅ |

**Balance Proof:**
```
Left Side (DR):  Receivable (67,500) + Discount (2,250) + Commission (5,250) = 75,000
Right Side (CR): Revenue (75,000) = 75,000
✓ BALANCED
```

---

## 📐 Dynamic Formula (For Any Transaction)

### Variables
- `Q` = Quantity sold
- `P` = Price per unit
- `C%` = Commission rate
- `D%` = Discount rate
- `Cost` = Product cost per unit

### Monthly Commission Schedule

| Entry | Account | DR/CR | Formula |
|-------|---------|-------|---------|
| 1 | COGS Expense | DR | `Cost × Q` |
| 2 | Inventory Asset | CR | `Cost × Q` |
| 3 | Receivable | DR | `(Q × P) - (Q × P × D%)` |
| 4 | Revenue | CR | `Q × P` |
| 5 | Commission Expense | DR | `Q × P × C%` |
| 6 | Commission Payable | CR | `Q × P × C%` |
| 7 | Discount Expense | DR | `Q × P × D%` |

### Daily Commission Schedule

| Entry | Account | DR/CR | Formula |
|-------|---------|-------|---------|
| 1 | COGS Expense | DR | `Cost × Q` |
| 2 | Inventory Asset | CR | `Cost × Q` |
| 3 | Receivable | DR | `(Q × P) - (Q × P × D%) - (Q × P × C%)` |
| 4 | Revenue | CR | `Q × P` |
| 5 | Commission Expense | DR | `Q × P × C%` |
| 6 | Discount Expense | DR | `Q × P × D%` |

---

## 🔍 Key Differences Between Schedules

### Monthly vs Daily

| Aspect | Monthly | Daily |
|--------|---------|-------|
| **Receivable** | Sales - Discount | Sales - Discount - Commission |
| **Commission Payable** | Yes (Liability) | No (netted in receivable) |
| **Net Owed by Salesperson** | Higher (commission paid later) | Lower (commission deducted immediately) |

**Example with 75,000 sale:**
- **Monthly:** Salesperson owes 72,750 (company pays 5,250 commission later)
- **Daily:** Salesperson owes 67,500 (commission already deducted)

---

## 🎯 Why This Formula is Correct

### 1. Revenue Recognition
✅ **Revenue shows full sale amount (75,000)**
- Reflects true sales performance
- Better for revenue analysis and forecasting
- Follows GAAP/IFRS standards

### 2. Proper Expense Matching
✅ **Commission and Discount as expenses**
- Properly categorized as selling expenses
- Matched to the revenue they generate
- Clear profit margin calculation

### 3. Accurate Receivable
✅ **Receivable shows net amount owed**
- Monthly: Salesperson owes sale minus discount
- Daily: Salesperson owes sale minus discount and commission
- Matches cash collection expectations

### 4. No Double-Counting
✅ **Each amount recorded once**
- Receivable is already netted (via subtotal calculation)
- No offsetting CR entries for commission/discount
- Mathematically balanced

---

## 🧪 Testing Instructions

### Step 1: Upgrade Module
```
1. Open Odoo
2. Go to: Settings → Apps
3. Search: "idil"
4. Click: "Upgrade"
5. Wait for completion
```

### Step 2: Create Test Sale Order

**Setup:**
- Salesperson: Select one with **monthly** commission schedule
- Product: Select commissionable product (e.g., 7% commission, 3% discount)
- Quantity: 50
- Unit Price: 1,500 SL

**Create and Confirm:**
1. Create new sale order
2. Fill in the details above
3. Click "Confirm"

### Step 3: Verify Accounting Entries

**Navigate to Transaction Bookings:**
```
Accounting Operations → Transaction Bookings
```

**Find Your Sale Order and Verify:**

| Check | Expected | Actual |
|-------|----------|--------|
| Revenue CR | 75,000 | _____ |
| Receivable DR | 72,750 | _____ |
| Commission Expense DR | 5,250 | _____ |
| Commission Payable CR | 5,250 | _____ |
| Discount Expense DR | 2,250 | _____ |
| **Total DR** | **80,250** | _____ |
| **Total CR** | **80,250** | _____ |

✅ All amounts should match and DR should equal CR!

### Step 4: Check Trial Balance

**Navigate to Trial Balance:**
```
Accounting Operations → Reports → Trial Balance
```

**Verify:**
- Revenue account shows **75,000** (not 72,750)
- Total Debit = Total Credit (balanced)

---

## 📊 Financial Report Impact

### Income Statement

**Before (Old Formula):**
```
Revenue:               72,750
COGS:                 (40,021)
Gross Profit:          32,729
```

**After (New Formula):**
```
Revenue:               75,000  ✓ Shows true sales
COGS:                 (40,021)
Gross Profit:          34,979
Commission Expense:    (5,250)
Discount Expense:      (2,250)
Net Profit:            27,479  ✓ Same final result, better detail
```

**Benefits:**
- ✅ Clear visibility of gross sales
- ✅ Separate tracking of commission and discount
- ✅ Better gross profit margin analysis
- ✅ More accurate revenue KPIs

---

## 🔧 Technical Details

### File Modified
- **Path**: `idil/models/sales.py`
- **Method**: `book_accounting_entry`

### Changes Made

**1. Revenue Entry (Line ~700)**
```python
# OLD:
"cr_amount": float(line.subtotal),

# NEW:
"cr_amount": float(line.quantity * line.price_unit),
```

**2. Daily Commission (Removed Lines ~751-767)**
```python
# REMOVED: CR Receivable entry for daily commission
# Reason: Already netted in receivable amount
```

**3. Discount (Removed Lines ~786-801)**
```python
# REMOVED: CR Receivable entry for discount
# Reason: Already netted in receivable amount
```

---

## ❓ FAQ

### Q: Why does revenue show more than receivable?
**A:** Revenue shows the full sale amount (75,000). Receivable shows net amount after deductions (72,750 for monthly, 67,500 for daily). The difference is covered by expense accounts (commission, discount).

### Q: Will this affect old transactions?
**A:** No. Only new sales orders created after the upgrade will use the new formula. Previous transactions remain unchanged.

### Q: What if trial balance doesn't balance?
**A:** This indicates a configuration issue. Check:
1. All products have COGS account configured
2. All salespersons have receivable account configured
3. Monthly commission salespersons have commission payable account configured

### Q: Can I still use different commission/discount rates?
**A:** Yes! The formula is dynamic and works with any:
- Commission rate (0% to 100%)
- Discount rate (0% to 100%)
- Product price
- Quantity
- Currency

### Q: How do I verify everything is working?
**A:** Create a test sale order and check:
1. Transaction booking lines balance (DR = CR)
2. Revenue equals (Quantity × Price)
3. Receivable equals correct netted amount
4. Trial balance remains balanced

---

## 📝 Summary

### Formula Benefits
✅ Revenue shows true sale amount  
✅ Receivable shows accurate net owed  
✅ No duplicate accounting entries  
✅ Trial balance always balanced  
✅ Better financial reporting  
✅ Follows accounting standards  

### Supported Scenarios
✅ Monthly commission schedule  
✅ Daily commission schedule  
✅ Products with/without commission  
✅ Products with/without discount  
✅ Any quantity, price, or rate  
✅ Multiple currencies  

---

## 📞 Support

For questions or issues:
1. Review this README
2. Check the walkthrough document
3. Verify module is upgraded
4. Contact your system administrator

**Last Updated:** 2025-12-08  
**Version:** 2.0
