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
from pathlib import Path

def scrypt(password, salt, log2_N, r, p, length):
	# I found no Python scrypt implementation in dom0 repository :(
	return subprocess.check_output([
		"perl",
		"-e",
		'use Crypt::ScryptKDF; use MIME::Base64; print(Crypt::ScryptKDF::scrypt_raw(decode_base64($ARGV[5]), decode_base64($ARGV[0]), 1<<($ARGV[1]+0), ($ARGV[2]+0), ($ARGV[3]+0), ($ARGV[4]+0)));',
		"--",
		base64.b64encode(salt),
		str(log2_N),
		str(r),
		str(p),
		str(length),
		base64.b64encode(password.encode("utf-8"))
	])

# Encrypts or decrypts in AES-256 CTR mode. Encryption and decryption are the same. This is a low-level (pure) function where one has to specify IV.
def aes256_ctr(key, iv, data):
	assert len(key) == 32
	assert len(iv) == 16
	# crosstest: http://www.cryptogrium.com/aes-ctr.html
	return subprocess.check_output(
		["openssl", "enc", "-aes-256-ctr", "-K", binascii.hexlify(key), "-iv", binascii.hexlify(iv)],
		input=data
	)

# AES-HIV is like AES-SIV, but it uses HMAC-SHA256 instead of S2V…

def aes256_hiv_key_split(key):
	assert(len(key) == 64)
	key_crypt = key[:32]
	key_mac = key[32:]
	return [key_crypt, key_mac]

def aes256_hiv_encrypt(key, plaintext, mac_size_bytes = 32):
	assert(mac_size_bytes <= 32) # more bytes would not work well with SHA-256
	assert(mac_size_bytes >= 16) # less bytes could cause problems with IV
	[key_crypt, key_mac] = aes256_hiv_key_split(key)
	mac = hmac.new(key_mac, plaintext, "sha256").digest()[:mac_size_bytes]
	iv = mac[:16]
	encrypted = aes256_ctr(key_crypt, iv, plaintext)
	return mac + encrypted

def aes256_hiv_decrypt(key, ciphertext, mac_size_bytes = 32):
	assert(mac_size_bytes <= 32) # more bytes would not work well with SHA-256
	assert(mac_size_bytes >= 16) # less bytes could cause problems with IV
	[key_crypt, key_mac] = aes256_hiv_key_split(key)
	mac_actual = ciphertext[:mac_size_bytes]
	iv = mac_actual[:16]
	encrypted = ciphertext[mac_size_bytes:]
	plaintext_unverified = aes256_ctr(key_crypt, iv, encrypted)
	mac_expected = hmac.new(key_mac, plaintext_unverified, "sha256").digest()[:mac_size_bytes]
	if hmac.compare_digest(mac_expected, mac_actual):
		return plaintext_unverified
	else:
		raise Exception("bad MAC")

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

class Vm:
	def __init__(self, name):
		pattern = re.compile("\\A[a-zA-Z0-9-]+\\Z")
		if not pattern.match(name):
			raise Exception("bad name")
		self.name = name
	def is_running(self):
		ret = subprocess.call(["qvm-check", "--running", self.name], stdout=subprocess.DEVNULL)
		if ret == 0:
			return True
		elif ret == 1:
			return False
		else:
			raise Exception("unexpected return code: "+str(ret))
	def private_volume_path(self):
		return Path("/var/lib/qubes/appvms/"+self.name+"/private.img")
	def private_volume(self):
		path = self.private_volume_path()
		if path.is_symlink():
			pat = re.compile("^/dev/([^/]+)/([^/]+)$")
			location = os.readlink(str(path))
			parts = pat.match(location)
			if parts:
				vg = parts.group(1)
				lv = parts.group(2)
				return LvmVolume(self, vg, lv)
			else:
				raise Exception("Cannot parse link to LVM volume: "+location)
		elif path.is_file():
			return FileVolume(self, path)
		else:
			raise Exception("unexpected file type")

class DvmInstance: # We could extract VmInstance superclass, but we don't need it
	def __init__(self, name):
		self.name = name
	@staticmethod
	def create(color = "red"):
		return DvmInstance(subprocess.check_output(["/usr/lib/qubes/qfile-daemon-dvm", "LAUNCH", "dom0", "", color]).decode("ascii").rstrip("\n"))
	def close(self):
		subprocess.check_output(["/usr/lib/qubes/qfile-daemon-dvm", "FINISH", self.name])
	def attach(self, name, volume):
		subprocess.check_output(["qvm-block", "--attach-file", self.name, volume.xen_path(), "-f", name])
	def detach_all(self):
		subprocess.check_output(["qvm-block", "--detach", self.name])
	def create_command(self, command):
		return ["qvm-run", "-p", self.name, command]
	def check_output(self, command, stdin = None, input = None):
		if stdin == None:
			return subprocess.check_output(self.create_command(command), input = input)
		elif input == None:
			return subprocess.check_output(self.create_command(command), stdin = stdin)
		else:
			raise Exception("cannot handle both stdin and input")

class Volume:
	def __init__(self, vm):
		self.vm = vm
	def clone(self):
		raise Exception("not implemented")
	def remove(self):
		raise Exception("not implemented")
	def xen_path(self):
		raise Exception("not implemented")

class LvmVolume(Volume):
	def __init__(self, vm, vg, lv):
		super().__init__(vm)
		self.lv = lv
		self.vg = vg
	def __str__(self):
		return "LvmVolume("+str(self.vm)+", "+str(self.lv)+", "+str(self.vg)+")"
	def clone(self):
		clone_lv = "clone-"+self.lv
		clone_volume = LvmVolume(self.vm, self.vg, clone_lv)
		if clone_volume.exists():
			clone_volume.remove()
		subprocess.check_output(["sudo", "lvcreate", "-L512M", "-s", "-n", clone_lv, self.lvm_path()])
		return clone_volume
	def remove(self):
		subprocess.check_output(["sudo", "lvremove", "-f", self.file_path()])
	def exists(self):
		return os.path.exists(self.file_path())
	def lvm_path(self):
		return self.vg+"/"+self.lv
	def file_path(self):
		return "/dev/"+self.lvm_path()
	def xen_path(self):
		return "dom0:"+self.file_path()

class FileVolume(Volume):
	def __init__(self, vm, path):
		super().__init__(vm)
		self.path = path
	def __str__(self):
		return "FileVolume("+str(self.vm)+", "+str(self.path)+")"
	def clone(self):
		if self.vm.is_running():
			raise Exception("VM is running, backup is not supported for this type of VM when running")
		clone_path = Path(str(self.path)+".clone")
		#shutil.copyfile(str(self.path), str(clone_path)) <— does not seem to support sparse files, so it is slooooooow
		subprocess.check_output(["cp", "--sparse=always", "--", str(self.path), str(clone_path)])
		return FileVolume(self.vm, clone_path)
	def remove(self):
		os.remove(str(self.path))
	def xen_path(self):
		return "dom0:"+str(self.path)

class ConfigItem(collections.namedtuple('ConfigItem', 'default_generator')):
	def default(self):
		return self.default_generator()
class SaltConfigItem(ConfigItem):
	def read(self, inp):
		res = inp.read(32)
		assert(len(res) == 32)
		assert(len(inp.read(1)) == 0) # check EOF
		return res
	def write(self, out, value):
		out.write(value)

class IntConfigItem(ConfigItem):
	def read(self, inp):
		res = inp.read(10) # up to 10 characters
		assert(len(inp.read(1)) == 0) # check EOF
		return int(res)
	def write(self, out, value):
		out.write(str(value).encode("ascii"))

class BackupConfig:
	def __init__(self, path, master_pass_config):
		self.master_pass_config = master_pass_config
		self.path = path
	@staticmethod
	def read_or_create(path):
		# Maybe one could find an existing library that does this better. The problem is that the library would have to be reasonably reviewed, which is not an easy task.
		conf = {
			"salt": SaltConfigItem(lambda: os.urandom(32)),
			"log2_N": IntConfigItem(lambda: 17),
			"r": IntConfigItem(lambda: 8),
			"p": IntConfigItem(lambda: 8)
		}
		res = {}
		master_path = path / "master"
		if not os.path.exists(str(master_path)):
			os.makedirs(str(master_path))
		for key, value_coder in conf.items():
			f = master_path / key
			if f.exists():
				with open(str(f), "rb") as inp:
					res[key] = value_coder.read(inp)
			else:
				with open(str(f), "wb+") as out:
					value = value_coder.default()
					value_coder.write(out, value)
					res[key] = value
		return BackupConfig(path, res)
	def get_password_kdf(self):
		return lambda password: scrypt(password, self.master_pass_config['salt'], self.master_pass_config['log2_N'], self.master_pass_config['r'], self.master_pass_config['p'], 32)
	def _passphrase_test_file(self):
		return self.path / "passphrase_test"
	def passphrase_exists(self):
		return os.path.exists(str(self._passphrase_test_file()))
	def get_passphrase_test(self):
		with open(str(self._passphrase_test_file()), "rb") as f: return f.read(64)
	def save_passphrase_test(self, new_data):
		with open(str(self._passphrase_test_file()), "wb+") as f: return f.write(new_data)

def main():
	if len(sys.argv) == 2:
		vm = sys.argv[1]
	else:
		print("Usage: "+sys.argv[0]+" vm-name")
		exit(1)

	config = BackupConfig.read_or_create(Path(os.path.expanduser("~/.v6-qubes-backup-poc")))
	# TODO: refactor password handling (repeated prompt when creating, repeated prompt when entering bad password, …)
	kdf = config.get_password_kdf()
	password = ask_for_password("Backup passphrase" if config.passphrase_exists() else "Create a new backup passphrase")
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
