# Daily Sales Report - User Guide

## Overview

The Daily Sales Report provides comprehensive sales analytics with flexible filtering options, allowing you to analyze sales performance by date, sales source (Salesperson, Customer, Staff), products, payment methods, and more. It unifies data from all sales channels into a single view.

## Features

### **Multi-Dimensional Analysis**
- **Daily Summary**: Revenue, order count, average order value
- **Products Breakdown**: Which products were sold and how much
- **Payment Methods**: Cash, credit, and other payment method tracking
- **Sales Performance**: Breakdown by Salesperson, Customer Sales, or Staff Sales

### **Flexible Filtering**
- **Date Range**: Select any period for analysis
- **Sales Source Filter**: Filter by **All Sales**, **Salesperson Sales**, **Customer Sales**, or **Staff Sales**
- **Salesperson Filter**: View specific salesperson (only available when "Salesperson Sales" is selected)
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

**Sales Source Filter (NEW):**
- **All Sales**: Combines data from Salespeople, Customers, and Staff
- **Salesperson Sales**: Only sales made by sales personnel
- **Customer Sales**: Direct customer sales orders
- **Staff Sales**: Internal staff sales

**Salesperson Filter:**
- Only appears when **Salesperson Sales** is selected above
- Select a **specific salesperson** to view only their sales

**Report Type:**
- **Summary**: High-level totals per day (faster, compact)
- **Detailed**: Full breakdown with products, payments, and performance (comprehensive)

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

### **4. Sales Performance** (Detailed Mode Only)

Shows performance breakdown by source:

| Column | Description |
|--------|-------------|
| **Salesperson/Source** | Employee name, "Customer Sales", or "Staff Sales" |
| **Orders** | Number of sales made |
| **Revenue (USD)** | Total sales in USD |
| **Revenue (Shillings)** | Total sales in local currency |

**Use Case:** Compare performance across different sales channels

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
Individual salesperson and sales source performance by day

**Benefits:**
✅ Sort and filter data your own way  
✅ Create pivot tables  
✅ Build custom charts  
✅ Compare periods side-by-side  

## Common Use Cases

### **Weekly Sales Review**
**Filters:**
- Date: Last 7 days
- Source: All Sales
- Type: Summary
- Currency: USD

**Result:** Quick overview of total weekly performance across all channels

---

### **Salesperson Performance Review**
**Filters:**
- Date: This month
- Source: Salesperson Sales
- Salesperson: John Doe
- Type: Detailed
- Currency: USD

**Result:** Complete view of John's sales activity

---

### **Direct Customer Sales Analysis**
**Filters:**
- Date: Last 30 days
- Source: Customer Sales
- Type: Detailed
- Currency: USD

**Result:** Analyze sales made directly to customers (bypassing salespeople)

---

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

The report uses the `user_id` field from the sales order to determine which salesperson made the sale. For Customer and Staff sales, they are grouped under their respective categories.

## Tips & Best Practices

### **Performance Tips**

1. **Use Summary Mode** when you just need daily totals (much faster)
2. **Limit date ranges** to 3 months or less for large datasets
3. **Export to Excel** for heavy data manipulation instead of regenerating PDFs

### **Recommended Reporting Schedule**

| Frequency | Purpose | Settings |
|-----------|---------|----------|
| **Daily** | Quick check | Yesterday's date, Summary, USD |
| **Weekly** | Team meeting | Last 7 days, Detailed, All Sales |
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
- Try "All Sales" filter

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
- `idil_sale_order` - Salesperson Sales
- `idil_customer_sale_order` - Customer Sales
- `idil_staff_sales` - Staff Sales
- `idil_sale_order_line` / `idil_customer_sale_order_line` / `idil_staff_sales_line` - Product Lines
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
    DATE(sale_date) as sale_date,
    COUNT(id) as order_count,
    SUM(amount_usd) as revenue_usd,
    SUM(amount_shillings) as revenue_shillings
FROM (
    SELECT ... FROM idil_sale_order
    UNION ALL
    SELECT ... FROM idil_customer_sale_order
    UNION ALL
    SELECT ... FROM idil_staff_sales
) as combined_sales
WHERE ...
GROUP BY DATE(sale_date)
```

The report uses **UNION ALL** queries to aggregate data from all three sales tables in one pass, ensuring fast performance and complete coverage.

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

- **v1.1** (2025-11-26): Unified Report Update
  - Added **Sales Source** filter (Salesperson, Customer, Staff)
  - Unified data from `idil_sale_order`, `idil_customer_sale_order`, and `idil_staff_sales`
  - Updated performance section to show all sales sources
- **v1.0** (2025-11-25): Initial implementation
  - Daily summary with revenue and order count
  - Products, payment methods, and salesperson breakdowns
  - PDF and Excel export
  - Multi-currency support
  - Summary and detailed view modes

---

**Module**: idil (BizCore ERP)  
**Author**: Antigravity AI  
**Last Updated**: 2025-11-26
