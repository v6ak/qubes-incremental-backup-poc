# python3
import subprocess
import re
from pathlib import Path
import os

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

class VmInstance:
	def __init__(self, name):
		self.name = name
	def get_name(self):
		return self.name
	def attach(self, name, volume):
		subprocess.check_output(["qvm-block", "--attach-file", self.name, volume.xen_path(), "-f", name])
	def detach_all(self):
		subprocess.check_output(["qvm-block", "--detach", self.name])
	def create_command(self, command):
		return ["qvm-run", "-a", "-p", self.name, command]
	def check_output(self, command, stdin = None, input = None):
		if stdin == None:
			return subprocess.check_output(self.create_command(command), input = input)
		elif input == None:
			return subprocess.check_output(self.create_command(command), stdin = stdin)
		else:
			raise Exception("cannot handle both stdin and input")
class DvmInstance(VmInstance):
	def __init__(self, name):
		super().__init__(name)
	@staticmethod
	def create(color = "red"):
		vm_name = subprocess.check_output(["/usr/lib/qubes/qfile-daemon-dvm", "LAUNCH", "dom0", "", color]).decode("ascii").rstrip("\n")
		if vm_name == '': # This theoretically should not happen, but I've seen this to happen when low on memory
			raise Exception("Unable to start DVM")
		return DvmInstance(vm_name)
	def close(self):
		subprocess.check_output(["/usr/lib/qubes/qfile-daemon-dvm", "FINISH", self.name])

class Volume:
	def __init__(self, vm):
		self.vm = vm
	def clone(self, mark):
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
	def clone(self, mark):
		clone_lv = mark+"-"+self.lv
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
	def clone(self, mark):
		if self.vm.is_running():
			raise Exception("VM is running, backup is not supported for this type of VM when running")
		clone_path = Path(str(self.path)+"."+mark)
		#shutil.copyfile(str(self.path), str(clone_path)) <— does not seem to support sparse files, so it is slooooooow
		subprocess.check_output(["cp", "--sparse=always", "--", str(self.path), str(clone_path)])
		return FileVolume(self.vm, clone_path)
	def remove(self):
		os.remove(str(self.path))
	def xen_path(self):
		return "dom0:"+str(self.path)
