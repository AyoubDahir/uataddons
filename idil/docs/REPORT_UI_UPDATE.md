# Report UI/UX Update Documentation

## Overview

All PDF reports in the IDIL module have been updated to use a consistent, modern design template matching the Cash Flow Statement report style. This update focuses on **UI/UX improvements only** - no changes were made to the underlying business logic or data calculations.

## Design Standards

### Color Palette

| Element | Color Code | Usage |
|---------|------------|-------|
| Primary Header | `#1a237e` | Report title bar, total rows |
| Secondary Header | `#3949ab` | Header border accent |
| Section Headers | `#e8eaf6` | Section title backgrounds |
| Light Background | `#f5f5f5` | Table headers, filter bars |
| Accent Blue | `#5c6bc0` | Subheader text, counts |
| Success Green | `#2e7d32` | Positive amounts, totals |
| Warning Orange | `#ef6c00` | Warning status, aging 31-60 |
| Danger Red | `#c62828` | Critical status, overdue |
| Text Primary | `#424242` | Main text content |
| Text Secondary | `#757575` | Secondary labels |
| Border Light | `#eeeeee` | Table row borders |

### Typography

- **Font Family**: 'Segoe UI', Arial, sans-serif
- **Header Title**: 24px, bold, white
- **Section Headers**: 12px, bold, primary blue
- **Table Headers**: 10-11px, bold, dark gray
- **Body Text**: 11px, normal weight
- **Footer Note**: 10px, italic, gray

### Layout Components

1. **Report Header**
   - Dark blue background (#1a237e)
   - Report title in white
   - Company name
   - Report date/period
   - 4px accent border at bottom

2. **Filter Summary Bar**
   - Light gray background (#f5f5f5)
   - Shows applied filters
   - 4px border radius

3. **Section Headers**
   - Light blue background (#e8eaf6)
   - Arrow indicator (►)
   - Bold uppercase text

4. **Data Tables**
   - 2px solid bottom border on headers
   - 1px light borders on rows
   - Alternating row styling where applicable

5. **Total Rows**
   - Dark blue background (#1a237e)
   - White text
   - Bold, larger font

6. **Status Badges**
   - Colored background with matching text
   - 3px border radius
   - 10px font size

7. **Footer Note**
   - Right-aligned
   - Italic style
   - Currency indication

## Updated Reports

### Financial Reports

| Report | File Location |
|--------|---------------|
| Cash Flow Statement | `reports/report_cashflow.xml` |
| Customer Outstanding Balance | `views/report_customer_outstanding.xml` |
| Balance Sheet | `views/report_balance_sheet.xml` |
| Income Statement | `views/report_income_statement.xml` |
| Daily Cash Collection | `views/report_daily_cash_collection.xml` |

### Sales Reports

| Report | File Location |
|--------|---------------|
| Daily Sales | `reports/report_daily_sales.xml` |
| Pending Orders | `views/report_pending_orders.xml` |

### Inventory Reports

| Report | File Location |
|--------|---------------|
| Expiring Inventory | `views/report_expiring_inventory.xml` |
| Low Stock Alert | `views/report_low_stock_alert.xml` |
| Kitchen Quantity | `views/report_kitchen_quantity.xml` |

## Template Structure

```xml
<template id="report_example_template">
    <t t-call="web.html_container">
        <t t-call="web.external_layout">
            <div class="page" style="font-family: 'Segoe UI', Arial, sans-serif;">
                
                <!-- Report Header -->
                <div style="background-color: #1a237e; color: white; padding: 20px; margin-bottom: 25px; border-bottom: 4px solid #3949ab;">
                    <h1 style="font-size: 24px; font-weight: bold; margin: 0 0 8px 0; color: white;">Report Title</h1>
                    <div style="font-size: 16px; color: white; margin-bottom: 5px;">Company Name</div>
                    <div style="font-size: 12px; color: #c5cae9;">
                        Date: <strong style="color: white;">2024-01-01</strong>
                    </div>
                </div>

                <!-- Filter Summary -->
                <div style="background-color: #f5f5f5; padding: 12px 15px; margin-bottom: 20px; border-radius: 4px; font-size: 11px;">
                    <strong>Filters:</strong>
                    Filter1: <span style="color: #1a237e;">Value</span>
                </div>

                <!-- Summary Table -->
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 25px; font-size: 11px;">
                    <thead>
                        <tr style="background-color: #f5f5f5;">
                            <th style="border-bottom: 2px solid #1a237e; padding: 12px 10px;">Column</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr style="background-color: #e8eaf6;">
                            <td colspan="2" style="padding: 12px 10px; font-weight: bold; color: #1a237e;">
                                ► SECTION HEADER
                            </td>
                        </tr>
                        <!-- Data rows -->
                        <tr style="background-color: #1a237e;">
                            <td style="padding: 15px 10px; font-weight: bold; color: white;">
                                TOTAL
                            </td>
                        </tr>
                    </tbody>
                </table>

                <!-- Footer Note -->
                <div style="text-align: right; font-size: 10px; color: #757575; margin-top: 15px; font-style: italic;">
                    All amounts are expressed in United States Dollars (USD)
                </div>
            </div>
        </t>
    </t>
</template>
```

## Reports Without QWeb Templates

The following reports generate PDFs/Excel directly from Python code and do not have QWeb templates:

- Account Statements (`report_account_statements.xml`)
- HRM Salary Reports (`report_hrm_salary.xml`, `report_hrm_salary_department.xml`)
- Product Profitability (`report_productprofitability.xml`)
- Sales Summary by Person (`report_sales_summary_by_person.xml`)
- Product Inventory Summary (`report_product_inventory_summary.xml`)
- Item Summary by Vendor (`report_item_summary_by_vendor.xml`)

## Implementation Notes

1. **No Logic Changes**: All updates are CSS/HTML styling only. Business logic remains unchanged.

2. **External Layout**: All reports use `web.external_layout` for consistent header/footer with company branding.

3. **Responsive Design**: Tables use 100% width for proper PDF rendering.

4. **Currency Display**: All monetary values show currency symbols where applicable.

5. **Color Accessibility**: High contrast colors used for readability.

## Deployment

After making changes, restart the Odoo server or upgrade the module:

```bash
# Restart Odoo service
sudo systemctl restart odoo

# Or upgrade the module
./odoo-bin -u idil -d your_database
```

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2024-12-16 | 1.0 | Initial UI/UX update for all reports |

---

*This documentation was created as part of the IDIL module report standardization project.*
