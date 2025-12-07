# Sales Commission System (Salespeople)

## 🎯 Overview
The Sales Commission System manages commissions earned by **Sales Personnel** from **Sale Orders**. Unlike the previous system where commissions were immediately deducted from the salesperson's account, this new system **defers** the commission payment based on a configured schedule (Daily or Monthly).

## ⚙️ Configuration

### 1. Salesperson Setup
Go to **Sales Operations > General Operations > Sales Team List**.
Open a Salesperson profile and configure the **Commission Settings**:

- **Commission Payment Schedule**:
  - **Daily**: Commissions become payable on the same day as the sale.
  - **Monthly**: Commissions become payable on a specific day of the month.
- **Payment Day of Month**: (Only for Monthly) The day (1-31) when commissions are due.

## 🔄 Workflow

### 1. Sale Order Confirmationsg
When a Sale Order is confirmed:
1. **Sales Amount** and **Discount** are posted **immediately** to the salesperson's transaction history (increasing their debt/receivable).
2. **Commission** is **NOT** posted immediately. Instead, a **Sales Commission Record** is created in the new system.

### 2. Due Date Calculation
The system automatically calculates the `Due Date` for the commission:
- **Daily Schedule**: Due Date = Order Date.
- **Monthly Schedule**:
  - If Order Date < Payment Day: Due on the Payment Day of the **current month**.
  - If Order Date >= Payment Day: Due on the Payment Day of the **next month**.

### 3. Payment Process
1. Go to **Sales Operations > Commissions > Payable Now**.
2. This view shows all commissions that are due today or earlier (Green rows).
3. Select a commission and click **Pay Commission**.
4. Choose the **Cash/Bank Account** to pay from.
5. **Result**:
   - A transaction is created in the salesperson's account (Credit/In), reducing their balance.
   - The commission status changes to **Paid**.

## 📊 Models & Technical Details

### `idil.sales.commission`
- Tracks the individual commission record.
- **Key Fields**:
  - `sale_order_id`: Link to the source sale.
  - `sales_person_id`: The salesperson.
  - `due_date`: Calculated payment date.
  - `is_payable`: Boolean, true if `due_date <= today`.
  - `payment_status`: Pending, Partial Paid, Paid.

### `idil.sales.commission.payment`
- Tracks the actual payments made against a commission.
- Creates the corresponding `idil.salesperson.transaction` entry.

### Changes in `idil.sale.order`
- The `button_confirm` method now calls `_create_sales_commission_record()` instead of posting the commission transaction immediately.
