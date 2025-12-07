# Sales Discount System (Salespeople)

## 🎯 Overview
The Sales Discount System manages discounts given by **Sales Personnel** on **Sale Orders**. Similar to commissions, this system **defers** the processing of discounts based on a configured schedule (Daily or Monthly), instead of immediately posting them to the salesperson's transaction history.

## ⚙️ Configuration

### 1. Salesperson Setup
Go to **Sales Operations > General Operations > Sales Team List**.
Open a Salesperson profile and configure the **Discount Payment Settings** (separate from Commission settings):

- **Discount Payment Schedule**:
  - **Daily**: Discounts are processed on the same day as the sale.
  - **Monthly**: Discounts are processed on a specific day of the month.
- **Discount Payment Day**: (Only for Monthly) The day (1-31) when discounts are processed.

## 🔄 Workflow

### 1. Sale Order Confirmation
When a Sale Order is confirmed:
1. **Sales Amount** is posted **immediately** to the salesperson's transaction history.
2. **Discount** is **NOT** posted immediately. Instead, a **Sales Discount Record** is created.

### 2. Due Date Calculationss
The system automatically calculates the `Due Date` for the discount processing:
- **Daily Schedule**: Due Date = Order Date.
- **Monthly Schedule**:
  - If Order Date < Payment Day: Due on the Payment Day of the **current month**.
  - If Order Date >= Payment Day: Due on the Payment Day of the **next month**.

### 3. Processing Workflow
1. Go to **Sales Operations > Discounts > Processable Now**.
2. This view shows all discounts that are due for processing (Green rows).
3. Select a discount and click **Process Discount**.
4. **Result**:
   - A transaction is created in the salesperson's account (Out), reducing their balance (or increasing debt depending on perspective).
   - The discount status changes to **Processed**.

## 📊 Models & Technical Details

### `idil.sales.discount`
- Tracks the individual discount record.
- **Key Fields**:
  - `sale_order_id`: Link to the source sale.
  - `sales_person_id`: The salesperson.
  - `due_date`: Calculated processing date.
  - `is_payable`: Boolean, true if `due_date <= today`.
  - `state`: Pending, Partial, Processed.

### `idil.sales.discount.process`
- Tracks the processing events.
- Creates the corresponding `idil.salesperson.transaction` entry.

### Changes in `idil.sale.order`
- The `button_confirm` method now calls `_create_sales_discount_record()` instead of posting the discount transaction immediately.
