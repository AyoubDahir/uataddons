# Operational Reports for Low-Level Managers

This document describes the operational reports available in the IDIL module, designed to help low-level managers run daily operations efficiently.

## Location

All reports are accessible via: **IDIL → Reports → Operational Reports**

---

## 1. Daily Cash Collection Report

**Purpose:** End-of-day cash reconciliation and collection tracking.

**Menu Path:** Reports → Operational Reports → Daily Cash Collection

### Filters
| Field | Description |
|-------|-------------|
| Date | Select the date to report on (default: today) |
| Salesperson | Filter by specific salesperson (optional) |
| Payment Account | Filter by payment method - cash, bank, etc. (optional) |

### Report Sections
- **Summary Cards:** Total Sales, Total Collected, Collection Rate %
- **Collection by Salesperson:** Breakdown of receipts, sales, and collections per salesperson
- **Collection by Payment Method:** Breakdown by cash, bank transfer, etc.

### Use Cases
- Daily cash drawer reconciliation
- Identify collection gaps
- Track salesperson performance

---

## 2. Low Stock Alert Report

**Purpose:** Identify items that need restocking to prevent stockouts.

**Menu Path:** Reports → Operational Reports → Low Stock Alert

### Filters
| Field | Description |
|-------|-------------|
| Stock Threshold | Show items with quantity below this number (default: 10) |
| Category | Filter by item category (optional) |
| Include Zero Stock | Include items with zero quantity (default: yes) |

### Report Sections
- **Summary Cards:** Critical (zero stock), Low Stock count, Total Items, Restock Value
- **Items Table:** Item name, category, current qty, unit, cost, shortage, restock value, status

### Status Indicators
- 🔴 **Critical** - Zero stock, immediate action required
- 🟡 **Low** - Below threshold, schedule reorder

### Use Cases
- Daily inventory check
- Generate purchase orders
- Prevent production delays

---

## 3. Expiring Inventory Report

**Purpose:** Track items approaching or past their expiration date to minimize wastage.

**Menu Path:** Reports → Operational Reports → Expiring Inventory

### Filters
| Field | Description |
|-------|-------------|
| Days Ahead | Show items expiring within X days (default: 30) |
| Category | Filter by item category (optional) |
| Include Already Expired | Include past-due items (default: yes) |

### Report Sections
- **Summary Cards:** Expired count, Critical (≤7 days), Warning (≤30 days), Value at Risk
- **Items Table:** Item, category, expiration date, days left, quantity, cost, value at risk, status

### Status Indicators
- 🔴 **Expired** - Already past expiration date
- 🟠 **Critical** - Expires within 7 days
- 🟡 **Warning** - Expires within 30 days
- 🟢 **Upcoming** - Expires after 30 days

### Use Cases
- Daily FIFO (First In, First Out) checks
- Plan promotions for near-expiry items
- Calculate potential wastage losses
- Food safety compliance

---

## 4. Pending Orders Report

**Purpose:** Track unfulfilled orders to ensure timely processing.

**Menu Path:** Reports → Operational Reports → Pending Orders

### Filters
| Field | Description |
|-------|-------------|
| Order Type | All, Sales Orders, Customer Orders, or Salesperson Place Orders |
| Salesperson | Filter by salesperson (optional) |
| Customer | Filter by customer (optional) |
| Older Than (Days) | Only show orders older than X days (default: 0 = all) |

### Report Sections
- **Summary Cards:** Pending Orders count, Total Value, Average Age, Old Orders (>7 days)
- **Orders Table:** Type, reference, date, salesperson, customer, total, age in days, status

### Age Indicators
- **Red bold** - Orders older than 7 days (requires attention)
- **Orange** - Orders 4-7 days old
- **Normal** - Orders 0-3 days old

### Use Cases
- Daily order fulfillment prioritization
- Identify bottlenecks in order processing
- Follow up on stale orders
- Workload planning

---

## 5. Customer Outstanding Balance Report

**Purpose:** Accounts receivable aging report for collection follow-up.

**Menu Path:** Reports → Operational Reports → Customer Outstanding Balance

### Filters
| Field | Description |
|-------|-------------|
| As of Date | Report date for aging calculation (default: today) |
| Customer | Filter by specific customer (optional) |
| Salesperson | Filter by salesperson (optional) |
| Minimum Balance | Only show balances above this amount (default: 0) |
| Include Salesperson AR | Include salesperson receivables (default: yes) |

### Report Sections
- **Aging Buckets Summary:** 0-30 days, 31-60 days, 61-90 days, 90+ days, Total Outstanding
- **Customer Table:** Type, name, contact, receipt count, aging buckets, total outstanding

### Aging Buckets
| Bucket | Description | Priority |
|--------|-------------|----------|
| 0-30 days | Current receivables | Normal |
| 31-60 days | Slightly overdue | Monitor |
| 61-90 days | Significantly overdue | Follow up |
| 90+ days | Severely overdue | **Urgent action** |

### Use Cases
- Daily collection calls
- Credit limit decisions
- Cash flow forecasting
- Identify problem accounts

---

## Technical Information

### Files Structure

```
idil/
├── models/
│   ├── report_daily_cash_collection.py
│   ├── report_low_stock_alert.py
│   ├── report_expiring_inventory.py
│   ├── report_pending_orders.py
│   └── report_customer_outstanding.py
├── views/
│   ├── report_daily_cash_collection.xml
│   ├── report_low_stock_alert.xml
│   ├── report_expiring_inventory.xml
│   ├── report_pending_orders.xml
│   └── report_customer_outstanding.xml
└── docs/
    └── OPERATIONAL_REPORTS_README.md
```

### Security

All reports require `base.group_user` access. Reports are accessible to all internal users by default.

### Output Format

All reports generate **PDF documents** using QWeb templates, suitable for:
- Printing
- Email attachments
- Archiving

---

## Installation

1. Update the module: `-u idil`
2. Access via: **IDIL → Reports → Operational Reports**

---

## Support

For issues or feature requests, contact the development team.
