import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

class RecurringJournalEntry(models.Model):
    _name = "idil.recurring.journal.entry"
    _description = "Advanced Recurring Journal Entry"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True, default=lambda self: _('New'))
    description = fields.Char(string="Description", required=True)
    
    # Scheduling
    start_date = fields.Date(string="Start Date", required=True, default=fields.Date.context_today)
    
    # 🕒 Changed to Datetime for precision
    next_run_time = fields.Datetime(string="Next Run Time", required=True, default=fields.Datetime.now)
    
    interval_number = fields.Integer(string="Interval Number", default=1, required=True)
    interval_type = fields.Selection([
        ('minutes', 'Minutes'),
        ('hours', 'Hours'),
        ('days', 'Days'),
        ('weeks', 'Weeks'),
        ('months', 'Months'),
        ('years', 'Years'),
    ], string="Interval Unit", default='months', required=True)
    
    end_date = fields.Date(string="End Date", help="Stop running after this date. Leave empty for infinite.")
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('running', 'Running'),
        ('stopped', 'Stopped'),
        ('done', 'Done'),
    ], string="Status", default='draft', tracking=True)

    # Lines template
    line_ids = fields.One2many('idil.recurring.journal.line', 'recurring_id', string="Journal Lines")
    
    # Generated Entries
    generated_entry_ids = fields.One2many('idil.journal.entry', 'recurring_source_id', string="Generated Entries")
    generated_count = fields.Integer(compute='_compute_generated_count')
    
    # 📜 Audit Logs
    log_ids = fields.One2many('idil.recurring.journal.log', 'recurring_id', string="Execution Logs")
    log_count = fields.Integer(compute='_compute_log_count')

    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')

    run_count = fields.Integer(string="Total Runs", default=0, readonly=True, help="Number of times this entry has been successfully generated.")
    
    cron_id = fields.Many2one('ir.cron', string="Scheduled Action", ondelete='set null', copy=False)

    # Timer field
    remaining_time = fields.Char(string="Next Run In", compute='_compute_remaining_time')

    @api.depends('next_run_time', 'state')
    def _compute_remaining_time(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.remaining_time = ""
            if rec.state == 'running' and rec.next_run_time:
                diff = rec.next_run_time - now
                if diff.total_seconds() > 0:
                    d = diff.days
                    h, rem = divmod(diff.seconds, 3600)
                    m, s = divmod(rem, 60)
                    
                    parts = []
                    if d > 0: parts.append(f"{d}d")
                    if h > 0: parts.append(f"{h}h")
                    if m > 0: parts.append(f"{m}m")
                    # if s > 0: parts.append(f"{s}s") # seconds might be too noisy
                    
                    rec.remaining_time = " ".join(parts) if parts else "< 1m"
                else:
                    rec.remaining_time = "Overdue - Pending Run"
            elif rec.state == 'stopped':
                 rec.remaining_time = "Stopped"
            elif rec.state == 'draft':
                 rec.remaining_time = "Draft"

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('idil.recurring.journal') or _('New')
        return super(RecurringJournalEntry, self).create(vals)

    def write(self, vals):
        res = super(RecurringJournalEntry, self).write(vals)
        # Synchronize cron job if relevant fields changed
        # CRITICAL: We skip this if skip_cron_update is in context to avoid "Record cannot be modified" (locking) 
        # when this is called from within the cron job itself.
        if any(field in vals for field in ['next_run_time', 'state', 'interval_number', 'interval_type', 'active']):
            if not self._context.get('skip_cron_update'):
                self._sync_cron()
        return res

    def unlink(self):
        # Delete associated cron jobs before deleting records
        for rec in self:
            if rec.cron_id:
                rec.cron_id.unlink()
        return super(RecurringJournalEntry, self).unlink()

    def _sync_cron(self):
        """Creates, updates or deletes a dedicated ir.cron for this record."""
        for rec in self:
            if rec.state == 'running':
                # Map our interval types to ir.cron interval types
                # Odoo ir.cron uses: minutes, hours, days, weeks, months
                # Our selection: hours, days, weeks, months, years
                interval_type = rec.interval_type
                if interval_type == 'years':
                    # Odoo doesn't have 'years' in ir.cron interval_type, we use months=12 * interval
                    interval_type = 'months'
                    interval_number = rec.interval_number * 12
                else:
                    interval_number = rec.interval_number

                vals = {
                    'name': _('Recurring JV: %s') % rec.name,
                    'model_id': self.env['ir.model']._get_id(self._name),
                    'state': 'code',
                    'code': f'log("Starting Auto-Execution for {rec.name}"); model.browse({rec.id})._generate_entry_from_cron()',
                    'interval_number': interval_number,
                    'interval_type': interval_type,
                    'numbercall': -1,
                    # Ensure nextcall is written as a string format Odoo expects
                    'nextcall': fields.Datetime.to_string(rec.next_run_time),
                    'active': True,
                    'user_id': self.env.ref('base.user_root').id,
                }
                
                if rec.cron_id:
                    try:
                        # Use call_kw style or sudo() to ensure writing to ir.cron
                        rec.cron_id.sudo().write(vals)
                    except Exception as e:
                        _logger.debug("Could not update cron [ID: %s] - it might be currently running: %s", rec.cron_id.id, str(e))
                else:
                    cron = self.env['ir.cron'].sudo().create(vals)
                    rec.with_context(skip_cron_update=True).write({'cron_id': cron.id})
            else:
                # If stopped, draft or done, we deactivate the cron
                if rec.cron_id:
                    try:
                        rec.cron_id.sudo().write({'active': False})
                    except Exception as e:
                        _logger.info("Could not deactivate cron [ID: %s]: %s", rec.cron_id.id, str(e))

    def action_view_cron(self):
        self.ensure_one()
        if not self.cron_id:
             self._sync_cron()
             
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ir.cron',
            'res_id': self.cron_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _generate_entry_from_cron(self):
        """Method called by the dedicated Cron Job"""
        self = self.sudo()
        self.ensure_one()
        _logger.info("CRON RUNNER: Executing catch-up for recurring entry %s", self.name)
        return self.action_process_overdue()

    def action_process_overdue(self):
        """Processes missed intervals to catch up to the current time."""
        self.ensure_one()
        if self.state != 'running':
            return
            
        now = fields.Datetime.now()
        count = 0
        limit = 20 # Safety limit to prevent timeouts
        
        while self.state == 'running' and self.next_run_time <= now and count < limit:
            _logger.info("Catch-up: Processing Run #%s for %s", self.run_count + 1, self.name)
            # Try to generate. We ONLY want to increment count and allow the loop 
            # to continue if it SUCCEEDED. If it fails (funds, etc), we STOP 
            # so it retries the same time/run next minute.
            success = self.with_context(skip_cron_update=True)._generate_entry()
            if not success:
                 _logger.info("Catch-up: Stop/Retry later for %s (Likely funds or validation)", self.name)
                 break
                 
            count += 1
            # Refresh 'now' to be precise
            now = fields.Datetime.now()
            
        if count >= limit:
            _logger.warning("Catch-up limit reached (20) for %s. More pending entries exist.", self.name)
        
        return True

    @api.model
    def _cron_check_pending_dues(self):
        """Global check for any running entries that are overdue."""
        now = fields.Datetime.now()
        overdue_entries = self.sudo().search([
            ('state', '=', 'running'),
            ('next_run_time', '<=', now)
        ])
        _logger.info("Global Check: Found %s overdue recurring entries.", len(overdue_entries))
        for entry in overdue_entries:
            try:
                entry.action_process_overdue()
            except Exception as e:
                _logger.error("Global Check failed for %s: %s", entry.name, str(e))

    @api.depends('generated_entry_ids')
    def _compute_generated_count(self):
        for rec in self:
            rec.generated_count = len(rec.generated_entry_ids)

    @api.depends('log_ids')
    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.log_ids)

    def action_start(self):
        self.ensure_one()
        self.state = 'running'
        # Trigger immediate generation if overdue
        if self.next_run_time and self.next_run_time <= fields.Datetime.now():
            self._generate_entry()
        
        self._sync_cron()

    def action_stop(self):
        self.write({'state': 'stopped'})
        self._sync_cron()

    def action_draft(self):
        self.write({'state': 'draft'})
        self._sync_cron()

    def action_view_generated_entries(self):
        self.ensure_one()
        return {
            'name': _('Generated Journal Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'idil.journal.entry',
            'view_mode': 'tree,form',
            'domain': [('recurring_source_id', '=', self.id)],
            'context': {'default_recurring_source_id': self.id},
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            'name': _('Execution Logs'),
            'type': 'ir.actions.act_window',
            'res_model': 'idil.recurring.journal.log',
            'view_mode': 'tree,form',
            'domain': [('recurring_id', '=', self.id)],
            'context': {'default_recurring_id': self.id},
        }

    def _get_next_time(self, current_time):
        if not current_time:
            current_time = fields.Datetime.now()
        if self.interval_type == 'minutes':
            return current_time + relativedelta(minutes=self.interval_number)
        elif self.interval_type == 'hours':
            return current_time + relativedelta(hours=self.interval_number)
        elif self.interval_type == 'days':
            return current_time + relativedelta(days=self.interval_number)
        elif self.interval_type == 'weeks':
            return current_time + relativedelta(weeks=self.interval_number)
        elif self.interval_type == 'months':
            return current_time + relativedelta(months=self.interval_number)
        elif self.interval_type == 'years':
            return current_time + relativedelta(years=self.interval_number)
        return current_time

    def action_generate_entry_manual(self):
        self._generate_entry(manual=True)

    def _log_execution(self, status, message, entry_id=False):
        self.env['idil.recurring.journal.log'].create({
            'recurring_id': self.id,
            'status': status,
            'journal_entry_id': entry_id,
            'message': message,
        })
        if status == 'failed':
            _logger.warning("Recurring Entry [%s] Failed: %s", self.name, message)
        else:
            _logger.info("Recurring Entry [%s] Success: %s", self.name, message)

    def _check_funds_availability(self):
        """Check if accounts have enough balance based on template lines."""
        for line in self.line_ids:
            account = line.account_id
            if not account:
                continue
                
            # Calculate current balance in the same way as journal_entry.py
            # Using sudo() to ensure visibility of all bookings
            account_balance = self.env["idil.transaction_bookingline"].sudo().search(
                [("account_number", "=", account.id)]
            )
            debit_total = sum(b_line.dr_amount for b_line in account_balance)
            credit_total = sum(b_line.cr_amount for b_line in account_balance)
            current_balance = debit_total - credit_total

            if account.sign == "Dr":
                if line.credit > 0 and current_balance < line.credit:
                    msg = _("Insufficient funds in account %s (Balance: %s, Required: %s)") % (account.name, current_balance, line.credit)
                    _logger.warning("FUND CHECK FAILED for %s: %s", self.name, msg)
                    return False, msg
            elif account.sign == "Cr":
                if line.debit > 0 and current_balance < line.debit:
                    msg = _("Insufficient funds in account %s (Balance: %s, Required: %s)") % (account.name, current_balance, line.debit)
                    _logger.warning("FUND CHECK FAILED for %s: %s", self.name, msg)
                    return False, msg
        return True, ""

    def _generate_entry(self, manual=False):
        """
        Creates or Retries the Journal Entry.
        """
        self.ensure_one()
        _logger.info("Starting recurring generation for %s (Manual: %s)", self.name, manual)
        
        # Determine Accounting Date (Date only)
        run_datetime = self.next_run_time or fields.Datetime.now()
        accounting_date = run_datetime.date()
        
        # Check end date
        if self.end_date and accounting_date > self.end_date:
            self.state = 'done'
            _logger.info("Ending recurring cycle for %s (End Date reached)", self.name)
            return False

        # 0. Check minimum lines (at least 2)
        if len(self.line_ids) < 2:
            msg = _("Recurring entry must have at least two journal lines.")
            self._log_execution('failed', msg)
            if manual:
                raise UserError(msg)
            return False

        # 1. Check for duplicates using the target Run Number
        next_run_number = self.run_count + 1
        target_entry = False
        
        existing_entry = self.env['idil.journal.entry'].search([
            ('recurring_source_id', '=', self.id),
            ('recurring_run_number', '=', next_run_number),
            ('state', '!=', 'cancel')
        ], limit=1)

        if existing_entry:
            if existing_entry.state == 'draft':
                # If there's a draft, we try to process it instead of creating a new one
                _logger.info("Found existing draft for Run #%s, retrying confirmation.", next_run_number)
                target_entry = existing_entry
            else:
                # Already posted/confirmed. We MUST advance the schedule and Run Count to avoid getting stuck.
                _logger.info("Run #%s already posted for %s, synchronizing schedule and run_count.", next_run_number, self.name)
                self.with_context(skip_cron_update=True).write({
                    'next_run_time': self._get_next_time(self.next_run_time),
                    'run_count': next_run_number
                })
                return True
        # We don't reuse draft entries anymore to keep it simple and avoid "already exists" confusion;
        # if a fresh run is needed, we create a fresh entry.

        # 2. Check funds availability BEFORE creating a new entry if none exists
        if not target_entry:
            funds_ok, msg = self._check_funds_availability()
            if not funds_ok:
                # Log failure and stop (don't create journal entry as requested)
                # DO NOT advance next_run_time here so it retries next minute
                self._log_execution('failed', msg)
                self.message_post(body=_("Automatic generation failed: %s. Will retry when funds are available.") % msg)
                if manual:
                    raise ValidationError(msg)
                return False

            # Prepare Template Lines with Increment Info
            jv_lines = []
            for line in self.line_ids:
                # Append Run # to description for uniqueness and tracking
                desc = f"{line.description or self.description} (Run #{next_run_number})"
                jv_lines.append((0, 0, {
                    'account_id': line.account_id.id,
                    'description': desc,
                    'debit': line.debit,
                    'credit': line.credit,
                }))

            # Create Journal Entry (Draft)
            jv_vals = {
                'partner_type': 'others', 
                'date': accounting_date,
                'line_ids': jv_lines,
                'recurring_source_id': self.id,
                'recurring_run_number': next_run_number,
                'state': 'draft', 
                'company_id': self.company_id.id,
            }
            
            try:
                target_entry = self.env['idil.journal.entry'].create(jv_vals)
                _logger.info("Created draft Journal Entry %s for recurring source %s", target_entry.id, self.name)
                if not target_entry: # Should not happen with create, but as a safeguard
                    msg = f"Failed to create draft entry: target_entry is None after creation."
                    self._log_execution('failed', msg)
                    if manual:
                        raise UserError(msg)
                    return False # Failed
            except Exception as e:
                msg = f"Failed to create draft entry: {str(e)}"
                self._log_execution('failed', msg)
                if manual:
                    raise UserError(msg)
                return False # Failed

        # 3. Try to confirm (validate balance)
        try:
            target_entry.action_confirm()
            
            # Log success
            self._log_execution('success', f"Successfully generated and posted {target_entry.name}.", entry_id=target_entry.id)
            self.message_post(body=_("Successfully generated and posted journal entry: %s") % target_entry.name)
            
            # SUCCESS: Advance schedule and increment run count
            self.with_context(skip_cron_update=True).write({
                'next_run_time': self._get_next_time(self.next_run_time),
                'run_count': self.run_count + 1
            })
            return True
            
        except ValidationError as e:
            # Final validation check before posting
            self._log_execution('failed', f"Validation failed: {str(e)}. Will retry later.", entry_id=target_entry.id)
            self.message_post(body=_("Validation failed during generation: %s. It will retry automatically.") % str(e))
            
            if manual:
                raise e
            
            return False




class RecurringJournalLine(models.Model):
    _name = "idil.recurring.journal.line"
    _description = "Recurring Journal Entry Line"

    recurring_id = fields.Many2one('idil.recurring.journal.entry', required=True, ondelete='cascade')
    account_id = fields.Many2one('idil.chart.account', string="Account", required=True)
    description = fields.Char(string="Description")
    debit = fields.Float(string="Debit")
    credit = fields.Float(string="Credit")
    company_id = fields.Many2one('res.company', related='recurring_id.company_id')


class RecurringJournalLog(models.Model):
    _name = "idil.recurring.journal.log"
    _description = "Recurring Journal Execution Log"
    _order = "create_date desc"

    recurring_id = fields.Many2one('idil.recurring.journal.entry', string="Recurring Source", required=True, ondelete='cascade')
    run_date = fields.Datetime(string="Run Date", default=fields.Datetime.now, readonly=True)
    status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed')
    ], string="Status", required=True)
    
    journal_entry_id = fields.Many2one('idil.journal.entry', string="Generated Entry", readonly=True)
    message = fields.Text(string="Message")
