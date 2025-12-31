# -*- coding: utf-8 -*-
import os
import re
import zipfile
import tempfile
import shutil
import subprocess
import base64
import logging
from datetime import datetime

from odoo import models, fields, _
from odoo.exceptions import UserError
from odoo.tools import config

import psycopg2

_logger = logging.getLogger(__name__)


class BizcoreDbBackupWizard(models.TransientModel):
    _name = "bizcore.db.backup.wizard"
    _description = "Database Backup & Restore Wizard"

    # ------------------------
    # Backup fields
    # ------------------------
    backup_name = fields.Char(
        string="Backup File Name",
        default=lambda self: f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        readonly=True,
    )
    attachment_id = fields.Many2one("ir.attachment", readonly=True)

    # ------------------------
    # Restore fields
    # ------------------------
    restore_zip = fields.Binary(string="Upload Backup ZIP")
    restore_zip_filename = fields.Char(string="Filename")
    restore_db_name = fields.Char(string="Restore As (New DB Name)")
    restore_result = fields.Text(string="Result", readonly=True)

    # ============================================================
    # Helpers
    # ============================================================
    def _get_pg_config(self):
        db_host = config.get("db_host") or "localhost"
        db_port = int(config.get("db_port") or 5432)
        db_user = config.get("db_user") or "odoo"
        db_password = config.get("db_password") or ""
        if not db_password:
            raise UserError(_("db_password is empty in odoo.conf"))
        return db_host, db_port, db_user, db_password

    def _get_tool(self, conf_key, fallback):
        """
        Resolve executable path safely on Windows & Linux.
        Prefer conf value (pg_dump_path/pg_restore_path). Fallback to PATH.
        """
        tool = config.get(conf_key) or fallback
        if isinstance(tool, str):
            tool = tool.strip()

        # If conf gives full path (Windows)
        if isinstance(tool, str) and (
            tool.lower().endswith(".exe") or ":" in tool or "\\" in tool
        ):
            if not os.path.isfile(tool):
                raise UserError(_("%s not found at: %s") % (conf_key, tool))
            return tool

        # Otherwise rely on PATH
        resolved = shutil.which(tool)
        if not resolved:
            raise UserError(
                _("%s not found. Set %s in odoo.conf.") % (fallback, conf_key)
            )
        return resolved

    def _get_filestore_dir(self, dbname):
        data_dir = config["data_dir"]
        return os.path.join(data_dir, "filestore", dbname)

    def _validate_dbname(self, dbname):
        if not dbname:
            raise UserError(_("Please enter the new database name."))
        if not re.match(r"^[A-Za-z0-9_]+$", dbname):
            raise UserError(
                _("Database name must contain only letters, numbers, and underscores.")
            )
        return True

    def _create_database(self, new_dbname):
        db_host, db_port, db_user, db_password = self._get_pg_config()

        conn = psycopg2.connect(
            dbname="postgres",
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
        )
        conn.autocommit = True
        cur = conn.cursor()

        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (new_dbname,))
        if cur.fetchone():
            cur.close()
            conn.close()
            raise UserError(
                _("Database '%s' already exists. Choose another name.") % new_dbname
            )

        cur.execute(
            f"CREATE DATABASE \"{new_dbname}\" WITH TEMPLATE template0 ENCODING 'UTF8';"
        )

        cur.close()
        conn.close()

    # ============================================================
    # Backup
    # ============================================================
    def action_backup_now(self):
        self.ensure_one()

        dbname = self.env.cr.dbname
        db_host, db_port, db_user, db_password = self._get_pg_config()

        pg_dump = self._get_tool("pg_dump_path", "pg_dump")

        filestore_dir = self._get_filestore_dir(dbname)
        if not os.path.isdir(filestore_dir):
            raise UserError(
                _("Filestore not found for DB '%s': %s") % (dbname, filestore_dir)
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            dump_path = os.path.join(tmpdir, "db.dump")
            zip_path = os.path.join(tmpdir, self.backup_name)

            env = os.environ.copy()
            env["PGPASSWORD"] = db_password

            cmd = [
                pg_dump,
                "-Fc",
                "-f",
                dump_path,
                "-h",
                db_host,
                "-p",
                str(db_port),
                "-U",
                db_user,
                dbname,
            ]

            _logger.warning("EXECUTING pg_dump: %s", cmd)

            try:
                subprocess.check_call(cmd, env=env)
            except subprocess.CalledProcessError as e:
                raise UserError(_("Database dump failed: %s") % str(e))

            # ZIP db.dump + filestore
            data_dir = config["data_dir"]
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                z.write(dump_path, arcname="db.dump")

                for root, dirs, files in os.walk(filestore_dir):
                    for f in files:
                        full_path = os.path.join(root, f)
                        rel = os.path.relpath(
                            full_path, os.path.join(data_dir, "filestore")
                        )
                        z.write(full_path, arcname=os.path.join("filestore", rel))

            with open(zip_path, "rb") as f:
                content = f.read()

            att = (
                self.env["ir.attachment"]
                .sudo()
                .create(
                    {
                        "name": self.backup_name,
                        "type": "binary",
                        "datas": base64.b64encode(content),
                        "mimetype": "application/zip",
                        "res_model": self._name,
                        "res_id": self.id,
                    }
                )
            )
            self.attachment_id = att.id

        # download immediately
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.attachment_id.id}?download=true",
            "target": "self",
        }

    def action_download_backup(self):
        self.ensure_one()
        if not self.attachment_id:
            raise UserError(_("No backup generated yet. Click Backup Now first."))
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{self.attachment_id.id}?download=true",
            "target": "self",
        }

    # ============================================================
    # Restore (safe: restore into NEW DB)
    # ============================================================
    def action_restore_to_new_db(self):
        self.ensure_one()

        if not self.restore_zip:
            raise UserError(_("Please upload a backup ZIP file."))

        new_dbname = (self.restore_db_name or "").strip()
        self._validate_dbname(new_dbname)

        db_host, db_port, db_user, db_password = self._get_pg_config()
        pg_restore = self._get_tool("pg_restore_path", "pg_restore")

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = os.path.join(tmpdir, "backup.zip")
            with open(zip_path, "wb") as f:
                f.write(base64.b64decode(self.restore_zip))

            extract_dir = os.path.join(tmpdir, "extract")
            os.makedirs(extract_dir, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_dir)

            dump_path = os.path.join(extract_dir, "db.dump")
            if not os.path.exists(dump_path):
                raise UserError(_("Invalid backup ZIP: db.dump not found."))

            # Create new DB
            self._create_database(new_dbname)

            env = os.environ.copy()
            env["PGPASSWORD"] = db_password

            cmd = [
                pg_restore,
                "--no-owner",
                "--no-privileges",
                "-h",
                db_host,
                "-p",
                str(db_port),
                "-U",
                db_user,
                "-d",
                new_dbname,
                dump_path,
            ]

            _logger.warning("EXECUTING pg_restore: %s", cmd)

            try:
                subprocess.check_call(cmd, env=env)
            except subprocess.CalledProcessError as e:
                raise UserError(_("Database restore failed: %s") % str(e))

            # Restore filestore (if exists in ZIP)
            data_dir = config["data_dir"]
            src_filestore_root = os.path.join(extract_dir, "filestore")
            if os.path.isdir(src_filestore_root):
                subfolders = [
                    d
                    for d in os.listdir(src_filestore_root)
                    if os.path.isdir(os.path.join(src_filestore_root, d))
                ]
                if subfolders:
                    old_db_folder = subfolders[0]
                    src_filestore_dir = os.path.join(src_filestore_root, old_db_folder)
                    dst_filestore_dir = os.path.join(data_dir, "filestore", new_dbname)

                    if os.path.exists(dst_filestore_dir):
                        shutil.rmtree(dst_filestore_dir)
                    shutil.copytree(src_filestore_dir, dst_filestore_dir)

            self.restore_result = (
                f"Restore completed successfully.\n"
                f"New Database: {new_dbname}\n"
                f"Open /web/database/selector to access it."
            )

        return {"type": "ir.actions.act_window_close"}
