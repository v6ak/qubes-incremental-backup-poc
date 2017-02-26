# python2 module
import re
import duplicity.backend
import duplicity.urlparse_2_5 as urlparser
import subprocess
from duplicity.backends.qubesintervmbackendprivate.common import Commands, StatusCodes, write_zero_terminated_ascii, sanitize_filename
from os.path import basename
from shutil import copyfileobj


class QubesInterVmBackend(duplicity.backend.Backend):
	def __init__(self, parsed_url):
		duplicity.backend.Backend.__init__(self, parsed_url)
		print(parsed_url.path)
		pat = re.compile("^/+([^/]+)/([^/]+)$")
		parts = pat.match(parsed_url.path)
		self.vm = parts.group(1)
		self.path = parts.group(2)

	def _call_command(self, command_letter):
		return _QubesInterVmBackendChannel(command_letter, self.path, self.vm);

	def _check_for_error_message(self, inp):
		response = inp.read(1)
		if response == StatusCodes.ERROR:
			raise Exception("Error messge from the other end: "+inp.read(1024).decode('ascii'))
		elif response == StatusCodes.OK:
			print("got OK code")
			return inp # OK
		elif len(response) == 0:
			raise Exception("Unexpected empty response")
		else:
			raise Exception("Unexpected response code: "+str(ord(response)))

	def _read_all(self, proc):
		return self._check_for_error_message(proc.stdout).read()

	# Methods required for Duplicity:
	def _list(self):
		with self._call_command(Commands.LIST) as proc:
			return map(sanitize_filename, self._read_all(proc).decode('ascii').split('\0'))

	def put(self, source_path, remote_filename = None):
		name = remote_filename or source_path.get_filename()
		with source_path.open("rb") as f, self._call_command(Commands.PUT) as proc:
			write_zero_terminated_ascii(proc.stdin, name)
			copyfileobj(f, proc.stdin)
			proc.stdin.close() # let the peer know we are finished. TODO: close automatically in _call_command?
			self._check_for_error_message(proc.stdout)
	
	def get(self, remote_filename, local_path):
		with local_path.open("w") as f, self._call_command(Commands.GET) as proc:
			write_zero_terminated_ascii(proc.stdin, remote_filename)
			proc.stdin.close()
			self._check_for_error_message(proc.stdout)
			copyfileobj(proc.stdout, f)

	# TODO:
	# def delete(self, filename_list) <-- not needed yet


class _QubesInterVmBackendChannel:
	def __init__(self, command_letter, path, vm):
		self.command_letter = command_letter
		self.path = path
		self.vm = vm
		self.initialized = False
	def __enter__(self):
		self.proc = subprocess.Popen([
			"/usr/lib/qubes/qrexec-client-vm",
			self.vm,
			"v6ak.QubesInterVmBackupStorage"
		], stdin = subprocess.PIPE, stdout = subprocess.PIPE)# , stderr = subprocess.PIPE
		try:
			self.proc.stdin.write(self.command_letter)
			write_zero_terminated_ascii(self.proc.stdin, self.path)
		except:
			self.__exit__(*sys.exc_info())
			raise
		self.initialized = True
		return self.proc
	def __exit__(self, type, value, traceback):
		def close(f):
			if f is not None:
				f.close()
		def check_empty(f):
			if f is None: return
			res = f.read(1)
			if len(res) <> 0:
				raise Exception("Unexpected byte "+str(ord(res)))
		try:
			if self.initialized and (type is None): # Do not perform sanity checks when an exception is thrown, as they would likely fail and hide the root of cause
				# Assert that nothing remains
				check_empty(self.proc.stdout)
				check_empty(self.proc.stderr)
		finally:
			close(self.proc.stdin)
			close(self.proc.stderr)
			close(self.proc.stdout)
			return_code = self.proc.wait()
		if return_code <> 0:
			raise Exception("process did not finish with success: "+str(return_code))

duplicity.backend.register_backend('qubesintervm', QubesInterVmBackend)
