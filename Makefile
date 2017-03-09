.PHONY: test test-unit test-unit-backupsession default

default: test
test: test-unit
test-unit: test-unit-backupsession
	python3 -m unittest tests.backupsessiontest
