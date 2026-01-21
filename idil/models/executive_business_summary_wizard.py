from odoo import models, fields
from odoo.exceptions import ValidationError

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
    KeepTogether,
)
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle
from reportlab.graphics.charts.barcharts import VerticalBarChart

import io
import base64
from datetime import timedelta


# =============================================================================
# PREMIUM COLOR PALETTE
# =============================================================================
class Colors:
    # Primary brand colors
    GOLD = "#C9A227"
    GOLD_DARK = "#A8860D"
    GOLD_LIGHT = "#E8D48B"
    
    # Neutral palette
    DARK = "#1A1A2E"
    DARK_SECONDARY = "#2D2D44"
    MEDIUM = "#4A4A68"
    LIGHT = "#6E6E8F"
    LIGHTER = "#9E9EBF"
    LIGHTEST = "#F5F5FA"
    WHITE = "#FFFFFF"
    
    # Accent colors
    SUCCESS = "#10B981"
    SUCCESS_DARK = "#059669"
    INFO = "#3B82F6"
    INFO_DARK = "#2563EB"
    WARNING = "#F59E0B"
    WARNING_DARK = "#D97706"
    DANGER = "#EF4444"
    DANGER_DARK = "#DC2626"
    
    # Subtle backgrounds
    BG_GOLD = "#FEF9E7"
    BG_SUCCESS = "#ECFDF5"
    BG_INFO = "#EFF6FF"
    BG_WARNING = "#FFFBEB"
    BG_DANGER = "#FEF2F2"
    
    # Borders and dividers
    BORDER = "#E5E5EA"
    BORDER_DARK = "#D1D1D6"


class ExecutiveBusinessSummaryWizard(models.TransientModel):
    _name = "idil.executive.business.summary.wizard"
    _description = "Executive Business Summary (Owner PDF)"

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)

    def generate_pdf_report(self):
        return self._generate_and_process_report(download=True)

    def view_report(self):
        result = self._generate_and_process_report(download=False)
        if result.get("type") == "ir.actions.act_url":
            result["target"] = "new"
        return result

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    def _money(self, v):
        """Format monetary value with $ and commas"""
        return f"${float(v or 0.0):,.2f}"

    def _pct(self, n, d):
        """Calculate and format percentage"""
        d = float(d or 0.0)
        if d == 0:
            return "0.00%"
        return f"{(float(n or 0.0) / d) * 100.0:,.2f}%"

    def _get_styles(self, base):
        """Create premium typography styles"""
        return {
            "normal": base["Normal"],
            
            # Hero title for report header
            "hero_title": ParagraphStyle(
                "hero_title",
                parent=base["Title"],
                fontSize=24,
                leading=30,
                alignment=TA_CENTER,
                textColor=colors.HexColor(Colors.DARK),
                fontName="Helvetica-Bold",
                spaceAfter=4,
            ),
            
            # Subtitle for date range
            "hero_subtitle": ParagraphStyle(
                "hero_subtitle",
                parent=base["Normal"],
                fontSize=11,
                alignment=TA_CENTER,
                textColor=colors.HexColor(Colors.MEDIUM),
                fontName="Helvetica",
                spaceAfter=16,
            ),
            
            # Section headers
            "section_header": ParagraphStyle(
                "section_header",
                parent=base["Heading2"],
                fontSize=14,
                leading=18,
                textColor=colors.HexColor(Colors.DARK),
                fontName="Helvetica-Bold",
                spaceBefore=8,
                spaceAfter=8,
                borderPadding=0,
            ),
            
            # Company info (header)
            "company_name": ParagraphStyle(
                "company_name",
                parent=base["Normal"],
                fontSize=18,
                alignment=TA_RIGHT,
                textColor=colors.HexColor(Colors.DARK),
                fontName="Helvetica-Bold",
            ),
            "company_info": ParagraphStyle(
                "company_info",
                parent=base["Normal"],
                fontSize=9,
                alignment=TA_RIGHT,
                textColor=colors.HexColor(Colors.MEDIUM),
                leading=13,
            ),
            
            # KPI tile styles
            "kpi_value": ParagraphStyle(
                "kpi_value",
                parent=base["Normal"],
                fontSize=16,
                fontName="Helvetica-Bold",
                textColor=colors.HexColor(Colors.DARK),
            ),
            "kpi_label": ParagraphStyle(
                "kpi_label",
                parent=base["Normal"],
                fontSize=8,
                textColor=colors.HexColor(Colors.LIGHT),
                fontName="Helvetica",
            ),
            
            # Card styles
            "card_title": ParagraphStyle(
                "card_title",
                parent=base["Normal"],
                fontSize=11,
                textColor=colors.HexColor(Colors.WHITE),
                fontName="Helvetica-Bold",
            ),
            "card_subtitle": ParagraphStyle(
                "card_subtitle",
                parent=base["Normal"],
                fontSize=9,
                textColor=colors.HexColor(Colors.DARK),
                fontName="Helvetica-Bold",
            ),
            
            # Table cells
            "cell_left": ParagraphStyle(
                "cell_left",
                parent=base["Normal"],
                fontSize=9,
                textColor=colors.HexColor(Colors.DARK_SECONDARY),
                fontName="Helvetica",
            ),
            "cell_center": ParagraphStyle(
                "cell_center",
                parent=base["Normal"],
                fontSize=9,
                alignment=TA_CENTER,
                textColor=colors.HexColor(Colors.DARK_SECONDARY),
                fontName="Helvetica",
            ),
            "cell_right": ParagraphStyle(
                "cell_right",
                parent=base["Normal"],
                fontSize=9,
                alignment=TA_RIGHT,
                textColor=colors.HexColor(Colors.DARK_SECONDARY),
                fontName="Helvetica",
            ),
            "cell_right_bold": ParagraphStyle(
                "cell_right_bold",
                parent=base["Normal"],
                fontSize=9,
                alignment=TA_RIGHT,
                textColor=colors.HexColor(Colors.DARK),
                fontName="Helvetica-Bold",
            ),
            
            # Table headers
            "th": ParagraphStyle(
                "th",
                parent=base["Normal"],
                fontSize=9,
                textColor=colors.HexColor(Colors.WHITE),
                fontName="Helvetica-Bold",
            ),
            "th_dark": ParagraphStyle(
                "th_dark",
                parent=base["Normal"],
                fontSize=9,
                textColor=colors.HexColor(Colors.DARK),
                fontName="Helvetica-Bold",
            ),
            
            # Footer
            "footer": ParagraphStyle(
                "footer",
                parent=base["Normal"],
                fontSize=8,
                textColor=colors.HexColor(Colors.LIGHT),
            ),
            
            # Small text
            "small": ParagraphStyle(
                "small",
                parent=base["Normal"],
                fontSize=8,
                textColor=colors.HexColor(Colors.LIGHT),
            ),
        }

    def _build_premium_header(self, company, content_w, styles):
        """Build elegant header with logo and company info"""
        elements = []
        
        # Logo
        logo_cell = Paragraph("", styles["normal"])
        if company.logo:
            try:
                logo_cell = Image(
                    io.BytesIO(base64.b64decode(company.logo)), 
                    width=120, 
                    height=60
                )
            except Exception:
                pass
        
        # Company info block
        company_block = f"""
        <b>{(company.name or 'COMPANY').upper()}</b><br/>
        <font size="9" color="{Colors.MEDIUM}">
        {company.partner_id.city or ''}{', ' if company.partner_id.city else ''}{company.partner_id.country_id.name or ''}<br/>
        {company.partner_id.phone or ''} • {company.partner_id.email or ''}<br/>
        {company.website or ''}
        </font>
        """
        info_cell = Paragraph(company_block, styles["company_name"])
        
        header_tbl = Table(
            [[logo_cell, info_cell]], 
            colWidths=[140, content_w - 140]
        )
        header_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_tbl)
        elements.append(Spacer(1, 16))
        
        # Elegant gold divider line
        divider = Drawing(content_w, 3)
        divider.add(Rect(0, 1, content_w, 1.5, 
                        strokeColor=None, 
                        fillColor=colors.HexColor(Colors.GOLD)))
        elements.append(divider)
        elements.append(Spacer(1, 20))
        
        # Report Title
        elements.append(Paragraph("Executive Business Summary", styles["hero_title"]))
        elements.append(Paragraph(
            f"Financial Performance Report • {self.start_date.strftime('%B %d, %Y')} to {self.end_date.strftime('%B %d, %Y')}",
            styles["hero_subtitle"]
        ))
        elements.append(Spacer(1, 8))
        
        return elements

    def _build_section_header(self, title, content_w, accent_color=None):
        """Build elegant section header with accent line"""
        accent = accent_color or Colors.GOLD
        
        d = Drawing(content_w, 28)
        # Accent bar on left
        d.add(Rect(0, 6, 4, 16, strokeColor=None, fillColor=colors.HexColor(accent)))
        # Title text
        d.add(String(14, 10, title, fontName="Helvetica-Bold", fontSize=12, 
                    fillColor=colors.HexColor(Colors.DARK)))
        return d

    def _build_kpi_tile(self, width, height, label, value, accent_color, icon="●"):
        """Build premium KPI tile with accent and shadow effect"""
        d = Drawing(width, height)
        
        # Shadow (subtle offset rectangle)
        d.add(Rect(2, -2, width - 4, height - 4, 
                  strokeColor=None, 
                  fillColor=colors.HexColor("#E8E8EE"),
                  rx=6, ry=6))
        
        # Main card background
        d.add(Rect(0, 0, width - 4, height - 4, 
                  strokeColor=colors.HexColor(Colors.BORDER),
                  strokeWidth=0.5,
                  fillColor=colors.HexColor(Colors.WHITE),
                  rx=6, ry=6))
        
        # Left accent bar
        d.add(Rect(0, 0, 5, height - 4, 
                  strokeColor=None, 
                  fillColor=colors.HexColor(accent_color),
                  rx=3, ry=3))
        
        # Icon circle
        d.add(Circle(22, height - 22, 8, 
                    strokeColor=None, 
                    fillColor=colors.HexColor(accent_color + "20")))  # 20% opacity
        d.add(String(18, height - 26, icon, 
                    fontName="Helvetica-Bold", 
                    fontSize=10,
                    fillColor=colors.HexColor(accent_color)))
        
        # Value (large, bold)
        d.add(String(14, height - 48, str(value), 
                    fontName="Helvetica-Bold", 
                    fontSize=15,
                    fillColor=colors.HexColor(Colors.DARK)))
        
        # Label (small, gray)
        d.add(String(14, 10, str(label), 
                    fontName="Helvetica", 
                    fontSize=8,
                    fillColor=colors.HexColor(Colors.LIGHT)))
        
        return d

    def _build_summary_card(self, title, rows, width, styles, accent_color=None):
        """Build premium summary card with header and data rows"""
        accent = accent_color or Colors.GOLD
        
        # Build data rows
        data = [[Paragraph(f"<b>{title}</b>", styles["card_title"]), ""]]
        
        for i, (key, val) in enumerate(rows):
            # Alternate row backgrounds
            data.append([
                Paragraph(str(key), styles["cell_left"]),
                Paragraph(str(val), styles["cell_right_bold"]),
            ])
        
        tbl = Table(data, colWidths=[width * 0.60, width * 0.40])
        
        style_commands = [
            # Header row
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(accent)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("SPAN", (0, 0), (-1, 0)),
            ("ALIGN", (0, 0), (-1, 0), "LEFT"),
            
            # All cells
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
            ("TOPPADDING", (0, 1), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            
            # Data rows background
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor(Colors.WHITE)),
            
            # Outer border only
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(Colors.BORDER)),
            
            # Subtle inner lines
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor(Colors.BORDER)),
        ]
        
        # Zebra striping
        for i in range(2, len(data), 2):
            style_commands.append(
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor(Colors.LIGHTEST))
            )
        
        tbl.setStyle(TableStyle(style_commands))
        return tbl

    def _build_data_table(self, columns, rows, col_widths, styles, header_color=None):
        """Build premium styled data table"""
        header_bg = header_color or Colors.DARK_SECONDARY
        
        # Build header row
        data = [[Paragraph(f"<b>{c}</b>", styles["th"]) for c in columns]]
        
        # Add data rows
        for row in rows:
            data.append(row)
        
        tbl = Table(data, colWidths=col_widths, splitByRow=1, repeatRows=1)
        
        style_commands = [
            # Header
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            
            # All cells
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            
            # Data rows
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor(Colors.WHITE)),
            
            # Borders
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor(Colors.BORDER)),
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor(Colors.BORDER)),
        ]
        
        # Zebra striping
        for i in range(2, len(data), 2):
            style_commands.append(
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor(Colors.LIGHTEST))
            )
        
        tbl.setStyle(TableStyle(style_commands))
        return tbl

    def _build_chart_box(self, title, width, height, chart_builder, accent_color=None):
        """Build chart inside a premium bordered box"""
        accent = accent_color or Colors.GOLD
        
        d = Drawing(width, height)
        
        # Shadow
        d.add(Rect(3, -3, width - 6, height - 6,
                  strokeColor=None,
                  fillColor=colors.HexColor("#E8E8EE"),
                  rx=4, ry=4))
        
        # Main box
        d.add(Rect(0, 0, width - 6, height - 6,
                  strokeColor=colors.HexColor(Colors.BORDER),
                  strokeWidth=0.5,
                  fillColor=colors.HexColor(Colors.WHITE),
                  rx=4, ry=4))
        
        # Title bar
        d.add(Rect(0, height - 32, width - 6, 26,
                  strokeColor=None,
                  fillColor=colors.HexColor(Colors.LIGHTEST),
                  rx=4, ry=4))
        d.add(Rect(0, height - 32, width - 6, 16,
                  strokeColor=None,
                  fillColor=colors.HexColor(Colors.LIGHTEST)))
        
        # Accent dot
        d.add(Circle(16, height - 19, 4,
                    strokeColor=None,
                    fillColor=colors.HexColor(accent)))
        
        # Title text
        d.add(String(28, height - 23, title,
                    fontName="Helvetica-Bold",
                    fontSize=9,
                    fillColor=colors.HexColor(Colors.DARK)))
        
        # Build inner chart
        inner_w = width - 30
        inner_h = height - 60
        chart = chart_builder(inner_w, inner_h)
        chart.x = 16
        chart.y = 16
        d.add(chart)
        
        return d

    def _status_badge(self, text, bg_color, text_color, styles):
        """Create a status badge paragraph"""
        return Paragraph(
            f'<font color="{text_color}" size="8"><b>{text}</b></font>',
            styles["cell_center"]
        )

    def _icon_dot(self, hex_color, styles):
        """Create colored indicator dot"""
        return Paragraph(
            f'<font color="{hex_color}"><b>●</b></font>',
            styles["cell_center"]
        )

    def _col_exists(self, table, col):
        """Check if a column exists in a table"""
        self.env.cr.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s AND column_name=%s
            LIMIT 1
        """, (table, col))
        return bool(self.env.cr.fetchone())

    # =========================================================================
    # MAIN REPORT GENERATION
    # =========================================================================
    def _generate_and_process_report(self, download=True):
        """Generate premium Executive Business Summary PDF"""
        self.ensure_one()
        
        if self.start_date > self.end_date:
            raise ValidationError("Start Date must be before End Date.")

        company = self.env.company
        start_minus_1 = self.start_date - timedelta(days=1)

        # Document setup
        pagesize = landscape(A4)
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=pagesize,
            leftMargin=28,
            rightMargin=28,
            topMargin=28,
            bottomMargin=36,
        )
        page_w, page_h = pagesize
        content_w = page_w - doc.leftMargin - doc.rightMargin

        # Footer function
        def _footer(canvas, doc_):
            canvas.saveState()
            
            # Footer divider line
            canvas.setStrokeColor(colors.HexColor(Colors.BORDER))
            canvas.setLineWidth(0.5)
            canvas.line(doc_.leftMargin, 28, page_w - doc_.rightMargin, 28)
            
            # Left side: branding
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.HexColor(Colors.LIGHT))
            canvas.drawString(doc_.leftMargin, 14, 
                            f"Generated by BizCore • {company.name}")
            
            # Right side: page number
            canvas.drawRightString(page_w - doc_.rightMargin, 14, 
                                  f"Page {doc_.page}")
            
            # Center: Confidential notice
            canvas.drawCentredString(page_w / 2, 14, 
                                    "Confidential • For Management Use Only")
            
            canvas.restoreState()

        # Setup styles
        base = getSampleStyleSheet()
        styles = self._get_styles(base)

        elements = []

        # =====================================================================
        # HEADER
        # =====================================================================
        elements += self._build_premium_header(company, content_w, styles)

        # =====================================================================
        # FETCH DATA
        # =====================================================================
        # Period financials
        period_query = """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN ca."FinancialReporting"='PL' AND h.code LIKE '4%%'
                        THEN (COALESCE(tl.cr_amount,0) - COALESCE(tl.dr_amount,0))
                        ELSE 0
                    END
                ),0) AS total_sales,
                COALESCE(SUM(
                    CASE
                        WHEN ca.account_type='COGS'
                        THEN (COALESCE(tl.dr_amount,0) - COALESCE(tl.cr_amount,0))
                        ELSE 0
                    END
                ),0) AS total_cogs,
                COALESCE(SUM(
                    CASE
                        WHEN ca."FinancialReporting"='PL'
                        AND (h.code LIKE '5%%' OR h.code LIKE '6%%')
                        AND COALESCE(ca.account_type,'') <> 'COGS'
                        THEN (COALESCE(tl.dr_amount,0) - COALESCE(tl.cr_amount,0))
                        ELSE 0
                    END
                ),0) AS total_expenses
            FROM idil_transaction_bookingline tl
            JOIN idil_chart_account ca ON ca.id = tl.account_number
            JOIN idil_chart_account_subheader sh ON sh.id = ca.subheader_id
            JOIN idil_chart_account_header h ON h.id = sh.header_id
            WHERE tl.company_id = %s
            AND tl.transaction_date BETWEEN %s AND %s
        """
        with self.env.cr.savepoint():
            self.env.cr.execute(period_query, (company.id, self.start_date, self.end_date))
            total_sales, total_cogs, total_expenses = self.env.cr.fetchone() or (0, 0, 0)

        gross_profit = float(total_sales) - float(total_cogs)
        net_profit = gross_profit - float(total_expenses)
        profit_margin = self._pct(net_profit, total_sales)
        gross_margin = self._pct(gross_profit, total_sales)

        # Cash balances
        cash_query = """
            SELECT
                COALESCE(SUM(
                    CASE WHEN ca.account_type='cash'
                    THEN (COALESCE(tl.dr_amount,0) - COALESCE(tl.cr_amount,0))
                    ELSE 0 END
                ),0) AS cash_balance,
                COALESCE(SUM(
                    CASE WHEN ca.account_type='bank_transfer'
                    THEN (COALESCE(tl.dr_amount,0) - COALESCE(tl.cr_amount,0))
                    ELSE 0 END
                ),0) AS bank_balance
            FROM idil_transaction_bookingline tl
            JOIN idil_chart_account ca ON ca.id = tl.account_number
            WHERE tl.company_id = %s
            AND tl.transaction_date <= %s
        """
        with self.env.cr.savepoint():
            self.env.cr.execute(cash_query, (company.id, start_minus_1))
            opening_cash, opening_bank = self.env.cr.fetchone() or (0, 0)
        
        with self.env.cr.savepoint():
            self.env.cr.execute(cash_query, (company.id, self.end_date))
            closing_cash, closing_bank = self.env.cr.fetchone() or (0, 0)

        # Cash flow
        cash_flow_query = """
            SELECT
                COALESCE(SUM(CASE WHEN ca.account_type IN ('cash','bank_transfer')
                    THEN COALESCE(tl.dr_amount,0) ELSE 0 END),0) AS cash_in,
                COALESCE(SUM(CASE WHEN ca.account_type IN ('cash','bank_transfer')
                    THEN COALESCE(tl.cr_amount,0) ELSE 0 END),0) AS cash_out
            FROM idil_transaction_bookingline tl
            JOIN idil_chart_account ca ON ca.id = tl.account_number
            WHERE tl.company_id = %s
            AND tl.transaction_date BETWEEN %s AND %s
        """
        with self.env.cr.savepoint():
            self.env.cr.execute(cash_flow_query, (company.id, self.start_date, self.end_date))
            cash_in, cash_out = self.env.cr.fetchone() or (0, 0)
        net_cash_flow = float(cash_in) - float(cash_out)

        # AR/AP
        ar_ap_query = """
            SELECT
                COALESCE(SUM(
                    CASE WHEN ca.account_type='receivable'
                    THEN (COALESCE(tl.dr_amount,0) - COALESCE(tl.cr_amount,0))
                    ELSE 0 END
                ),0) AS customer_outstanding,
                COALESCE(SUM(
                    CASE WHEN ca.account_type='payable'
                    THEN (COALESCE(tl.cr_amount,0) - COALESCE(tl.dr_amount,0))
                    ELSE 0 END
                ),0) AS vendor_outstanding
            FROM idil_transaction_bookingline tl
            JOIN idil_chart_account ca ON ca.id = tl.account_number
            WHERE tl.company_id = %s
            AND tl.transaction_date <= %s
        """
        with self.env.cr.savepoint():
            self.env.cr.execute(ar_ap_query, (company.id, self.end_date))
            customer_outstanding, vendor_outstanding = self.env.cr.fetchone() or (0, 0)
        net_exposure = float(customer_outstanding) - float(vendor_outstanding)

        # Alerts
        with self.env.cr.savepoint():
            self.env.cr.execute("SELECT COUNT(*) FROM idil_item WHERE COALESCE(quantity,0) < COALESCE(min,0)")
            low_stock_count = int((self.env.cr.fetchone() or [0])[0] or 0)

        with self.env.cr.savepoint():
            self.env.cr.execute("""
                SELECT COUNT(DISTINCT sol.product_id)
                FROM idil_sale_order_line sol
                LEFT JOIN my_product_product p ON p.id = sol.product_id
                WHERE sol.company_id = %s
                AND sol.create_date::date BETWEEN %s AND %s
                AND COALESCE(p.cost,0) > 0
                AND COALESCE(sol.subtotal_usd,0) < (COALESCE(sol.quantity,0) * COALESCE(p.cost,0))
            """, (company.id, self.start_date, self.end_date))
            negative_margin_products = int((self.env.cr.fetchone() or [0])[0] or 0)

        with self.env.cr.savepoint():
            self.env.cr.execute("""
                SELECT COALESCE(SUM(sol.subtotal_usd),0)
                FROM idil_sale_order_line sol
                WHERE sol.company_id = %s
                AND sol.create_date::date BETWEEN %s AND %s
            """, (company.id, self.start_date, self.end_date))
            sales_total = float((self.env.cr.fetchone() or [0])[0] or 0.0)

        with self.env.cr.savepoint():
            self.env.cr.execute("""
                SELECT COALESCE(SUM(COALESCE(srl.net_amount, srl.subtotal, 0)),0)
                FROM idil_sale_return_line srl
                WHERE srl.create_date::date BETWEEN %s AND %s
            """, (self.start_date, self.end_date))
            returns_total = float((self.env.cr.fetchone() or [0])[0] or 0.0)
        return_ratio = self._pct(returns_total, sales_total)

        # =====================================================================
        # KPI TILES ROW
        # =====================================================================
        tile_w = (content_w - 24) / 4.0
        tile_h = 70
        
        kpi_row = Table(
            [[
                self._build_kpi_tile(tile_w, tile_h, "Total Revenue", 
                                    self._money(total_sales), Colors.SUCCESS, "$"),
                self._build_kpi_tile(tile_w, tile_h, "Gross Profit", 
                                    self._money(gross_profit), Colors.GOLD, "↑"),
                self._build_kpi_tile(tile_w, tile_h, "Net Profit", 
                                    self._money(net_profit), Colors.INFO, "★"),
                self._build_kpi_tile(tile_w, tile_h, "Profit Margin", 
                                    profit_margin, Colors.WARNING, "%"),
            ]],
            colWidths=[tile_w + 6] * 4
        )
        kpi_row.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(kpi_row)
        elements.append(Spacer(1, 20))

        # =====================================================================
        # SUMMARY CARDS ROW
        # =====================================================================
        gap = 16
        card_w = (content_w - (2 * gap)) / 3.0
        
        # Card 1: Period Overview
        card1 = self._build_summary_card(
            "📊 Period Overview",
            [
                ("Total Sales", self._money(total_sales)),
                ("Cost of Goods Sold", self._money(total_cogs)),
                ("Gross Profit", self._money(gross_profit)),
                ("Gross Margin", gross_margin),
                ("Operating Expenses", self._money(total_expenses)),
                ("Net Profit", self._money(net_profit)),
            ],
            card_w, styles, Colors.GOLD
        )
        
        # Card 2: Cash Position
        card2 = self._build_summary_card(
            "💰 Cash Position",
            [
                ("Opening Cash", self._money(opening_cash)),
                ("Opening Bank", self._money(opening_bank)),
                ("Cash In (Period)", self._money(cash_in)),
                ("Cash Out (Period)", self._money(cash_out)),
                ("Closing Cash", self._money(closing_cash)),
                ("Closing Bank", self._money(closing_bank)),
            ],
            card_w, styles, Colors.SUCCESS
        )
        
        # Card 3: Receivables & Payables
        card3 = self._build_summary_card(
            "📋 Receivables & Payables",
            [
                ("Customer Outstanding (AR)", self._money(customer_outstanding)),
                ("Vendor Outstanding (AP)", self._money(vendor_outstanding)),
                ("Net Exposure (AR - AP)", self._money(net_exposure)),
                ("", ""),
                ("Low Stock Alerts", str(low_stock_count)),
                ("Negative Margin Products", str(negative_margin_products)),
            ],
            card_w, styles, Colors.INFO
        )
        
        cards_row = Table(
            [[card1, "", card2, "", card3]],
            colWidths=[card_w, gap, card_w, gap, card_w]
        )
        cards_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(cards_row)
        elements.append(Spacer(1, 20))

        # =====================================================================
        # CHARTS ROW
        # =====================================================================
        chart_gap = 16
        chart_w = (content_w - chart_gap) / 2.0
        chart_h = 200

        def build_performance_chart(inner_w, inner_h):
            bc = VerticalBarChart()
            bc.x = 30
            bc.y = 10
            bc.height = inner_h - 20
            bc.width = inner_w - 50
            bc.data = [[
                float(total_sales), 
                float(total_cogs), 
                float(total_expenses), 
                float(net_profit)
            ]]
            bc.categoryAxis.categoryNames = ["Revenue", "COGS", "Expenses", "Net Profit"]
            bc.categoryAxis.labels.fontName = "Helvetica"
            bc.categoryAxis.labels.fontSize = 8
            bc.valueAxis.labels.fontName = "Helvetica"
            bc.valueAxis.labels.fontSize = 8
            bc.valueAxis.valueMin = 0
            maxv = max(float(total_sales), float(total_cogs), 
                      float(total_expenses), abs(float(net_profit)), 1.0)
            bc.valueAxis.valueMax = maxv * 1.25
            bc.valueAxis.valueStep = max(maxv / 5.0, 1.0)
            bc.barWidth = 20
            bc.groupSpacing = 12
            bc.barSpacing = 6
            bc.bars[0].fillColor = colors.HexColor(Colors.SUCCESS)
            bc.bars[0].strokeColor = None
            return bc

        def build_cash_flow_chart(inner_w, inner_h):
            bc = VerticalBarChart()
            bc.x = 30
            bc.y = 10
            bc.height = inner_h - 20
            bc.width = inner_w - 50
            bc.data = [[float(cash_in), float(cash_out), net_cash_flow]]
            bc.categoryAxis.categoryNames = ["Cash In", "Cash Out", "Net Flow"]
            bc.categoryAxis.labels.fontName = "Helvetica"
            bc.categoryAxis.labels.fontSize = 8
            bc.valueAxis.labels.fontName = "Helvetica"
            bc.valueAxis.labels.fontSize = 8
            bc.valueAxis.valueMin = 0
            maxv = max(float(cash_in), float(cash_out), abs(net_cash_flow), 1.0)
            bc.valueAxis.valueMax = maxv * 1.25
            bc.valueAxis.valueStep = max(maxv / 5.0, 1.0)
            bc.barWidth = 26
            bc.groupSpacing = 16
            bc.barSpacing = 8
            bc.bars[0].fillColor = colors.HexColor(Colors.INFO)
            bc.bars[0].strokeColor = None
            return bc

        perf_chart = self._build_chart_box(
            "Financial Performance Overview", 
            chart_w, chart_h, 
            build_performance_chart,
            Colors.GOLD
        )
        cash_chart = self._build_chart_box(
            "Cash Flow Analysis", 
            chart_w, chart_h, 
            build_cash_flow_chart,
            Colors.INFO
        )
        
        charts_row = Table(
            [[perf_chart, "", cash_chart]],
            colWidths=[chart_w, chart_gap, chart_w]
        )
        charts_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(charts_row)

        # =====================================================================
        # PAGE 2: DETAILED ANALYTICS
        # =====================================================================
        elements.append(PageBreak())
        
        # Section header
        elements.append(self._build_section_header("Top Selling Products", content_w, Colors.SUCCESS))
        elements.append(Spacer(1, 12))

        # Fetch top products
        with self.env.cr.savepoint():
            self.env.cr.execute("""
                SELECT
                    p.id,
                    p.name,
                    COALESCE(SUM(sol.quantity),0) AS qty_sold,
                    COALESCE(SUM(sol.subtotal_usd),0) AS sales_usd,
                    COALESCE(AVG(p.cost),0) AS avg_cost,
                    COALESCE(SUM(sol.quantity) * AVG(p.cost),0) AS est_cost_usd,
                    COALESCE(SUM(sol.subtotal_usd) - (SUM(sol.quantity) * AVG(p.cost)),0) AS profit_usd,
                    CASE
                        WHEN COALESCE(SUM(sol.subtotal_usd),0) = 0 THEN 0
                        ELSE (COALESCE(SUM(sol.subtotal_usd) - (SUM(sol.quantity) * AVG(p.cost)),0) / SUM(sol.subtotal_usd)) * 100
                    END AS margin_pct
                FROM idil_sale_order_line sol
                LEFT JOIN my_product_product p ON p.id = sol.product_id
                WHERE sol.company_id = %s
                AND sol.create_date::date BETWEEN %s AND %s
                GROUP BY p.id, p.name
                ORDER BY sales_usd DESC
                LIMIT 10
            """, (company.id, self.start_date, self.end_date))
            top_products = self.env.cr.fetchall() or []

        # Build product table
        prod_rows = []
        prod_labels = []
        prod_vals = []
        for i, (pid, name, qty, sales, avg_cost, est_cost, profit, margin) in enumerate(top_products):
            # Margin badge color
            margin_val = float(margin or 0)
            if margin_val >= 20:
                margin_color = Colors.SUCCESS
            elif margin_val >= 0:
                margin_color = Colors.WARNING
            else:
                margin_color = Colors.DANGER
            
            prod_rows.append([
                Paragraph(f"<font color='{Colors.SUCCESS}'><b>●</b></font>", styles["cell_center"]),
                Paragraph(str(name or "N/A")[:35], styles["cell_left"]),
                Paragraph(f"{float(qty or 0):,.0f}", styles["cell_right"]),
                Paragraph(self._money(sales), styles["cell_right"]),
                Paragraph(self._money(profit), styles["cell_right"]),
                Paragraph(f"<font color='{margin_color}'><b>{margin_val:,.1f}%</b></font>", styles["cell_right"]),
            ])
            
            if i < 6:
                prod_labels.append((name or "N/A")[:10])
                prod_vals.append(float(sales or 0.0))

        elements.append(self._build_data_table(
            ["", "Product Name", "Qty Sold", "Revenue", "Profit", "Margin"],
            prod_rows,
            [content_w * 0.04, content_w * 0.40, content_w * 0.10, 
             content_w * 0.16, content_w * 0.16, content_w * 0.14],
            styles,
            Colors.SUCCESS_DARK
        ))
        elements.append(Spacer(1, 16))

        # Product sales chart
        def build_product_chart(inner_w, inner_h):
            bc = VerticalBarChart()
            bc.x = 28
            bc.y = 10
            bc.width = inner_w - 40
            bc.height = inner_h - 20
            bc.data = [prod_vals] if prod_vals else [[0]]
            bc.categoryAxis.categoryNames = prod_labels if prod_labels else ["No Data"]
            bc.categoryAxis.labels.fontSize = 7
            bc.categoryAxis.labels.fontName = "Helvetica"
            bc.valueAxis.labels.fontSize = 7
            bc.valueAxis.labels.fontName = "Helvetica"
            bc.valueAxis.valueMin = 0
            mv = max(prod_vals) if prod_vals else 1.0
            bc.valueAxis.valueMax = mv * 1.25
            bc.valueAxis.valueStep = max(mv / 5.0, 1.0)
            bc.bars[0].fillColor = colors.HexColor(Colors.SUCCESS)
            bc.bars[0].strokeColor = None
            bc.barWidth = 14
            bc.groupSpacing = 8
            return bc

        elements.append(self._build_chart_box(
            "Top Products by Revenue",
            content_w * 0.6, 180,
            build_product_chart,
            Colors.SUCCESS
        ))
        elements.append(Spacer(1, 24))

        # =====================================================================
        # SALESPERSON PERFORMANCE
        # =====================================================================
        elements.append(self._build_section_header("Salesperson Performance", content_w, Colors.GOLD))
        elements.append(Spacer(1, 12))

        with self.env.cr.savepoint():
            self.env.cr.execute("""
                SELECT
                    sp.name,
                    COUNT(DISTINCT tb.sale_order_id) AS orders_count,
                    COALESCE(SUM(tb.amount),0) AS total_sales,
                    COALESCE(SUM(tb.amount_paid),0) AS total_paid,
                    COALESCE(SUM(tb.remaining_amount),0) AS total_balance
                FROM idil_transaction_booking tb
                LEFT JOIN idil_sales_sales_personnel sp ON sp.id = tb.sales_person_id
                WHERE tb.sales_person_id IS NOT NULL
                AND tb.trx_date BETWEEN %s AND %s
                GROUP BY sp.name
                ORDER BY total_sales DESC
                LIMIT 10
            """, (self.start_date, self.end_date))
            top_salespeople = self.env.cr.fetchall() or []

        sp_rows = []
        sp_labels = []
        sp_vals = []
        for i, (name, orders, total, paid, balance) in enumerate(top_salespeople):
            collection_rate = self._pct(paid, total)
            
            sp_rows.append([
                Paragraph(f"<font color='{Colors.GOLD}'><b>●</b></font>", styles["cell_center"]),
                Paragraph(str(name or "N/A")[:25], styles["cell_left"]),
                Paragraph(str(int(orders or 0)), styles["cell_center"]),
                Paragraph(self._money(total), styles["cell_right"]),
                Paragraph(self._money(paid), styles["cell_right"]),
                Paragraph(self._money(balance), styles["cell_right"]),
                Paragraph(f"<b>{collection_rate}</b>", styles["cell_right"]),
            ])
            
            if i < 6:
                sp_labels.append((name or "N/A")[:8])
                sp_vals.append(float(total or 0.0))

        elements.append(self._build_data_table(
            ["", "Salesperson", "Orders", "Total Sales", "Collected", "Balance", "Collection %"],
            sp_rows,
            [content_w * 0.04, content_w * 0.24, content_w * 0.08, 
             content_w * 0.16, content_w * 0.16, content_w * 0.16, content_w * 0.16],
            styles,
            Colors.GOLD_DARK
        ))
        elements.append(Spacer(1, 16))

        # Salesperson chart
        def build_sp_chart(inner_w, inner_h):
            bc = VerticalBarChart()
            bc.x = 28
            bc.y = 10
            bc.width = inner_w - 40
            bc.height = inner_h - 20
            bc.data = [sp_vals] if sp_vals else [[0]]
            bc.categoryAxis.categoryNames = sp_labels if sp_labels else ["No Data"]
            bc.categoryAxis.labels.fontSize = 7
            bc.categoryAxis.labels.fontName = "Helvetica"
            bc.valueAxis.labels.fontSize = 7
            bc.valueAxis.labels.fontName = "Helvetica"
            bc.valueAxis.valueMin = 0
            mv = max(sp_vals) if sp_vals else 1.0
            bc.valueAxis.valueMax = mv * 1.25
            bc.valueAxis.valueStep = max(mv / 5.0, 1.0)
            bc.bars[0].fillColor = colors.HexColor(Colors.GOLD)
            bc.bars[0].strokeColor = None
            bc.barWidth = 14
            bc.groupSpacing = 8
            return bc

        elements.append(self._build_chart_box(
            "Top Salespeople by Revenue",
            content_w * 0.6, 180,
            build_sp_chart,
            Colors.GOLD
        ))

        # =====================================================================
        # BUILD PDF
        # =====================================================================
        doc.build(elements, onFirstPage=_footer, onLaterPages=_footer)
        buffer.seek(0)
        pdf_data = buffer.read()
        buffer.close()

        attachment = self.env["ir.attachment"].create({
            "name": f"Executive_Business_Summary_{self.start_date}_{self.end_date}.pdf",
            "type": "binary",
            "datas": base64.b64encode(pdf_data),
            "mimetype": "application/pdf",
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download={'true' if download else 'false'}",
            "target": "new",
        }
