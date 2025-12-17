from odoo import models, fields, api
import xlsxwriter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    KeepTogether,
)
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io
import base64
from datetime import datetime


class TransactionReportWizard(models.TransientModel):
    _name = "transaction.report.wizard"
    _description = "Transaction Report Wizard"

    account_number = fields.Many2one(
        "idil.chart.account",
        string="Account Number",
        help="Filter transactions by account number",
        required=True,
    )
    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)

    def generate_excel_report(self):
        # Query to compute the previous balance
        previous_balance_query = """
            SELECT 
                SUM(COALESCE(dr_amount, 0)) - SUM(COALESCE(cr_amount, 0)) AS previous_balance
            FROM 
                idil_transaction_bookingline
            WHERE 
                transaction_date < %s
                AND account_number = %s
        """
        self.env.cr.execute(
            previous_balance_query, (self.start_date, self.account_number.id)
        )
        previous_balance_result = self.env.cr.fetchone()
        previous_balance = (
            previous_balance_result[0]
            if previous_balance_result and previous_balance_result[0] is not None
            else 0.0
        )

        # Query to fetch transaction data
        transaction_query = """
            SELECT 
                transaction_date,
                (SELECT code FROM idil_chart_account WHERE id = account_number) AS account_number,
                transaction_booking_id,
                description,
                account_display,
                dr_amount,
                cr_amount,
                ROUND(
                    CAST(
                        SUM(COALESCE(dr_amount, 0) - COALESCE(cr_amount, 0)) OVER (
                            ORDER BY transaction_date, transaction_booking_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        ) + %s AS NUMERIC
                    ), 2
                ) AS running_balance
            FROM 
                idil_transaction_bookingline
            WHERE 
                transaction_date BETWEEN %s AND %s
                AND account_number = %s
            ORDER BY 
                transaction_date, transaction_booking_id
        """
        self.env.cr.execute(
            transaction_query,
            (previous_balance, self.start_date, self.end_date, self.account_number.id),
        )
        transactions = self.env.cr.fetchall()

        # Initialize totals
        total_debit = 0.0
        total_credit = 0.0

        # Create an Excel file in memory
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("Account Statement")

        # Define formats
        bold = workbook.add_format({"bold": True})
        bold_centered = workbook.add_format(
            {"bold": True, "align": "center", "valign": "vcenter"}
        )
        header_format = workbook.add_format(
            {"bold": True, "align": "center", "border": 1, "bg_color": "#D3D3D3"}
        )
        cell_format = workbook.add_format({"border": 1})
        bold_border = workbook.add_format({"bold": True, "border": 1})
        currency_format = workbook.add_format({"num_format": "#,##0.00", "border": 1})

        # Write the report title
        worksheet.merge_range("A1:H1", "Account Statement", bold_centered)
        worksheet.merge_range(
            "A2:H2", f"Date Range: {self.start_date} to {self.end_date}", bold_centered
        )

        # Write header row
        headers = [
            "Transaction Date",
            "Account Number",
            "Transaction ID",
            "Description",
            "Account Display",
            "Debit Amount",
            "Credit Amount",
            "Running Balance",
        ]
        for col, header in enumerate(headers):
            worksheet.write(3, col, header, header_format)

        # Write previous balance as the first row
        row_num = 4
        worksheet.write(
            row_num, 0, "N/A", cell_format
        )  # No transaction date for previous balance
        worksheet.write(row_num, 1, self.account_number.code, cell_format)
        worksheet.write(
            row_num, 2, "N/A", cell_format
        )  # No transaction ID for previous balance
        worksheet.write(row_num, 3, "Previous Balance", cell_format)
        worksheet.write(
            row_num, 4, "", cell_format
        )  # No account display for previous balance
        worksheet.write(row_num, 5, 0.0, currency_format)  # No debit amount
        worksheet.write(row_num, 6, 0.0, currency_format)  # No credit amount
        worksheet.write(
            row_num, 7, previous_balance, currency_format
        )  # Previous balance as running balance

        # Write transaction rows
        row_num += 1
        for transaction in transactions:
            for col_num, value in enumerate(transaction):
                format_to_use = currency_format if col_num in [5, 6, 7] else cell_format
                worksheet.write(row_num, col_num, value, format_to_use)
            # Update totals for debit and credit
            total_debit += transaction[5] if transaction[5] else 0.0
            total_credit += transaction[6] if transaction[6] else 0.0
            row_num += 1

        # Write totals row
        worksheet.write(row_num, 4, "Grand Total", bold_border)
        worksheet.write(row_num, 5, total_debit, bold_border)  # Total debit
        worksheet.write(row_num, 6, total_credit, bold_border)  # Total credit
        worksheet.write(row_num, 7, "", bold_border)  # No running balance for total row

        # Adjust column widths
        worksheet.set_column("A:A", 15)  # Transaction Date
        worksheet.set_column("B:B", 18)  # Account Number
        worksheet.set_column("C:C", 15)  # Transaction ID
        worksheet.set_column("D:D", 30)  # Description
        worksheet.set_column("E:E", 20)  # Account Display
        worksheet.set_column("F:H", 15)  # Debit, Credit, Running Balance

        workbook.close()
        output.seek(0)

        # Encode the Excel file as Base64
        excel_data = base64.b64encode(output.read()).decode("utf-8")
        output.close()

        # Create an attachment
        attachment = self.env["ir.attachment"].create(
            {
                "name": "Account_Statement.xlsx",
                "type": "binary",
                "datas": excel_data,
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "new",
        }

    def generate_pdf_report(self):
        # Query to fetch account details
        account_query = """
            SELECT code, name, currency_id, header_name
            FROM idil_chart_account
            WHERE id = %s
        """
        self.env.cr.execute(account_query, (self.account_number.id,))
        account_result = self.env.cr.fetchone()
        account_code = account_result[0] if account_result else "N/A"
        account_name = account_result[1] if account_result else "N/A"
        account_currency = account_result[2] if account_result else "N/A"
        account_type = account_result[3] if account_result else "N/A"

        # Create PDF document in landscape format
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            rightMargin=30,
            leftMargin=30,
            topMargin=40,
            bottomMargin=30,
        )
        elements = []

        # Define color scheme (matching cash flow statement)
        primary_color = colors.HexColor("#1a237e")  # Dark blue
        secondary_color = colors.HexColor("#3949ab")  # Lighter blue
        light_bg = colors.HexColor("#e8eaf6")  # Light purple/blue
        header_text = colors.HexColor("#c5cae9")  # Light text for header
        success_color = colors.HexColor("#2e7d32")  # Green for positive
        danger_color = colors.HexColor("#c62828")  # Red for negative
        gray_bg = colors.HexColor("#f5f5f5")  # Gray background
        border_color = colors.HexColor("#9e9e9e")  # Border gray
        text_dark = colors.HexColor("#424242")  # Dark text
        text_light = colors.HexColor("#757575")  # Light text

        # Get styles
        styles = getSampleStyleSheet()

        # Create header table (mimicking the dark blue header from cash flow)
        header_data = [
            [Paragraph("<b>Account Statement</b>", ParagraphStyle(
                'HeaderTitle',
                fontName='Helvetica-Bold',
                fontSize=20,
                textColor=colors.white,
                alignment=0,
            ))],
            [Paragraph(f"<b>{account_name}</b> ({account_code})", ParagraphStyle(
                'HeaderSubtitle',
                fontName='Helvetica',
                fontSize=14,
                textColor=colors.white,
                alignment=0,
            ))],
            [Paragraph(
                f"For the Period: <b>{self.start_date.strftime('%m/%d/%Y') if self.start_date else 'N/A'}</b> to "
                f"<b>{self.end_date.strftime('%m/%d/%Y') if self.end_date else 'N/A'}</b>",
                ParagraphStyle(
                    'HeaderPeriod',
                    fontName='Helvetica',
                    fontSize=11,
                    textColor=header_text,
                    alignment=0,
                )
            )],
        ]
        header_table = Table(header_data, colWidths=[730])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), primary_color),
            ('TOPPADDING', (0, 0), (-1, 0), 15),
            ('BOTTOMPADDING', (0, -1), (-1, -1), 15),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('LINEBELOW', (0, -1), (-1, -1), 4, secondary_color),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 15))

        # Account Info Section
        account_info_data = [[
            Paragraph(f"<b>Account Type:</b> {account_type}", ParagraphStyle(
                'AccountInfo', fontName='Helvetica', fontSize=10, textColor=text_dark)),
            Paragraph(f"<b>Currency:</b> {account_currency}", ParagraphStyle(
                'AccountInfo', fontName='Helvetica', fontSize=10, textColor=text_dark)),
        ]]
        account_info_table = Table(account_info_data, colWidths=[365, 365])
        account_info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), light_bg),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('LINEBELOW', (0, 0), (-1, -1), 2, colors.HexColor("#c5cae9")),
        ]))
        elements.append(account_info_table)
        elements.append(Spacer(1, 15))

        # Query to fetch transactions
        transaction_query = """
            SELECT
                transaction_date,
                transaction_booking_id,
                description,
                account_display,
                dr_amount,
                cr_amount,
                ROUND(
                    CAST(
                        SUM(COALESCE(dr_amount, 0) - COALESCE(cr_amount, 0)) OVER (
                            ORDER BY transaction_date, transaction_booking_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                        ) AS NUMERIC
                    ), 2
                ) AS running_balance
            FROM
                idil_transaction_bookingline
            WHERE
                transaction_date BETWEEN %s AND %s
                AND account_number = %s
            ORDER BY
                transaction_date, transaction_booking_id
        """
        self.env.cr.execute(
            transaction_query, (self.start_date, self.end_date, self.account_number.id)
        )
        transactions = self.env.cr.fetchall()

        # Create styled header for table
        header_style = ParagraphStyle(
            'TableHeader',
            fontName='Helvetica-Bold',
            fontSize=10,
            textColor=colors.white,
            alignment=1,
        )
        
        # Table header
        data = [[
            Paragraph("Transaction Date", header_style),
            Paragraph("TRS NO", header_style),
            Paragraph("Description", header_style),
            Paragraph("Debit", header_style),
            Paragraph("Credit", header_style),
            Paragraph("Balance", header_style),
        ]]

        # Cell styles
        cell_style = ParagraphStyle('Cell', fontName='Helvetica', fontSize=9, textColor=text_dark, alignment=1)
        cell_style_left = ParagraphStyle('CellLeft', fontName='Helvetica', fontSize=9, textColor=text_dark, alignment=0)
        debit_style = ParagraphStyle('Debit', fontName='Helvetica', fontSize=9, textColor=success_color, alignment=2)
        credit_style = ParagraphStyle('Credit', fontName='Helvetica', fontSize=9, textColor=danger_color, alignment=2)
        balance_style = ParagraphStyle('Balance', fontName='Helvetica-Bold', fontSize=9, textColor=text_dark, alignment=2)

        for transaction in transactions:
            dr_amount = transaction[4] if transaction[4] else 0.0
            cr_amount = transaction[5] if transaction[5] else 0.0
            balance = transaction[6] if transaction[6] else 0.0
            
            # Format balance with color based on positive/negative
            if balance >= 0:
                balance_cell_style = ParagraphStyle('BalancePos', fontName='Helvetica-Bold', fontSize=9, textColor=success_color, alignment=2)
                balance_text = f"${balance:,.2f}"
            else:
                balance_cell_style = ParagraphStyle('BalanceNeg', fontName='Helvetica-Bold', fontSize=9, textColor=danger_color, alignment=2)
                balance_text = f"(${abs(balance):,.2f})"

            data.append([
                Paragraph(transaction[0].strftime("%m/%d/%Y") if transaction[0] else "", cell_style),
                Paragraph(str(transaction[1]) if transaction[1] else "", cell_style),
                Paragraph(str(transaction[2]) if transaction[2] else "", cell_style_left),
                Paragraph(f"${dr_amount:,.2f}" if dr_amount else "-", debit_style),
                Paragraph(f"(${cr_amount:,.2f})" if cr_amount else "-", credit_style),
                Paragraph(balance_text, balance_cell_style),
            ])

        # Add totals
        total_debit = sum(row[4] for row in transactions if row[4])
        total_credit = sum(row[5] for row in transactions if row[5])
        net_balance = total_debit - total_credit
        
        total_style = ParagraphStyle('Total', fontName='Helvetica-Bold', fontSize=10, textColor=colors.white, alignment=2)
        total_label_style = ParagraphStyle('TotalLabel', fontName='Helvetica-Bold', fontSize=10, textColor=colors.white, alignment=0)
        
        if net_balance >= 0:
            net_text = f"${net_balance:,.2f}"
        else:
            net_text = f"(${abs(net_balance):,.2f})"

        data.append([
            Paragraph("", total_style),
            Paragraph("", total_style),
            Paragraph("GRAND TOTAL", total_label_style),
            Paragraph(f"${total_debit:,.2f}", total_style),
            Paragraph(f"(${total_credit:,.2f})", total_style),
            Paragraph(net_text, total_style),
        ])

        # Create and style the table
        table = Table(data, colWidths=[90, 60, 280, 90, 90, 100])
        
        # Build table styles
        table_styles = [
            # Header row styling
            ('BACKGROUND', (0, 0), (-1, 0), primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('LINEBELOW', (0, 0), (-1, 0), 2, secondary_color),
            
            # Grand total row styling (last row)
            ('BACKGROUND', (0, -1), (-1, -1), primary_color),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
            ('LINEABOVE', (0, -1), (-1, -1), 2, border_color),
            
            # General styling
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            
            # Alternating row colors for data rows
            ('LINEBELOW', (0, 1), (-1, -2), 0.5, colors.HexColor("#eeeeee")),
        ]
        
        # Add alternating row backgrounds
        for i in range(1, len(data) - 1):
            if i % 2 == 0:
                table_styles.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor("#fafafa")))
        
        table.setStyle(TableStyle(table_styles))

        elements.append(table)
        elements.append(Spacer(1, 20))

        # Footer with modern styling
        current_user = self.env.user.name
        current_datetime = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
        
        footer_data = [[
            Paragraph(f"<i>Printed By: {current_user}</i>", ParagraphStyle(
                'FooterLeft', fontName='Helvetica', fontSize=9, textColor=text_light, alignment=0)),
            Paragraph(f"<i>Report Date: {current_datetime}</i>", ParagraphStyle(
                'FooterRight', fontName='Helvetica', fontSize=9, textColor=text_light, alignment=2)),
        ]]
        footer_table = Table(footer_data, colWidths=[365, 365])
        footer_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 1, colors.HexColor("#e0e0e0")),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
        ]))
        elements.append(footer_table)

        # Build the PDF document
        doc.build(elements)

        # Save the PDF as an attachment
        buffer.seek(0)
        pdf_data = buffer.read()
        buffer.close()

        attachment = self.env["ir.attachment"].create(
            {
                "name": "Account_Statement_Report.pdf",
                "type": "binary",
                "datas": base64.b64encode(pdf_data),
                "mimetype": "application/pdf",
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "new",
        }
