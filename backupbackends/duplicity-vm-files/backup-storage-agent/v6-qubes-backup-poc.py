#!/usr/bin/python2 -u
# -*- coding=utf-8 -*-
# In python 2, we cannot be so generic to use /usr/bin/env. If we were, we could not pass the -u parameter.

import sys
import os
from os import close
import subprocess
import base64
import time
import duplicity.backend
import duplicity.log
import duplicity.path
from common import Commands, StatusCodes, read_until_zero, read_safe_filename
from tempfile import NamedTemporaryFile
from shutil import copyfileobj

def action_list(backend, inp, out):
	result = backend.list()
	out.write(StatusCodes.OK)
	for i in result:
		assert(i.find(b'\0') == -1)
		out.write(i.encode('ascii'))
		out.write(b'\0')

def action_put(backend, inp, out):
	filename = read_safe_filename(inp)
	tmp = NamedTemporaryFile(delete = False)
	try:
		try:
			copyfileobj(inp, tmp.file)
		finally:
			tmp.file.close()
		backend.put(duplicity.path.Path(tmp.name), filename)
		out.write(StatusCodes.OK)
	finally:
		os.remove(tmp.name)

def action_get(backend, inp, out):
	filename = read_safe_filename(inp)
	tmp = NamedTemporaryFile(delete = False)
	try:
		tmp.file.close()
		backend.get(filename, duplicity.path.Path(tmp.name))
		with open(tmp.name, "rb") as f:
			out.write(StatusCodes.OK)
			copyfileobj(f, out)
	finally:
		os.remove(tmp.name)

def action_delete(inp):
	raise Exception("Not implemented")

def main():
	with open("/tmp/backup-log-"+str(time.time()), "w+") as logfile:
		def error(s, additional_data = None):
			logfile.write(s+str(additional_data))
			print(StatusCodes.ERROR + s)
			exit(1)
		inp = sys.stdin# For Python 3: .buffer
		out = sys.stdout# For Python 3: .buffer
		remote = os.environ['QREXEC_REMOTE_DOMAIN']
		action_letter = inp.read(1)
		actions = {
			Commands.LIST: action_list,
			Commands.PUT: action_put,
			Commands.DELETE: action_delete,
			Commands.GET: action_get
		}
		duplicity.log._logger = duplicity.log.DupLogger("some logger")
		duplicity.backend.import_backends()
		with open("/rw/config/v6-qubes-backup-poc-duplicity-path", "r") as f:
			path_prefix = f.read().rstrip("\n")
		# The file-based auth was chosen in order to preserve state across processes. Yes, we could use IPC, but this would be probably more complex.
		with open("/var/run/v6-qubes-backup-poc-permissions/"+base64.b64encode(remote.encode("ascii")).decode("ascii"), "rb") as f:
			allowed_path = f.read()
		requested_path = read_until_zero(inp)
		if allowed_path != requested_path:
			error("bad path: " + str(allowed_path) + " vs " + str(requested_path))
		else:
			backend_url = path_prefix+"/"+requested_path
			backend = duplicity.backend.get_backend(backend_url)
			if backend is None:
				error("Don't know backend for the URL", backend_url)
			act = actions.get(action_letter)
			if act is None:
				error("bad command")
			act(backend, inp, out)

if __name__ == "__main__":
	main()
