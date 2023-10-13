"""
Ip aware code
"""
import ipaddress


def get_client_ip(request):
    """
    Get the Client IP address from the `X-Forwarded-For` header.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip_addr = x_forwarded_for.split(",")[0]
    else:
        ip_addr = request.META.get("REMOTE_ADDR")
    return ip_addr


def allowed_client_ip(client_ip: str, allowed_networks: list) -> bool:
    """
    Check if the client_ip is inside of one of the allowed networks.
    """
    return next(
        filter(
            lambda net: ipaddress.ip_address(client_ip) in ipaddress.ip_network(net),
            allowed_networks,
        ) is not None
    )
