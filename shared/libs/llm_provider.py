"""
LLM Provider Abstraction Layer
Supports multiple providers with fallback logic
"""
import os
import logging
from typing import Optional, Dict, List
from enum import Enum

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM providers"""
    GROQ = "groq"
    OLLAMA = "ollama"


class LLMConfig:
    """LLM Configuration"""
    
    def __init__(self):
        # Provider settings
        self.primary_provider = os.getenv("LLM_PRIMARY_PROVIDER", "ollama").lower()
        self.fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "groq").lower()
        self.enable_fallback = os.getenv("LLM_ENABLE_FALLBACK", "true").lower() == "true"
        self.strict_local = os.getenv("LLM_STRICT_LOCAL", "false").lower() == "true"
        
        # Ollama settings
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
        
        # Groq settings
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_model = os.getenv("GROQ_MODEL", "mixtral-8x7b-32768")
        
        # Generation settings
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "500"))
        self.timeout = int(os.getenv("LLM_TIMEOUT", "30"))


class OllamaProvider:
    """Ollama LLM Provider"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        try:
            import requests
            self.requests = requests
        except ImportError:
            raise ImportError("requests library required for Ollama provider")
    
    def generate(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        """Generate response using Ollama"""
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            
            response = self.requests.post(
                f"{self.config.ollama_url}/api/chat",
                json={
                    "model": self.config.ollama_model,
                    "messages": messages,
                    "temperature": self.config.temperature,
                    "stream": False
                },
                timeout=self.config.timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("message", {}).get("content", "")
            else:
                logger.error(f"Ollama error: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Ollama provider error: {e}")
            return None

    def validate_ready(self) -> None:
        """Fail-fast check that Ollama is reachable and model is available."""
        try:
            response = self.requests.get(
                f"{self.config.ollama_url}/api/tags",
                timeout=self.config.timeout,
            )
        except Exception as e:
            raise RuntimeError(
                f"LLM strict local mode: cannot reach Ollama at {self.config.ollama_url}: {e}"
            ) from e

        if response.status_code != 200:
            raise RuntimeError(
                f"LLM strict local mode: Ollama health check failed with status {response.status_code}"
            )

        payload = response.json() if response.content else {}
        available_models = [model.get("name", "") for model in payload.get("models", [])]
        requested = self.config.ollama_model
        requested_prefix = f"{requested}:"
        if not any(name == requested or name.startswith(requested_prefix) for name in available_models):
            raise RuntimeError(
                "LLM strict local mode: configured model "
                f"'{requested}' is not available in Ollama. "
                f"Run: ollama pull {requested}"
            )


class GroqProvider:
    """Groq LLM Provider"""
    
    def __init__(self, config: LLMConfig):
        self.config = config
        if not config.groq_api_key:
            logger.warning("GROQ_API_KEY not set - Groq provider will not work")
        try:
            from groq import Groq
            self.client = Groq(api_key=config.groq_api_key)
        except ImportError:
            raise ImportError("groq library required for Groq provider")
    
    def generate(self, prompt: str, system: Optional[str] = None) -> Optional[str]:
        """Generate response using Groq"""
        try:
            if not self.config.groq_api_key:
                logger.error("Groq API key not configured")
                return None
            
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            
            response = self.client.chat.completions.create(
                model=self.config.groq_model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                timeout=self.config.timeout
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Groq provider error: {e}")
            return None


class LLMClient:
    """Universal LLM Client with Fallback Support"""
    
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self.providers: Dict[str, object] = {}
        self._initialize_providers()
    
    def _initialize_providers(self):
        """Initialize configured providers"""
        if self.config.strict_local:
            if self.config.primary_provider != "ollama":
                raise RuntimeError("LLM strict local mode requires LLM_PRIMARY_PROVIDER=ollama")
            if self.config.enable_fallback:
                raise RuntimeError("LLM strict local mode requires LLM_ENABLE_FALLBACK=false")

        try:
            if self.config.primary_provider == "ollama":
                ollama_provider = OllamaProvider(self.config)
                if self.config.strict_local:
                    ollama_provider.validate_ready()
                self.providers["ollama"] = ollama_provider
                logger.info("Ollama provider initialized")
        except Exception as e:
            if self.config.strict_local:
                raise RuntimeError(f"Failed to initialize Ollama in strict local mode: {e}") from e
            logger.warning(f"Failed to initialize Ollama: {e}")
        
        try:
            if self.config.fallback_provider == "groq" or self.config.primary_provider == "groq":
                self.providers["groq"] = GroqProvider(self.config)
                logger.info("Groq provider initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Groq: {e}")
    
    def generate(self, prompt: str, system: Optional[str] = None) -> str:
        """
        Generate response with fallback logic
        
        Args:
            prompt: User prompt
            system: System message for context
            
        Returns:
            Generated response or empty string if all providers fail
        """
        # Try primary provider first
        primary = self.config.primary_provider
        if primary in self.providers:
            provider = self.providers[primary]
            result = provider.generate(prompt, system)
            if result:
                logger.debug(f"Generated response using {primary}")
                return result
            else:
                logger.warning(f"{primary} provider failed")
        
        # Try fallback provider
        if self.config.enable_fallback:
            fallback = self.config.fallback_provider
            if fallback in self.providers and fallback != primary:
                provider = self.providers[fallback]
                result = provider.generate(prompt, system)
                if result:
                    logger.info(f"Generated response using fallback {fallback}")
                    return result
                else:
                    logger.warning(f"{fallback} fallback provider failed")

        if self.config.strict_local:
            raise RuntimeError(
                "LLM strict local mode: Ollama generation failed and fallback is disabled. "
                "Check Ollama service health and model availability."
            )
        
        logger.error("All LLM providers failed")
        return ""
    
    def get_status(self) -> Dict[str, str]:
        """Get status of available providers"""
        status = {
            "primary": self.config.primary_provider,
            "fallback": self.config.fallback_provider,
            "strict_local": self.config.strict_local,
            "available_providers": list(self.providers.keys())
        }
        return status


# Global client instance
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create global LLM client"""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
