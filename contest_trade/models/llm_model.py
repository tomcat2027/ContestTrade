"""
Multi-Provider LLM Model Implementation

This module provides an implementation of the BaseAgentModel that supports
multiple LLM providers: OpenAI, Gemini, and Ollama.
It follows an async-first approach, where the primary implementation is the
asynchronous streaming method (a_stream_run).
"""
import os
import sys
import httpx
import asyncio
import time
import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, AsyncIterator, Callable, Any
from enum import Enum
from loguru import logger
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
from config.config import cfg

from models.base_agent_model import (
    BaseAgentModel,
    AsyncResponseStream,
    StreamingChunk,
    ModelResponse
)


class ProviderType(Enum):
    """Enumeration of supported LLM providers."""
    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"

class LLMModelConfig:
    def __init__(self, provider: str, model_name: str, api_key: str = None, base_url: str = None,
                 max_retries: int = 3, retry_delay: float = 20.0, timeout: float = 60.0, 
                 extra_headers: dict = None, proxys: dict = None, **kwargs):
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.extra_headers = extra_headers
        self.proxys = proxys
        # Store additional provider-specific configuration
        self.extra_config = kwargs


class BaseProvider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self, config: LLMModelConfig):
        self.config = config
        self.model_name = config.model_name
        self.api_key = config.api_key
        self.base_url = config.base_url
        self.extra_headers = config.extra_headers
        self.proxys = config.proxys
    
    @abstractmethod
    async def create_stream(self, messages: List[Dict[str, str]], temperature: float, 
                           max_tokens: Optional[int], **kwargs) -> Any:
        """Create a streaming response from the provider."""
        pass
    
    @abstractmethod
    def process_chunk(self, chunk: Any) -> StreamingChunk[str]:
        """Process a streaming chunk from the provider."""
        pass
    
    def preprocess_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Preprocess messages for the provider. Can be overridden by subclasses."""
        return messages


class OpenAIProvider(BaseProvider):
    """OpenAI provider implementation."""
    
    def __init__(self, config: LLMModelConfig):
        super().__init__(config)
        
        # Import OpenAI modules
        try:
            import openai
            from openai import OpenAI, AsyncOpenAI
            from openai.types.chat import ChatCompletionChunk
            self._openai = openai
            self._ChatCompletionChunk = ChatCompletionChunk
        except ImportError:
            raise ImportError("openai package is required for OpenAI provider. Install with: pip install openai")
        
        # Set default values from environment if not provided
        if self.api_key is None:
            self.api_key = os.environ.get("OPENAI_API_KEY")
        if self.base_url is None:
            self.base_url = os.environ.get("OPENAI_BASE_URL")
        
        # Initialize clients (lazy initialization if no API key)
        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=httpx.Client(proxy=self.proxys) if self.proxys else None
            )
            
            self.async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=httpx.AsyncClient(proxy=self.proxys) if self.proxys else None
            )
            
            if self.extra_headers is not None:
                self.client = self.client.with_options(default_headers=self.extra_headers)
                self.async_client = self.async_client.with_options(default_headers=self.extra_headers)
        else:
            # Defer client initialization until first use
            self.client = None
            self.async_client = None
    
    def _ensure_clients(self):
        """Ensure OpenAI clients are initialized."""
        if self.async_client is None:
            if not self.api_key:
                raise ValueError("OpenAI API key is required but not provided. Set it in config or OPENAI_API_KEY environment variable.")
            
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=httpx.Client(proxy=self.proxys) if self.proxys else None
            )
            
            self.async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                http_client=httpx.AsyncClient(proxy=self.proxys) if self.proxys else None
            )
            
            if self.extra_headers is not None:
                self.client = self.client.with_options(default_headers=self.extra_headers)
                self.async_client = self.async_client.with_options(default_headers=self.extra_headers)
    
    async def create_stream(self, messages: List[Dict[str, str]], temperature: float, 
                           max_tokens: Optional[int], **kwargs) -> Any:
        self._ensure_clients()  # Ensure clients are initialized
        processed_messages = self.preprocess_messages(messages)
        
        params = {
            "model": self.model_name,
            "messages": processed_messages,
            "temperature": temperature,
            "stream": True,
            **kwargs
        }
        
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        
        # Handle thinking mode for compatible models
        if 'thinking' in params:
            thinking_flag = params.pop('thinking')
            if thinking_flag:
                params['extra_body'] = {"thinking": {"type": "enabled"}}
            else:
                params['extra_body'] = {"thinking": {"type": "disabled"}}
        
        return await self.async_client.chat.completions.create(**params)
    
    def process_chunk(self, chunk) -> StreamingChunk[str]:
        """Process a streaming chunk from OpenAI."""
        if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content:
            content = chunk.choices[0].delta.reasoning_content
            is_reasoning = True
        else:
            content = chunk.choices[0].delta.content or ""
            is_reasoning = False
        
        is_finished = len(chunk.choices) > 0 and chunk.choices[0].finish_reason is not None
        
        return StreamingChunk(
            content=content,
            is_finished=is_finished,
            raw_chunk=chunk,
            is_reasoning=is_reasoning
        )


class GeminiProvider(BaseProvider):
    """Google Gemini provider implementation."""
    
    def __init__(self, config: LLMModelConfig):
        super().__init__(config)
        
        try:
            import google.generativeai as genai
            self.genai = genai
        except ImportError:
            raise ImportError("google-generativeai package is required for Gemini provider. Install with: pip install google-generativeai")
        
        # Set API key
        if self.api_key is None:
            self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
        
        # Configure model
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 64,
            "max_output_tokens": 8192,
        }
        
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            generation_config=generation_config
        )
    
    def preprocess_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Convert OpenAI format messages to Gemini format."""
        gemini_messages = []
        
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            
            # Map OpenAI roles to Gemini roles
            if role == "system":
                # Gemini doesn't have system role, prepend to first user message
                if gemini_messages and gemini_messages[-1].get("role") == "user":
                    gemini_messages[-1]["parts"] = [f"{content}\n\n{gemini_messages[-1]['parts'][0]}"]
                else:
                    gemini_messages.append({"role": "user", "parts": [content]})
            elif role == "user":
                gemini_messages.append({"role": "user", "parts": [content]})
            elif role == "assistant":
                gemini_messages.append({"role": "model", "parts": [content]})
        
        return gemini_messages
    
    async def create_stream(self, messages: List[Dict[str, str]], temperature: float, 
                           max_tokens: Optional[int], **kwargs) -> Any:
        processed_messages = self.preprocess_messages(messages)
        
        # Update generation config
        generation_config = self.model._generation_config.copy()
        generation_config["temperature"] = temperature
        if max_tokens:
            generation_config["max_output_tokens"] = max_tokens
        
        # Create chat session
        chat = self.model.start_chat(history=processed_messages[:-1] if len(processed_messages) > 1 else [])
        
        # Get the last message content
        last_message = processed_messages[-1]["parts"][0] if processed_messages else ""
        
        # Generate streaming response
        response = await chat.send_message_async(last_message, stream=True)
        return response
    
    def process_chunk(self, chunk) -> StreamingChunk[str]:
        """Process a streaming chunk from Gemini."""
        content = ""
        is_finished = False
        
        if hasattr(chunk, 'text'):
            content = chunk.text
        
        # Gemini doesn't provide explicit finish signals in chunks
        # We'll rely on the async iterator to determine when finished
        
        return StreamingChunk(
            content=content,
            is_finished=is_finished,
            raw_chunk=chunk,
            is_reasoning=False
        )


class OllamaProvider(BaseProvider):
    """Ollama provider implementation."""
    
    def __init__(self, config: LLMModelConfig):
        super().__init__(config)
        
        # Set default base URL for Ollama
        if self.base_url is None:
            self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        
        # Ollama doesn't typically require API keys, but support it if provided
        if self.api_key is None:
            self.api_key = os.environ.get("OLLAMA_API_KEY")
    
    async def create_stream(self, messages: List[Dict[str, str]], temperature: float, 
                           max_tokens: Optional[int], **kwargs) -> Any:
        processed_messages = self.preprocess_messages(messages)
        
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.extra_headers:
            headers.update(self.extra_headers)
        
        payload = {
            "model": self.model_name,
            "messages": processed_messages,
            "stream": True,
            "options": {
                "temperature": temperature,
            }
        }
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        # Add any extra options from config
        if self.config.extra_config:
            payload["options"].update(self.config.extra_config)
        
        # Make HTTP request to Ollama API
        async with httpx.AsyncClient(proxy=self.proxys) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                headers=headers,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            return response.aiter_lines()
    
    def process_chunk(self, chunk_line: str) -> StreamingChunk[str]:
        """Process a streaming chunk from Ollama."""
        import json
        
        try:
            chunk_data = json.loads(chunk_line)
            content = chunk_data.get("message", {}).get("content", "")
            is_finished = chunk_data.get("done", False)
            
            return StreamingChunk(
                content=content,
                is_finished=is_finished,
                raw_chunk=chunk_data,
                is_reasoning=False
            )
        except json.JSONDecodeError:
            # Skip malformed JSON lines
            return StreamingChunk(
                content="",
                is_finished=False,
                raw_chunk=chunk_line,
                is_reasoning=False
            )


def create_provider(config: LLMModelConfig) -> BaseProvider:
    """Factory function to create the appropriate provider based on config."""
    provider_type = config.provider.lower()
    
    if provider_type == ProviderType.OPENAI.value:
        return OpenAIProvider(config)
    elif provider_type == ProviderType.GEMINI.value:
        return GeminiProvider(config)
    elif provider_type == ProviderType.OLLAMA.value:
        return OllamaProvider(config)
    else:
        raise ValueError(f"Unsupported provider: {provider_type}. Supported providers: {[p.value for p in ProviderType]}")


class LLMModel(BaseAgentModel):
    """
    Multi-provider LLM model implementation.
    
    This class provides a concrete implementation of the BaseAgentModel that supports
    multiple LLM providers (OpenAI, Gemini, Ollama).
    Following the async-first approach, it delegates to the appropriate provider
    for the actual implementation.
    """
    
    def __init__(
        self,
        config: LLMModelConfig,
        **kwargs
    ):
        """
        Initialize the LLM model with the specified provider.
        
        Args:
            config: LLMModelConfig instance specifying provider and configuration
            **kwargs: Additional configuration parameters
        """
        super().__init__(config.model_name, **kwargs)
        
        self.config = config
        self.model_name = config.model_name
        
        # Create the appropriate provider
        self.provider = create_provider(config)
    
    def preprocess_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Preprocess messages using the provider's preprocessing."""
        return self.provider.preprocess_messages(messages)

    # ---- 重试 / 退避 内部 helper（a_run 与 a_stream_run 共用）----
    @staticmethod
    def _is_rate_limit_error(e: Exception) -> bool:
        """识别 429 限流：openai 官方库的 RateLimitError 或 status_code==429。"""
        if getattr(e, 'status_code', None) == 429:
            return True
        try:
            import openai
            if isinstance(e, openai.RateLimitError):
                return True
        except (ImportError, AttributeError):
            pass
        return False

    @staticmethod
    def _compute_backoff(attempt: int, retry_delay: float, is_rate_limit: bool) -> float:
        """指数退避 + 随机抖动。429 时退避加倍，上限 240 秒。"""
        base = retry_delay if retry_delay else 20.0
        backoff = min(base * (2 ** attempt), 120)
        if is_rate_limit:
            backoff = min(backoff * 2, 240)
        backoff += random.uniform(0, 5)
        return backoff

    async def _sleep_with_backoff(self, attempt: int, max_retries: int, retry_delay: float, e: Exception):
        """计算退避并 sleep，同时打印日志。"""
        is_rate_limit = self._is_rate_limit_error(e)
        backoff = self._compute_backoff(attempt, retry_delay, is_rate_limit)
        tag = " (429限流,退避加倍)" if is_rate_limit else ""
        print(f"🔄 LLM API调用失败 (尝试 {attempt + 1}/{max_retries + 1}): {type(e).__name__}: {e}{tag}")
        print(f"⏳ 等待 {backoff:.1f} 秒后重试...")
        await asyncio.sleep(backoff)

    async def a_run(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        verbose: bool = False,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
        timeout: Optional[float] = None,
        post_process_func: Optional[Callable[[str], str]] = None,
        **kwargs
    ) -> ModelResponse[str]:
        """
        Run the model asynchronously and return a complete response.

        This is a wrapper around a_stream_run() that collects all chunks
        and combines them into a single response. Subclasses should
        implement a_stream_run() as the primary method and this method
        will be handled automatically.

        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional model-specific parameters

        Returns:
            A ModelResponse containing the generated content
        """
        call_start = time.time()
        model_name = self.model_name

        if max_retries is None:
            max_retries = getattr(self, 'config', LLMModelConfig("", "", "")).max_retries
        if retry_delay is None:
            retry_delay = getattr(self, 'config', LLMModelConfig("", "", "")).retry_delay
        if timeout is None:
            timeout = 60

        for attempt in range(max_retries + 1):
            try:
                # Get the stream
                stream = await self.a_stream_run(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    **kwargs
                )

                # Collect all chunks
                reasoning_content = ""
                full_content = ""
                raw_chunks = []

                # 流式接收总超时保护：避免连接建立后 chunk 不来导致永久挂起
                # 总超时 = 单次 timeout × 3，给长摘要/推理留足时间
                stream_total_timeout = max(timeout * 3, 180) if timeout else 180

                async def _collect_stream():
                    async for chunk in stream:
                        if chunk.is_reasoning:
                            reasoning_content_local[0] += chunk.content
                        else:
                            full_content_local[0] += chunk.content
                        if chunk.raw_chunk is not None:
                            raw_chunks_local[0].append(chunk.raw_chunk)
                            if verbose:
                                print(chunk.content, end="", flush=True)

                # 用可变容器让内部协程能写回（绕过闭包只读限制）
                reasoning_content_local = [""]
                full_content_local = [""]
                raw_chunks_local = [[]]
                try:
                    await asyncio.wait_for(_collect_stream(), timeout=stream_total_timeout)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"流式接收超时({stream_total_timeout}秒)，可能连接挂起")
                reasoning_content = reasoning_content_local[0]
                full_content = full_content_local[0]
                raw_chunks = raw_chunks_local[0]

                if post_process_func is not None:
                    proc_response = post_process_func(full_content)
                else:
                    proc_response = None

                call_elapsed = time.time() - call_start
                logger.info(f"[耗时] LLM调用完成 ({model_name}): {call_elapsed:.2f}秒, 输出tokens约{len(full_content)//4}")

                # 空响应保护：内容过短（含思考内容）视为异常，触发重试
                # 避免限流/异常返回的空内容被当成成功结果（如 DeepSeek 限流后返回 ~50 字符废内容）
                effective_content = full_content if not reasoning_content else (full_content + reasoning_content)
                if len(effective_content.strip()) < 20 and attempt < max_retries:
                    raise ValueError(f"空响应或内容过短({len(effective_content.strip())}字符)，疑似限流/异常返回")

                # Create a response with the collected content
                return ModelResponse(
                    content=self.postprocess_response(full_content),
                    reasoning_content=reasoning_content,
                    model_name=self.model_name,
                    raw_response=raw_chunks if raw_chunks else None,
                    proc_response=proc_response
                )
            except Exception as e:
                if attempt < max_retries:
                    await self._sleep_with_backoff(attempt, max_retries, retry_delay, e)
                    continue
                else:
                    call_elapsed = time.time() - call_start
                    logger.error(f"[耗时] LLM调用最终失败 ({model_name}): {call_elapsed:.2f}秒")
                    print(f"❌ LLM API调用最终失败，已重试 {max_retries} 次: {type(e).__name__}: {e}")
                    raise


    async def a_stream_run(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
        timeout: Optional[float] = None,
        **kwargs
    ) -> AsyncResponseStream[str]:
        """
        Run the model asynchronously and stream the response with retry mechanism.
        
        This is the primary implementation that all other methods
        (run, a_run, stream_run) will use as their base.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Delay between retries in seconds (default: 20.0)
            timeout: Timeout for each attempt in seconds (default: 60.0)
            **kwargs: Additional model-specific parameters
            
        Returns:
            An AsyncResponseStream that yields chunks of the generated content
        """
        
        # 使用配置中的默认值（如果未指定）
        if max_retries is None:
            max_retries = getattr(self, 'config', LLMModelConfig("", "", "")).max_retries
        if retry_delay is None:
            retry_delay = getattr(self, 'config', LLMModelConfig("", "", "")).retry_delay
        if timeout is None:
            timeout = getattr(self, 'config', LLMModelConfig("", "", "")).timeout
        
        for attempt in range(max_retries + 1):
            try:
                return await asyncio.wait_for(
                    self._internal_a_stream_run(messages, temperature, max_tokens, **kwargs),
                    timeout=timeout
                )
            except (
                asyncio.TimeoutError,
                ConnectionError,
                TimeoutError
            ) as e:
                # Handle provider-specific exceptions
                should_retry = False
                if self.config.provider == ProviderType.OPENAI.value:
                    try:
                        import openai
                        if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError)):
                            should_retry = True
                    except ImportError:
                        pass

                # Always retry on these common exceptions
                if isinstance(e, (asyncio.TimeoutError, ConnectionError, TimeoutError)):
                    should_retry = True

                if should_retry and attempt < max_retries:
                    await self._sleep_with_backoff(attempt, max_retries, retry_delay, e)
                    continue
                else:
                    print(f"❌ LLM API调用最终失败，已重试 {max_retries} 次: {type(e).__name__}: {e}")
                    raise

    async def _internal_a_stream_run(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncResponseStream[str]:
        """
        Internal implementation of async streaming run without retry logic.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content' keys
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum number of tokens to generate
            **kwargs: Additional model-specific parameters
            
        Returns:
            An AsyncResponseStream that yields chunks of the generated content
        """
        # Get the stream from the provider
        stream = await self.provider.create_stream(messages, temperature, max_tokens, **kwargs)
        
        # Create async iterator that processes chunks using provider's chunk processor
        async def chunk_iterator() -> AsyncIterator[StreamingChunk[str]]:
            if self.config.provider == ProviderType.OLLAMA.value:
                # Handle Ollama's line-by-line streaming
                async for line in stream:
                    if line.strip():
                        chunk = self.provider.process_chunk(line)
                        if chunk.content or chunk.is_finished:
                            yield chunk
            elif self.config.provider == ProviderType.GEMINI.value:
                # Handle Gemini streaming
                async for chunk in stream:
                    processed_chunk = self.provider.process_chunk(chunk)
                    if processed_chunk.content:
                        yield processed_chunk
            else:
                # Handle OpenAI and OpenAI-compatible streaming
                async for chunk in stream:
                    if hasattr(chunk, 'choices') and not chunk.choices:
                        continue
                    yield self.provider.process_chunk(chunk)
        
        return AsyncResponseStream(
            iterator=chunk_iterator(),
            model_name=self.model_name
        )

# Helper function to determine provider from model name or base URL
def detect_provider(model_name: str, base_url: str = None) -> str:
    """Auto-detect provider based on model name or base URL."""
    model_name = model_name.lower()
    
    # Check for Gemini models
    if "gemini" in model_name or "google" in model_name:
        return ProviderType.GEMINI.value
    
    # Check for Ollama (usually local models or specific patterns)
    if base_url and ("localhost" in base_url or "127.0.0.1" in base_url or ":11434" in base_url):
        return ProviderType.OLLAMA.value
    
    # Check for common Ollama model names
    ollama_models = ["llama", "mistral", "codellama", "vicuna", "alpaca", "orca", "phi", "neural-chat"]
    if any(ollama_model in model_name for ollama_model in ollama_models):
        return ProviderType.OLLAMA.value
    
    # Default to OpenAI (includes OpenAI-compatible APIs)
    return ProviderType.OPENAI.value


# Create global configurations with auto-detected providers
llm_provider = cfg.llm.get("provider", detect_provider(cfg.llm["model_name"], cfg.llm.get("base_url")))
GLOBAL_LLM_CONFIG = LLMModelConfig(
    provider=llm_provider,
    model_name=cfg.llm["model_name"],
    api_key=cfg.llm.get("api_key"),
    base_url=cfg.llm.get("base_url")
)
GLOBAL_LLM = LLMModel(GLOBAL_LLM_CONFIG)

try:
    thinking_provider = cfg.llm_thinking.get("provider", detect_provider(cfg.llm_thinking["model_name"], cfg.llm_thinking.get("base_url")))
    GLOBAL_THINKING_LLM_CONFIG = LLMModelConfig(
        provider=thinking_provider,
        model_name=cfg.llm_thinking["model_name"],
        api_key=cfg.llm_thinking.get("api_key"),
        base_url=cfg.llm_thinking.get("base_url")
    )
    assert GLOBAL_THINKING_LLM_CONFIG.api_key is not None
    GLOBAL_THINKING_LLM = LLMModel(GLOBAL_THINKING_LLM_CONFIG)
except Exception as e:
    print(f"加载thinking模型失败，使用llm模型替代: {e}")
    GLOBAL_THINKING_LLM = GLOBAL_LLM

try:
    vlm_provider = cfg.vlm.get("provider", detect_provider(cfg.vlm["model_name"], cfg.vlm.get("base_url")))
    GLOBAL_VLM_CONFIG = LLMModelConfig(
        provider=vlm_provider,
        model_name=cfg.vlm["model_name"],
        api_key=cfg.vlm.get("api_key"),
        base_url=cfg.vlm.get("base_url")
    )
    assert GLOBAL_VLM_CONFIG.api_key is not None
    GLOBAL_VISION_LLM = LLMModel(GLOBAL_VLM_CONFIG)
except Exception as e:
    print(f"加载vlm模型失败，vision能力不可用: {e}")
    GLOBAL_VISION_LLM = None

if __name__ == "__main__":
    pass
