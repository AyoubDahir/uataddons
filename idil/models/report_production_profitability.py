from odoo import models, fields, tools

class ProductionProfitabilityReport(models.Model):
    _name = "idil.report.production.profitability"
    _description = "Production Profitability Report"
    _auto = False
    _order = "date desc"

    date = fields.Date(string="Date", readonly=True)
    product_id = fields.Many2one("my_product.product", string="Product", readonly=True)

    # Production
    produced_qty = fields.Float(string="Produced Qty", readonly=True)
    production_cost_usd = fields.Float(string="Production Cost (USD)", readonly=True)
    production_cost_sl = fields.Float(string="Production Cost (SL)", readonly=True)

    # Unit Production Cost
    unit_production_cost_usd = fields.Float(
        string="Unit Prod Cost (USD)", readonly=True, group_operator="avg", digits=(16, 4)
    )
    unit_production_cost_sl = fields.Float(
        string="Unit Prod Cost (SL)", readonly=True, group_operator="avg", digits=(16, 4)
    )

    # Sales
    sold_qty = fields.Float(string="Sold Qty", readonly=True)
    sales_amount_usd = fields.Float(string="Sales Revenue (USD)", readonly=True)
    sales_amount_sl = fields.Float(string="Sales Revenue (SL)", readonly=True)

    # Avg Sales Price
    avg_sales_price_usd = fields.Float(
        string="Avg Sales Price (USD)", readonly=True, group_operator="avg", digits=(16, 4)
    )
    avg_sales_price_sl = fields.Float(
        string="Avg Sales Price (SL)", readonly=True, group_operator="avg", digits=(16, 4)
    )

    # Cost of Sales (COGS)
    cost_of_sales_usd = fields.Float(string="Cost of Sales (USD)", readonly=True)
    cost_of_sales_sl = fields.Float(string="Cost of Sales (SL)", readonly=True)

    # Profit
    profit_amount_usd = fields.Float(string="Profit (USD)", readonly=True)
    profit_amount_sl = fields.Float(string="Profit (SL)", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW idil_report_production_profitability AS (
                WITH
                -- 1) Daily Production (Cost & Qty)
                -- IMPORTANT: Make SL cost exactly match MO screen:
                -- SL = mo.product_cost (USD) * mo.rate, rounded to 2 decimals.
                production AS (
                    SELECT
                        DATE(mo.scheduled_start_date) AS date,
                        mo.product_id,

                        SUM(COALESCE(mo.product_qty, 0)) AS produced_qty,

                        -- USD total (from MO) - rounded to 2 decimals
                        ROUND(SUM(COALESCE(mo.product_cost, 0))::numeric, 2) AS cost_usd_total,

                        -- SL total EXACT (USD * rate) with numeric + rounding
                        SUM(
                            ROUND(
                                (COALESCE(mo.product_cost, 0)::numeric * COALESCE(mo.rate, 0)::numeric),
                                2
                            )
                        ) AS cost_sl_total

                    FROM idil_manufacturing_order mo
                    WHERE mo.status = 'done'
                    GROUP BY DATE(mo.scheduled_start_date), mo.product_id
                ),

                -- 2) Consolidated Daily Sales
                all_sales AS (
                    -- A) Salesperson Orders
                    SELECT
                        DATE(so.order_date) AS date,
                        l.product_id,
                        l.quantity AS qty,

                        -- USD: Round conversion results to 2 decimals
                        ROUND(
                            CASE
                                WHEN cur.name = 'USD' THEN (l.quantity * l.price_unit)
                                WHEN cur.name = 'SL'  THEN (l.quantity * l.price_unit) / NULLIF(so.rate, 0)
                                ELSE 0
                            END::numeric, 2
                        ) AS amt_usd,

                        -- SL: Round conversion results to 2 decimals
                        ROUND(
                            CASE
                                WHEN cur.name = 'SL'  THEN (l.quantity * l.price_unit)
                                WHEN cur.name = 'USD' THEN (l.quantity * l.price_unit) * so.rate
                                ELSE 0
                            END::numeric, 2
                        ) AS amt_sl

                    FROM idil_sale_order_line l
                    JOIN idil_sale_order so ON l.order_id = so.id
                    LEFT JOIN res_currency cur ON l.currency_id = cur.id
                    WHERE so.state = 'confirmed'

                    UNION ALL

                    -- B) Customer Sales Orders
                    SELECT
                        DATE(cso.order_date) AS date,
                        l.product_id,
                        l.quantity AS qty,

                        -- USD: Round conversion results to 2 decimals
                        ROUND(
                            CASE
                                WHEN cur.name = 'USD' THEN (l.quantity * l.price_unit)
                                WHEN cur.name = 'SL'  THEN (l.quantity * l.price_unit) / NULLIF(cso.rate, 0)
                                ELSE 0
                            END::numeric, 2
                        ) AS amt_usd,

                        -- SL: Round conversion results to 2 decimals
                        ROUND(
                            CASE
                                WHEN cur.name = 'SL'  THEN (l.quantity * l.price_unit)
                                WHEN cur.name = 'USD' THEN (l.quantity * l.price_unit) * cso.rate
                                ELSE 0
                            END::numeric, 2
                        ) AS amt_sl

                    FROM idil_customer_sale_order_line l
                    JOIN idil_customer_sale_order cso ON l.order_id = cso.id
                    LEFT JOIN res_currency cur ON cso.currency_id = cur.id
                    WHERE cso.state = 'confirmed'

                    UNION ALL

                    -- C) Staff Sales
                    SELECT
                        DATE(ss.sales_date) AS date,
                        l.product_id,
                        l.quantity AS qty,

                        -- USD: Round conversion results to 2 decimals
                        ROUND(
                            CASE
                                WHEN cur.name = 'USD' THEN l.total
                                WHEN cur.name = 'SL'  THEN l.total / NULLIF(ss.rate, 0)
                                ELSE 0
                            END::numeric, 2
                        ) AS amt_usd,

                        -- SL: Round conversion results to 2 decimals
                        ROUND(
                            CASE
                                WHEN cur.name = 'SL'  THEN l.total
                                WHEN cur.name = 'USD' THEN l.total * ss.rate
                                ELSE 0
                            END::numeric, 2
                        ) AS amt_sl

                    FROM idil_staff_sales_line l
                    JOIN idil_staff_sales ss ON l.sales_id = ss.id
                    LEFT JOIN res_currency cur ON ss.currency_id = cur.id
                    WHERE ss.state = 'confirmed'
                ),

                daily_sales AS (
                    SELECT
                        date,
                        product_id,
                        SUM(COALESCE(qty, 0)) AS sold_qty,
                        ROUND(SUM(COALESCE(amt_usd, 0))::numeric, 2) AS sales_amount_usd,
                        ROUND(SUM(COALESCE(amt_sl, 0))::numeric, 2) AS sales_amount_sl
                    FROM all_sales
                    GROUP BY date, product_id
                ),

                -- 3) Combined Dates & Products
                dates_products AS (
                    SELECT date, product_id FROM production
                    UNION
                    SELECT date, product_id FROM daily_sales
                ),

                -- 4) Metrics base with pre-calculated unit costs (rounded to 4 decimals for precision)
                metrics AS (
                    SELECT
                        row_number() OVER () AS id,
                        dp.date,
                        dp.product_id,

                        COALESCE(p.produced_qty, 0) AS produced_qty,
                        COALESCE(p.cost_usd_total, 0) AS production_cost_usd,
                        COALESCE(p.cost_sl_total, 0) AS production_cost_sl,

                        COALESCE(s.sold_qty, 0) AS sold_qty,
                        COALESCE(s.sales_amount_usd, 0) AS sales_amount_usd,
                        COALESCE(s.sales_amount_sl, 0) AS sales_amount_sl,

                        -- Pre-calculate unit costs with 4 decimal precision to minimize rounding errors
                        CASE
                            WHEN COALESCE(p.produced_qty, 0) > 0 
                            THEN ROUND((COALESCE(p.cost_usd_total, 0) / p.produced_qty)::numeric, 4)
                            ELSE 0
                        END AS unit_cost_usd,

                        CASE
                            WHEN COALESCE(p.produced_qty, 0) > 0 
                            THEN ROUND((COALESCE(p.cost_sl_total, 0) / p.produced_qty)::numeric, 4)
                            ELSE 0
                        END AS unit_cost_sl

                    FROM dates_products dp
                    LEFT JOIN production p ON dp.date = p.date AND dp.product_id = p.product_id
                    LEFT JOIN daily_sales s ON dp.date = s.date AND dp.product_id = s.product_id
                )

                SELECT
                    m.id,
                    m.date,
                    m.product_id,

                    m.produced_qty,
                    m.production_cost_usd,
                    m.production_cost_sl,

                    -- Unit Production Cost (display with 4 decimals for transparency)
                    m.unit_cost_usd AS unit_production_cost_usd,
                    m.unit_cost_sl AS unit_production_cost_sl,

                    m.sold_qty,
                    m.sales_amount_usd,
                    m.sales_amount_sl,

                    -- Avg Sales Price (rounded to 4 decimals)
                    CASE
                        WHEN m.sold_qty > 0 THEN ROUND((m.sales_amount_usd / m.sold_qty)::numeric, 4)
                        ELSE 0
                    END AS avg_sales_price_usd,

                    CASE
                        WHEN m.sold_qty > 0 THEN ROUND((m.sales_amount_sl / m.sold_qty)::numeric, 4)
                        ELSE 0
                    END AS avg_sales_price_sl,

                    -- Cost of Sales: Use pre-calculated unit cost, then round final result to 2 decimals
                    ROUND((m.sold_qty * m.unit_cost_usd)::numeric, 2) AS cost_of_sales_usd,
                    ROUND((m.sold_qty * m.unit_cost_sl)::numeric, 2) AS cost_of_sales_sl,

                    -- Profit: sales - COGS, rounded to 2 decimals
                    ROUND((m.sales_amount_usd - (m.sold_qty * m.unit_cost_usd))::numeric, 2) AS profit_amount_usd,
                    ROUND((m.sales_amount_sl - (m.sold_qty * m.unit_cost_sl))::numeric, 2) AS profit_amount_sl

                FROM metrics m
            )
        """)
