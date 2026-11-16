import unittest

from app.core import whatsapp_digits


class ContactTests(unittest.TestCase):
    def test_old_placeholder_uses_phone(self):
        self.assertEqual(
            whatsapp_digits({"phone": "+7 700 000 00 00", "whatsapp": "77000000000"}),
            "77000000000",
        )

    def test_custom_whatsapp_is_kept(self):
        self.assertEqual(
            whatsapp_digits({"phone": "+7 700 000 00 00", "whatsapp": "77011112233"}),
            "77011112233",
        )

    def test_empty_whatsapp_uses_phone(self):
        self.assertEqual(
            whatsapp_digits({"phone": "+7 700 000 00 00", "whatsapp": ""}),
            "77000000000",
        )
