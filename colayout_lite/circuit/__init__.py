"""Local circuit facts and verified schematic/layout correspondence.

Models, decoding and validation are independent of Qt, SSH and the Agent API.
Only Adapter orchestrates acquisition through NativeTransport.
"""
from .models import CircuitContext, LayoutConnectivity

__all__ = ['CircuitContext', 'LayoutConnectivity']
