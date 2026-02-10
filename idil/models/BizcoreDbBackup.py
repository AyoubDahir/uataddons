# -*- coding: utf-8 -*-
import os
import re
import zipfile
import tempfile
import shutil
import subprocess
import base64
import logging
from datetime import datetime, timezone

from odoo import models, fields, _
from odoo.exceptions import UserError
from odoo.tools import config

import psycopg2

try:
    import oci
    from oci.object_storage import ObjectStorageClient
    from oci.object_storage.models import CreatePreauthenticatedRequestDetails
    OCI_AVAILABLE = True
except ImportError:
    OCI_AVAILABLE = False
    _logger.warning("OCI SDK not installed. Install with: pip3 install oci")

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
    # OCI Object Storage Helpers
    # ============================================================
    def _get_oci_config(self):
        """Get OCI configuration from odoo.conf"""
        oci_config = {
            "user": config.get("oci_user_ocid"),
            "key_file": config.get("oci_key_file"),
            "fingerprint": config.get("oci_fingerprint"),
            "tenancy": config.get("oci_tenancy_ocid"),
            "region": config.get("oci_region"),
        }
        
        # Validate required fields
        missing = [k for k, v in oci_config.items() if not v]
        if missing:
            raise UserError(
                _("Missing OCI configuration in odoo.conf: %s\n\n"
                  "Please add these values to your odoo.conf file.") % ", ".join(missing)
            )
        
        return oci_config
    
    def _get_oci_client(self):
        """Initialize OCI Object Storage client"""
        if not OCI_AVAILABLE:
            raise UserError(
                _("OCI SDK not installed. Please install it on the server:\n"
                  "pip3 install oci")
            )
        
        oci_config = self._get_oci_config()
        return ObjectStorageClient(oci_config)
    
    def _get_oci_namespace(self):
        """Get OCI Object Storage namespace"""
        namespace = config.get("oci_namespace")
        if not namespace:
            raise UserError(_("Missing 'oci_namespace' in odoo.conf"))
        return namespace
    
    def _get_oci_bucket(self):
        """Get OCI bucket name"""
        bucket = config.get("oci_bucket_name")
        if not bucket:
            raise UserError(_("Missing 'oci_bucket_name' in odoo.conf"))
        return bucket
    
    def _upload_to_oci(self, file_path, object_name):
        """Upload backup file to OCI Object Storage with streaming"""
        client = self._get_oci_client()
        namespace = self._get_oci_namespace()
        bucket = self._get_oci_bucket()
        
        _logger.info(f"Uploading {object_name} to OCI bucket {bucket}")
        
        # Stream upload to avoid memory issues
        with open(file_path, 'rb') as f:
            client.put_object(
                namespace_name=namespace,
                bucket_name=bucket,
                object_name=object_name,
                put_object_body=f
            )
        
        _logger.info(f"Successfully uploaded {object_name} to OCI")
        return True
    
    def _download_from_oci(self, object_name, destination_path):
        """Download backup from OCI to local file"""
        client = self._get_oci_client()
        namespace = self._get_oci_namespace()
        bucket = self._get_oci_bucket()
        
        _logger.info(f"Downloading {object_name} from OCI")
        
        response = client.get_object(
            namespace_name=namespace,
            bucket_name=bucket,
            object_name=object_name
        )
        
        # Stream write to avoid memory issues
        with open(destination_path, 'wb') as f:
            for chunk in response.data.raw.stream(8192, decode_content=False):
                f.write(chunk)
        
        _logger.info(f"Successfully downloaded {object_name} from OCI")
        return True
    
    def _list_oci_backups(self):
        """List all backups in OCI bucket"""
        client = self._get_oci_client()
        namespace = self._get_oci_namespace()
        bucket = self._get_oci_bucket()
        
        backups = []
        list_objects = client.list_objects(
            namespace_name=namespace,
            bucket_name=bucket,
            prefix="backup_"
        )
        
        for obj in list_objects.data.objects:
            backups.append({
                'name': obj.name,
                'size': obj.size,
                'time_created': obj.time_created,
            })
        
        return backups
    
    def _delete_oci_backup(self, object_name):
        """Delete a specific backup from OCI"""
        client = self._get_oci_client()
        namespace = self._get_oci_namespace()
        bucket = self._get_oci_bucket()
        
        _logger.info(f"Deleting {object_name} from OCI")
        
        client.delete_object(
            namespace_name=namespace,
            bucket_name=bucket,
            object_name=object_name
        )
        
        _logger.info(f"Successfully deleted {object_name} from OCI")
        return True
    
    def _cleanup_old_oci_backups(self, days=30):
        """Delete backups older than specified days"""
        from datetime import timedelta
        
        backups = self._list_oci_backups()
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        deleted_count = 0
        
        for backup in backups:
            if backup['time_created'] < cutoff_date:
                self._delete_oci_backup(backup['name'])
                deleted_count += 1
        
        return deleted_count
    
    def _generate_oci_download_url(self, object_name, expiration_hours=24):
        """Generate pre-authenticated request URL for downloading backup"""
        client = self._get_oci_client()
        namespace = self._get_oci_namespace()
        bucket = self._get_oci_bucket()
        
        from datetime import timedelta
        expiration = datetime.now(timezone.utc) + timedelta(hours=expiration_hours)
        
        par_details = CreatePreauthenticatedRequestDetails(
            name=f"download_{object_name}_{int(datetime.now().timestamp())}",
            access_type="ObjectRead",
            time_expires=expiration,
            object_name=object_name
        )
        
        par = client.create_preauthenticated_request(
            namespace_name=namespace,
            bucket_name=bucket,
            create_preauthenticated_request_details=par_details
        )
        
        # Construct full URL
        region = config.get("oci_region")
        full_url = f"https://objectstorage.{region}.oraclecloud.com{par.data.access_uri}"
        
        return full_url


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


            # Upload to OCI Object Storage instead of storing in database
            try:
                self._upload_to_oci(zip_path, self.backup_name)
                
                # Store metadata reference in attachment (without binary data)
                att = (
                    self.env["ir.attachment"]
                    .sudo()
                    .create(
                        {
                            "name": self.backup_name,
                            "type": "url",
                            "url": f"oci://{self.backup_name}",
                            "mimetype": "application/zip",
                            "res_model": self._name,
                            "res_id": self.id,
                        }
                    )
                )
                self.attachment_id = att.id
                
                # Generate download URL (valid for 24 hours)
                download_url = self._generate_oci_download_url(self.backup_name)
                
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Backup Created Successfully"),
                        "message": _("Backup uploaded to OCI Object Storage. Download link generated (valid 24h)."),
                        "type": "success",
                        "sticky": True,
                        "next": {
                            "type": "ir.actions.act_url",
                            "url": download_url,
                            "target": "new",
                        },
                    },
                }
            except Exception as e:
                _logger.error(f"Failed to upload backup to OCI: {str(e)}")
                raise UserError(_("Failed to upload backup to OCI: %s") % str(e))


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
