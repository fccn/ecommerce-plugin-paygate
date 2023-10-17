from django.test.testcases import TestCase
from mock import Mock
from paygate import ip


class PayGateIPTestCase(TestCase):
    """
    Test the IP address logic to protect the PayGate server callback.
    """

    def test_get_client_ip_address_from_x_forwarded_for(self):
        """
        Get the client IP from X-Forwarded-For HTTP request header with different proxies.
        """
        request = Mock(path="/")
        request.META = {
            "HTTP_X_FORWARDED_FOR": "103.0.213.125, 80.91.3.17, 120.192.335.629",
        }
        self.assertEqual(ip.get_client_ip(request), "103.0.213.125")

    def test_get_client_ip_address_from_remote_addr(self):
        """
        Get the client IP from REMOTE_ADDR HTTP request header.
        """
        request = Mock(path="/")
        request.META = {
            "REMOTE_ADDR": "143.0.213.124",
        }
        self.assertEqual(ip.get_client_ip(request), "143.0.213.124")

    def test_client_ip_list_ips_allowed(self):
        """
        Test the `allowed_client_ip` method using a list of IPs and one is allowed.
        """
        self.assertTrue(
            ip.allowed_client_ip(
                "143.0.213.123", ["143.0.213.122", "143.0.213.123", "143.0.213.124"]
            )
        )

    def test_client_ip_list_ips_disallowed(self):
        """
        Test the `allowed_client_ip` method using a list of IPs any is allowed.
        """
        self.assertFalse(
            ip.allowed_client_ip(
                "143.0.213.123", ["143.0.213.121", "143.0.213.122", "143.0.213.124"]
            )
        )

    def test_client_ip_network_24_allowed(self):
        """
        Test the `allowed_client_ip` method using a list of IPs any is allowed.
        """
        self.assertTrue(ip.allowed_client_ip("192.168.1.100", ["192.168.1.0/24"]))

    def test_client_ip_network_24_disallowed(self):
        """
        Test the `allowed_client_ip` method using a list of IPs any is allowed.
        """
        self.assertFalse(ip.allowed_client_ip("143.0.213.123", ["192.168.1.0/24"]))

    def test_client_ip_network_multiple_allowed(self):
        """
        Test the `allowed_client_ip` method using a multiple networks, one should allow the client.
        """
        self.assertTrue(ip.allowed_client_ip("192.168.1.100", ["193.161.1.0/24", "192.168.1.0/24"]))

    def test_client_ip_network_multiple_disallowed(self):
        """
        Test the `allowed_client_ip` method using a multiple networks any should allow the client.
        """
        self.assertFalse(ip.allowed_client_ip("190.121.1.101", ["193.161.1.0/24", "192.168.1.0/24"]))
