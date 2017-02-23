# python3
import collections
import os
from cryptopunk import scrypt
from pathlib import Path

class ConfigItem(collections.namedtuple('ConfigItem', 'default_generator')):
	def default(self):
		return self.default_generator()
class SaltConfigItem(ConfigItem):
	def read(self, inp):
		res = inp.read(32)
		assert(len(res) == 32)
		assert(len(inp.read(1)) == 0) # check EOF
		return res
	def write(self, out, value):
		out.write(value)

class IntConfigItem(ConfigItem):
	def read(self, inp):
		res = inp.read(10) # up to 10 characters
		assert(len(inp.read(1)) == 0) # check EOF
		return int(res)
	def write(self, out, value):
		out.write(str(value).encode("ascii"))

class BackupConfig:
	def __init__(self, path, master_pass_config):
		self.master_pass_config = master_pass_config
		self.path = path
	@staticmethod
	def get_default_path(): return Path(os.path.expanduser("~/.v6-qubes-backup-poc"))
	@staticmethod
	def read_or_create(path):
		# Maybe one could find an existing library that does this better. The problem is that the library would have to be reasonably reviewed, which is not an easy task.
		conf = {
			"salt": SaltConfigItem(lambda: os.urandom(32)),
			"log2_N": IntConfigItem(lambda: 17),
			"r": IntConfigItem(lambda: 8),
			"p": IntConfigItem(lambda: 8)
		}
		res = {}
		master_path = path / "master"
		if not os.path.exists(str(master_path)):
			os.makedirs(str(master_path))
		for key, value_coder in conf.items():
			f = master_path / key
			if f.exists():
				with open(str(f), "rb") as inp:
					res[key] = value_coder.read(inp)
			else:
				with open(str(f), "wb+") as out:
					value = value_coder.default()
					value_coder.write(out, value)
					res[key] = value
		return BackupConfig(path, res)
	def get_password_kdf(self):
		return lambda password: scrypt(password, self.master_pass_config['salt'], self.master_pass_config['log2_N'], self.master_pass_config['r'], self.master_pass_config['p'], 32)
	def _passphrase_test_file(self):
		return self.path / "passphrase_test"
	def passphrase_exists(self):
		return os.path.exists(str(self._passphrase_test_file()))
	def get_passphrase_test(self):
		with open(str(self._passphrase_test_file()), "rb") as f: return f.read(64)
	def save_passphrase_test(self, new_data):
		with open(str(self._passphrase_test_file()), "wb+") as f: return f.write(new_data)
