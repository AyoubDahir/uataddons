from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class IdilBudget(models.Model):
    _name = 'idil.budget'
    _description = 'Budget and Control'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char('Budget Name', required=True, tracking=True)
    date_start = fields.Date('Start Date', required=True, tracking=True)
    date_end = fields.Date('End Date', required=True, tracking=True)
    department_id = fields.Many2one('idil.employee_department', string='Department', tracking=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')
    ], default='draft', string='Status', tracking=True)

    line_ids = fields.One2many('idil.budget.line', 'budget_id', string='Budget Lines')

    control_action = fields.Selection([
        ('none', 'No Control'),
        ('warn', 'Warn'),
        ('block', 'Block')
    ], string='Overspending Action', default='warn', help="Action to take when actuals exceed budget.", tracking=True)
    
    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_refresh_actuals(self):
        for rec in self:
            rec.line_ids._compute_actual_amount()

    def action_print_report(self):
        self.action_refresh_actuals()
        return self.env.ref('idil.action_report_budget').report_action(self)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start > rec.date_end:
                raise UserError(_('Start Date must be before End Date.'))
                
    def get_budget_state(self, account_id, date, department_id=False):
        """
        Return dict describing budget status for an account/date/department.
        {
            'active': bool,
            'planned': float,
            'used': float,
            'remaining': float,
            'msg': str
        }
        """
        domain = [
            ('state', '=', 'confirmed'),
            ('date_start', '<=', date),
            ('date_end', '>=', date),
            ('company_id', '=', self.env.company.id)
        ]
        
        # Filter budgets by department if provided, else ensure global budgets (so departmental budgets don't leak into global checks)
        if department_id:
             domain.append(('department_id', '=', department_id))
        else:
             domain.append(('department_id', '=', False))

        budgets = self.search(domain)
        if not budgets:
            return {'active': False}
            
        relevant_lines = budgets.mapped('line_ids').filtered(lambda l: l.account_id.id == account_id)
        if not relevant_lines:
            return {'active': False}
            
        min_date = min(budgets.mapped('date_start'))
        max_date = max(budgets.mapped('date_end'))
        
        BookingLine = self.env['idil.transaction_bookingline']
        actual_domain = [
            ('account_number', '=', account_id),
            ('transaction_date', '>=', min_date),
            ('transaction_date', '<=', max_date),
            ('company_id', '=', self.env.company.id)
        ]
        
        if department_id:
            # Filter actuals by department (via employee)
            actual_domain.append(('employee_id.department_id', '=', department_id))
        else:
            # For global budget, include transactions with NO department (either no employee or employee with no dept)
            actual_domain.extend(['|', ('employee_id', '=', False), ('employee_id.department_id', '=', False)])
        
        booked_lines = BookingLine.search(actual_domain)
        
        total_dr = sum(booked_lines.mapped('dr_amount'))
        total_cr = sum(booked_lines.mapped('cr_amount'))
        
        account = self.env['idil.chart.account'].browse(account_id)
        is_revenue = account.code and account.code.startswith('4')
        
        if is_revenue:
            current_actual = total_cr - total_dr
        else:
            current_actual = total_dr - total_cr
            
        total_planned = sum(relevant_lines.mapped('planned_amount'))
        remaining = total_planned - current_actual
        
        return {
            'active': True,
            'planned': total_planned,
            'used': current_actual,
            'remaining': remaining,
            'min_date': min_date,
            'max_date': max_date
        }

    def check_budget_availability(self, account_id, amount, date, department_id=False):
        """
        Check if budget is available for account on date with amount.
        Returns (allowed_bool, message)
        """
        state = self.get_budget_state(account_id, date, department_id)
        if not state.get('active'):
            return True, ""
            
        remaining = state['remaining']
        total_planned = state['planned']
        current_actual = state['used']
        
        if amount > remaining:
            # Re-fetch budgets to check action
            domain = [
                ('state', '=', 'confirmed'),
                ('date_start', '<=', date),
                ('date_end', '>=', date),
                ('company_id', '=', self.env.company.id)
            ]
            if department_id:
                domain.append(('department_id', '=', department_id))
            else:
                domain.append(('department_id', '=', False))
                
            budgets = self.search(domain)
            actions = budgets.mapped('control_action')
            account = self.env['idil.chart.account'].browse(account_id)
            department_name = budgets[0].department_id.name if budgets and budgets[0].department_id else "Global"

            msg = f"Budget Control: Account '{account.name}' (Code: {account.code}).\n" \
                  f"Department: {department_name}\n" \
                  f"Budget Period: {state.get('min_date')} to {state.get('max_date')}.\n" \
                  f"Total Budget: {total_planned:,.2f}\n" \
                  f"Used So Far: {current_actual:,.2f}\n" \
                  f"Remaining: {remaining:,.2f}\n" \
                  f"Requested: {amount:,.2f}\n" \
                  f"Exceeds by: {amount - remaining:,.2f}"

            if 'block' in actions:
                return False, msg
            elif 'warn' in actions:
                return True, "WARNING: " + msg
            
        return True, ""


class IdilBudgetLine(models.Model):
    _name = 'idil.budget.line'
    _description = 'Budget Line'

    budget_id = fields.Many2one('idil.budget', string='Budget', required=True, ondelete='cascade')
    account_id = fields.Many2one('idil.chart.account', string='Account', required=True)
    planned_amount = fields.Float('Planned Amount', required=True)
    
    actual_amount = fields.Float('Actual Amount', compute='_compute_actual_amount', store=True)
    variance = fields.Float('Variance', compute='_compute_actual_amount', store=True)
    percentage = fields.Float('Usage %', compute='_compute_actual_amount', store=True)

    @api.depends('budget_id.date_start', 'budget_id.date_end', 'account_id', 'budget_id.state', 'budget_id.department_id')
    def _compute_actual_amount(self):
        BookingLine = self.env['idil.transaction_bookingline']
        for line in self:
            if not line.budget_id.date_start or not line.budget_id.date_end or not line.account_id:
                line.actual_amount = 0.0
                line.variance = line.planned_amount
                line.percentage = 0.0
                continue
                
            domain = [
                ('account_number', '=', line.account_id.id),
                ('transaction_date', '>=', line.budget_id.date_start),
                ('transaction_date', '<=', line.budget_id.date_end),
                ('company_id', '=', line.budget_id.company_id.id)
            ]
            
            if line.budget_id.department_id:
                domain.append(('employee_id.department_id', '=', line.budget_id.department_id.id))
            else:
                domain.extend(['|', ('employee_id', '=', False), ('employee_id.department_id', '=', False)])
            
            lines = BookingLine.search(domain)
            
            total_dr = sum(lines.mapped('dr_amount'))
            total_cr = sum(lines.mapped('cr_amount'))
            
            # Default Expense logic: Debit - Credit
            actual = total_dr - total_cr
            
            # If Revenue: Credit - Debit
            if line.account_id.code and line.account_id.code.startswith('4'):
                 actual = total_cr - total_dr
            
            line.actual_amount = actual
            line.variance = line.planned_amount - line.actual_amount
            if line.planned_amount:
                line.percentage = (line.actual_amount / line.planned_amount) * 100
            else:
                line.percentage = 0.0
