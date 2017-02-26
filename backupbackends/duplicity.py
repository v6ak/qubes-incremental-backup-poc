# python3
import os
import subprocess
import shlex
import base64

# If you want to implement another backend, you can, but maybe you should wait a while until the API becomes more stable.
# TODO: document interface
class DuplicityBackupBackend:
	base_path = os.path.dirname(os.path.realpath(__file__))+"/duplicity-vm-files/"
	def upload_agent(self, vm):
		with open(self.base_path+"vm-backup-agent", "rb") as inp:
			vm.check_output("cat > /tmp/backup-agent", stdin = inp)
		vm.check_output("chmod +x /tmp/backup-agent")
		with open(self.base_path+"qubesintervmbackend.py", "rb") as inp:
			vm.check_output("sudo tee /usr/lib/python2.7/dist-packages/duplicity/backends/qubesintervmbackend.py", stdin = inp)
		with open(self.base_path+"common.py", "rb") as inp:
			vm.check_output("sudo mkdir /usr/lib/python2.7/dist-packages/duplicity/backends/qubesintervmbackendprivate")
			vm.check_output("sudo touch /usr/lib/python2.7/dist-packages/duplicity/backends/qubesintervmbackendprivate/__init__.py")
			vm.check_output("sudo tee /usr/lib/python2.7/dist-packages/duplicity/backends/qubesintervmbackendprivate/common.py", stdin = inp)

	def install_dom0(self, vm):
		subprocess.check_call("echo "+shlex.quote("$anyvm  "+vm.get_name()+" allow")+" | sudo tee /etc/qubes-rpc/policy/v6ak.QubesInterVmBackupStorage", shell=True, stdout=subprocess.DEVNULL)

	def install_backup_storage_vm(self, vm):
		# TODO: make it persistent across reboots
		vm.check_output("sudo mkdir -p /usr/local/share/v6-qubes-backup-poc/")
		vm.check_output("echo /usr/local/share/v6-qubes-backup-poc/v6-qubes-backup-poc.py | sudo tee /etc/qubes-rpc/v6ak.QubesInterVmBackupStorage")
		with open(self.base_path+"backup-storage-agent/v6-qubes-backup-poc.py") as inp:
			vm.check_output("sudo tee /usr/local/share/v6-qubes-backup-poc/v6-qubes-backup-poc.py && sudo chmod +x /usr/local/share/v6-qubes-backup-poc/v6-qubes-backup-poc.py", stdin = inp)
		with open(self.base_path+"common.py") as inp:
			# FIXME: Don't be so aggressive!
			vm.check_output("sudo tee /usr/local/share/v6-qubes-backup-poc/common.py", stdin = inp)

	def add_permissions(self, backup_storage_vm, dvm, encrypted_name):
		permission_file = "/var/run/v6-qubes-backup-poc-permissions/"+base64.b64encode(dvm.get_name().encode("ascii")).decode("ascii")
		return _DuplicityPermissionsContext(backup_storage_vm, encrypted_name, permission_file)

class _DuplicityPermissionsContext:
	def __init__(self, backup_storage_vm, encrypted_name, permission_file):
		self.permission_file = permission_file
		self.backup_storage_vm = backup_storage_vm
		self.encrypted_name = encrypted_name
	def __enter__(self):
		self.backup_storage_vm.check_output("sudo mkdir -p /var/run/v6-qubes-backup-poc-permissions")
		self.backup_storage_vm.check_output("echo -n "+shlex.quote(self.encrypted_name)+" | sudo tee "+shlex.quote(self.permission_file)+".ip")
		self.backup_storage_vm.check_output("sudo mv "+shlex.quote(self.permission_file)+".ip "+shlex.quote(self.permission_file)) # This way prevents race condition. I know, this is not the best approach for duraility, but that's not what we need. (Especially if those files don't survive reboot.)
	def __exit__(self, type, value, traceback):
		self.backup_storage_vm.check_output("sudo rm "+shlex.quote(self.permission_file)) # remove permissions (not strictly needed for security, just hygiene)
