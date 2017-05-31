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
from collections import namedtuple
import argparse
from backupsession import MasterBackupSession
from qubesvmtools import Vm, VmInstance, DvmInstance, Dvm
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


def action_backup(vm_info, config, session, args):
	vm = vm_info.vm
	vm_keys = vm_info.vm_keys
	backup_backend = config.get_backup_backend()
	vm_instance = vm_info.vm.instance_if_running()
	if vm_instance is not None:
		vm_instance.try_sync()
	backup_storage_vm = VmInstance(config.get_backup_storage_vm_name())
	backup_backend.backup_vm(vm, vm_keys, backup_storage_vm)

def action_restore(restored_vm_info, config, session, args):
	# Maybe type vm_info is not what I need here…
	new_name = args.vm_name_template.replace("%", restored_vm_info.vm.get_name())
	new_vm = Vm(new_name)
	backup_backend = config.get_backup_backend()
	backup_storage_vm = VmInstance(config.get_backup_storage_vm_name())
	backup_backend.restore_vm(new_vm, new_name, args.vm_size, args.qvm_create_args, restored_vm_info.vm_keys, backup_storage_vm)

def action_show_vm_keys(vm_info, config, session, args):
	print(vm_info.vm_keys.encrypted_name+": "+base64.b64encode(vm_info.vm_keys.key).decode("ascii"))

def action_list_backups(config, session, args):
	encrypted_names = config.get_backup_backend().list_backups(VmInstance(config.get_backup_storage_vm_name()))
	names = list(map(session.file_name_crypter.decrypt, encrypted_names))
	names.sort()
	for i in names:
		print(i)

def multiple_vm_action(prefix, action):
	def extended_action(vms, config, session, args):
		if len(vms) == 0:
			raise Exception("Expected at least one VM")
		n = 0
		succeeded_for = []
		try:
			for i in vms:
				n += 1
				print(prefix+" "+i.vm.get_name()+" ("+str(n)+"/"+str(len(vms))+"):")
				action(i, config, session, args)
				succeeded_for.append(i)
		except:
			if len(succeeded_for) == 0:
				print("Fail occured when trying the first VM")
			else:
				print("Action has been successfuly completed for those VMs: "+str(list(map(lambda vmi: vmi.vm.get_name(), succeeded_for))))
			raise
	return extended_action

def no_vm_action(action):
	def extended_action(vms, config, session, args):
		if len(vms) != 0:
			raise Exception("This action does not accept VM list!")
		action(config, session, args)
	return extended_action

ACTIONS = {
	"backup": multiple_vm_action('Backing up VM', action_backup),
	"restore": multiple_vm_action("Restoring VM", action_restore),
	"show_vm_keys": multiple_vm_action('VM keys for', action_show_vm_keys),
	"list_backups": no_vm_action(action_list_backups),
}

class VmInfo(namedtuple('VmInfo', 'vm vm_keys')): pass

def main():
	parser = argparse.ArgumentParser(description='Backups your VMs. Performs incremental file-based backup.')
	parser.add_argument('vms', metavar='VM name', type=str, nargs='*', help='Name of VM(s)')
	parser.add_argument('--passphrase', dest='passphrase', action='store', help='passphrase (Intended mostly for testing.)')
	parser.add_argument('--config-dir', dest='config_dir', action='store', default=BackupConfig.get_default_path(), type=Path, help='path to config directory (Intended for testing.)')
	parser.add_argument('--vm-name-template', dest='vm_name_template', action='store', default='%', help='How should be the new VM named. Character %% is replaced by the original name.')
	parser.add_argument('--vm-size', dest='vm_size', action='store', default=None, help='VM size after restore')
	parser.add_argument('--qvm-create-args', dest='qvm_create_args', action='store', default='', help='Args for qvm_create. (Used for restore)')
	parser.add_argument('--action', dest='action', action='store', default='backup', help='What should be done with the VMs? Allowed values: '+(', '.join(sorted(ACTIONS.keys())))+'.')
	args = parser.parse_args()

	config = BackupConfig.read_or_create(args.config_dir)
	session = create_session_gui(config, args.passphrase)
	if session is None: return 1 # aborted
	vms = list(map(lambda name: VmInfo(Vm(name), session.vm_keys(name)), args.vms))
	act = ACTIONS.get(args.action)
	if act is None:
		print("Bad action")
		exit(1)
	act(vms, config, session, args)

if __name__ == "__main__":
	main()
