# python3

from cryptopunk import aes256_hiv_encrypt, aes256_hiv_decrypt
import hmac
import collections
import base64

# Plaintext filename: Any case-sensitive utf-8 string without binary zeros (i.e. '\0') of size (in bytes) at most filename_plain_size
# Ciphertext filename: A case-insensitive ascii base32 name of length base32_size_increase(filename_plain_size+mac_size)
# Properties:
# * Does not leak filename length
# * The same plaintext filename is encrypted to the same ciphertext filename
# * Related plaintext filenames are encrypted to unrelated ciphertext filenames
# * Filenames are authenticated, i.e. attacker cannot abuse malleability
# We use base32 in order to survive case-insensitive filesystem
class FileNameCrypter:
	def __init__(self, key, mac_size, filename_plain_size):
		self.key = key
		self.mac_size = mac_size
		self.filename_plain_size = filename_plain_size
	def encrypt(self, filename):
		encoded_filename_unpadded = filename.encode("utf-8")
		assert(encoded_filename_unpadded.find(b'\0') == -1)
		encoded_filename_padded = encoded_filename_unpadded.ljust(self.filename_plain_size, b'\0')
		assert(len(encoded_filename_unpadded) <= self.filename_plain_size)
		assert(len(encoded_filename_padded) == self.filename_plain_size)
		encrypted_filename_bytes = aes256_hiv_encrypt(self.key, encoded_filename_padded, self.mac_size)
		return base64.b32encode(encrypted_filename_bytes).decode("ascii")
	def decrypt(self, filename):
		plain_padded = aes256_hiv_decrypt(self.key, base64.b32decode(filename.upper()), self.mac_size)
		assert(len(plain_padded) == self.filename_plain_size )
		plain = plain_padded.rstrip(b'\0')
		assert(plain.find(b'\0') == -1)
		return plain.decode("utf-8")

class VmKeys(collections.namedtuple('VmKeys', 'encrypted_name key')):
	def __str__(self):
		return "VmKeys(…)"

class MasterBackupSession:
	def __init__(self, master_key, filename_mac_size = 16):
		self.master_key = master_key
		self.filename_mac_size = filename_mac_size
		self.file_name_crypter = FileNameCrypter(self.subkey(b"files", 512), self.filename_mac_size, 96)
	def subkey(self, subkey_id, length=256):
		assert((length == 256) or (length == 512))
		HASHES = {
			256: "sha256",
			512: "sha512"
		}
		return hmac.new(self.master_key, subkey_id, HASHES[length]).digest()
	def subkey_vm(self, vm_name):
		return self.subkey(("vm-"+vm_name).encode("utf-8"))
	def test_master_key(self, test_content):
		return hmac.compare_digest(test_content, self.gen_test_content())
	def gen_test_content(self):
		# Derive a testing key and MAC some hardcoded content :)
		return hmac.new(self.subkey(b"test"), base64.b64decode("UMWZw61sacWhIMW+bHXFpW91xI1rw70ga8WvbiDDunDEm2wgxI/DoWJlbHNrw6kgw7NkeS4="), "sha256").digest()
	def vm_keys(self, vm_name):
		return VmKeys(
			encrypted_name = self.file_name_crypter.encrypt(vm_name),
			key = self.subkey_vm(vm_name)
		)
