# Manufacturing Commission System (Employees)

## 🎯 Overview
The Manufacturing Commission System manages commissions earned by **Employees** (Staff) from **Manufacturing Orders**. This system ensures that employees are paid their production commissions according to their preferred schedule (Daily or Monthly).

## ⚙️ Configuration

### 1. Employee Setup
Go to **Manufacturing Operations > Employees**.
Open an Employee profile and configure the **Commission Settings**:

- **Commission Payment Schedule**:
  - **Daily**: Commissions become payable on the same day as the production.
  - **Monthly**: Commissions become payable on a specific day of the month.
- **Payment Day of Month**: (Only for Monthly) The day (1-31) when commissions are due.

## 🔄 Workflow

### 1. Manufacturing Order Creation
When a Manufacturing Order is created and an employee is assigned:
1. The system calculates the commission amount based on the product's BOM configuration.
2. An **Employee Commission Record** is created (`idil.commission`).

### 2. Due Date Calculation
The system automatically calculates the `Due Date` for the commission:
- **Daily Schedule**: Due Date = Manufacturing Date.
- **Monthly Schedule**:
  - If Date < Payment Day: Due on the Payment Day of the **current month**.
  - If Date >= Payment Day: Due on the Payment Day of the **next month**.

### 3. Payment Process
1. Go to **Manufacturing Operations > Commissions Management > Commissions**.
2. Use the filter **"Payable Now"** to see commissions due today.
3. Select commissions and process payment (supports individual or bulk payment depending on configuration).
4. **Result**:
   - The commission is marked as **Paid**.
   - Accounting entries are generated (if configured).

## 📊 Models & Technical Details

### `idil.commission`
- Tracks the commission earned by the employee.
- **Key Fields**:
  - `employee_id`: The employee.
  - `manufacturing_order_id`: Link to production.
  - `due_date`: Calculated payment date.
  - `is_payable`: Boolean, true if `due_date <= today`.

### `idil.employee`
- Extended to include `commission_payment_schedule` and `commission_payment_day`.

## 💡 Key Differences from Sales Commission
- **Source**: Comes from Manufacturing Orders, not Sale Orders.
- **Beneficiary**: Paid to **Employees**, not Sales Personnel.
- **Accounting**: Typically treated as an expense/liability, whereas Sales Commission interacts with the Salesperson's receivable account.
