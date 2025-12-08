# Product Inventory Summary Report

## Overview

The **Product Inventory Summary Report** provides a comprehensive view of product inventory status including production, stock levels, disposals, and sales data for a specified period.

---

## Location

**Menu Path:** `Reports → Product Inventory Summary`

---

## Report Columns

| Column | Description |
|--------|-------------|
| **Product** | Product name |
| **Prod Qty** | Quantity produced from Manufacturing Orders |
| **Total Qty** | Total incoming quantity (from all sources) |
| **Unit Cost** | Product unit cost (USD) |
| **Total Cost** | Total inventory cost (Qty × Unit Cost) |
| **Disposed** | Quantity disposed/wasted |
| **Ready Qty** | Current available stock quantity |
| **Sold Qty** | Quantity sold during the period |
| **Sold Cost** | Cost of goods sold (Sold Qty × Unit Cost) |
| **Sales Price** | Product sales price |

---

## Filters

| Filter | Description |
|--------|-------------|
| **Start Date** | Beginning of report period (required) |
| **End Date** | End of report period (required) |
| **Company** | Filter by company (defaults to current) |
| **Product** | Optional - filter for specific product |

---

## Usage

1. Navigate to `Reports → Product Inventory Summary`
2. Set **Start Date** and **End Date**
3. Optionally select a specific **Product**
4. Click **Generate PDF Report**
5. PDF downloads automatically

---

## Data Sources

| Data Point | Source Model |
|------------|--------------|
| Production Qty | `idil.manufacturing.order` |
| Stock Movements | `idil.product.movement` |
| Sales Data | `idil.sale.order.line` |
| Current Stock | `my_product.product.stock_quantity` |
| Cost/Price | `my_product.product` |

---

## Technical Details

**Files:**
- `models/report_product_inventory_summary.py` - Wizard and PDF generation
- `views/report_product_inventory_summary.xml` - Form view and menu

**Model:** `idil.product.inventory.summary.wizard`

**Dependencies:** ReportLab library (for PDF generation)

---

## Sample Output

```
┌─────────┬──────────┬──────────┬──────────┬───────────┬──────────┬──────────┬──────────┬───────────┬───────────┐
│ Product │ Prod Qty │ Total Qty│ Unit Cost│ Total Cost│ Disposed │ Ready Qty│ Sold Qty │ Sold Cost │ Sales Price│
├─────────┼──────────┼──────────┼──────────┼───────────┼──────────┼──────────┼──────────┼───────────┼───────────┤
│ F1      │    50.00 │    50.00 │     0.04 │      2.12 │     0.00 │    50.00 │   100.00 │      4.24 │   1,500.00│
│ F2      │   150.00 │   150.00 │     0.03 │      4.95 │     0.00 │   150.00 │    30.00 │      0.99 │   2,000.00│
├─────────┼──────────┼──────────┼──────────┼───────────┼──────────┼──────────┼──────────┼───────────┼───────────┤
│ TOTALS  │   200.00 │   200.00 │          │      7.07 │     0.00 │   200.00 │   130.00 │      5.23 │           │
└─────────┴──────────┴──────────┴──────────┴───────────┴──────────┴──────────┴──────────┴───────────┴───────────┘
```
