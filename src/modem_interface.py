"""
Abstract base class and types for modem implementations.

Each modem model (SB6183, SB8200, T25, S33, etc.) should inherit from
ModemInterface and implement the required methods to handle authentication,
data fetching, and parsing.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Union
import requests

# RawData can be either HTML string or JSON dict depending on modem type
RawData = Union[str, Dict[str, Any]]


class ModemInterface(ABC):
    """
    Abstract base class for all modem implementations.

    Each modem model must implement these methods to integrate with the
    main application loop.
    """

    @abstractmethod
    def get_config_keys(self) -> List[str]:
        """
        Return list of required config keys for this modem.

        Example: ['modem_url', 'modem_username', 'modem_password', 'modem_verify_ssl']

        Returns:
            List[str]: Config keys required by this modem
        """
        pass

    @abstractmethod
    def authenticate(self, config: Dict[str, Any], session: requests.Session) -> bool:
        """
        Authenticate with the modem and store any credentials/tokens internally.

        This method should handle all authentication logic and store the result
        as instance variables for use in fetch_data().

        Args:
            config: Configuration dictionary
            session: requests.Session object for HTTP requests

        Returns:
            bool: True if authentication successful, False otherwise
        """
        pass

    @abstractmethod
    def fetch_data(self, config: Dict[str, Any], session: requests.Session) -> RawData:
        """
        Fetch raw data from the modem (HTML or JSON).

        This method uses any credentials/tokens stored during authenticate()
        to fetch the actual status data from the modem.

        Args:
            config: Configuration dictionary
            session: requests.Session object for HTTP requests

        Returns:
            RawData: Raw data from modem (HTML string or JSON dict)
        """
        pass

    @abstractmethod
    def parse_data(self, raw_data: RawData) -> Dict[str, List[Dict[str, Any]]]:
        """
        Parse raw modem data into standardized stats dictionary.

        Returns a dict with 'downstream' and 'upstream' keys, each containing
        a list of channel dicts with stats.

        Args:
            raw_data: Raw data from modem (HTML string or JSON dict)

        Returns:
            Dict with structure:
            {
                'downstream': [
                    {
                        'channel_id': str,
                        'frequency': str or int,
                        'power': str or float,
                        'snr': str or float,
                        'corrected': str or int,
                        'uncorrectables': str or int,
                        ... (optional model-specific fields)
                    },
                    ...
                ],
                'upstream': [
                    {
                        'channel_id': str,
                        'frequency': str or int,
                        'power': str or float,
                        ... (optional model-specific fields)
                    },
                    ...
                ]
            }
        """
        pass
