# python2

# Common file for both parts of the inter-VM backup protocol

class Commands:
	LIST = b'L'
	PUT = b'P'
	GET = b'G'
	DELETE = b'D'

class StatusCodes:
	OK = b'O'
	ERROR = b'E'

def sanitize_filename(filename):
	dot_allowed = True
	for c in filename:
		if (c == '.') and dot_allowed:
			dot_allowed = False
			continue
		dot_allowed = True # Will not read untill next iteration, so we can change it now. TODO: make the flow more clear
		if (c >= 'a') and (c <= 'z'): continue
		if (c >= 'A') and (c <= 'Z'): continue
		if (c >= '0') and (c <= '9'): continue
		if (c == '-') or (c == '_'): continue
		raise Exception("Unexpected character: "+str(ord(c)))
	return filename

def read_until_zero(inp, maxlen = None):
	# The bytearray wrap is needed in Python2; Without this, it behaves cucumbersome: It converts inp to string. In Python 3, this hack should not be needed.
	return bytes(bytearray(_read_until_zero_intgen(inp, maxlen)))

def _read_until_zero_intgen(inp, maxlen = None):
	n = 0
	while True:
		n += 1
		if (maxlen is not None) and (n > maxlen):
			raise Exception("Reading data longer than "+str(maxlen))
		chunk = inp.read(1)
		if len(chunk) == 1:
			if chunk == b'\0':
				break
			else:
				yield chunk[0] # contains int
		elif len(chunk) == 0:
			raise Exception("Reached EOF after reading "+str(n)+" bytes witout seeing any zero byte!")
		else:
			assert(False)

def read_safe_filename(inp):
	return sanitize_filename(read_until_zero(inp, 255))

def write_zero_terminated_ascii(f, bs):
	assert(bs.find(b'\0') == -1)
	f.write(bs.encode("ascii"))
	f.write(b'\0')

