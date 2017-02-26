#!/usr/bin/env python3
from backupconfig import BackupConfig
from pathlib import Path
import argparse
from qubesvmtools import VmInstance

def main():
	parser = argparse.ArgumentParser(description='Installs backup storage to BackupStorageVM')
	parser.add_argument('--config-dir', dest='config_dir', action='store', default=BackupConfig.get_default_path(), type=Path, help='path to config directory (Intended for testing.)')
	parser.add_argument('--without-dom0', dest='with_dom0', action='store_false', default=True, help='Skip the needed dom0 RPC permission file(s) – useful if you want to handle it yourself')
	parser.add_argument('--vm', dest='vm', action='store', help='Overrides VM you want install the tools needed for backup storage. Useful when installing then to TemplateVM.')
	args = parser.parse_args()
	config = BackupConfig.read_or_create(args.config_dir)
	backup_backend = config.get_backup_backend()
	vm = VmInstance(args.vm or config.get_backup_storage_vm_name())
	backup_backend.install_backup_storage_vm(vm)
	if args.with_dom0:
		print("As requested, installing also dom0 RPC permission file(s). If you want to skip this, add --without-dom0.")
		backup_backend.install_dom0(vm)

if __name__ == "__main__":
	main()
