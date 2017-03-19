# python3
import os
import subprocess
import shlex
import base64
from .dvmbased import DvmBasedBackupBackend

# I know this is duplicated code, but sharing the same code between Python 2 and Python 3 would be probably hell.

def sanitize_filename(filename):
	dot_allowed = True
	for c in filename:
		if (c == '.') and dot_allowed:
			dot_allowed = False
			continue
		dot_allowed = True # Will not read untill next iteration, so we can change it now. TODO: make the flow more clear
		if (c >= 'a') and (c <= 'z'): continue
		if (c >= 'A') and (c <= 'Z'): continue
		if (c >= '0') and (c <= '9'): continue
		if (c == '-') or (c == '_') or (c == '='): continue
		raise Exception("Unexpected character: "+str(ord(c)))
	return filename

def read_until_zero(inp, maxlen = None):
	return bytes(_read_until_zero_intgen(inp, maxlen))

def _read_until_zero_intgen(inp, maxlen = None):
	n = 0
	while True:
		n += 1
		if (maxlen is not None) and (n > maxlen):
			raise Exception("Reading data longer than "+str(maxlen))
		chunk = inp.read(1)
		if len(chunk) == 1:
			if chunk == b'\0':
				break
			else:
				yield chunk[0] # contains int
		elif len(chunk) == 0:
			raise Exception("Reached EOF after reading "+str(n)+" bytes witout seeing any zero byte!")
		else:
			assert(False)

def read_safe_filename(inp):
	return sanitize_filename(read_until_zero(inp, 255).decode("ascii"))


class DuplicityBackupBackend(DvmBasedBackupBackend):
	base_path = os.path.dirname(os.path.realpath(__file__))+"/duplicity-vm-files/"
	def upload_agent(self, vm):
		with open(self.base_path+"vm-backup-agent", "rb") as inp:
			vm.check_call("cat > /tmp/backup-agent", stdin = inp)
		vm.check_call("chmod +x /tmp/backup-agent")
		with open(self.base_path+"vm-restore-agent", "rb") as inp:
			vm.check_call("cat > /tmp/restore-agent", stdin = inp)
		vm.check_call("chmod +x /tmp/restore-agent")
		with open(self.base_path+"qubesintervmbackend.py", "rb") as inp:
			vm.check_call("sudo tee /usr/lib/python2.7/dist-packages/duplicity/backends/qubesintervmbackend.py", stdin = inp)
		with open(self.base_path+"common.py", "rb") as inp:
			vm.check_call("sudo mkdir /usr/lib/python2.7/dist-packages/duplicity/backends/qubesintervmbackendprivate")
			vm.check_call("sudo touch /usr/lib/python2.7/dist-packages/duplicity/backends/qubesintervmbackendprivate/__init__.py")
			vm.check_call("sudo tee /usr/lib/python2.7/dist-packages/duplicity/backends/qubesintervmbackendprivate/common.py", stdin = inp)
	
	# TODO: Move methods below to backupbackend-agnostic backup storage handler:
	
	def install_dom0(self, vm):
		subprocess.check_call("echo "+shlex.quote("$anyvm  "+vm.get_name()+" allow")+" | sudo tee /etc/qubes-rpc/policy/v6ak.QubesInterVmBackupStorage", shell=True, stdout=subprocess.DEVNULL)

	def install_backup_storage_vm(self, vm):
		# TODO: make it persistent across reboots
		vm.check_call("sudo mkdir -p /usr/local/share/v6-qubes-backup-poc/")
		vm.check_call("echo /usr/local/share/v6-qubes-backup-poc/v6-qubes-backup-poc.py | sudo tee /etc/qubes-rpc/v6ak.QubesInterVmBackupStorage")
		with open(self.base_path+"backup-storage-agent/v6-qubes-backup-poc.py") as inp:
			vm.check_call("sudo tee /usr/local/share/v6-qubes-backup-poc/v6-qubes-backup-poc.py && sudo chmod +x /usr/local/share/v6-qubes-backup-poc/v6-qubes-backup-poc.py", stdin = inp)
		with open(self.base_path+"backup-storage-agent/list-backups.py") as inp:
			vm.check_call("sudo tee /usr/local/share/v6-qubes-backup-poc/list-backups.py && sudo chmod +x /usr/local/share/v6-qubes-backup-poc/list-backups.py", stdin = inp)
		with open(self.base_path+"common.py") as inp:
			# FIXME: Don't be so aggressive!
			vm.check_call("sudo tee /usr/local/share/v6-qubes-backup-poc/common.py", stdin = inp)

	def list_backups(self, backup_storage_vm):
		vms = []
		with backup_storage_vm.popen("/usr/local/share/v6-qubes-backup-poc/list-backups.py", stdout = subprocess.PIPE) as proc:
			while True:
				c = proc.stdout.read(1)
				if c == b'N':
					vms.append(read_safe_filename(proc.stdout))
				elif c == b'':
					assert(proc.wait() == 0)
					return vms
				else:
					raise Exception("Unexpected character #"+str(ord(c)))

