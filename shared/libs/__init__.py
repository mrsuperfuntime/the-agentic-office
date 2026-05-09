"""
Shared Libraries for Agentic Office
"""

from .llm_provider import LLMClient, LLMConfig, get_llm_client
from .prompts import OfficePromptsFactory, generate_office_decision

__all__ = [
    "LLMClient",
    "LLMConfig",
    "get_llm_client",
    "OfficePromptsFactory",
    "generate_office_decision"
]
