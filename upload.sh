#!/bin/bash
# safety settings
set -u
set -e
set -o pipefail

# This script uploads all scripts from dom0 to a VM mentioned in repo_vm file

PACK=(
	backup backup.py
	install-backup-storage-vm install-backup-storage-vm.py
	backupbackends/duplicity.py
	backupbackends/duplicity-vm-files/vm-backup-agent backupbackends/duplicity-vm-files/qubesintervmbackend.py
	backupbackends/duplicity-vm-files/backup-storage-agent/v6-qubes-backup-poc.py
	backupbackends/duplicity-vm-files/common.py
	# install-dom0 install-backup-storage-vm install
	#config.sample
	upload.sh
	qubesvmtools.py
	backupconfig.py
	cryptopunk.py
	backupsession.py
)
IGNORE=(
	bordel
	#config
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
