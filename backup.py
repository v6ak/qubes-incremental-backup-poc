#!/usr/bin/env python3
# Preconditions: sudo qubes-dom0-update zenity perl-Crypt-ScryptKDF

# The code is a PoC quality. It should generally work, but:
# * Backup format and configuration can be changed without automatic migration.
# * It probably violates some generally-accepted Python code style. I am sorry for that. I am new to Python. This is not a good excude for ugly code, but it is an excuse for suboptimal first version.
# * It uses shell calls too much. Maybe it is evident that this code was originally written as Bash script.
# * It does not use Qubes API, it calls shell commands instead and guesses some default paths. Maybe this will be fixed when ported for Qubes 4. Before switching to Qubes 4, we would get mix of Python 2 and Python 3.
# * Exceptions are usually not caught. That is, you will probably get an ugly stacktrace rather than some friendly error message.

import subprocess
import base64
import hmac
import binascii
import re
import os
import sys
import shutil
import shlex
import collections
import argparse
from backupsession import MasterBackupSession
from qubesvmtools import Vm, VmInstance, DvmInstance
from backupconfig import BackupConfig
from pathlib import Path

def ask_for_password(title):
	return subprocess.check_output(["zenity", "--password", "--title="+title]).rstrip(b'\n').decode("utf-8")

def create_session_gui(config, passphrase):
	def create_session(passphrase):
		kdf = config.get_password_kdf()
		return MasterBackupSession(kdf(passphrase), 32)

	if passphrase is not None:
		session = create_session(passphrase)
		if session.test_master_key(config.get_passphrase_test()):
			return session
		else:
			print("Bad passphrase")
			return None

	if config.passphrase_exists():
		first = True
		while True:
			p = ask_for_password("Your backup passphrase" if first else "Bad backup passphrase, try again")
			if p is None:
				return None
			session = create_session(p)
			if session.test_master_key(config.get_passphrase_test()):
				return session
			first = False
	else:
		# Creating a new passphrase
		while True:
			p1 = ask_for_password("Create a new backup passphrase")
			if p1 is None:
				return None
			p2 = ask_for_password("Retype your backup passphrase")
			if p2 is None:
				return None
			if hmac.compare_digest(p1.encode("utf-8"), p2.encode("utf-8")):
				session = create_session(p1)
				config.save_passphrase_test(session.gen_test_content())
				return session
			subprocess.check_call(["zenity", "--error", "--text=Passphrases do not match"])


def action_backup(vm, vm_keys, config):
	backup_backend = config.get_backup_backend()
	volume_clone = vm.private_volume().clone("v6-qubes-backup-poc-cloned")
	try:
		backup_storage_vm = VmInstance(config.get_backup_storage_vm_name())
		dvm = DvmInstance.create()
		try:
			dvm.attach("xvdz", volume_clone)  # --ro: 1. is not needed since it is a clone, 2. blocks repair procedures when mounting
			try:
				dvm.check_output("sudo mkdir /mnt/clone")
				dvm.check_output("sudo mount /dev/xvdz /mnt/clone") # TODO: consider -o nosuid,noexec – see issue #16
				try:
					backup_backend.upload_agent(dvm)
					with backup_backend.add_permissions(backup_storage_vm, dvm, vm_keys.encrypted_name):
						# run the agent
						with subprocess.Popen(dvm.create_command("/tmp/backup-agent "+shlex.quote(backup_storage_vm.get_name())+" "+shlex.quote(vm_keys.encrypted_name)), stdin = subprocess.PIPE) as proc:
							proc.stdin.write(vm_keys.key)
							proc.stdin.close()
							assert(proc.wait() == 0) # uarrgh, implemented by busy loop
					# TODO: also copy ~/.v6-qubes-backup-poc/master to the backup in order to make it recoverable without additional data (except password). See issue #12.
				finally: dvm.check_output("sudo umount /mnt/clone")
			finally: dvm.detach_all()
		finally: dvm.close()
	finally: volume_clone.remove()

def action_show_vm_keys(vm, vm_keys, config):
	print(vm_keys)

ACTIONS = {
	"backup": action_backup,
	"show_vm_keys": action_show_vm_keys
}

def main():
	parser = argparse.ArgumentParser(description='Backups your VMs. Performs incremental file-based backup.')
	parser.add_argument('vms', metavar='VM name', type=str, nargs=1, help='Name of VM to backup')
	parser.add_argument('--passphrase', dest='passphrase', action='store', help='passphrase (Intended mostly for testing.)')
	parser.add_argument('--config-dir', dest='config_dir', action='store', default=BackupConfig.get_default_path(), type=Path, help='path to config directory (Intended for testing.)')
	parser.add_argument('--action', dest='action', action='store', default='backup', help='What should be done with the VMs? Allowed values: backup, show_vm_keys.')
	args = parser.parse_args()
	vm = Vm(args.vms[0])

	config = BackupConfig.read_or_create(args.config_dir)
	session = create_session_gui(config, args.passphrase)
	if session is None: return 1 # aborted
	vm_keys = session.vm_keys(vm.get_name())
	act = ACTIONS.get(args.action)
	if act is None:
		print("Bad action")
		exit(1)
	act(vm, vm_keys, config)

if __name__ == "__main__":
	main()
