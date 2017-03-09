from backupsession import VmKeys;
from unittest import TestCase;

class VmKeysTest(TestCase):
	def test_no_data_leaks(self):
		a = VmKeys(encrypted_name='AAA', key = b'asdf')
		b = VmKeys(encrypted_name='AAB', key = b'asdg')
		self.assertNotEqual(a, b)
		self.assertEqual(str(a), str(b))
	
	
if __name__ == 'main':
	unittest.main()
