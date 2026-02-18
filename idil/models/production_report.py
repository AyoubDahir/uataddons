from collections import defaultdict
from odoo import models, fields, api, tools
from datetime import datetime, time, timedelta


class IdilProductionReportWizard(models.TransientModel):
    _name = "idil.production.report.wizard"
    _description = "Production Report Wizard"

    date_from = fields.Date(
        string="Date From", required=True, default=fields.Date.context_today
    )
    date_to = fields.Date(
        string="Date To", required=True, default=fields.Date.context_today
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )

    product_ids = fields.Many2many("my_product.product", string="Products")
    status_draft = fields.Boolean(string="Include Draft", default=False)
    status_confirmed = fields.Boolean(string="Include Confirmed", default=True)
    status_in_progress = fields.Boolean(string="Include In Progress", default=True)
    status_done = fields.Boolean(string="Include Done", default=True)
    kpi_html = fields.Html(string="Executive Summary", readonly=True)
    insights_html = fields.Html(string="AI Insights", readonly=True)
    order_ids = fields.Many2many(
        "idil.manufacturing.order", string="Included MOs", readonly=True
    )

    # New Analysis Tabs
    commission_html = fields.Html(string="Commission Analysis", readonly=True)
    tfg_html = fields.Html(string="TFG Analysis", readonly=True)
    accounting_html = fields.Html(string="Accounting Summary", readonly=True)
    comparison_html = fields.Html(string="Comparisons", readonly=True)
    graphs_html = fields.Html(string="Charts & Trends", readonly=True, sanitize=False)
    extra_kpi_html = fields.Html(string="Extra KPIs", readonly=True)

    def action_refresh(self):
        """Manually trigger the compute methods and reload the view"""
        self._compute_all()
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def _compute_all(self):
        self._compute_orders()
        self._compute_kpi_html()
        self._compute_insights()
        self._compute_commission_html()
        self._compute_tfg_html()
        self._compute_accounting_html()
        self._compute_comparison_html()
        self._compute_graphs_html()
        self._compute_extra_kpi_html()

    def _get_domain(self):
        start_dt = datetime.combine(self.date_from, time.min)
        end_dt = datetime.combine(self.date_to, time.max)

        domain = [
            ("scheduled_start_date", ">=", start_dt),
            ("scheduled_start_date", "<=", end_dt),
            ("company_id", "=", self.company_id.id),
        ]

        statuses = []
        if self.status_draft:
            statuses.append("draft")
        if self.status_confirmed:
            statuses.append("confirmed")
        if self.status_in_progress:
            statuses.append("in_progress")
        if self.status_done:
            statuses.append("done")

        if statuses:
            domain.append(("status", "in", statuses))
        else:
            domain.append(("status", "in", []))

        if self.product_ids:
            domain.append(("product_id", "in", self.product_ids.ids))

        return domain

    def _compute_orders(self):
        for rec in self:
            domain = rec._get_domain()
            # Ensure we are getting the right records
            rec.order_ids = self.env["idil.manufacturing.order"].search(
                domain, order="scheduled_start_date desc"
            )

    def _compute_kpi_html(self):
        for rec in self:
            orders = rec.order_ids

            total_mos = len(orders)
            total_produced_qty = sum(orders.mapped("product_qty"))
            unique_products = len(orders.mapped("product_id"))

            bom_usd_total = sum(orders.mapped("bom_grand_total"))
            bom_sos_total = sum(mo.report_bom_sos for mo in orders)
            extra_sos_total = sum(mo.extra_cost_total for mo in orders)
            commission_sos_total = sum(mo.commission_amount for mo in orders)

            total_production_cost_sos = (
                bom_sos_total + extra_sos_total + commission_sos_total
            )
            avg_unit_cost_sos = (
                total_production_cost_sos / total_produced_qty
                if total_produced_qty
                else 0
            )

            total_demand = 0.0
            total_used = 0.0
            if orders:
                self.env.cr.execute(
                    """
                    SELECT SUM(quantity_bom), SUM(quantity) 
                    FROM idil_manufacturing_order_line 
                    WHERE manufacturing_order_id IN %s
                """,
                    (tuple(orders.ids),),
                )
                res = self.env.cr.fetchone()
                total_demand = res[0] or 0.0
                total_used = res[1] or 0.0

            total_variance = total_demand - total_used

            html = f"""
            <div class="row">
                <div class="col-md-3">
                    <div class="card text-white bg-primary mb-3">
                        <div class="card-header">Production Output</div>
                        <div class="card-body">
                            <h5 class="card-title">{total_produced_qty:,.2f} Units</h5>
                            <p class="card-text">Total MOs: {total_mos}<br/>Products: {unique_products}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card text-white bg-success mb-3">
                        <div class="card-header">Total Cost (SOS)</div>
                        <div class="card-body">
                            <h5 class="card-title">SOS {total_production_cost_sos:,.2f}</h5>
                            <p class="card-text">Avg Unit Cost: SOS {avg_unit_cost_sos:,.2f}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card text-white bg-info mb-3">
                        <div class="card-header">Cost Breakdown</div>
                        <div class="card-body">
                            <p class="card-text" style="font-size: 0.85em;">
                            BOM (USD): ${bom_usd_total:,.2f}<br/>
                            BOM (SOS): {bom_sos_total:,.2f}<br/>
                            Extra (SOS): {extra_sos_total:,.2f}<br/>
                            Comm (SOS): {commission_sos_total:,.2f}
                            </p>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card text-white { 'bg-danger' if total_variance < 0 else 'bg-success' } mb-3">
                        <div class="card-header">Efficiency (Qty)</div>
                        <div class="card-body">
                            <h5 class="card-title">{total_variance:,.2f} Var</h5>
                            <p class="card-text">Demand: {total_demand:,.2f}<br/>Used: {total_used:,.2f}</p>
                        </div>
                    </div>
                </div>
                <div class="col-12">
                    <small class="text-muted">
                        <b>Calculation Formula:</b> Total Cost (SOS) = (BOM Grand Total USD × Rate) + Extra Cost (SOS) + Commission (SOS)
                    </small>
                </div>
            </div>
            """
            rec.kpi_html = html

    def _compute_insights(self):
        for rec in self:
            orders = rec.order_ids
            insights = []

            start_dt = datetime.combine(rec.date_from - timedelta(days=7), time.min)
            end_dt = datetime.combine(rec.date_from - timedelta(days=1), time.max)

            last_week_domain = [
                ("scheduled_start_date", ">=", start_dt),
                ("scheduled_start_date", "<=", end_dt),
                ("company_id", "=", rec.company_id.id),
                ("status", "in", ["confirmed", "done"]),
            ]
            last_week_orders = self.env["idil.manufacturing.order"].search(
                last_week_domain
            )

            current_total_qty = sum(orders.mapped("product_qty"))
            current_total_cost = sum(o.report_total_sos for o in orders)

            past_total_qty = sum(last_week_orders.mapped("product_qty"))
            past_total_cost = sum(o.report_total_sos for o in last_week_orders)

            current_avg_cost = (
                current_total_cost / current_total_qty if current_total_qty else 0
            )
            past_avg_cost = past_total_cost / past_total_qty if past_total_qty else 0

            if past_avg_cost > 0 and current_avg_cost > past_avg_cost * 1.10:
                insights.append(
                    f"⚠️ <b>Unit Cost Spike:</b> Current unit cost (SOS {current_avg_cost:,.0f}) is >10% higher than last week's average (SOS {past_avg_cost:,.0f}). Investigate extra costs or material usage."
                )

            total_bom_sos = sum(o.report_bom_sos for o in orders)
            total_extra_sos = sum(orders.mapped("extra_cost_total"))

            if total_bom_sos > 0 and total_extra_sos > (total_bom_sos * 0.20):
                insights.append(
                    "⚠️ <b>High Extra Costs:</b> Extra costs exceed 20% of BOM costs."
                )

            total_comm = sum(orders.mapped("commission_amount"))
            if current_total_cost > 0 and total_comm > (current_total_cost * 0.15):
                insights.append(
                    "⚠️ <b>High Commissions:</b> Commissions are over 15% of production cost."
                )

            missing_emp_cost_lines = self.env[
                "idil.manufacturing.order.cost.line"
            ].search_count(
                [
                    ("manufacturing_order_id", "in", orders.ids),
                    ("employee_id", "=", False),
                ]
            )
            if missing_emp_cost_lines > 0:
                insights.append(
                    f"❌ <b>Missing Cost Ownership:</b> {missing_emp_cost_lines} extra cost lines have no employee assigned."
                )

            if not insights:
                insights.append(
                    "✅ <b>Production looks stable.</b> No major anomalies detected."
                )

            rec.insights_html = (
                "<ul class='list-unstyled'>"
                + "".join([f"<li class='mb-2'>{i}</li>" for i in insights])
                + "</ul>"
            )

    def _compute_commission_html(self):
        for rec in self:
            orders = rec.order_ids
            if not orders:
                rec.commission_html = (
                    "<div class='alert alert-warning'>No data available</div>"
                )
                continue

            order_ids_tuple = tuple(orders.ids)
            currency_symbol = "SOS"

            # --- 1. SQL Aggregations for Performance ---

            # A. Employee Breakdown
            self.env.cr.execute(
                """
                SELECT commission_employee_id, SUM(commission_amount), COUNT(*), SUM(product_qty), MAX(commission_amount), MIN(commission_amount)
                FROM idil_manufacturing_order
                WHERE id IN %s AND commission_employee_id IS NOT NULL
                GROUP BY commission_employee_id
                ORDER BY SUM(commission_amount) DESC
            """,
                (order_ids_tuple,),
            )
            emp_data_raw = self.env.cr.fetchall()

            # B. Product Breakdown
            self.env.cr.execute(
                """
                SELECT product_id, SUM(commission_amount), SUM(product_qty)
                FROM idil_manufacturing_order
                WHERE id IN %s
                GROUP BY product_id
                ORDER BY SUM(commission_amount) DESC
            """,
                (order_ids_tuple,),
            )
            prod_data_raw = self.env.cr.fetchall()

            # C. Daily Trend
            self.env.cr.execute(
                """
                SELECT scheduled_start_date::date, SUM(commission_amount), SUM(product_qty)
                FROM idil_manufacturing_order
                WHERE id IN %s
                GROUP BY scheduled_start_date::date
                ORDER BY scheduled_start_date::date
            """,
                (order_ids_tuple,),
            )
            trend_data_raw = self.env.cr.fetchall()

            # Resolve Names
            emp_ids = [r[0] for r in emp_data_raw if r[0]]
            prod_ids = [r[0] for r in prod_data_raw if r[0]]

            emp_map = {e.id: e.name for e in self.env["idil.employee"].browse(emp_ids)}
            prod_map = {
                p.id: p.name for p in self.env["my_product.product"].browse(prod_ids)
            }

            # --- 2. KPI Calculations ---

            total_comm_expense = sum(r[1] for r in emp_data_raw) if emp_data_raw else 0
            # Note: Total commission might be higher if some MOs have commission but no employee (validation issue)
            # Let's verify sum from python objects for absolute truth or use SQL without WHERE employee IS NOT NULL
            self.env.cr.execute(
                "SELECT SUM(commission_amount) FROM idil_manufacturing_order WHERE id IN %s",
                (order_ids_tuple,),
            )
            total_comm_real = self.env.cr.fetchone()[0] or 0.0

            total_qty_produced = sum(orders.mapped("product_qty"))
            total_mos = len(orders)

            avg_comm_mo = total_comm_real / total_mos if total_mos else 0
            avg_comm_unit = (
                total_comm_real / total_qty_produced if total_qty_produced else 0
            )

            # Production Cost for % Calc
            total_production_cost = sum(o.report_total_sos for o in orders)
            comm_pct_cost = (
                (total_comm_real / total_production_cost * 100)
                if total_production_cost
                else 0
            )

            count_employees = len(emp_ids)
            highest_earner_name = (
                emp_map.get(emp_data_raw[0][0], "N/A") if emp_data_raw else "None"
            )
            highest_earner_val = emp_data_raw[0][1] if emp_data_raw else 0

            lowest_earner_name = (
                emp_map.get(emp_data_raw[-1][0], "N/A") if emp_data_raw else "None"
            )
            lowest_earner_val = emp_data_raw[-1][1] if emp_data_raw else 0

            # Concentration (Top 3)
            top_3_sum = sum(r[1] for r in emp_data_raw[:3])
            top_3_share = (top_3_sum / total_comm_real * 100) if total_comm_real else 0

            # --- 3. HTML Construction ---

            html = f"""
            <div class="container-fluid p-0">
                <!-- KPI Cards -->
                <div class="row mb-3">
                    <div class="col-md-3">
                        <div class="card bg-primary text-white h-100">
                            <div class="card-body p-2">
                                <h6 class="card-title text-uppercase font-size-xs mb-1">Total Commission</h6>
                                <h3 class="mb-0">{currency_symbol} {total_comm_real:,.2f}</h3>
                                <small>Expense (Paid + Pending)</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-info text-white h-100">
                            <div class="card-body p-2">
                                <h6 class="card-title text-uppercase font-size-xs mb-1">Averages</h6>
                                <p class="mb-0">Per MO: <strong>{avg_comm_mo:,.2f}</strong></p>
                                <p class="mb-0">Per Unit: <strong>{avg_comm_unit:,.2f}</strong></p>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-warning text-white h-100">
                            <div class="card-body p-2">
                                <h6 class="card-title text-uppercase font-size-xs mb-1">Cost Impact</h6>
                                <h3 class="mb-0">{comm_pct_cost:.1f}%</h3>
                                <small>of Production Cost</small>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="card bg-secondary text-white h-100">
                            <div class="card-body p-2">
                                <h6 class="card-title text-uppercase font-size-xs mb-1">Distribution</h6>
                                <p class="mb-0">Recipients: <strong>{count_employees}</strong></p>
                                <p class="mb-0">Top 3 Share: <strong>{top_3_share:.0f}%</strong></p>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="row mb-3">
                   <div class="col-md-6">
                        <!-- Employee Detail Table -->
                        <h6>Employee Breakdown</h6>
                        <div style="max-height: 300px; overflow-y: auto;">
                            <table class="table table-sm table-striped table-hover">
                                <thead style="position: sticky; top: 0; background: white; z-index: 1;">
                                    <tr>
                                        <th>Employee</th>
                                        <th class="text-right">Total (SOS)</th>
                                        <th class="text-right">Cnt</th>
                                        <th class="text-right">Avg/MO</th>
                                        <th class="text-right">%</th>
                                    </tr>
                                </thead>
                                <tbody>
            """
            for row in emp_data_raw:
                eid, amt, cnt, qty_sum, mx, mn = row
                name = emp_map.get(eid, "Unknown")
                share = (amt / total_comm_real * 100) if total_comm_real else 0
                avg = amt / cnt if cnt else 0
                html += f"<tr><td>{name}</td><td class='text-right'>{amt:,.2f}</td><td class='text-right'>{cnt}</td><td class='text-right'>{avg:,.2f}</td><td class='text-right'>{share:.1f}%</td></tr>"

            html += """
                                </tbody>
                            </table>
                        </div>
                   </div>
                   <div class="col-md-6">
                        <!-- Charts Section -->
                        <h6>Top 10 Employees (Share)</h6>
                        <div class="d-flex flex-column gap-1">
            """

            # Simple CSS Bar Chart for Top 10
            for row in emp_data_raw[:10]:
                eid, amt, cnt, _, _, _ = row
                name = emp_map.get(eid, "Unknown")
                share = (amt / total_comm_real * 100) if total_comm_real else 0
                html += f"""
                    <div class="d-flex align-items-center mb-1">
                        <div style="width: 120px; font-size: 0.8em; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;">{name}</div>
                        <div class="flex-grow-1 progress" style="height: 10px;">
                            <div class="progress-bar bg-success" role="progressbar" style="width: {share}%" aria-valuenow="{share}" aria-valuemin="0" aria-valuemax="100"></div>
                        </div>
                        <div style="width: 50px; text-align: right; font-size: 0.8em;">{share:.1f}%</div>
                    </div>
                """

            html += """
                        </div>
                        <h6 class="mt-3">Products (Top 5 Commission Cost)</h6>
                        <div style="max-height: 150px; overflow-y: auto;">
                            <table class="table table-sm text-muted" style="font-size: 0.85em;">
                                <thead><tr><th>Product</th><th class="text-right">Total Comm</th><th class="text-right">Per Unit</th></tr></thead>
                                <tbody>
            """
            for row in prod_data_raw[:5]:
                pid, amt, qty = row
                pname = prod_map.get(pid, "Unknown")
                p_unit = amt / qty if qty else 0
                html += f"<tr><td>{pname}</td><td class='text-right'>{amt:,.2f}</td><td class='text-right'>{p_unit:,.2f}</td></tr>"

            html += """
                                </tbody>
                            </table>
                        </div>
                   </div>
                </div>

                <div class="row mb-3">
                   <div class="col-12">
                     <h6>Daily Trend (Commission vs Qty)</h6>
                     <div style="display: flex; align-items: flex-end; height: 100px; gap: 2px; border-bottom: 1px solid #ddd; padding-bottom: 2px;">
            """
            # Daily Trend Chart
            if trend_data_raw:
                max_comm = max(r[1] for r in trend_data_raw) if trend_data_raw else 0
                for row in trend_data_raw:
                    dt, amt, qty = row
                    h_pct = (amt / max_comm * 100) if max_comm else 0
                    c_style = "background-color: #007bff;"  # Blue for comm
                    html += f"<div style='width: 100%; {c_style} height: {h_pct}%; border-radius: 2px 2px 0 0;' title='{dt}: {amt:,.0f} (Qty: {qty})'></div>"

            html += """
                     </div>
                     <div style="display: flex; justify-content: space-between; font-size: 0.7em; color: #666;">
                        <span>Start</span><span>End</span>
                     </div>
                   </div>
                </div>

                <!-- Insights & Comparison -->
                <div class="row">
                    <div class="col-md-6">
                        <div class="alert alert-light border">
                            <strong>💡 Insights</strong>
                            <ul class="mb-0 pl-3">
            """

            # Insights Logic
            insights_list = []
            if comm_pct_cost > 15:
                insights_list.append(
                    f"⚠️ <b>High Ratio:</b> Commission is {comm_pct_cost:.1f}% of production cost (Target: <15%)."
                )
            if top_3_share > 70:
                insights_list.append(
                    f"⚠️ <b>Concentration Risk:</b> Top 3 employees take {top_3_share:.0f}% of all commissions."
                )

            # Check for missing employees
            self.env.cr.execute(
                "SELECT COUNT(*) FROM idil_manufacturing_order WHERE id IN %s AND commission_amount > 0 AND commission_employee_id IS NULL",
                (order_ids_tuple,),
            )
            missing_emp_count = self.env.cr.fetchone()[0]
            if missing_emp_count > 0:
                insights_list.append(
                    f"❌ <b>Missing Assignment:</b> {missing_emp_count} MOs have commission amount but no employee."
                )

            if not insights_list:
                insights_list.append("✅ Commission trends look stable.")

            for i in insights_list:
                html += f"<li>{i}</li>"

            html += """
                            </ul>
                        </div>
                    </div>
            """

            # Comparison Logic (Simplified for performance)
            # Compare Total Commission with previous period (Last 7 days approx equivalent)
            prev_days = (rec.date_to - rec.date_from).days + 1
            start_prev = rec.date_from - timedelta(days=prev_days)
            end_prev = rec.date_to - timedelta(days=prev_days)

            # Only do a quick sum check
            self.env.cr.execute(
                """
                SELECT SUM(commission_amount) 
                FROM idil_manufacturing_order 
                WHERE scheduled_start_date >= %s AND scheduled_start_date <= %s
                AND company_id = %s
            """,
                (
                    datetime.combine(start_prev, time.min),
                    datetime.combine(end_prev, time.max),
                    rec.company_id.id,
                ),
            )
            prev_comm = self.env.cr.fetchone()[0] or 0.0

            diff_comm = total_comm_real - prev_comm
            pct_diff = (diff_comm / prev_comm * 100) if prev_comm else 0
            trend_icon = "⬆️" if diff_comm > 0 else "⬇️"
            trend_color = "text-danger" if diff_comm > 0 else "text-success"

            html += f"""
                    <div class="col-md-6">
                        <div class="card">
                            <div class="card-header py-1"><strong>Period Comparison</strong></div>
                            <div class="card-body py-2">
                                <table class="table table-sm table-borderless mb-0">
                                    <tr>
                                        <td>Total Commission</td>
                                        <td class="text-right">{total_comm_real:,.2f}</td>
                                    </tr>
                                    <tr>
                                        <td>Previous Period</td>
                                        <td class="text-right">{prev_comm:,.2f}</td>
                                    </tr>
                                    <tr>
                                        <td>Difference</td>
                                        <td class="text-right {trend_color}"><strong>{trend_icon} {diff_comm:+,.2f} ({pct_diff:+.1f}%)</strong></td>
                                    </tr>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            """

            rec.commission_html = html

    def _compute_tfg_html(self):
        for rec in self:
            orders = rec.order_ids
            products = {}

            for mo in orders:
                pid = mo.product_id.id
                if pid not in products:
                    products[pid] = {
                        "name": mo.product_id.name,
                        "qty": 0,
                        "tfg_sum": 0,
                        "min_tfg": 999999,
                        "max_tfg": 0,
                    }

                products[pid]["qty"] += mo.product_qty
                tfg = mo.tfg_qty or 0
                products[pid]["tfg_sum"] += tfg * mo.product_qty

                if tfg < products[pid]["min_tfg"]:
                    products[pid]["min_tfg"] = tfg
                if tfg > products[pid]["max_tfg"]:
                    products[pid]["max_tfg"] = tfg

            html = "<table class='table table-sm table-striped'><thead><tr><th>Product</th><th class='text-right'>Prod Qty</th><th class='text-right'>Avg TFG</th><th class='text-right'>Min</th><th class='text-right'>Max</th><th class='text-right'>Weighted Total</th></tr></thead><tbody>"
            for pid, vals in products.items():
                if vals["min_tfg"] == 999999:
                    vals["min_tfg"] = 0

                weighted_sum = vals["tfg_sum"]
                avg_tfg = weighted_sum / vals["qty"] if vals["qty"] else 0

                html += f"<tr><td>{vals['name']}</td><td class='text-right'>{vals['qty']:,.2f}</td><td class='text-right'>{avg_tfg:,.2f}</td><td class='text-right'>{vals['min_tfg']:,.2f}</td><td class='text-right'>{vals['max_tfg']:,.2f}</td><td class='text-right'>{weighted_sum:,.2f}</td></tr>"
            html += "</tbody></table>"
            rec.tfg_html = html

    def _compute_accounting_html(self):
        for rec in self:
            if not rec.order_ids:
                rec.accounting_html = "No orders"
                continue

            # Find bookings related to these MOs
            bookings = self.env["idil.transaction_booking"].search(
                [("manufacturing_order_id", "in", rec.order_ids.ids)]
            )

            # Find lines related to those bookings
            lines = self.env["idil.transaction_bookingline"].search(
                [("transaction_booking_id", "in", bookings.ids)]
            )

            accounts = {}
            for line in lines:
                acc_name = line.account_number.name
                if "Exchange Clearing Account" in acc_name:
                    continue

                code = line.account_number.code
                key = (code, acc_name)
                if key not in accounts:
                    accounts[key] = {"debit": 0.0, "credit": 0.0}

                # Check for rate. If missing or 0, assume 1 (SOS) or handle carefully.
                # In IDIL, rate usually present on booking.
                rate = line.rate if line.rate else 1.0

                # Convert to SOS
                dr_sos = line.dr_amount * rate
                cr_sos = line.cr_amount * rate

                accounts[key]["debit"] += dr_sos
                accounts[key]["credit"] += cr_sos

            html = "<table class='table table-sm'><thead><tr><th>Account</th><th class='text-right'>Debit (SOS)</th><th class='text-right'>Credit (SOS)</th></tr></thead><tbody>"
            for (code, name), vals in accounts.items():
                net = vals["debit"] - vals["credit"]
                # Only show rows with non-zero values
                if abs(vals["debit"]) > 0.01 or abs(vals["credit"]) > 0.01:
                    html += f"<tr><td>{code} {name}</td><td class='text-right'>{vals['debit']:,.2f}</td><td class='text-right'>{vals['credit']:,.2f}</tr>"
            html += "</tbody></table>"
            rec.accounting_html = html

    def _get_comparison_row(self, label, curr, prev, is_cost=False):
        diff = curr - prev
        pct = (diff / prev * 100) if prev else 0

        # Color rules:
        # Cost: Increase (Red), Decrease (Green)
        # Qty: Increase (Green), Decrease (Red)
        color = "text-muted"
        if prev != 0:
            if is_cost:
                if diff > 0:
                    color = "text-danger"  # Cost up = bad
                elif diff < 0:
                    color = "text-success"  # Cost down = good
            else:  # Qty or other 'good' metrics
                if diff > 0:
                    color = "text-success"  # Qty up = good
                elif diff < 0:
                    color = "text-danger"  # Qty down = bad

        pct_str = f"{pct:+.1f}%" if prev else "N/A"
        return f"<tr><td>{label}</td><td class='text-right'>{curr:,.2f}</td><td class='text-right'>{prev:,.2f}</td><td class='text-right {color}'>{diff:+,.2f}</td><td class='text-right {color}'>{pct_str}</td></tr>"

    def _compute_comparison_html(self):
        for rec in self:
            orders = (
                rec.order_ids
            )  # ✅ already filtered by date/status/products/company
            if not orders:
                rec.comparison_html = "<div class='alert alert-warning'>No data for selected filters.</div>"
                continue

            # Group selected orders by date
            by_day = defaultdict(list)
            for mo in orders:
                d = mo.scheduled_start_date.date() if mo.scheduled_start_date else None
                if d:
                    by_day[d].append(mo)

            def metrics(mos):
                qty = sum(m.product_qty for m in mos)
                total = sum(m.report_total_sos for m in mos)
                avg = (total / qty) if qty else 0
                return qty, total, avg

            html = ""

            # --- 1) Daily (within selected range) ---
            html += "<h5>Daily Analysis (Day vs Previous Day)</h5>"
            html += "<div style='max-height:300px; overflow-y:auto;'><table class='table table-sm table-bordered'>"
            html += "<thead><tr><th>Date</th><th class='text-right'>Produced Qty</th><th class='text-right'>Total SOS</th><th class='text-right'>Avg Unit Cost</th><th class='text-right'>vs Prev Day</th></tr></thead><tbody>"

            current_date = rec.date_from
            while current_date <= rec.date_to:
                prev_date = current_date - timedelta(days=1)

                curr_orders = by_day.get(current_date, [])
                prev_orders = by_day.get(prev_date, [])

                c_qty, c_cost, c_avg = metrics(curr_orders)
                p_qty, p_cost, p_avg = metrics(prev_orders)

                diff_avg = c_avg - p_avg
                color = (
                    "text-success"
                    if diff_avg < 0
                    else ("text-danger" if diff_avg > 0 else "text-muted")
                )

                date_str = current_date.strftime("%b %d")
                html += (
                    f"<tr>"
                    f"<td>{date_str}</td>"
                    f"<td class='text-right'>{c_qty:,.0f}</td>"
                    f"<td class='text-right'>{c_cost:,.0f}</td>"
                    f"<td class='text-right'>{c_avg:,.0f}</td>"
                    f"<td class='{color} text-right'>{diff_avg:+.0f}</td>"
                    f"</tr>"
                )

                current_date += timedelta(days=1)

            html += "</tbody></table></div>"

            # helper: get orders in a date window from the same filtered dataset
            def orders_in_window(d1, d2):
                res = []
                d = d1
                while d <= d2:
                    res.extend(by_day.get(d, []))
                    d += timedelta(days=1)
                return res

            def get_metrics_full(mos):
                qty = sum(m.product_qty for m in mos)
                bom = sum(m.report_bom_sos for m in mos)
                extra = sum(m.extra_cost_total for m in mos)
                comm = sum(m.commission_amount for m in mos)
                total = bom + extra + comm
                avg = total / qty if qty else 0
                return qty, bom, extra, comm, total, avg

            # --- 2) Weekly (last 7 days inside selected range) ---
            html += "<h5 class='mt-4'>Weekly (Last 7 Days vs Previous 7 Days)</h5>"

            end_date = rec.date_to
            w_curr_start = max(rec.date_from, end_date - timedelta(days=6))
            w_prev_end = w_curr_start - timedelta(days=1)
            w_prev_start = w_prev_end - timedelta(days=6)

            w_curr_orders = orders_in_window(w_curr_start, end_date)
            w_prev_orders = orders_in_window(w_prev_start, w_prev_end)

            wc_qty, wc_bom, wc_extra, wc_comm, wc_total, wc_avg = get_metrics_full(
                w_curr_orders
            )
            wp_qty, wp_bom, wp_extra, wp_comm, wp_total, wp_avg = get_metrics_full(
                w_prev_orders
            )

            html += "<table class='table table-sm table-striped'><thead><tr><th>Metric</th><th>Current 7d</th><th>Prev 7d</th><th>Diff</th><th>%</th></tr></thead><tbody>"
            html += rec._get_comparison_row(
                "Produced Qty", wc_qty, wp_qty, is_cost=False
            )
            html += rec._get_comparison_row(
                "Total Cost SOS", wc_total, wp_total, is_cost=True
            )
            html += rec._get_comparison_row(
                "Avg Unit Cost", wc_avg, wp_avg, is_cost=True
            )
            html += rec._get_comparison_row("BOM SOS", wc_bom, wp_bom, is_cost=True)
            html += rec._get_comparison_row(
                "Extra SOS", wc_extra, wp_extra, is_cost=True
            )
            html += rec._get_comparison_row(
                "Commission SOS", wc_comm, wp_comm, is_cost=True
            )
            html += "</tbody></table>"

            # --- 3) Monthly (MTD within selected range, compared to prev month same days) ---
            html += "<h5 class='mt-4'>Monthly (MTD vs Prev MTD)</h5>"

            m_curr_start = rec.date_to.replace(day=1)
            m_curr_end = rec.date_to

            prev_month_date = m_curr_start - timedelta(days=1)
            m_prev_start = prev_month_date.replace(day=1)
            try:
                m_prev_end = m_prev_start.replace(day=m_curr_end.day)
            except ValueError:
                m_prev_end = prev_month_date

            m_curr_orders = orders_in_window(m_curr_start, m_curr_end)
            m_prev_orders = orders_in_window(m_prev_start, m_prev_end)

            mc_qty, mc_bom, mc_extra, mc_comm, mc_total, mc_avg = get_metrics_full(
                m_curr_orders
            )
            mp_qty, mp_bom, mp_extra, mp_comm, mp_total, mp_avg = get_metrics_full(
                m_prev_orders
            )

            html += "<table class='table table-sm table-striped'><thead><tr><th>Metric</th><th>Current MTD</th><th>Prev MTD</th><th>Diff</th><th>%</th></tr></thead><tbody>"
            html += rec._get_comparison_row(
                "Produced Qty", mc_qty, mp_qty, is_cost=False
            )
            html += rec._get_comparison_row(
                "Total Cost SOS", mc_total, mp_total, is_cost=True
            )
            html += rec._get_comparison_row(
                "Avg Unit Cost", mc_avg, mp_avg, is_cost=True
            )
            html += rec._get_comparison_row("BOM SOS", mc_bom, mp_bom, is_cost=True)
            html += rec._get_comparison_row(
                "Extra SOS", mc_extra, mp_extra, is_cost=True
            )
            html += rec._get_comparison_row(
                "Commission SOS", mc_comm, mp_comm, is_cost=True
            )
            html += "</tbody></table>"

            rec.comparison_html = html

    # def _compute_comparison_html(self):
    #     for rec in self:
    #         html = ""

    #         # --- 1. Daily (Day-by-Day within range) ---
    #         html += "<h5>Daily Analysis (Day vs Previous Day)</h5>"
    #         html += "<div style='max-height:300px; overflow-y:auto;'><table class='table table-sm table-bordered'><thead><tr><th>Date</th><th>Produced Qty</th><th>Total SOS</th><th>Avg Unit Cost</th><th>vs Prev Day</th></tr></thead><tbody>"

    #         current_date = rec.date_from
    #         while current_date <= rec.date_to:
    #             prev_date = current_date - timedelta(days=1)

    #             # Current Day Data
    #             dt_start = datetime.combine(current_date, time.min)
    #             dt_end = datetime.combine(current_date, time.max)
    #             curr_orders = self.env['idil.manufacturing.order'].search([
    #                 ('scheduled_start_date', '>=', dt_start),('scheduled_start_date', '<=', dt_end),
    #                 ('company_id', '=', rec.company_id.id),('status', 'in', ['confirmed', 'done', 'in_progress'])
    #             ])

    #             # Previous Day Data
    #             p_items = self.env['idil.manufacturing.order'].search([
    #                 ('scheduled_start_date', '>=', datetime.combine(prev_date, time.min)),
    #                 ('scheduled_start_date', '<=', datetime.combine(prev_date, time.max)),
    #                 ('company_id', '=', rec.company_id.id),('status', 'in', ['confirmed', 'done', 'in_progress'])
    #             ])

    #             c_qty = sum(curr_orders.mapped('product_qty'))
    #             c_cost = sum(o.report_total_sos for o in curr_orders)
    #             c_avg = c_cost / c_qty if c_qty else 0

    #             p_qty = sum(p_items.mapped('product_qty'))
    #             p_cost = sum(o.report_total_sos for o in p_items)
    #             p_avg = p_cost / p_qty if p_qty else 0

    #             # Compare Avg Cost
    #             diff_avg = c_avg - p_avg
    #             color = "text-success" if diff_avg < 0 else ("text-danger" if diff_avg > 0 else "text-muted")

    #             date_str = current_date.strftime('%b %d')
    #             html += f"<tr><td>{date_str}</td><td class='text-right'>{c_qty:,.0f}</td><td class='text-right'>{c_cost:,.0f}</td><td class='text-right'>{c_avg:,.0f}</td><td class='{color} text-right'>{diff_avg:+.0f}</td></tr>"

    #             current_date += timedelta(days=1)
    #         html += "</tbody></table></div>"

    #         # --- 2. Weekly (Rolling 7 Days) ---
    #         html += "<h5 class='mt-4'>Weekly (Last 7 Days vs Previous 7 Days)</h5>"

    #         end_date = rec.date_to
    #         w_curr_start = end_date - timedelta(days=6)
    #         w_prev_end = w_curr_start - timedelta(days=1)
    #         w_prev_start = w_prev_end - timedelta(days=6)

    #         # Fetch
    #         w_curr_orders = self.env['idil.manufacturing.order'].search([
    #             ('scheduled_start_date', '>=', datetime.combine(w_curr_start, time.min)),
    #             ('scheduled_start_date', '<=', datetime.combine(end_date, time.max)),
    #             ('company_id', '=', rec.company_id.id),('status', 'in', ['confirmed', 'done', 'in_progress'])
    #         ])
    #         w_prev_orders = self.env['idil.manufacturing.order'].search([
    #             ('scheduled_start_date', '>=', datetime.combine(w_prev_start, time.min)),
    #             ('scheduled_start_date', '<=', datetime.combine(w_prev_end, time.max)),
    #             ('company_id', '=', rec.company_id.id),('status', 'in', ['confirmed', 'done', 'in_progress'])
    #         ])

    #         # Metrics
    #         def get_metrics(mos):
    #             qty = sum(mos.mapped('product_qty'))
    #             bom = sum(m.report_bom_sos for m in mos)
    #             extra = sum(m.extra_cost_total for m in mos)
    #             comm = sum(m.commission_amount for m in mos)
    #             total = bom + extra + comm
    #             avg = total / qty if qty else 0
    #             return qty, bom, extra, comm, total, avg

    #         wc_qty, wc_bom, wc_extra, wc_comm, wc_total, wc_avg = get_metrics(w_curr_orders)
    #         wp_qty, wp_bom, wp_extra, wp_comm, wp_total, wp_avg = get_metrics(w_prev_orders)

    #         html += "<table class='table table-sm table-striped'><thead><tr><th>Metric</th><th>Current 7d</th><th>Prev 7d</th><th>Diff</th><th>%</th></tr></thead><tbody>"
    #         html += rec._get_comparison_row("Produced Qty", wc_qty, wp_qty, is_cost=False)
    #         html += rec._get_comparison_row("Total Cost SOS", wc_total, wp_total, is_cost=True)
    #         html += rec._get_comparison_row("Avg Unit Cost", wc_avg, wp_avg, is_cost=True)
    #         html += rec._get_comparison_row("BOM SOS", wc_bom, wp_bom, is_cost=True)
    #         html += rec._get_comparison_row("Extra SOS", wc_extra, wp_extra, is_cost=True)
    #         html += rec._get_comparison_row("Commission SOS", wc_comm, wp_comm, is_cost=True)
    #         html += "</tbody></table>"

    #         # --- 3. Monthly (MTD vs Prev Month MTD) ---
    #         html += "<h5 class='mt-4'>Monthly (MTD vs Prev MTD)</h5>"

    #         m_curr_start = rec.date_to.replace(day=1)
    #         m_curr_end = rec.date_to

    #         prev_month_date = m_curr_start - timedelta(days=1)
    #         m_prev_start = prev_month_date.replace(day=1)
    #         # End date should match same day number or end of month
    #         try:
    #             m_prev_end = m_prev_start.replace(day=m_curr_end.day)
    #         except ValueError:
    #             # e.g. March 31 -> Feb 28
    #             m_prev_end = prev_month_date

    #         # Fetch
    #         m_curr_orders = self.env['idil.manufacturing.order'].search([
    #             ('scheduled_start_date', '>=', datetime.combine(m_curr_start, time.min)),
    #             ('scheduled_start_date', '<=', datetime.combine(m_curr_end, time.max)),
    #             ('company_id', '=', rec.company_id.id),('status', 'in', ['confirmed', 'done', 'in_progress'])
    #         ])
    #         m_prev_orders = self.env['idil.manufacturing.order'].search([
    #             ('scheduled_start_date', '>=', datetime.combine(m_prev_start, time.min)),
    #             ('scheduled_start_date', '<=', datetime.combine(m_prev_end, time.max)),
    #             ('company_id', '=', rec.company_id.id),('status', 'in', ['confirmed', 'done', 'in_progress'])
    #         ])

    #         mc_qty, mc_bom, mc_extra, mc_comm, mc_total, mc_avg = get_metrics(m_curr_orders)
    #         mp_qty, mp_bom, mp_extra, mp_comm, mp_total, mp_avg = get_metrics(m_prev_orders)

    #         html += "<table class='table table-sm table-striped'><thead><tr><th>Metric</th><th>Current MTD</th><th>Prev MTD</th><th>Diff</th><th>%</th></tr></thead><tbody>"
    #         html += rec._get_comparison_row("Produced Qty", mc_qty, mp_qty, is_cost=False)
    #         html += rec._get_comparison_row("Total Cost SOS", mc_total, mp_total, is_cost=True)
    #         html += rec._get_comparison_row("Avg Unit Cost", mc_avg, mp_avg, is_cost=True)
    #         html += rec._get_comparison_row("BOM SOS", mc_bom, mp_bom, is_cost=True)
    #         html += rec._get_comparison_row("Extra SOS", mc_extra, mp_extra, is_cost=True)
    #         html += rec._get_comparison_row("Commission SOS", mc_comm, mp_comm, is_cost=True)
    #         html += "</tbody></table>"

    #         rec.comparison_html = html

    def _compute_graphs_html(self):
        for rec in self:
            orders = rec.order_ids
            rec.extra_kpi_html = (
                ""  # Clear this, we will use graphs_html for the whole dashboard
            )

            if not orders:
                rec.graphs_html = """
                <div class="alert alert-info text-center p-5">
                    <h4>No Data Available</h4>
                    <p>Please select a valid date range and click "Refresh Data".</p>
                </div>
                """
                continue

            # --- 1. Data Aggregation (SQL) ---
            ids = tuple(orders.ids)

            # Daily Aggregates
            query_daily = """
                SELECT 
                    scheduled_start_date::date as d,
                    SUM(product_qty) as qty,
                    SUM(bom_grand_total * rate) as bom,
                    SUM(extra_cost_total) as extra,
                    SUM(commission_amount) as comm,
                    COUNT(*) as count
                FROM idil_manufacturing_order
                WHERE id IN %s
                GROUP BY scheduled_start_date::date
                ORDER BY scheduled_start_date::date
            """
            self.env.cr.execute(query_daily, (ids,))
            daily_data = self.env.cr.fetchall()

            # Product Aggregates
            query_prod = """
                SELECT 
                    p.name,
                    SUM(m.product_qty) as qty,
                    SUM((m.bom_grand_total * m.rate) + m.extra_cost_total + m.commission_amount) as total_cost
                FROM idil_manufacturing_order m
                JOIN my_product_product p ON m.product_id = p.id
                WHERE m.id IN %s
                GROUP BY p.name
            """
            self.env.cr.execute(query_prod, (ids,))
            prod_data = self.env.cr.fetchall()

            # Global Totals
            t_mos = sum(d[5] for d in daily_data)
            t_qty = sum(d[1] for d in daily_data)
            t_bom = sum(d[2] for d in daily_data)
            t_extra = sum(d[3] for d in daily_data)
            t_comm = sum(d[4] for d in daily_data)
            t_cost = t_bom + t_extra + t_comm

            avg_unit_cost = t_cost / t_qty if t_qty else 0

            bom_pct = (t_bom / t_cost * 100) if t_cost else 0
            other_pct = ((t_extra + t_comm) / t_cost * 100) if t_cost else 0

            # --- 2. Charting Engine (SVG) ---
            def render_svg(
                chart_type, data, title, height=220, color="#4e73df", stacked=False
            ):
                if not data:
                    return f'<div class="alert alert-light">No data for {title}</div>'

                # Canvas dims
                w, h = 800, height
                pad_left, pad_right, pad_top, pad_bottom = 80, 20, 30, 40
                plot_w = w - pad_left - pad_right
                plot_h = h - pad_top - pad_bottom

                # Determine Max Value
                if stacked:
                    max_val = (
                        max(
                            (d.get("v1", 0) + d.get("v2", 0) + d.get("v3", 0))
                            for d in data
                        )
                        or 1
                    )
                else:
                    max_val = max((d.get("value", 0) for d in data), default=0) or 1

                # SVG Container
                svg = f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet" style="width:100%; height:{height}px; background:#fff; border-radius:4px;">'

                # Grid lines & Y-Axis Labels (5 steps)
                steps = 5
                for i in range(steps + 1):
                    val = max_val * (i / steps)
                    y = pad_top + plot_h - (plot_h * (i / steps))
                    # Grid line
                    stroke = "#e0e0e0" if i > 0 else "#ccc"
                    svg += f'<line x1="{pad_left}" y1="{y}" x2="{w-pad_right}" y2="{y}" stroke="{stroke}" stroke-width="1"/>'
                    # Label
                    svg += f'<text x="{pad_left-10}" y="{y+4}" text-anchor="end" font-family="Roboto, sans-serif" font-size="11" fill="#666">{val:,.0f}</text>'

                # X-Axis & Plotting
                count = len(data)
                if count == 0:
                    return svg + "</svg>"

                # Widths
                bar_w = (plot_w / count) * 0.6 if chart_type == "bar" else 0
                step_x = (
                    plot_w / (count - 1)
                    if count > 1 and chart_type == "line"
                    else plot_w / count
                )

                # Draw Chart
                if chart_type == "bar":
                    for i, d in enumerate(data):
                        x = (
                            pad_left
                            + (i * (plot_w / count))
                            + ((plot_w / count - bar_w) / 2)
                        )

                        if stacked:
                            v1, v2, v3 = d.get("v1", 0), d.get("v2", 0), d.get("v3", 0)
                            h1 = (v1 / max_val) * plot_h
                            h2 = (v2 / max_val) * plot_h
                            h3 = (v3 / max_val) * plot_h

                            y = pad_top + plot_h
                            # Stack 1 (BOM - Blue)
                            y -= h1
                            svg += f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h1}" fill="#4e73df"><title>BOM: {v1:,.0f}</title></rect>'
                            # Stack 2 (Extra - Yellow)
                            y -= h2
                            svg += f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h2}" fill="#f6c23e"><title>Extra: {v2:,.0f}</title></rect>'
                            # Stack 3 (Comm - Green)
                            y -= h3
                            svg += f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h3}" fill="#1cc88a"><title>Comm: {v3:,.0f}</title></rect>'

                        else:
                            val = d["value"]
                            h_bar = (val / max_val) * plot_h
                            y = pad_top + plot_h - h_bar
                            svg += f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h_bar}" fill="{color}"><title>{d["label"]}: {val:,.0f}</title></rect>'

                elif chart_type == "line":
                    points = []
                    # Shadow/Area under line (Optional, maybe for layout)
                    poly_points = [f"{pad_left},{pad_top+plot_h}"]

                    for i, d in enumerate(data):
                        val = d["value"]
                        px = pad_left + (i * step_x)
                        py = pad_top + plot_h - ((val / max_val) * plot_h)
                        points.append(f"{px},{py}")
                        poly_points.append(f"{px},{py}")

                        # Dot
                        svg += f'<circle cx="{px}" cy="{py}" r="3" fill="#fff" stroke="{color}" stroke-width="2"><title>{d["label"]}: {val:,.0f}</title></circle>'

                    # Close Area
                    poly_points.append(
                        f"{pad_left + ((count-1)*step_x)},{pad_top+plot_h}"
                    )

                    # Draw Line
                    if points:
                        svg += f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'

                # X-Axis Labels (Prevent Overlap)
                # Max labels we can fit roughly 10-12
                step_skip = max(1, int(count / 10))

                for i, d in enumerate(data):
                    if i % step_skip == 0:
                        x_pos = (
                            pad_left + (i * (plot_w / count)) + (plot_w / count / 2)
                            if chart_type != "line"
                            else pad_left + (i * step_x)
                        )

                        # Fix for last label cutoff in line chart
                        if chart_type == "line" and i == count - 1:
                            x_pos -= 10

                        label_text = d["label"]
                        svg += f'<text x="{x_pos}" y="{h-15}" text-anchor="middle" font-family="Roboto, sans-serif" font-size="11" fill="#555">{label_text}</text>'

                svg += "</svg>"
                return svg

            # --- 3. HTML Construction ---

            # CSS Styles
            css = """
            <style>
                .db-card { background: #fff; border: 1px solid #e3e6f0; border-radius: 0.5rem; box-shadow: 0 4px 6px rgba(0,0,0,0.05); height: 100%; display: flex; flex-direction: column; }
                .db-head { padding: 1rem 1.25rem; font-weight: 700; color: #4e73df; border-bottom: 1px solid #f0f2f5; display: flex; justify-content: space-between; align-items: center; }
                .db-body { padding: 10px; flex: 1; position: relative; }
                .kpi-box { padding: 15px; border-left: 5px solid; background: #fff; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
                .kpi-label { font-size: 0.75rem; font-weight: 700; text-transform: uppercase; margin-bottom: 5px; letter-spacing: 0.5px; }
                .kpi-val { font-size: 1.5rem; font-weight: 700; color: #5a5c69; }
                .table-sm th, .table-sm td { padding: 0.5rem; font-size: 0.85rem; }
            </style>
            """

            html = f"""
            <div style="font-family: 'Roboto', 'Nunito', sans-serif; background-color: #f8f9fc; padding: 20px;">
                {css}
                
                <!-- KPI Section -->
                <div class="row mb-4">
                    <div class="col-lg-2 col-md-4 mb-2">
                        <div class="kpi-box" style="border-color: #4e73df;">
                            <div class="kpi-label" style="color: #4e73df;">Total MOs</div>
                            <div class="kpi-val">{t_mos}</div>
                        </div>
                    </div>
                    <div class="col-lg-2 col-md-4 mb-2">
                         <div class="kpi-box" style="border-color: #1cc88a;">
                            <div class="kpi-label" style="color: #1cc88a;">Produced Qty</div>
                            <div class="kpi-val">{t_qty:,.0f}</div>
                        </div>
                    </div>
                    <div class="col-lg-2 col-md-4 mb-2">
                         <div class="kpi-box" style="border-color: #36b9cc;">
                            <div class="kpi-label" style="color: #36b9cc;">Total Cost</div>
                            <div class="kpi-val">{t_cost:,.0f}</div>
                        </div>
                    </div>
                    <div class="col-lg-2 col-md-4 mb-2">
                         <div class="kpi-box" style="border-color: #f6c23e;">
                            <div class="kpi-label" style="color: #f6c23e;">Avg Cost/Unit</div>
                            <div class="kpi-val">{avg_unit_cost:,.0f} <small class="text-muted">SOS</small></div>
                        </div>
                    </div>
                    <div class="col-lg-2 col-md-4 mb-2">
                         <div class="kpi-box" style="border-color: #e74a3b;">
                            <div class="kpi-label" style="color: #e74a3b;">BOM Share</div>
                            <div class="kpi-val">{bom_pct:.1f}%</div>
                        </div>
                    </div>
                    <div class="col-lg-2 col-md-4 mb-2">
                         <div class="kpi-box" style="border-color: #858796;">
                            <div class="kpi-label" style="color: #858796;">Extra Costs</div>
                            <div class="kpi-val">{other_pct:.1f}%</div>
                        </div>
                    </div>
                </div>

                <!-- Charts Row 1: Production & Cost -->
                <div class="row mb-4">
                    <div class="col-md-6">
                        <div class="db-card">
                            <div class="db-head">
                                <span>Production Volume Trend</span>
                                <small class="text-muted">Daily Units</small>
                            </div>
                            <div class="db-body">
            """
            c1_data = [
                {"label": d[0].strftime("%d-%b"), "value": d[1]} for d in daily_data
            ]
            html += render_svg(
                "bar", c1_data, "Daily Produced Qty", height=240, color="#4e73df"
            )
            html += """     </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="db-card">
                             <div class="db-head">
                                <span>Total Cost Trend</span>
                                <small class="text-muted">SOS</small>
                            </div>
                            <div class="db-body">
            """
            c2_data = [
                {"label": d[0].strftime("%d-%b"), "value": d[2] + d[3] + d[4]}
                for d in daily_data
            ]
            html += render_svg(
                "line", c2_data, "Daily Total Cost", height=240, color="#1cc88a"
            )
            html += """     </div>
                        </div>
                    </div>
                </div>

                <!-- Charts Row 2: Efficiency & Composition -->
                <div class="row mb-4">
                     <div class="col-md-6">
                        <div class="db-card">
                             <div class="db-head">
                                <span>Unit Cost Efficiency</span>
                                <small class="text-muted">Avg Cost per Unit</small>
                            </div>
                            <div class="db-body">
            """
            c3_data = [
                {
                    "label": d[0].strftime("%d-%b"),
                    "value": ((d[2] + d[3] + d[4]) / d[1] if d[1] else 0),
                }
                for d in daily_data
            ]
            html += render_svg(
                "line", c3_data, "Avg Unit Cost", height=240, color="#f6c23e"
            )
            html += """     </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="db-card">
                             <div class="db-head">
                                <span>Cost Stack Analysis</span>
                                <small class="text-muted">BOM vs Extra vs Comm</small>
                            </div>
                            <div class="db-body">
            """
            c4_data = [
                {"label": d[0].strftime("%d-%b"), "v1": d[2], "v2": d[3], "v3": d[4]}
                for d in daily_data
            ]
            html += render_svg(
                "bar", c4_data, "Cost Breakdown", height=240, stacked=True
            )
            html += """
                            <div class="text-center mt-2" style="font-size: 0.8rem;">
                                <span class="badge badge-primary mr-2" style="background:#4e73df">BOM</span>
                                <span class="badge badge-warning mr-2" style="background:#f6c23e">Extra</span>
                                <span class="badge badge-success" style="background:#1cc88a">Comm</span>
                            </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Rankings Row -->
                <div class="row mb-4">
                    <div class="col-md-6">
                         <div class="db-card">
                             <div class="db-head">
                                <span>Top Expensive MOs</span>
                                <small class="text-muted">By Unit Cost</small>
                            </div>
                            <div class="p-0 table-responsive">
                                <table class="table table-sm table-striped mb-0 text-dark">
                                    <thead class="thead-light"><tr><th>MO Ref</th><th class="text-right">Qty</th><th class="text-right">Unit Cost</th><th class="text-right">Total SOS</th></tr></thead>
                                    <tbody>
            """
            mo_list = sorted(
                orders,
                key=lambda x: (
                    (x.report_total_sos / x.product_qty) if x.product_qty else 0
                ),
                reverse=True,
            )[:8]
            avg_network = avg_unit_cost
            for m in mo_list:
                u_c = (m.report_total_sos / m.product_qty) if m.product_qty else 0
                is_spike = u_c > avg_network * 1.10
                spike_html = (
                    ' <span class="badge badge-danger">Spike</span>' if is_spike else ""
                )
                html += f"<tr><td>{m.name}{spike_html}</td><td class='text-right'>{m.product_qty:,.0f}</td><td class='text-right font-weight-bold'>{u_c:,.0f}</td><td class='text-right'>{m.report_total_sos:,.0f}</td></tr>"

            html += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <div class="db-card">
                             <div class="db-head">
                                <span>Top Products</span>
                                <small class="text-muted">By Avg Unit Cost</small>
                            </div>
                            <div class="p-0 table-responsive">
                                <table class="table table-sm table-striped mb-0 text-dark">
                                    <thead class="thead-light"><tr><th>Product</th><th class="text-right">MOs</th><th class="text-right">Avg Unit Cost</th></tr></thead>
                                    <tbody>
            """
            # prod_names = ... (Removed to fix TypeError)
            # Actually prod_data is list of tuples (name, qty, cost)
            prod_sorted = sorted(
                prod_data, key=lambda x: (x[2] / x[1]) if x[1] else 0, reverse=True
            )[:8]
            for p in prod_sorted:
                p_name = p[0]
                # specific check for jsonb translation dict from raw sql
                if isinstance(p_name, dict):
                    p_name = (
                        p_name.get("en_US") or list(p_name.values())[0]
                        if p_name
                        else "Unknown"
                    )

                u_c = (p[2] / p[1]) if p[1] else 0
                html += f"<tr><td>{p_name}</td><td class='text-right'>{p[1]:,.0f}</td><td class='text-right font-weight-bold'>{u_c:,.0f}</td></tr>"

            html += """
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Alert Section -->
                <div class="row">
                    <div class="col-12">
                        <div class="alert alert-light border shadow-sm">
                            <h6 class="font-weight-bold text-danger">🔥 Cost Spike Detection</h6>
            """
            spike_count = sum(
                1
                for m in mo_list
                if ((m.report_total_sos / m.product_qty) if m.product_qty else 0)
                > avg_network * 1.10
            )
            if spike_count > 0:
                html += f"<p class='mb-0'>Identified <strong>{spike_count}</strong> MOs in the top ranking causing cost spikes (Unit Cost > 10% above average). Investigate Extra Costs or Material usage.</p>"
            else:
                html += "<p class='mb-0 text-success'>✅ No significant cost spikes detected in the top productions.</p>"

            html += """
                        </div>
                    </div>
                </div>

            </div>
            """

            rec.graphs_html = html

    def _compute_extra_kpi_html(self):
        for rec in self:
            rec.extra_kpi_html = ""

    def _get_view_domain(self):
        domain = [
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("company_id", "=", self.company_id.id),
        ]
        statuses = []
        if self.status_draft:
            statuses.append("draft")
        if self.status_confirmed:
            statuses.append("confirmed")
        if self.status_in_progress:
            statuses.append("in_progress")
        if self.status_done:
            statuses.append("done")

        if statuses:
            domain.append(("status", "in", statuses))
        else:
            domain.append(("status", "in", []))
        if self.product_ids:
            domain.append(("product_id", "in", self.product_ids.ids))
        return domain

    def action_view_daily_summary(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "idil.action_production_report_daily_view"
        )
        action["domain"] = self._get_view_domain()
        return action

    def action_view_product_breakdown(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "idil.action_production_report_product_view"
        )
        action["domain"] = self._get_view_domain()
        return action

    def action_print_pdf(self):
        return self.env.ref("idil.action_report_production_daily").report_action(self)


class ManufacturingOrderReportExtension(models.Model):
    _inherit = "idil.manufacturing.order"

    report_bom_sos = fields.Float(compute="_compute_report_sos", string="BOM (SOS)")
    report_total_sos = fields.Float(compute="_compute_report_sos", string="Total (SOS)")

    @api.depends("bom_grand_total", "rate", "extra_cost_total", "commission_amount")
    def _compute_report_sos(self):
        for mo in self:
            bom_sos = mo.bom_grand_total * mo.rate
            mo.report_bom_sos = bom_sos
            mo.report_total_sos = bom_sos + mo.extra_cost_total + mo.commission_amount


class IdilProductionReportView(models.Model):
    """SQL View for detailed analysis"""

    _name = "idil.production.report.view"
    _description = "Production Report Analysis"
    _auto = False

    date = fields.Date(string="Date")
    manufacturing_order_id = fields.Many2one(
        "idil.manufacturing.order", string="MO", readonly=True
    )
    product_id = fields.Many2one("my_product.product", string="Product", readonly=True)
    product_qty = fields.Float(string="Produced Qty")

    bom_cost = fields.Float(string="BOM Cost")
    extra_cost = fields.Float(string="Extra Cost")
    commission_cost = fields.Float(string="Commission")
    total_cost = fields.Float(string="Total Cost")

    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
    )
    company_id = fields.Many2one("res.company", string="Company")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW idil_production_report_view AS (
                SELECT
                    mo.id as id,
                    mo.id as manufacturing_order_id,
                    CAST(mo.scheduled_start_date AS DATE) as date,
                    mo.product_id,
                    mo.product_qty,
                    mo.bom_grand_total as bom_cost,
                    mo.extra_cost_total as extra_cost,
                    mo.commission_amount as commission_cost,
                    ((mo.bom_grand_total * COALESCE(NULLIF(mo.rate, 0), 1)) + mo.extra_cost_total + mo.commission_amount) as total_cost,
                    mo.status,
                    mo.company_id
                FROM
                    idil_manufacturing_order mo
            )
        """
        )
