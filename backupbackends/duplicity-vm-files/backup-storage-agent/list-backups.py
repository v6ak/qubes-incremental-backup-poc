#!/usr/bin/python2 -u
# -*- coding=utf-8 -*-
# In python 2, we cannot be so generic to use /usr/bin/env. If we were, we could not pass the -u parameter.

import sys
import duplicity.backend
import duplicity.log
import duplicity.path
from common import write_zero_terminated_ascii


def main():
	inp = sys.stdin# For Python 3: .buffer
	out = sys.stdout# For Python 3: .buffer
	# TODO: extract to some common function
	duplicity.log._logger = duplicity.log.DupLogger("some logger")
	duplicity.backend.import_backends()
	with open("/rw/config/v6-qubes-backup-poc-duplicity-path", "r") as f:
		backend_url = f.read().rstrip("\n")
	backend = duplicity.backend.get_backend(backend_url)
	if backend is None:
		raise Exception("Don't know backend for the URL", backend_url)
	for i in backend.list():
		out.write(b'N')
		write_zero_terminated_ascii(out, i)		

if __name__ == "__main__":
	main()
