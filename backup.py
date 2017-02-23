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
import collections
import argparse
from qubesvmtools import Vm, VmInstance, DvmInstance
from backupconfig import BackupConfig
from pathlib import Path
from cryptopunk import aes256_hiv_encrypt, aes256_hiv_decrypt


def ask_for_password(title):
	return subprocess.check_output(["zenity", "--password", "--title="+title]).rstrip(b'\n').decode("utf-8")

# Plaintext filename: Any case-sensitive utf-8 string without binary zeros (i.e. '\0') of size (in bytes) at most filename_plain_size
# Ciphertext filename: A case-insensitive ascii base32 name of length base32_size_increase(filename_plain_size+mac_size)
# Properties:
# * Does not leak filename length
# * The same plaintext filename is encrypted to the same ciphertext filename
# * Related plaintext filenames are encrypted to unrelated ciphertext filenames
# * Filenames are authenticated, i.e. attacker cannot abuse malleability
# We use base32 in order to survive case-insensitive filesystem
class FileNameCrypter:
	def __init__(self, key, mac_size, filename_plain_size):
		self.key = key
		self.mac_size = mac_size
		self.filename_plain_size = filename_plain_size
	def encrypt(self, filename):
		encoded_filename_unpadded = filename.encode("utf-8")
		assert(encoded_filename_unpadded.find(b'\0') == -1)
		encoded_filename_padded = encoded_filename_unpadded.ljust(self.filename_plain_size, b'\0')
		assert(len(encoded_filename_unpadded) <= self.filename_plain_size)
		assert(len(encoded_filename_padded) == self.filename_plain_size)
		encrypted_filename_bytes = aes256_hiv_encrypt(self.key, encoded_filename_padded, self.mac_size)
		return base64.b32encode(encrypted_filename_bytes).decode("ascii")
	def decrypt(self, filename):
		plain_padded = aes256_hiv_decrypt(self.key, base64.b32decode(filename.upper()), self.mac_size)
		assert(len(plain_padded) == self.filename_plain_size )
		plain = plain_padded.rstrip(b'\0')
		assert(plain.find(b'\0') == -1)
		return plain.decode("utf-8")

class VmKeys(collections.namedtuple('VmKeys', 'encrypted_name key')): pass

class MasterBackupSession:
	def __init__(self, master_key, filename_mac_size = 16):
		self.master_key = master_key
		self.filename_mac_size = filename_mac_size
		self.file_name_crypter = FileNameCrypter(self.subkey(b"files", 512), self.filename_mac_size, 96)
	def subkey(self, subkey_id, length=256):
		assert((length == 256) or (length == 512))
		HASHES = {
			256: "sha256",
			512: "sha512"
		}
		return hmac.new(self.master_key, subkey_id, HASHES[length]).digest()
	def subkey_vm(self, vm_name):
		return self.subkey(("vm-"+vm_name).encode("utf-8"))
	def test_master_key(self, test_content):
		return hmac.compare_digest(test_content, self.gen_test_content())
	def gen_test_content(self):
		# Derive a testing key and MAC some hardcoded content :)
		return hmac.new(self.subkey(b"test"), base64.b64decode("UMWZw61sacWhIMW+bHXFpW91xI1rw70ga8WvbiDDunDEm2wgxI/DoWJlbHNrw6kgw7NkeS4="), "sha256").digest()
	def vm_keys(self, vm_name):
		return VmKeys(
			encrypted_name = self.file_name_crypter.encrypt(vm_name),
			key = self.subkey_vm(vm_name)
		)

def main():
	parser = argparse.ArgumentParser(description='Backups your VMs. Performs incremental file-based backup.')
	parser.add_argument('vms', metavar='VM name', type=str, nargs=1, help='Name of VM to backup')
	parser.add_argument('--passphrase', dest='passphrase', action='store', help='passphrase (Intended mostly for testing.)')
	parser.add_argument('--config-dir', dest='config_dir', action='store', default=BackupConfig.get_default_path(), type=Path, help='path to config directory (Intended for testing.)')
	args = parser.parse_args()
	vm = args.vms[0]

	config = BackupConfig.read_or_create(args.config_dir)
	# TODO: refactor password handling (repeated prompt when creating, repeated prompt when entering bad password, …)
	kdf = config.get_password_kdf()
	password = args.passphrase if args.passphrase is not None else ask_for_password("Backup passphrase" if config.passphrase_exists() else "Create a new backup passphrase")
	session = MasterBackupSession(kdf(password), 32)
	password = None # just hygiene
	if config.passphrase_exists():
		if not session.test_master_key(config.get_passphrase_test()):
			print("Bad password")
			exit(66)
	else:
		config.save_passphrase_test(session.gen_test_content())
	vm_keys = session.vm_keys(vm)

	volume_clone = Vm(vm).private_volume().clone()
	try:
		dvm = DvmInstance.create()
		try:
			dvm.attach("xvdz", volume_clone)  # --ro: 1. is not needed since it is a clone, 2. blocks repair procedures when mounting
			try:
				dvm.check_output("sudo mkdir /mnt/clone")
				dvm.check_output("sudo mount /dev/xvdz /mnt/clone") # TODO: consider -o nosuid,noexec – see issue #16
				try:
					with open(os.path.dirname(os.path.realpath(__file__))+"/vm-backup-agent", "rb") as inp:
						dvm.check_output("cat > /tmp/backup-agent", stdin = inp)
					dvm.check_output("chmod +x /tmp/backup-agent")
					with subprocess.Popen(dvm.create_command("/tmp/backup-agent "+vm_keys.encrypted_name), stdin = subprocess.PIPE) as proc:
						proc.stdin.write(vm_keys.key)
						proc.stdin.close()
						assert(proc.wait() == 0) # uarrgh, implemented by busy loop
					# TODO: also copy ~/.v6-qubes-backup-poc/master to the backup in order to make it recoverable without additional data (except password). See issue #12.
				finally: dvm.check_output("sudo umount /mnt/clone")
			finally: dvm.detach_all()
		finally: dvm.close()
	finally: volume_clone.remove()

if __name__ == "__main__":
	main()
