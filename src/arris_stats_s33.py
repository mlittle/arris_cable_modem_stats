"""
Modem implementation for Arris S33.
https://github.com/andrewfraley/arris_cable_modem_stats
"""
# pylint: disable=line-too-long
import time
import hmac
import logging
from typing import Any, Dict, List, Optional
import requests

try:
    from src.modem_interface import ModemInterface
except ImportError:
    from modem_interface import ModemInterface


class S33Modem(ModemInterface):
    """Arris S33 modem implementation using HNAP JSON API."""

    def __init__(self):
        """Initialize the modem with no credentials."""
        self.credential: Optional[Dict[str, str]] = None

    def get_config_keys(self) -> List[str]:
        """Return list of required config keys for S33."""
        return ['modem_ip', 'modem_username', 'modem_password', 'modem_verify_ssl', 'request_timeout']

    @staticmethod
    def _arris_hmac(key: bytes, msg: bytes) -> str:
        """
        HMAC a message with a key in the way the Arris S33 does it.

        Taken from https://github.com/t-mart/ispee/blob/master/src/ispee/s33.py
        """
        return (
            hmac.new(
                key=key,
                msg=msg,
                digestmod="md5",
            )
            .hexdigest()
            .upper()
        )

    @staticmethod
    def _hnap_auth_header(private_key: Optional[str], soap_action: str) -> str:
        """
        Return a value to be used for the custom HNAP_AUTH http header.

        This method works both before and after login. When not logged in,
        private_key should be None and a default key is used.
        """
        if private_key is None:
            private_key = "withoutloginkey"

        # Current time in milliseconds for auth timestamp
        cur_time_millis = str((time.time_ns() // 10**6) % 2_000_000_000_000)

        auth_part = S33Modem._arris_hmac(
            private_key.encode("utf-8"),
            (cur_time_millis + soap_action).encode("utf-8"),
        )

        return f"{auth_part} {cur_time_millis}"

    def authenticate(self, config: Dict[str, Any], session: requests.Session) -> bool:
        """
        Authenticate with the S33 modem using HNAP protocol.

        Args:
            config: Configuration dictionary with modem_ip, username, password, etc.
            session: requests.Session object

        Returns:
            bool: True if authentication successful, False otherwise
        """
        logging.info('Obtaining login session from modem')

        ip = config['modem_ip']
        username = config['modem_username']
        password = config['modem_password']
        verify_ssl = config['modem_verify_ssl']
        timeout = config.get('request_timeout', 10)
        url = f"https://{ip}/HNAP1/"

        # First request to get challenge
        payload = {
            "Login": {
                "Action": "request",
                "Username": username,
                "LoginPassword": "",
                "Captcha": "",
                "PrivateLogin": password,
            }
        }

        soap_action = '"http://purenetworks.com/HNAP1/Login"'

        headers = {
            "Accept": "application/json",
            "SOAPACTION": soap_action,
            "HNAP_AUTH": self._hnap_auth_header(private_key=None, soap_action=soap_action),
        }

        try:
            resp = requests.post(
                url=url,
                json=payload,
                headers=headers,
                verify=verify_ssl,
                timeout=timeout
            )

            if resp.status_code != 200:
                logging.error('Error requesting login with %s', url)
                logging.error('Status code: %s', resp.status_code)
                logging.error('Reason: %s', resp.reason)
                resp.close()
                return False

            response_obj = resp.json()
            public_key = response_obj["LoginResponse"]["PublicKey"]
            uid = response_obj["LoginResponse"]["Cookie"]
            challenge_msg = response_obj["LoginResponse"]["Challenge"]
            resp.close()

            # Calculate private key from challenge
            private_key = self._arris_hmac(
                key=(public_key + password).encode("utf-8"),
                msg=challenge_msg.encode("utf-8"),
            )

            # Second request to login with calculated credentials
            payload["Login"]["Action"] = "login"
            payload["Login"]["LoginPassword"] = self._arris_hmac(
                key=private_key.encode("utf-8"),
                msg=challenge_msg.encode("utf-8"),
            )

            headers["HNAP_AUTH"] = self._hnap_auth_header(
                private_key=private_key, soap_action=soap_action
            )
            headers["Cookie"] = (
                "Secure; Secure; "  # double secure is strange, but it's how they do it
                f"uid={uid}; "
                f"PrivateKey={private_key}"
            )

            resp = requests.post(
                url=url,
                json=payload,
                headers=headers,
                verify=verify_ssl,
                timeout=timeout
            )

            if resp.status_code != 200:
                logging.error('Error authenticating with %s', url)
                logging.error('Status code: %s', resp.status_code)
                logging.error('Reason: %s', resp.reason)
                resp.close()
                return False

            login_result = resp.json()["LoginResponse"]["LoginResult"]
            if login_result != "OK":
                logging.error('Error authenticating with %s', url)
                logging.error(f"Reason: Got {login_result} login result (expecting OK)")
                resp.close()
                return False

            resp.close()

            # Store credential for use in fetch_data
            self.credential = {'uid': uid, 'private_key': private_key}
            return True

        except Exception as exception:
            logging.error(exception)
            logging.error('Error authenticating with %s', url)
            return False

    def fetch_data(self, config: Dict[str, Any], session: requests.Session) -> Optional[Dict[str, Any]]:
        """
        Fetch JSON stats data from the S33 modem.

        Args:
            config: Configuration dictionary
            session: requests.Session object (should be authenticated first)

        Returns:
            dict: JSON response from modem, or None if error
        """
        if not self.credential:
            logging.error('Not authenticated. Call authenticate() first.')
            return None

        ip = config['modem_ip']
        verify_ssl = config['modem_verify_ssl']
        timeout = config.get('request_timeout', 10)
        url = f"https://{ip}/HNAP1/"

        soap_action = '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"'
        headers = {
            "Accept": "application/json",
            "SOAPACTION": soap_action,
            "HNAP_AUTH": self._hnap_auth_header(
                private_key=self.credential["private_key"], soap_action=soap_action
            ),
            "Cookie": (
                "Secure; Secure; "  # double secure is strange, but how they do it
                f"uid={self.credential['uid']}; "
                f"PrivateKey={self.credential['private_key']}"
            )
        }
        payload = {
            "GetMultipleHNAPs": {
                "GetCustomerStatusDownstreamChannelInfo": "",
                "GetCustomerStatusUpstreamChannelInfo": "",
            }
        }

        logging.info('Retrieving stats from %s', url)

        try:
            resp = requests.post(
                url=url,
                json=payload,
                headers=headers,
                verify=verify_ssl,
                timeout=timeout
            )
            if resp.status_code != 200:
                logging.error('Error retrieving json from %s', url)
                logging.error('Status code: %s', resp.status_code)
                logging.error('Reason: %s', resp.reason)
                return None
            status_json = resp.json()["GetMultipleHNAPsResponse"]
            resp.close()
            return status_json

        except Exception as exception:
            logging.error(exception)
            logging.error('Error retrieving json from %s', url)
            return None

    def parse_data(self, json_data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Parse JSON response into the modem stats dict.

        Args:
            json_data: JSON dict from modem API

        Returns:
            dict: Parsed stats with 'downstream' and 'upstream' keys
        """
        logging.info('Parsing JSON for modem model s33')

        stats = {}

        # downstream table
        stats['downstream'] = []
        for channel in json_data["GetCustomerStatusDownstreamChannelInfoResponse"]["CustomerConnDownstreamChannel"].split("|+|"):
            (
                channel_num,
                lock_status,
                modulation,
                channel_id,
                frequency,
                power,
                snr,
                corrected,
                uncorrectables,
                _,
            ) = channel.split("^")

            stats['downstream'].append({
                'channel_id': channel_id,
                'modulation': modulation,
                'frequency': frequency,
                'power': power,
                'snr': snr,
                'corrected': corrected,
                'uncorrectables': uncorrectables
            })

        logging.debug('downstream stats: %s', stats['downstream'])
        if not stats['downstream']:
            logging.error(
                'Failed to get any downstream stats! If you have selected the correct modem, '
                'then this could be a parsing issue in %s', __file__)

        # upstream table
        stats['upstream'] = []
        for channel in json_data["GetCustomerStatusUpstreamChannelInfoResponse"]["CustomerConnUpstreamChannel"].split("|+|"):
            (
                channel_num,
                lock_status,
                channel_type,
                channel_id,
                width,
                frequency,
                power,
                _,
            ) = channel.split("^")
            stats['upstream'].append({
                'channel_id': channel_id,
                'channel_type': channel_type,
                'frequency': frequency,
                'width': width,
                'power': power,
            })

        logging.debug('upstream stats: %s', stats['upstream'])
        if not stats['upstream']:
            logging.error(
                'Failed to get any upstream stats! If you have selected the correct modem, '
                'then this could be a parsing issue in %s', __file__)

        return stats


# Legacy functions for backward compatibility
def get_credential(config):
    """Legacy function for backward compatibility. Use S33Modem class instead."""
    modem = S33Modem()
    session = requests.Session()
    if modem.authenticate(config, session):
        return modem.credential
    return None


def get_json(config, credential):
    """Legacy function for backward compatibility. Use S33Modem class instead."""
    modem = S33Modem()
    modem.credential = credential
    session = requests.Session()
    return modem.fetch_data(config, session)


def parse_json(json):
    """Legacy function for backward compatibility. Use S33Modem class instead."""
    modem = S33Modem()
    return modem.parse_data(json)


def parse_html_s33(html_or_json):
    """
    Legacy function for backward compatibility with test suite.
    S33 uses JSON API, not HTML, so this function accepts JSON data or a JSON string.
    """
    modem = S33Modem()
    # Handle both raw JSON dict and JSON string
    if isinstance(html_or_json, str):
        import json as json_module
        try:
            data = json_module.loads(html_or_json)
        except:
            # If it's not JSON, try to parse it as a JSON response
            data = html_or_json
    else:
        data = html_or_json
    return modem.parse_data(data)


# Register this modem class with the registry
try:
    from src.modem_registry import register_modem
except ImportError:
    from modem_registry import register_modem
register_modem('s33', S33Modem)