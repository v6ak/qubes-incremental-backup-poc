#!/bin/bash
# safety settings
set -u
set -e
set -o pipefail

# This script uploads all scripts from dom0 to a VM mentioned in repo_vm file

PACK=(
	backup backup.py
	upload.sh
	qubesvmtools.py
	backupconfig.py
	cryptopunk.py
	vm-backup-agent
	backupsession.py
)
IGNORE=(
	repo_vm
	testconfig
	__pycache__
	backupbackends/__pycache__
)

if ! diff <(find "${PACK[@]}" "${IGNORE[@]}" -type f -or -type l | sort) <(find -type f -or -type l | sed 's#^\./##' | sort); then
	echo not continuing…
	exit 1
fi
echo uploading
tar czf - "${PACK[@]}" | qvm-run -p -a "$(cat repo_vm)" 'cd backup-tools; tar xzf -'
