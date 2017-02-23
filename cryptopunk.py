# python3
import subprocess
import base64
import hmac
import binascii

# This file calls external binaries and leaks sensitive data (inc. keys) in parameters. This is justifiable in dom0, but not as general-purpose library. This is also why it is named cryptopunk.

def scrypt(password, salt, log2_N, r, p, length):
	# I found no Python scrypt implementation in dom0 repository :(
	return subprocess.check_output([
		"perl",
		"-e",
		'use Crypt::ScryptKDF; use MIME::Base64; print(Crypt::ScryptKDF::scrypt_raw(decode_base64($ARGV[5]), decode_base64($ARGV[0]), 1<<($ARGV[1]+0), ($ARGV[2]+0), ($ARGV[3]+0), ($ARGV[4]+0)));',
		"--",
		base64.b64encode(salt),
		str(log2_N),
		str(r),
		str(p),
		str(length),
		base64.b64encode(password.encode("utf-8"))
	])

# Encrypts or decrypts in AES-256 CTR mode. Encryption and decryption are the same. This is a low-level (pure) function where one has to specify IV.
def aes256_ctr(key, iv, data):
	assert len(key) == 32
	assert len(iv) == 16
	# crosstest: http://www.cryptogrium.com/aes-ctr.html
	return subprocess.check_output(
		["openssl", "enc", "-aes-256-ctr", "-K", binascii.hexlify(key), "-iv", binascii.hexlify(iv)],
		input=data
	)

# AES-HIV is like AES-SIV, but it uses HMAC-SHA256 instead of S2V…

def aes256_hiv_key_split(key):
	assert(len(key) == 64)
	key_crypt = key[:32]
	key_mac = key[32:]
	return [key_crypt, key_mac]

def aes256_hiv_encrypt(key, plaintext, mac_size_bytes = 32):
	assert(mac_size_bytes <= 32) # more bytes would not work well with SHA-256
	assert(mac_size_bytes >= 16) # less bytes could cause problems with IV
	[key_crypt, key_mac] = aes256_hiv_key_split(key)
	mac = hmac.new(key_mac, plaintext, "sha256").digest()[:mac_size_bytes]
	iv = mac[:16]
	encrypted = aes256_ctr(key_crypt, iv, plaintext)
	return mac + encrypted

def aes256_hiv_decrypt(key, ciphertext, mac_size_bytes = 32):
	assert(mac_size_bytes <= 32) # more bytes would not work well with SHA-256
	assert(mac_size_bytes >= 16) # less bytes could cause problems with IV
	[key_crypt, key_mac] = aes256_hiv_key_split(key)
	mac_actual = ciphertext[:mac_size_bytes]
	iv = mac_actual[:16]
	encrypted = ciphertext[mac_size_bytes:]
	plaintext_unverified = aes256_ctr(key_crypt, iv, encrypted)
	mac_expected = hmac.new(key_mac, plaintext_unverified, "sha256").digest()[:mac_size_bytes]
	if hmac.compare_digest(mac_expected, mac_actual):
		return plaintext_unverified
	else:
		raise Exception("bad MAC")
