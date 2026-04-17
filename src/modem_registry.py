"""
Registry and factory for modem implementations.

This module provides a central registry of supported modems and a factory
function to instantiate the correct modem class based on the model name from config.
"""

from typing import Dict, Type
from src.modem_interface import ModemInterface


# Will be populated as modem classes are defined
_MODEM_REGISTRY: Dict[str, Type[ModemInterface]] = {}


def register_modem(model_name: str, modem_class: Type[ModemInterface]) -> None:
    """
    Register a modem class in the registry.

    Args:
        model_name: Model name key (e.g., 'sb6183', 'sb8200', 't25', 's33')
        modem_class: Class that implements ModemInterface
    """
    _MODEM_REGISTRY[model_name] = modem_class


def get_modem_instance(model_name: str) -> ModemInterface:
    """
    Get an instance of the modem class for the given model name.

    Args:
        model_name: Model name key (e.g., 'sb6183', 'sb8200', 't25', 's33')

    Returns:
        ModemInterface: Instance of the modem class

    Raises:
        RuntimeError: If modem model is not registered/supported
    """
    if model_name not in _MODEM_REGISTRY:
        supported = ', '.join(sorted(_MODEM_REGISTRY.keys()))
        raise RuntimeError(
            f"Modem model '{model_name}' is not supported. "
            f"Supported models: {supported}"
        )

    modem_class = _MODEM_REGISTRY[model_name]
    return modem_class()


def get_supported_models() -> list:
    """
    Get list of all supported modem model names.

    Returns:
        list: Sorted list of supported model names
    """
    return sorted(_MODEM_REGISTRY.keys())
