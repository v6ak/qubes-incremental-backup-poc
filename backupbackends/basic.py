from base64 import b64encode
import shlex

# If you want to implement another backend, you can, but maybe you should wait a while until the API becomes more stable.
# TODO: document interface
class BackupBackend:	
	
	# TODO: Move elsewhere. This will be done as part of backupbackend-agnostic backup storage within #37
	def add_permissions(self, backup_storage_vm, dvm, encrypted_name):
		permission_file = "/var/run/v6-qubes-backup-poc-permissions/"+b64encode(dvm.get_name().encode("ascii")).decode("ascii")
		return _DuplicityPermissionsContext(backup_storage_vm, encrypted_name, permission_file)


class _DuplicityPermissionsContext:
	def __init__(self, backup_storage_vm, encrypted_name, permission_file):
		self.permission_file = permission_file
		self.backup_storage_vm = backup_storage_vm
		self.encrypted_name = encrypted_name
	def __enter__(self):
		self.backup_storage_vm.check_call("sudo mkdir -p /var/run/v6-qubes-backup-poc-permissions")
		self.backup_storage_vm.check_call("echo -n "+shlex.quote(self.encrypted_name)+" | sudo tee "+shlex.quote(self.permission_file)+".ip")
		self.backup_storage_vm.check_call("sudo mv "+shlex.quote(self.permission_file)+".ip "+shlex.quote(self.permission_file)) # This way prevents race condition. I know, this is not the best approach for duraility, but that's not what we need. (Especially if those files don't survive reboot.)
	def __exit__(self, type, value, traceback):
		self.backup_storage_vm.check_call("sudo rm "+shlex.quote(self.permission_file)) # remove permissions (not strictly needed for security, just hygiene)
