from odoo import models, fields, api

class ProductionProfitabilityWizard(models.TransientModel):
    _name = 'idil.production.profitability.wizard'
    _description = 'Production Profitability Report Wizard'

    start_date = fields.Date(string="Start Date", required=True, default=fields.Date.context_today)
    end_date = fields.Date(string="End Date", required=True, default=fields.Date.context_today)

    def action_view_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Production Profitability',
            'res_model': 'idil.report.production.profitability',
            'view_mode': 'tree',
            'domain': [('date', '>=', self.start_date), ('date', '<=', self.end_date)],
            'context': {'search_default_group_product': 1},
        }

    def action_print_pdf(self):
        self.ensure_one()
        # Pass the dates in context or use a domain if the report supports it.
        # Check how the report action is defined. 
        # Usually for SQL view reports, we filter by domain in the action.
        # But for PDF, we need to pass the docids. 
        # Since this is a report on a view, we need to find the records first.
        
        records = self.env['idil.report.production.profitability'].search([
            ('date', '>=', self.start_date), 
            ('date', '<=', self.end_date)
        ])
        
        data = {
            'start_date': self.start_date,
            'end_date': self.end_date,
        }
        
        return self.env.ref('idil.action_report_production_profitability_pdf').report_action(records, data=data)
