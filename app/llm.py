import math
from typing import Dict, List, Optional, Union
import json
import asyncio
import re

import tiktoken
from openai import (
    APIError,
    AsyncAzureOpenAI,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat import ChatCompletion
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.bedrock import BedrockClient
from app.config import LLMSettings, config
from app.exceptions import TokenLimitExceeded
from app.logger import logger  # Assuming a logger is set up in your app
from app.schema import (
    ROLE_VALUES,
    TOOL_CHOICE_TYPE,
    TOOL_CHOICE_VALUES,
    Message,
    ToolChoice,
)
from app.huggingface_client import HuggingFaceClient


REASONING_MODELS = ["o1", "o3-mini"]
MULTIMODAL_MODELS = [
    "gpt-4-vision-preview",
    "gpt-4o",
    "gpt-4o-mini",
    "claude-3-opus-20240229",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
]

# Add HuggingFace models
HUGGINGFACE_MODELS = [
    "Qwen/Qwen2.5-72B-Instruct",
    "Salesforce/blip2-flan-t5-xl"
]


class TokenCounter:
    # Token constants
    BASE_MESSAGE_TOKENS = 4
    FORMAT_TOKENS = 2
    LOW_DETAIL_IMAGE_TOKENS = 85
    HIGH_DETAIL_TILE_TOKENS = 170

    # Image processing constants
    MAX_SIZE = 2048
    HIGH_DETAIL_TARGET_SHORT_SIDE = 768
    TILE_SIZE = 512

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def count_text(self, text: str) -> int:
        """Calculate tokens for a text string"""
        return 0 if not text else len(self.tokenizer.encode(text))

    def count_image(self, image_item: dict) -> int:
        """
        Calculate tokens for an image based on detail level and dimensions

        For "low" detail: fixed 85 tokens
        For "high" detail:
        1. Scale to fit in 2048x2048 square
        2. Scale shortest side to 768px
        3. Count 512px tiles (170 tokens each)
        4. Add 85 tokens
        """
        detail = image_item.get("detail", "medium")

        # For low detail, always return fixed token count
        if detail == "low":
            return self.LOW_DETAIL_IMAGE_TOKENS

        # For medium detail (default in OpenAI), use high detail calculation
        # OpenAI doesn't specify a separate calculation for medium

        # For high detail, calculate based on dimensions if available
        if detail == "high" or detail == "medium":
            # If dimensions are provided in the image_item
            if "dimensions" in image_item:
                width, height = image_item["dimensions"]
                return self._calculate_high_detail_tokens(width, height)

        # Default values when dimensions aren't available or detail level is unknown
        if detail == "high":
            # Default to a 1024x1024 image calculation for high detail
            return self._calculate_high_detail_tokens(1024, 1024)  # 765 tokens
        elif detail == "medium":
            # Default to a medium-sized image for medium detail
            return 1024  # This matches the original default
        else:
            # For unknown detail levels, use medium as default
            return 1024

    def _calculate_high_detail_tokens(self, width: int, height: int) -> int:
        """Calculate tokens for high detail images based on dimensions"""
        # Step 1: Scale to fit in MAX_SIZE x MAX_SIZE square
        if width > self.MAX_SIZE or height > self.MAX_SIZE:
            scale = self.MAX_SIZE / max(width, height)
            width = int(width * scale)
            height = int(height * scale)

        # Step 2: Scale so shortest side is HIGH_DETAIL_TARGET_SHORT_SIDE
        scale = self.HIGH_DETAIL_TARGET_SHORT_SIDE / min(width, height)
        scaled_width = int(width * scale)
        scaled_height = int(height * scale)

        # Step 3: Count number of 512px tiles
        tiles_x = math.ceil(scaled_width / self.TILE_SIZE)
        tiles_y = math.ceil(scaled_height / self.TILE_SIZE)
        total_tiles = tiles_x * tiles_y

        # Step 4: Calculate final token count
        return (
            total_tiles * self.HIGH_DETAIL_TILE_TOKENS
        ) + self.LOW_DETAIL_IMAGE_TOKENS

    def count_content(self, content: Union[str, List[Union[str, dict]]]) -> int:
        """Calculate tokens for message content"""
        if not content:
            return 0

        if isinstance(content, str):
            return self.count_text(content)

        token_count = 0
        for item in content:
            if isinstance(item, str):
                token_count += self.count_text(item)
            elif isinstance(item, dict):
                if "text" in item:
                    token_count += self.count_text(item["text"])
                elif "image_url" in item:
                    token_count += self.count_image(item)
        return token_count

    def count_tool_calls(self, tool_calls: List[dict]) -> int:
        """Calculate tokens for tool calls"""
        token_count = 0
        for tool_call in tool_calls:
            if "function" in tool_call:
                function = tool_call["function"]
                token_count += self.count_text(function.get("name", ""))
                token_count += self.count_text(function.get("arguments", ""))
        return token_count

    def count_message_tokens(self, messages: List[dict]) -> int:
        """Calculate the total number of tokens in a message list"""
        total_tokens = self.FORMAT_TOKENS  # Base format tokens

        for message in messages:
            tokens = self.BASE_MESSAGE_TOKENS  # Base tokens per message

            # Add role tokens
            tokens += self.count_text(message.get("role", ""))

            # Add content tokens
            if "content" in message:
                tokens += self.count_content(message["content"])

            # Add tool calls tokens
            if "tool_calls" in message:
                tokens += self.count_tool_calls(message["tool_calls"])

            # Add name and tool_call_id tokens
            tokens += self.count_text(message.get("name", ""))
            tokens += self.count_text(message.get("tool_call_id", ""))

            total_tokens += tokens

        return total_tokens


class LLM:
    _instances: Dict[str, "LLM"] = {}

    def __new__(
        cls,
        config_name: str = "default",
        llm_config: Optional[LLMSettings] = None,
        model_name: Optional[str] = None,
        **kwargs
    ):
        instance_key = f"{config_name}_{model_name}" if model_name else config_name

        if instance_key not in cls._instances:
            instance = super().__new__(cls)
            # Do NOT call __init__ here; Python will call it automatically after __new__ returns
            cls._instances[instance_key] = instance
        return cls._instances[instance_key]

    def __init__(
        self,
        config_name: str = "default",
        llm_config: Optional[LLMSettings] = None,
        model_name: Optional[str] = None,
        **kwargs
    ):
        logger.info(f"LLM __init__ entered for model: {model_name or config_name}")
        if hasattr(self, "_initialized") and self._initialized:
            logger.info(f"LLM instance for {model_name or config_name} already initialized, returning.")
            return

        logger.info(f"Initializing LLM for model: {model_name or config_name}")

        base_llm_config = llm_config or config.llm

        if config_name in base_llm_config:
            final_llm_config = base_llm_config[config_name]
        else:
            final_llm_config = base_llm_config.get("default", LLMSettings())
            logger.warning(f"LLM config '{config_name}' not found, using default.")

        self.model = model_name or final_llm_config.model
        self.max_tokens = final_llm_config.max_tokens
        self.temperature = final_llm_config.temperature
        self.api_type = final_llm_config.api_type
        self.api_key = final_llm_config.api_key
        self.api_version = final_llm_config.api_version
        self.base_url = final_llm_config.base_url

        self.total_input_tokens = 0
        self.total_completion_tokens = 0
        self.max_input_tokens = getattr(final_llm_config, 'max_input_tokens', None)

        try:
            self.tokenizer = tiktoken.encoding_for_model(self.model)
        except KeyError:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")

        self.token_counter = TokenCounter(self.tokenizer)

        # Initialize the appropriate client based on model type
        logger.info(f"Initializing client for model: {self.model} with API type: {self.api_type}")
        if self.model in HUGGINGFACE_MODELS:
            self.client = HuggingFaceClient(self.model)
            logger.info(f"HuggingFaceClient initialized for {self.model}")
        elif self.api_type == "azure":
            self.client = AsyncAzureOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                api_version=self.api_version,
            )
        elif self.api_type == "aws":
            self.client = BedrockClient(
                aws_region=config.get_aws_region(),
                model_name=self.model,
                temperature=self.temperature,
            )
        elif self.api_type == "ollama":
            self.client = AsyncOpenAI(base_url=self.base_url, api_key="ollama") # API key is not required for Ollama
        else:
            self.client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
        
        self._initialized = True
        logger.info(f"LLM initialization complete for model: {self.model}")

    def count_tokens(self, text: str) -> int:
        """Calculate the number of tokens in a text"""
        if not text:
            return 0
        return len(self.tokenizer.encode(text))

    def count_message_tokens(self, messages: List[dict]) -> int:
        return self.token_counter.count_message_tokens(messages)

    def update_token_count(self, input_tokens: int, completion_tokens: int = 0) -> None:
        """Update token counts"""
        # Only track tokens if max_input_tokens is set
        self.total_input_tokens += input_tokens
        self.total_completion_tokens += completion_tokens
        logger.info(
            f"Token usage: Input={input_tokens}, Completion={completion_tokens}, "
            f"Cumulative Input={self.total_input_tokens}, Cumulative Completion={self.total_completion_tokens}, "
            f"Total={input_tokens + completion_tokens}, Cumulative Total={self.total_input_tokens + self.total_completion_tokens}"
        )

    def check_token_limit(self, input_tokens: int) -> bool:
        """Check if token limits are exceeded"""
        if self.max_input_tokens is not None:
            return (self.total_input_tokens + input_tokens) <= self.max_input_tokens
        # If max_input_tokens is not set, always return True
        return True

    def get_limit_error_message(self, input_tokens: int) -> str:
        """Generate error message for token limit exceeded"""
        if (
            self.max_input_tokens is not None
            and (self.total_input_tokens + input_tokens) > self.max_input_tokens
        ):
            return f"Request may exceed input token limit (Current: {self.total_input_tokens}, Needed: {input_tokens}, Max: {self.max_input_tokens})"

        return "Token limit exceeded"

    @staticmethod
    def format_messages(
        messages: List[Union[dict, Message]], supports_images: bool = False
    ) -> List[dict]:
        """
        Format messages for LLM by converting them to OpenAI message format.

        Args:
            messages: List of messages that can be either dict or Message objects
            supports_images: Flag indicating if the target model supports image inputs

        Returns:
            List[dict]: List of formatted messages in OpenAI format

        Raises:
            ValueError: If messages are invalid or missing required fields
            TypeError: If unsupported message types are provided

        Examples:
            >>> msgs = [
            ...     Message.system_message("You are a helpful assistant"),
            ...     {"role": "user", "content": "Hello"},
            ...     Message.user_message("How are you?")
            ... ]
            >>> formatted = LLM.format_messages(msgs)
        """
        formatted_messages = []

        for message in messages:
            # Convert Message objects to dictionaries
            if isinstance(message, Message):
                message = message.to_dict()

            if isinstance(message, dict):
                # If message is a dict, ensure it has required fields
                if "role" not in message:
                    raise ValueError("Message dict must contain 'role' field")

                # Process base64 images if present and model supports images
                if supports_images and message.get("base64_image"):
                    # Initialize or convert content to appropriate format
                    if not message.get("content"):
                        message["content"] = []
                    elif isinstance(message["content"], str):
                        message["content"] = [
                            {"type": "text", "text": message["content"]}
                        ]
                    elif isinstance(message["content"], list):
                        # Convert string items to proper text objects
                        message["content"] = [
                            (
                                {"type": "text", "text": item}
                                if isinstance(item, str)
                                else item
                            )
                            for item in message["content"]
                        ]

                    # Add the image to content
                    message["content"].append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{message['base64_image']}"
                            },
                        }
                    )

                    # Remove the base64_image field
                    del message["base64_image"]
                # If model doesn't support images but message has base64_image, handle gracefully
                elif not supports_images and message.get("base64_image"):
                    # Just remove the base64_image field and keep the text content
                    del message["base64_image"]

                if "content" in message or "tool_calls" in message:
                    formatted_messages.append(message)
                # else: do not include the message
            else:
                raise TypeError(f"Unsupported message type: {type(message)}")

        # Validate all messages have required fields
        for msg in formatted_messages:
            if msg["role"] not in ROLE_VALUES:
                raise ValueError(f"Invalid role: {msg['role']}")

        return formatted_messages

    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask(
        self,
        messages: List[Message],
        system_msgs: Optional[List[Message]] = None,
        stream: bool = False,
        temperature: Optional[float] = None,
        stream_callback=None,
    ) -> str:
        try:
            if self.model in HUGGINGFACE_MODELS:
                # Format messages for HuggingFace model
                prompt = self._format_messages_for_huggingface(messages, system_msgs)
                
                # Use the async version of generate_text
                response = await self.client.generate_text_async(
                    prompt=prompt,
                    max_length=self.max_tokens,
                    temperature=temperature or self.temperature
                )
                
                # Update token counts (approximate for HuggingFace models)
                input_tokens = self.count_tokens(prompt)
                output_tokens = self.count_tokens(response)
                self.update_token_count(input_tokens, output_tokens)
                
                return response

            # Rest of the existing ask method for other models
            supports_images = self.model in MULTIMODAL_MODELS

            if system_msgs:
                system_msgs = self.format_messages(system_msgs, supports_images)
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                messages = self.format_messages(messages, supports_images)

            input_tokens = self.count_message_tokens(messages)

            if not self.check_token_limit(input_tokens):
                error_message = self.get_limit_error_message(input_tokens)
                raise TokenLimitExceeded(error_message)

            params = {
                "model": self.model,
                "messages": messages,
            }

            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            if not stream:
                response = await self.client.chat.completions.create(
                    **params, stream=False
                )

                if not response.choices or not response.choices[0].message.content:
                    raise ValueError("Empty or invalid response from LLM")

                self.update_token_count(
                    response.usage.prompt_tokens, response.usage.completion_tokens
                )

                return response.choices[0].message.content

            # Handle streaming response
            self.update_token_count(input_tokens)
            response = await self.client.chat.completions.create(**params)

            collected_messages = []
            completion_text = ""

            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    completion_text += content
                    collected_messages.append(content)

                    if stream_callback:
                        await stream_callback(content)

            return completion_text

        except Exception as e:
            logger.error(f"Error in ask method: {str(e)}")
            raise

    def _format_messages_for_huggingface(self, messages: List[Message], system_msgs: Optional[List[Message]] = None) -> str:
        """Format messages for HuggingFace model input"""
        formatted_prompt = ""
        
        if system_msgs:
            for msg in system_msgs:
                formatted_prompt += f"System: {msg.content}\n"
        
        for msg in messages:
            role = msg.role.capitalize()
            formatted_prompt += f"{role}: {msg.content}\n"
        
        formatted_prompt += "Assistant: "
        return formatted_prompt

    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask_with_images(
        self,
        messages: List[Union[dict, Message]],
        images: List[Union[str, dict]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send a prompt with images to the LLM and get the response.

        Args:
            messages: List of conversation messages
            images: List of image URLs or image data dictionaries
            system_msgs: Optional system messages to prepend
            stream (bool): Whether to stream the response
            temperature (float): Sampling temperature for the response

        Returns:
            str: The generated response

        Raises:
            TokenLimitExceeded: If token limits are exceeded
            ValueError: If messages are invalid or response is empty
            OpenAIError: If API call fails after retries
            Exception: For unexpected errors
        """
        try:
            # For ask_with_images, we always set supports_images to True because
            # this method should only be called with models that support images
            if self.model not in MULTIMODAL_MODELS:
                raise ValueError(
                    f"Model {self.model} does not support images. Use a model from {MULTIMODAL_MODELS}"
                )

            # Format messages with image support
            formatted_messages = self.format_messages(messages, supports_images=True)

            # Ensure the last message is from the user to attach images
            if not formatted_messages or formatted_messages[-1]["role"] != "user":
                raise ValueError(
                    "The last message must be from the user to attach images"
                )

            # Process the last user message to include images
            last_message = formatted_messages[-1]

            # Convert content to multimodal format if needed
            content = last_message["content"]
            multimodal_content = (
                [{"type": "text", "text": content}]
                if isinstance(content, str)
                else content
                if isinstance(content, list)
                else []
            )

            # Add images to content
            for image in images:
                if isinstance(image, str):
                    multimodal_content.append(
                        {"type": "image_url", "image_url": {"url": image}}
                    )
                elif isinstance(image, dict) and "url" in image:
                    multimodal_content.append({"type": "image_url", "image_url": image})
                elif isinstance(image, dict) and "image_url" in image:
                    multimodal_content.append(image)
                else:
                    raise ValueError(f"Unsupported image format: {image}")

            # Update the message with multimodal content
            last_message["content"] = multimodal_content

            # Add system messages if provided
            if system_msgs:
                all_messages = (
                    self.format_messages(system_msgs, supports_images=True)
                    + formatted_messages
                )
            else:
                all_messages = formatted_messages

            # Calculate tokens and check limits
            input_tokens = self.count_message_tokens(all_messages)
            if not self.check_token_limit(input_tokens):
                raise TokenLimitExceeded(self.get_limit_error_message(input_tokens))

            # Set up API parameters
            params = {
                "model": self.model,
                "messages": all_messages,
                "stream": stream,
            }

            # Add model-specific parameters
            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            # Handle non-streaming request
            if not stream:
                response = await self.client.chat.completions.create(**params)

                if not response.choices or not response.choices[0].message.content:
                    raise ValueError("Empty or invalid response from LLM")

                self.update_token_count(response.usage.prompt_tokens)
                return response.choices[0].message.content

            # Handle streaming request
            self.update_token_count(input_tokens)
            response = await self.client.chat.completions.create(**params)

            collected_messages = []
            completion_text = ""
            async for chunk in response:
                chunk_message = chunk.choices[0].delta.content or ""
                collected_messages.append(chunk_message)
                completion_text += chunk_message

                # Use the callback if provided, otherwise print to console
                if stream_callback and callable(stream_callback):
                    await stream_callback(chunk_message)
                else:
                    print(chunk_message, end="", flush=True)

            if not stream_callback:
                print()  # Newline after streaming only if not using callback
            full_response = "".join(collected_messages).strip()

            if not full_response:
                raise ValueError("Empty response from streaming LLM")

            return full_response

        except TokenLimitExceeded:
            raise
        except ValueError as ve:
            logger.error(f"Validation error in ask_with_images: {ve}")
            raise
        except OpenAIError as oe:
            logger.error(f"OpenAI API error: {oe}")
            if isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in ask_with_images: {e}")
            raise

    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask_tool(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        timeout: int = 300,
        tools: Optional[List[dict]] = None,
        tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,  # type: ignore
        temperature: Optional[float] = None,
        **kwargs,
    ) -> ChatCompletionMessage | None:
        """
        Ask LLM using functions/tools and return the response.

        Args:
            messages: List of conversation messages
            system_msgs: Optional system messages to prepend
            timeout: Request timeout in seconds
            tools: List of tools to use
            tool_choice: Tool choice strategy
            temperature: Sampling temperature for the response
            **kwargs: Additional completion arguments

        Returns:
            ChatCompletionMessage: The model's response

        Raises:
            TokenLimitExceeded: If token limits are exceeded
            ValueError: If tools, tool_choice, or messages are invalid
            OpenAIError: If API call fails after retries
            Exception: For unexpected errors
        """
        try:
            if self.model in HUGGINGFACE_MODELS:
                logger.warning("HuggingFace models do not support native tool calls. Simulating tool use via prompt.")

                # Create a more structured prompt for tool calling
                tool_prompt = ""
                if tools and tool_choice != ToolChoice.NONE:
                    # Format tools more clearly
                    formatted_tools = []
                    for tool in tools:
                        if "function" in tool:
                            func = tool["function"]
                            tool_desc = f"- {func['name']}: {func.get('description', 'No description')}"
                            if "parameters" in func:
                                params = func["parameters"].get("properties", {})
                                if params:
                                    param_list = [f"{k}" for k in params.keys()]
                                    tool_desc += f" (params: {', '.join(param_list)})"
                            formatted_tools.append(tool_desc)
                    
                    tool_prompt = f"""Available tools:
{chr(10).join(formatted_tools)}

IMPORTANT: You must respond with a valid JSON tool call in this exact format:
{{"tool_call": {{"name": "tool_name", "arguments": {{"param1": "value1", "param2": "value2"}}}}}}

Only use tools when necessary. If no tool is needed, respond with natural language."""

                # Format messages for HuggingFace
                combined_messages = []
                if system_msgs:
                    combined_messages.extend(system_msgs)
                combined_messages.extend(messages)

                # Create a more structured prompt
                conversation = []
                for msg in combined_messages:
                    if hasattr(msg, 'role') and hasattr(msg, 'content'):
                        conversation.append(f"{msg.role.upper()}: {msg.content}")
                    elif isinstance(msg, dict):
                        conversation.append(f"{msg.get('role', 'USER').upper()}: {msg.get('content', '')}")
                
                full_prompt = f"""{tool_prompt}

{chr(10).join(conversation)}

ASSISTANT:"""

                try:
                    # Generate response with better parameters
                    response_text = await self.client.generate_text_async(
                        prompt=full_prompt,
                        max_length=min(512, self.max_tokens),  # Shorter for faster response
                        temperature=0.1  # Lower temperature for more consistent JSON
                    )

                    # Update token counts
                    input_tokens = self.count_tokens(full_prompt)
                    output_tokens = self.count_tokens(response_text)
                    self.update_token_count(input_tokens, output_tokens)

                    logger.info(f"HuggingFace raw response: {response_text[:200]}...")

                    # Try to parse tool call with much better error handling
                    if tool_choice != ToolChoice.NONE and "{" in response_text:
                        try:
                            # Method 1: Look for exact format
                            tool_call_data = None
                            if '{"tool_call":' in response_text:
                                start_idx = response_text.find('{"tool_call":')
                                # Find the matching closing brace by counting braces
                                brace_count = 0
                                end_idx = start_idx
                                for i, char in enumerate(response_text[start_idx:], start_idx):
                                    if char == '{':
                                        brace_count += 1
                                    elif char == '}':
                                        brace_count -= 1
                                    if brace_count == 0:
                                        end_idx = i + 1
                                        break
                                
                                if end_idx > start_idx:
                                    tool_call_str = response_text[start_idx:end_idx]
                                    logger.info(f"Extracted tool call JSON: {tool_call_str}")
                                    try:
                                        tool_call_data = json.loads(tool_call_str)
                                    except json.JSONDecodeError as je:
                                        logger.warning(f"JSON decode error for extracted string: {je}")
                            
                            # Method 2: Try to extract any JSON object that might be a tool call
                            if not tool_call_data:
                                # Look for JSON objects
                                json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                                json_matches = re.findall(json_pattern, response_text)
                                
                                for match in json_matches:
                                    try:
                                        parsed = json.loads(match)
                                        if isinstance(parsed, dict) and "tool_call" in parsed:
                                            tool_call_data = parsed
                                            logger.info(f"Found tool call via regex: {match}")
                                            break
                                    except json.JSONDecodeError:
                                        continue
                            
                            # Method 3: Try to extract simpler patterns
                            if not tool_call_data:
                                # Look for patterns like: "name": "browser_use", "arguments": {...}
                                name_match = re.search(r'"name":\s*"([^"]+)"', response_text)
                                args_match = re.search(r'"arguments":\s*(\{[^}]*\})', response_text)
                                
                                if name_match and args_match:
                                    try:
                                        tool_name = name_match.group(1)
                                        args_str = args_match.group(1)
                                        args_dict = json.loads(args_str)
                                        tool_call_data = {
                                            "tool_call": {
                                                "name": tool_name,
                                                "arguments": args_dict
                                            }
                                        }
                                        logger.info(f"Reconstructed tool call: {tool_call_data}")
                                    except (json.JSONDecodeError, AttributeError):
                                        pass
                            
                            if tool_call_data and "tool_call" in tool_call_data:
                                tool_info = tool_call_data["tool_call"]
                                logger.info(f"Successfully parsed tool call: {tool_info}")
                                
                                return ChatCompletionMessage(
                                    role="assistant",
                                    content=None,
                                    tool_calls=[
                                        {
                                            "id": f"call_{hash(str(tool_info)) % 10000}",
                                            "type": "function",
                                            "function": {
                                                "name": tool_info["name"],
                                                "arguments": json.dumps(tool_info.get("arguments", {}))
                                            }
                                        }
                                    ]
                                )
                            else:
                                logger.warning("No valid tool call found in response")
                                
                        except Exception as e:
                            logger.warning(f"Tool call parsing error: {e}")

                    # Return as regular content if no tool call was found/needed
                    return ChatCompletionMessage(
                        role="assistant",
                        content=response_text.strip()
                    )

                except Exception as e:
                    logger.error(f"Error in HuggingFace tool call generation: {e}")
                    raise

            # Rest of the method for non-HuggingFace models...
            # Validate tool_choice
            if tool_choice not in TOOL_CHOICE_VALUES:
                raise ValueError(f"Invalid tool_choice: {tool_choice}")

            # Check if the model supports images
            supports_images = self.model in MULTIMODAL_MODELS

            # Format messages
            if system_msgs:
                system_msgs = self.format_messages(system_msgs, supports_images)
                messages = system_msgs + self.format_messages(messages, supports_images)
            else:
                messages = self.format_messages(messages, supports_images)

            # Calculate input token count
            input_tokens = self.count_message_tokens(messages)

            # If there are tools, calculate token count for tool descriptions
            tools_tokens = 0
            if tools:
                for tool in tools:
                    tools_tokens += self.count_tokens(str(tool))

            input_tokens += tools_tokens

            # Check if token limits are exceeded
            if not self.check_token_limit(input_tokens):
                error_message = self.get_limit_error_message(input_tokens)
                # Raise a special exception that won't be retried
                raise TokenLimitExceeded(error_message)

            # Validate tools if provided
            if tools:
                for tool in tools:
                    if not isinstance(tool, dict) or "type" not in tool:
                        raise ValueError("Each tool must be a dict with 'type' field")

            # Set up the completion request
            params = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "timeout": timeout,
                **kwargs,
            }

            if self.model in REASONING_MODELS:
                params["max_completion_tokens"] = self.max_tokens
            else:
                params["max_tokens"] = self.max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature
                )

            response = await self.client.chat.completions.create(
                **params, stream=False
            )

            # Check if response is valid
            if not response.choices or not response.choices[0].message:
                print(response)
                return None

            # Update token counts
            self.update_token_count(
                response.usage.prompt_tokens, response.usage.completion_tokens
            )

            return response.choices[0].message

        except TokenLimitExceeded:
            raise
        except ValueError as ve:
            logger.error(f"Validation error in ask_tool: {ve}")
            raise
        except OpenAIError as oe:
            logger.error(f"OpenAI API error: {oe}")
            if isinstance(oe, AuthenticationError):
                logger.error("Authentication failed. Check API key.")
            elif isinstance(oe, RateLimitError):
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")
            elif isinstance(oe, APIError):
                logger.error(f"API error: {oe}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in ask_tool: {e}")
            raise