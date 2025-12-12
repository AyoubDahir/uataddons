# Sales Commission Module Update

## Overview
This document describes the fixes and improvements made to the sales commission module to address overpayment bugs and ensure proper accounting integration.

## Issues Fixed

### 1. Commission Status Not Updating After Payment
**Problem**: After bulk payment confirmation, commission records still showed "pending" status, and the same amount was still displayed as due when creating a new bulk payment.

**Root Cause**: 
- Duplicate `_compute_commission_paid` method definitions conflicted with each other
- The `_update_commission_balance` method was writing directly to computed stored fields instead of triggering proper recomputation
- ORM cache was returning stale data

**Solution**:
- Removed duplicate compute methods
- Updated `_update_commission_balance` to use `invalidate_recordset()` and `flush_recordset()` to properly trigger recomputation
- Changed `_compute_commission_paid` to use SQL for fresh totals
- Updated `_compute_due_commission` in bulk payment to use SQL
- Updated onchange method to use SQL for fresh commission data

### 2. Transaction Booking Missing Required Rate Field
**Problem**: The `pay_commission` method created a transaction booking without the required `rate` field, causing the booking creation to fail silently. This meant no accounting entries were being created.

**Solution**: Added the `rate` field to the transaction booking creation, using the rate from the associated sale order:
```python
rate = self.sale_order_id.rate if self.sale_order_id and self.sale_order_id.rate else 1.0
booking = self.env["idil.transaction_booking"].create({
    ...
    "rate": rate,
    "sale_order_id": self.sale_order_id.id if self.sale_order_id else False,
})
```

### 3. Overpayment Bug
**Problem**: Users could pay commissions multiple times, exceeding the total commission amount. The system allowed overpayment because validation used cached ORM data that could become stale.

**Solution**: Implemented SQL-level locking and validation:
- Added `SELECT FOR UPDATE NOWAIT` to prevent race conditions
- Replaced ORM queries with direct SQL for fresh totals
- Applied fixes to:
  - `pay_commission()` method
  - `SalesCommissionPayment.create()`
  - `_check_amount_not_exceed_remaining` constraint
  - Bulk payment `action_confirm_payment()`
  - Bulk payment `_check_amount_to_pay` constraint

### 2. Daily Schedule Commission Payments
**Problem**: Daily schedule commissions were being tracked for payment even though the salesperson already receives their commission at the time of sale (netted from receivables).

**Solution**: Added validation to block payment attempts for daily schedule commissions:
```python
if self.payment_schedule == 'daily':
    raise ValidationError(
        "Daily schedule commissions are not payable. "
        "The salesperson already received their commission at the time of sale "
        "(netted from receivables)."
    )
```

### 3. Trial Balance Not Reflecting Payments
**Problem**: Commission payments were not properly linked to accounting entries, causing them not to appear in the chart of accounts and trial balance reports.

**Solution**: 
- Added `transaction_booking_id` field to `SalesCommissionPayment` model
- Updated payment process to link the transaction booking to payment records

## Accounting Entries

### Monthly Schedule (Deferred Commission)

#### At Time of Sale:
| SL | Account | Debit | Credit |
|----|---------|-------|--------|
| 1 | COGS Expense | ✓ | |
| 2 | Inventory Asset | | ✓ |
| 3 | Accounts Receivable | ✓ | |
| 4 | Sales Revenue | | ✓ |
| 5 | Commission Expense | ✓ | |
| 6 | Commission Payable (A/P) | | ✓ |

#### At Time of Payment:
| SL | Account | Debit | Credit |
|----|---------|-------|--------|
| 1 | Commission Payable (A/P) | ✓ | |
| 2 | Cash/Bank | | ✓ |

### Daily Schedule (Immediate Commission)

#### At Time of Sale:
| SL | Account | Debit | Credit |
|----|---------|-------|--------|
| 1 | COGS Expense | ✓ | |
| 2 | Inventory Asset | | ✓ |
| 3 | Accounts Receivable (net of commission) | ✓ | |
| 4 | Sales Discount | ✓ | |
| 5 | Commission Expense | ✓ | |
| 6 | Sales Revenue | | ✓ |

**Note**: No payment entry needed for daily schedule - the salesperson already keeps their commission at the time of sale.

## Files Modified

### `idil/models/sales_commission.py`
- `pay_commission()`: Added daily schedule block, SQL locking, and fresh data validation
- `SalesCommissionPayment.create()`: Added SQL-level validation and daily schedule block
- `_check_amount_not_exceed_remaining()`: Updated to use SQL for fresh totals
- Added `transaction_booking_id` field to link payments to accounting entries

### `idil/models/sales_commission_bulk_payment.py`
- `action_confirm_payment()`: Added SQL-level validation with monthly schedule filter
- `_check_amount_to_pay()`: Updated to use SQL for fresh totals

## Configuration Requirements

### For Monthly Schedule Salesperson:
1. Set `commission_payment_schedule` to "monthly"
2. Configure `commission_payable_account_id` (required liability account)
3. Set `commission_payment_day` (1-31)

### For Daily Schedule Salesperson:
1. Set `commission_payment_schedule` to "daily"
2. Commission is automatically netted from receivables at sale time
3. **No separate payment needed**

## Usage Notes

### Bulk Payment
- Only available for **monthly schedule** salespersons (enforced by domain filter)
- Validates total amount against fresh database totals before confirming
- Automatically allocates payments across unpaid commissions (oldest first)

### Individual Payment
- Daily schedule commissions will show an error if payment is attempted
- Monthly schedule commissions create proper DR/CR accounting entries
- All payments are linked to transaction bookings for trial balance tracking

## Testing Checklist

- [ ] Verify overpayment is blocked for individual commission payment
- [ ] Verify overpayment is blocked for bulk commission payment
- [ ] Verify daily schedule commissions cannot be paid
- [ ] Verify monthly schedule payments create proper accounting entries
- [ ] Verify commission payments appear in trial balance report
- [ ] Verify commission payable account is debited on payment
- [ ] Verify cash account is credited on payment

## Technical Details

### Cache Invalidation Pattern
All methods that modify commission payments now follow this pattern:
```python
# Invalidate cache to force recomputation
commission.invalidate_recordset(
    ['commission_paid', 'commission_remaining', 'payment_status']
)
# Trigger recomputation
commission._compute_commission_paid()
commission._compute_commission_remaining()
commission._compute_payment_status()
# Flush to database
commission.flush_recordset(
    ['commission_paid', 'commission_remaining', 'payment_status']
)
```

### SQL-Based Fresh Data Pattern
All computed fields and validations now use SQL to bypass ORM cache:
```python
self.env.cr.execute(
    """
    SELECT COALESCE(SUM(amount), 0)
    FROM idil_sales_commission_payment
    WHERE commission_id = %s
    """,
    (commission.id,)
)
fresh_total = self.env.cr.fetchone()[0]
```

## Version
- **Date**: December 12, 2025
- **Author**: Cascade AI Assistant
- **Update 2**: Fixed commission status not updating after bulk payment confirmation
- **Update 3**: Fixed missing `rate` field in transaction booking creation causing accounting entries to fail
