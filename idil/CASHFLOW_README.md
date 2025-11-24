# Cash Flow Statement - Implementation Guide

## Overview

This document explains the **account-based classification approach** used to generate a three-category Cash Flow Statement that complies with accounting standards (Operating, Investing, Financing Activities).

## Problem Statement

### Initial Challenge
The original Cash Flow report had several issues:
1. **Single Category**: Only showed "Operating Activities" without separating Investing and Financing
2. **Internal Transfers Inflating Figures**: Journal entries moving cash between accounts (e.g., Petty Cash → Bank) were counted as both inflows and outflows
3. **No Automatic Classification**: Required manual categorization of each transaction source

### Example of the Problem
```
Transaction: JE/0056
  Debit:  "22213 - Shiling" +25,000,000 (counted as Inflow)
  Credit: "Shiling on Hand"  -25,000,000 (counted as Outflow)

Result: Both sides counted, inflating total cash flow by 50,000,000
Reality: Net cash effect = 0 (just moving money between pockets)
```

## Solution Architecture

### Three-Tier Classification System

The solution implements **automatic account-based classification** that categorizes each cash transaction into one of three standard categories:

| Category | Business Activities | Examples |
|----------|-------------------|----------|
| **Operating** | Day-to-day business operations | Sales receipts, vendor payments, salaries, rent |
| **Investing** | Long-term asset transactions | Equipment purchases, vehicle sales |
| **Financing** | Capital structure changes | Owner contributions, loan proceeds, dividends |

### Classification Algorithm

#### Step 1: Identify Cash Transactions
```python
# Get all Cash/Bank accounts
cash_accounts = env['idil.chart.account'].search([
    ('account_type', 'in', ['cash', 'bank_transfer'])
])

# Get all transaction lines affecting cash accounts
lines = env['idil.transaction_bookingline'].search([
    ('account_number', 'in', cash_account_ids),
    ('transaction_date', '>=', start_date),
    ('transaction_date', '<=', end_date)
])
```

#### Step 2: Exclude Internal Transfers
```python
# For each transaction line
booking = line.transaction_booking_id
all_accounts = booking.booking_lines.mapped('account_number')

# Check if ALL accounts in the transaction are cash/bank
all_cash = all(acc.account_type in ['cash', 'bank_transfer'] 
               for acc in all_accounts)

if all_cash:
    continue  # Skip this transaction (internal transfer)
```

**Why this works:**
- A real cash flow has one cash account and one non-cash account
- An internal transfer has only cash/bank accounts on both sides
- By checking if ALL accounts are cash, we filter out transfers

#### Step 3: Classify by "Other Account" Type

For each remaining transaction, we examine the **non-cash account** to determine the category:

```python
# Get the "other" account (non-cash side)
other_accounts = [acc for acc in all_accounts 
                 if acc.account_type not in ['cash', 'bank_transfer']]
other_account = other_accounts[0]

# Classify based on account properties
if other_account.FinancialReporting == 'PL':
    # Profit & Loss account (Revenue/Expense)
    category = 'operating'
    
elif other_account.FinancialReporting == 'BS':
    # Balance Sheet account - need deeper analysis
    header_code = other_account.header_code
    account_name = other_account.name.lower()
    
    # INVESTING: Fixed Assets
    if header_code.startswith('15') or header_code.startswith('16') or \
       'equipment' in account_name or 'vehicle' in account_name:
        category = 'investing'
    
    # FINANCING: Equity, Loans
    elif header_code.startswith('3') or \
         'equity' in account_name or 'loan' in account_name:
        category = 'financing'
    
    else:
        # Other BS (Receivable, Payable, Inventory)
        category = 'operating'
```

### Classification Rules Table

| Account Characteristic | Category | Reasoning |
|-----------------------|----------|-----------|
| `FinancialReporting = 'PL'` | Operating | Revenue/Expense accounts represent core business |
| Header Code `4xxx`, `5xxx` | Operating | Income Statement accounts |
| Header Code `15xx`, `16xx` | Investing | Fixed Assets in chart of accounts |
| Name contains "equipment", "machinery" | Investing | Capital expenditure indicators |
| Header Code `3xxx` | Financing | Equity accounts |
| Name contains "loan", "capital" | Financing | Debt and equity transactions |
| Receivable/Payable | Operating | Working capital changes |
| Inventory | Operating | Part of operating cycle |

## Implementation Details

### File Structure

```
idil/
├── models/
│   └── report_cashflow.py          # Main report logic
├── reports/
│   └── report_cashflow.xml         # QWeb PDF template
└── views/
    └── report_cashflow.xml         # Wizard form & menu
```

### Data Flow

```
User Input (Wizard)
    ↓
┌─────────────────────────────────────────┐
│ CashFlowReportWizard.generate_report()  │
│ - Captures: start_date, end_date        │
│ - Calls: action_report_cashflow         │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ ReportCashFlow._get_report_values()     │
│                                         │
│ 1. Fetch cash/bank accounts            │
│ 2. Fetch booking lines (transactions)  │
│ 3. Loop through each line:             │
│    a. Skip internal transfers          │
│    b. Get "other" account              │
│    c. Classify (Operating/Investing/   │
│       Financing)                        │
│    d. Determine Inflow/Outflow         │
│    e. Aggregate by source & category   │
│ 4. Calculate net cash flows            │
│ 5. Return data to template             │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ report_cashflow_template (QWeb)         │
│ - Renders three sections                │
│ - Shows inflows/outflows per category   │
│ - Displays net cash flow                │
└─────────────────────────────────────────┘
    ↓
PDF Output
```

### Data Structure

The `_get_report_values()` method returns:

```python
{
    # Operating Activities
    'operating_inflows': [
        {'name': 'Bulk Receipt', 'amount': 146238000.00},
        {'name': 'Receipt', 'amount': 50000.00}
    ],
    'operating_outflows': [
        {'name': 'Pay Vendor', 'amount': 28073101.50}
    ],
    'net_operating': 118214898.50,
    
    # Investing Activities
    'investing_inflows': [...],
    'investing_outflows': [...],
    'net_investing': 0.00,
    
    # Financing Activities
    'financing_inflows': [...],
    'financing_outflows': [...],
    'net_financing': 0.00,
    
    # Total
    'net_cash_flow': 118214898.50
}
```

## Examples

### Example 1: Sales Receipt (Operating Inflow)

**Transaction:**
```
Dr: Cash                 $50,000
Cr: Accounts Receivable  $50,000
```

**Classification Logic:**
- Line examined: Cash (Dr = Inflow)
- Other account: Accounts Receivable (BS, working capital)
- **Category: Operating** (receivable = operating cycle)
- **Result: Operating Inflow of $50,000**

---

### Example 2: Equipment Purchase (Investing Outflow)

**Transaction:**
```
Dr: Equipment (Fixed Asset)  $20,000
Cr: Cash                     $20,000
```

**Classification Logic:**
- Line examined: Cash (Cr = Outflow)
- Other account: Equipment (header_code = "15xx")
- **Category: Investing** (fixed asset)
- **Result: Investing Outflow of $20,000**

---

### Example 3: Loan Received (Financing Inflow)

**Transaction:**
```
Dr: Cash              $100,000
Cr: Bank Loan Payable $100,000
```

**Classification Logic:**
- Line examined: Cash (Dr = Inflow)
- Other account: Bank Loan Payable (name contains "loan")
- **Category: Financing** (debt financing)
- **Result: Financing Inflow of $100,000**

---

### Example 4: Internal Transfer (EXCLUDED)

**Transaction:**
```
Dr: Bank Account      $25,000
Cr: Petty Cash        $25,000
```

**Classification Logic:**
- All accounts: [Bank Account (cash), Petty Cash (cash)]
- ALL are cash/bank accounts
- **Result: SKIPPED** (internal transfer, net effect = $0)

## Report Output Structure

```
CASH FLOW STATEMENT
YourCompany
From 2025-01-01 To 2025-12-31

OPERATING ACTIVITIES
  Cash Inflows:
    Bulk Receipt              $ 146,238,000.00
    Receipt                   $      50,000.00
  Cash Outflows:
    Pay Vendor                $ (28,073,101.50)
  Net Cash from Operating     $ 118,214,898.50

INVESTING ACTIVITIES
  Cash Inflows:
    Equipment Sale            $       5,000.00
  Cash Outflows:
    Equipment Purchase        $     (20,000.00)
  Net Cash from Investing     $     (15,000.00)

FINANCING ACTIVITIES
  Cash Inflows:
    Owner Contribution        $     100,000.00
  Cash Outflows:
    Loan Repayment            $     (50,000.00)
  Net Cash from Financing     $      50,000.00

NET CHANGE IN CASH            $ 118,249,898.50
```

## Configuration & Customization

### Adjusting Classification Rules

If your chart of accounts uses different codes, modify the classification logic in `report_cashflow.py`:

```python
# EXAMPLE: Add custom header codes for fixed assets
if header_code.startswith('15') or \
   header_code.startswith('16') or \
   header_code.startswith('17'):  # ← Add your code here
    category = 'investing'
```

### Adding New Keywords

```python
# EXAMPLE: Add custom keywords for loan accounts
if 'loan' in account_name or \
   'financing' in account_name or \
   'note payable' in account_name:  # ← Add your keyword
    category = 'financing'
```

## Testing & Validation

### SQL Query for Verification

To verify classification manually:

```sql
SELECT 
    tb.reffno AS transaction_ref,
    ca_cash.name AS cash_account,
    ca_other.name AS other_account,
    ca_other.FinancialReporting,
    ca_other.header_code,
    CASE 
        WHEN ca_other.FinancialReporting = 'PL' THEN 'Operating'
        WHEN ca_other.header_code LIKE '15%' THEN 'Investing'
        WHEN ca_other.header_code LIKE '16%' THEN 'Investing'
        WHEN ca_other.header_code LIKE '3%' THEN 'Financing'
        ELSE 'Operating'
    END AS category,
    tbl_cash.dr_amount AS inflow,
    tbl_cash.cr_amount AS outflow
FROM idil_transaction_bookingline tbl_cash
JOIN idil_transaction_booking tb ON tbl_cash.transaction_booking_id = tb.id
JOIN idil_chart_account ca_cash ON tbl_cash.account_number = ca_cash.id
JOIN idil_transaction_bookingline tbl_other ON tbl_other.transaction_booking_id = tb.id 
    AND tbl_other.id != tbl_cash.id
JOIN idil_chart_account ca_other ON tbl_other.account_number = ca_other.id
WHERE ca_cash.account_type IN ('cash', 'bank_transfer')
  AND ca_other.account_type NOT IN ('cash', 'bank_transfer')
ORDER BY tb.trx_date DESC;
```

### Expected Results

1. **All internal transfers excluded** (no rows where all accounts are cash)
2. **Revenue/Expense transactions → Operating**
3. **Fixed asset purchases/sales → Investing**
4. **Loan/equity transactions → Financing**

## Troubleshooting

### Issue: Transactions Misclassified

**Symptom:** Equipment purchase appears in Operating instead of Investing

**Solution:**
1. Check the `header_code` of your fixed asset accounts
2. Update classification rules if using different codes
3. Add account name keywords if needed

### Issue: Internal Transfers Still Appearing

**Symptom:** Cash transfers showing as both inflow and outflow

**Solution:**
1. Verify ALL accounts in the transaction are cash/bank type
2. Check if `account_type` field is set correctly
3. Review the `all_cash` logic in the code

### Issue: Empty Categories

**Symptom:** Investing or Financing sections have no transactions

**Solution:**
This is normal if your business:
- Has no fixed asset purchases (no investing)
- Has no loans or equity changes (no financing)

## Best Practices

1. **Maintain Consistent Account Codes**: Use a structured chart of accounts with consistent header codes
2. **Use Descriptive Account Names**: Include keywords like "equipment", "loan", "capital" in account names
3. **Regular Reconciliation**: Compare Cash Flow report with Balance Sheet cash changes
4. **Period Selection**: Use fiscal periods for meaningful comparisons

## References

- **Accounting Standards**: IAS 7 / SFAS 95 (Statement of Cash Flows)
- **Odoo ORM Documentation**: https://www.odoo.com/documentation/
- **Chart of Accounts Structure**: See `idil/models/chart_of_accounts.py`

## Version History

- **v1.0** (2025-11-24): Initial single-category implementation
- **v2.0** (2025-11-24): Three-category account-based classification
  - Added Operating/Investing/Financing separation
  - Implemented internal transfer exclusion
  - Account-based automatic classification

---

**Author**: Antigravity AI  
**Last Updated**: 2025-11-24  
**Module**: idil (BizCore ERP)
