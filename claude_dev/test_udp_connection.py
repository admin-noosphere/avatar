#!/usr/bin/env python3
"""Test UDP connection to Audio2Face server.

Usage:
    python claude_dev/test_udp_connection.py
"""

import socket
import sys
import time

from loguru import logger

# Configuration
UDP_HOST = "192.168.1.14"
UDP_PORT = 8080
TEST_MESSAGE = b"PIPECAT_TEST_PACKET"


def test_udp_connection(host: str = UDP_HOST, port: int = UDP_PORT) -> bool:
    """Test UDP connection to Audio2Face.

    Args:
        host: Target host IP
        port: Target UDP port

    Returns:
        True if connection successful, False otherwise
    """
    logger.info(f"Testing UDP connection to {host}:{port}")

    try:
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)

        # Send test packet
        logger.info(f"Sending test packet: {TEST_MESSAGE}")
        sock.sendto(TEST_MESSAGE, (host, port))

        logger.success(f"✅ UDP packet sent successfully to {host}:{port}")
        logger.info("Note: UDP is fire-and-forget, no ACK received")

        # Send multiple packets to simulate audio stream
        logger.info("Sending 10 test packets to simulate audio stream...")
        for i in range(10):
            test_data = f"PACKET_{i:03d}".encode() + b"\x00" * 1024  # ~1KB packets
            sock.sendto(test_data, (host, port))
            time.sleep(0.01)  # 100 packets/sec simulation

        logger.success("✅ Audio stream simulation complete")
        sock.close()
        return True

    except socket.gaierror as e:
        logger.error(f"❌ DNS resolution failed: {e}")
        logger.error(f"Cannot resolve hostname: {host}")
        return False

    except OSError as e:
        logger.error(f"❌ Network error: {e}")
        logger.error("Possible causes:")
        logger.error("  - Host unreachable (check network)")
        logger.error("  - Firewall blocking UDP port")
        logger.error("  - Invalid IP address")
        return False

    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False


def ping_host(host: str = UDP_HOST) -> bool:
    """Check if host is reachable via ICMP ping.

    Args:
        host: Target host IP

    Returns:
        True if ping successful
    """
    import subprocess

    logger.info(f"Pinging {host}...")
    try:
        result = subprocess.run(
            ["ping", "-c", "3", host],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            logger.success(f"✅ Host {host} is reachable")
            return True
        else:
            logger.error(f"❌ Host {host} is NOT reachable")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"❌ Ping timeout to {host}")
        return False
    except FileNotFoundError:
        logger.warning("⚠️  'ping' command not found, skipping ping test")
        return True  # Don't fail on missing ping


def main() -> None:
    """Main test function."""
    logger.info("=" * 60)
    logger.info("Audio2Face UDP Connection Test")
    logger.info("=" * 60)

    # Step 1: Ping test
    ping_success = ping_host(UDP_HOST)

    # Step 2: UDP test
    udp_success = test_udp_connection(UDP_HOST, UDP_PORT)

    # Summary
    logger.info("=" * 60)
    logger.info("Test Summary:")
    logger.info(f"  Ping Test: {'✅ PASS' if ping_success else '❌ FAIL'}")
    logger.info(f"  UDP Test:  {'✅ PASS' if udp_success else '❌ FAIL'}")
    logger.info("=" * 60)

    if not ping_success:
        logger.warning("\n⚠️  Troubleshooting Steps:")
        logger.warning("  1. Check that 192.168.1.14 is the correct IP")
        logger.warning("  2. Ensure both machines are on the same network")
        logger.warning("  3. Check network cables/WiFi connection")

    if ping_success and not udp_success:
        logger.warning("\n⚠️  UDP Connection Failed:")
        logger.warning("  1. Check firewall on 192.168.1.14:")
        logger.warning("     sudo ufw allow 8080/udp")
        logger.warning("  2. Verify Audio2Face is listening on port 8080")
        logger.warning("  3. Check router/switch configuration")

    sys.exit(0 if (ping_success and udp_success) else 1)


if __name__ == "__main__":
    main()
