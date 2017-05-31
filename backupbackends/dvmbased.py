from qubesvmtools import Dvm
import shlex
import subprocess
from .basic import BackupBackend

class DvmBasedBackupBackend(BackupBackend):
	def backup_vm(self, vm, vm_keys, backup_storage_vm):
		volume_clone = vm.private_volume().clone("v6-qubes-backup-poc-cloned")
		try:
			with Dvm() as dvm:
				dvm.attach("xvdz", volume_clone)  # --ro: 1. is not needed since it is a clone, 2. blocks repair procedures when mounting
				try:
					dvm.check_call("sudo mkdir /mnt/clone")
					dvm.check_call("sudo mount /dev/xvdz /mnt/clone") # TODO: consider -o nosuid,noexec – see issue #16
					try:
						self.upload_agent(dvm)
						with self.add_permissions(backup_storage_vm, dvm, vm_keys.encrypted_name):
							dvm.check_call("/tmp/backup-agent "+shlex.quote(backup_storage_vm.get_name())+" "+shlex.quote(vm_keys.encrypted_name), input = vm_keys.key, stdout = None, stderr = None)
					finally: dvm.check_call("sudo umount /mnt/clone")
				finally: dvm.detach_all()
		finally: volume_clone.remove()

	def restore_vm(self, new_vm, new_name, size, qvm_create_args, vm_keys, backup_storage_vm):
		subprocess.check_call("qvm-create "+shlex.quote(new_name)+" "+qvm_create_args, shell=True)
		subprocess.check_call(["qvm-prefs", "-s", new_name, "netvm", "none"]) # Safe approach…
		if size is not None:
			subprocess.check_call(["qvm-grow-private", new_name, size])
		with Dvm() as dvm:
			dvm.attach("xvdz", new_vm.private_volume())
			try:
				if size is not None:
					dvm.check_call("sudo e2fsck -f -p /dev/xvdz")
					dvm.check_call("sudo resize2fs /dev/xvdz")
				dvm.check_call("sudo mkdir /mnt/clone")
				dvm.check_call("sudo mount /dev/xvdz /mnt/clone")
				try:
					self.upload_agent(dvm)
					with self.add_permissions(backup_storage_vm, dvm, vm_keys.encrypted_name):
						dvm.check_call("/tmp/restore-agent "+shlex.quote(backup_storage_vm.get_name())+" "+shlex.quote(vm_keys.encrypted_name), input = vm_keys.key, stdout = None, stderr = None)
				finally: dvm.check_call("sudo umount /mnt/clone")
			finally: dvm.detach_all()

	# abstract def upload_agent(self, dvm)

