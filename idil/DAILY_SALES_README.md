# Daily Sales Report - User Guide

## Overview

The Daily Sales Report provides comprehensive sales analytics with flexible filtering options, allowing you to analyze sales performance by date, salesperson, products, payment methods, and more.

## Features

### **Multi-Dimensional Analysis**
- **Daily Summary**: Revenue, order count, average order value
- **Products Breakdown**: Which products were sold and how much
- **Payment Methods**: Cash, credit, and other payment method tracking
- **Salesperson Performance**: Individual salesperson metrics

### **Flexible Filtering**
- **Date Range**: Select any period for analysis
- **Salesperson Filter**: View all salespeople or filter by individual
- **Report Type**: Choose between Summary or Detailed view
- **Currency Display**: Show in USD, Shillings, or both

### **Multiple Export Formats**
- **PDF**: Professional formatted report for printing
- **Excel**: Multi-sheet workbook for data analysis

## How to Use

### **Accessing the Report**

1. Navigate to: **IDIL → Financial Reports → Daily Sales Report**
2. The report wizard will open

### **Setting Filters**

**Date Selection:**
- **Start Date**: First day of the period
- **End Date**: Last day of the period
- Example: `01/11/2025` to `25/11/2025`

**Salesperson Filter:**
- Leave **empty** for all salespeople
- Select a **specific salesperson** to view only their sales

**Report Type:**
- **Summary**: High-level totals per day (faster, compact)
- **Detailed**: Full breakdown with products, payments, and salespeople (comprehensive)

**Currency Display:**
- **USD Only**: All amounts in US Dollars
- **Shillings Only**: All amounts in Somali Shillings
- **Both Currencies**: Side-by-side comparison

### **Generating Reports**

**Option 1: PDF Report**
1. Set your filters
2. Click **"Generate PDF"**
3. Report opens in new tab for viewing/printing

**Option 2: Excel Export**
1. Set your filters
2. Click **"Export to Excel"**
3. File downloads automatically

## Report Sections

### **1. Daily Summary**

Shows aggregated metrics for each day:

| Column | Description |
|--------|-------------|
| **Date** | The sale date |
| **Orders** | Number of confirmed orders |
| **Revenue (USD)** | Total revenue converted to USD |
| **Revenue (Shillings)** | Total revenue in local currency |
| **Avg Order (USD)** | Average order value |

**Use Case:** Identify your best and worst sales days

---

### **2. Products Breakdown** (Detailed Mode Only)

Shows which products were sold each day:

| Column | Description |
|--------|-------------|
| **Product** | Product name |
| **Quantity** | Units sold |
| **Revenue (USD)** | Revenue from this product |
| **Revenue (Shillings)** | Revenue in local currency |

**Use Case:** Understand product demand patterns

---

### **3. Payment Methods** (Detailed Mode Only)

Shows how customers paid:

| Column | Description |
|--------|-------------|
| **Method** | Cash, Credit, etc. |
| **Transactions** | Number of payments |
| **Amount (USD)** | Total in USD |
| **Amount (Shillings)** | Total in local currency |

**Use Case:** Track cash flow and payment preferences

---

### **4. Salesperson Performance** (Detailed Mode Only)

Shows individual salesperson metrics:

| Column | Description |
|--------|-------------|
| **Salesperson** | Employee name |
| **Orders** | Number of sales made |
| **Revenue (USD)** | Total sales in USD |
| **Revenue (Shillings)** | Total sales in local currency |

**Use Case:** Evaluate team performance and set targets

**Note:** This section only appears when "All Salespeople" is selected (not filtered to one person)

---

### **5. Grand Totals**

Summary of the entire period:
- Total orders across all days
- Total revenue (in selected currency)
- Cumulative performance metrics

## Excel Export Structure

When you export to Excel, you get a workbook with **4 sheets**:

### **Sheet 1: Daily Summary**
All daily totals in one table

### **Sheet 2: Products**
Every product sold, every day, with quantities and revenue

### **Sheet 3: Payment Methods**
Payment method breakdown by day

### **Sheet 4: Salespeople**
Individual salesperson performance by day

**Benefits:**
✅ Sort and filter data your own way  
✅ Create pivot tables  
✅ Build custom charts  
✅ Compare periods side-by-side  

## Common Use Cases

### **Weekly Sales Review**
**Filters:**
- Date: Last 7 days
- Salesperson: All
- Type: Summary
- Currency: USD

**Result:** Quick overview of weekly performance

---

### **Month-End Report for Accounting**
**Filters:**
- Date: 01/11/2025 - 30/11/2025
- Salesperson: All
- Type: Detailed
- Currency: Both

**Output:** Excel export for detailed analysis

---

### **Individual Performance Review**
**Filters:**
- Date: This month
- Salesperson: John Doe
- Type: Detailed
- Currency: USD

**Result:** Complete view of John's sales activity

---

### **Product Demand Analysis**
**Filters:**
- Date: Last 30 days
- Type: Detailed
- Currency: USD

**Focus:** Products Breakdown section to see demand trends

## Understanding the Data

### **Currency Conversion**

All revenue is automatically converted to USD using the **exchange rate from the date of sale**.

**Example:**
```
Sale on Nov 1: 10,000 Shillings @ rate 1,050 = $9.52 USD
Sale on Nov 2: 10,000 Shillings @ rate 1,100 = $9.09 USD
```

This ensures historical accuracy even when exchange rates fluctuate.

### **What Counts as a "Confirmed Order"**

Only sales orders with `state = 'confirmed'` are included. Draft or cancelled orders are excluded.

### **Salesperson Assignment**

The report uses the `user_id` field from the sales order to determine which salesperson made the sale.

## Tips & Best Practices

### **Performance Tips**

1. **Use Summary Mode** when you just need daily totals (much faster)
2. **Limit date ranges** to 3 months or less for large datasets
3. **Export to Excel** for heavy data manipulation instead of regenerating PDFs

### **Recommended Reporting Schedule**

| Frequency | Purpose | Settings |
|-----------|---------|----------|
| **Daily** | Quick check | Yesterday's date, Summary, USD |
| **Weekly** | Team meeting | Last 7 days, Detailed, All Salespeople |
| **Monthly** | Accounting | Full month, Detailed, Both currencies, Excel |
| **Quarterly** | Performance review | 3 months, Summary, By salesperson |

## Troubleshooting

### **Issue: Report shows no data**

**Possible Causes:**
1. No confirmed orders in the date range
2. Salesperson filter set incorrectly
3. Orders not yet confirmed (still in draft)

**Solution:** 
- Check if orders exist for the period
- Verify order state is "confirmed"
- Try "All Salespeople" filter

---

### **Issue: Excel file won't download**

**Possible Cause:** xlsxwriter library not installed

**Solution:** 
```bash
pip install xlsxwriter
```

---

### **Issue: Currency amounts seem wrong**

**Check:**
- Is the exchange rate set correctly on each sale order?
- Is the `rate` field populated?

**Debug Query:**
```sql
SELECT order_date, reffno, rate, grand_total
FROM idil_sale_order
WHERE state = 'confirmed'
AND (rate IS NULL OR rate = 0)
LIMIT 10;
```

If this returns rows, those orders have missing exchange rates.

---

### **Issue: Salesperson section is empty**

This is normal if:
- You filtered by a specific salesperson (section only shows for "All")
- Orders don't have `user_id` assigned

**Solution:** Ensure salespeople are assigned to orders during creation

## Data Sources

The report pulls from:
- `idil_sale_order` - Order headers with totals and dates
- `idil_sale_order_line` - Individual line items for products
- `my_product_product` - Product names
- `res_users` - Salesperson names

## Comparison with Other Reports

| Feature | Daily Sales | Product Profitability | Cash Flow |
|---------|-------------|----------------------|-----------|
| **Focus** | Sales activity | Product margins | Cash movement |
| **Period** | Daily breakdown | Total period | Account categories |
| **Products** | Quantities sold | Profit per product | N/A |
| **Costs** | No | Yes | No |
| **Payments** | Yes | No | No |

**Use together for complete business insight!**

## Advanced: SQL Behind the Scenes

For technical users, here's what the report queries:

### Daily Summary Query
```sql
SELECT 
    DATE(so.order_date) as sale_date,
    COUNT(DISTINCT so.id) as order_count,
    SUM(so.grand_total / NULLIF(so.rate, 0)) as revenue_usd,
    SUM(so.grand_total) as revenue_shillings
FROM idil_sale_order so
WHERE so.state = 'confirmed'
  AND so.order_date BETWEEN :start AND :end
GROUP BY DATE(so.order_date)
```

The report uses **4 optimized SQL queries** to fetch all data in one pass, ensuring fast performance.

## Frequently Asked Questions

**Q: Can I schedule this report to run automatically?**  
A: Not currently, but you can use Odoo's scheduled actions module to automate it.

**Q: Can I customize the columns shown?**  
A: Yes, by modifying the report template in `reports/report_daily_sales.xml`.

**Q: Does this work with multiple companies?**  
A: Yes, use the Company filter in the wizard (visible with multi-company enabled).

**Q: Can I export to formats other than PDF/Excel?**  
A: You can extend the wizard to add CSV export if needed.

**Q: How far back can I go?**  
A: No limit, but very large date ranges will take longer to generate.

## Version History

- **v1.0** (2025-11-25): Initial implementation
  - Daily summary with revenue and order count
  - Products, payment methods, and salesperson breakdowns
  - PDF and Excel export
  - Multi-currency support
  - Summary and detailed view modes

---

**Module**: idil (BizCore ERP)  
**Author**: Antigravity AI  
**Last Updated**: 2025-11-25
