import os
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timedelta

import yaml


class LLMRouter:
    def __init__(self, config_path="config/models.yaml"):
        with open(config_path) as f:
            self._config = yaml.safe_load(f)["agents"]
        self._cache_dir = Path(os.environ.get("CACHE_DIR", ".cache/llm"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_ttl = int(os.environ.get("CACHE_TTL_HOURS", 24))

    def _cache_key(self, model: str, messages: list) -> str:
        payload = json.dumps({"model": model, "messages": messages}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def _read_cache(self, key: str):
        path = self._cache_dir / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        expires = datetime.fromisoformat(data["expires_at"])
        if datetime.utcnow() > expires:
            path.unlink(missing_ok=True)
            return None
        return data["response"]

    def _write_cache(self, key: str, response: str):
        path = self._cache_dir / f"{key}.json"
        expires = (datetime.utcnow() + timedelta(hours=self._cache_ttl)).isoformat()
        path.write_text(json.dumps({"response": response, "expires_at": expires}))

    def complete(self, agent_name: str, messages: list, system_prompt: str = None) -> str:
        cfg = self._config[agent_name]
        provider = cfg["provider"]
        model = cfg["model"]
        temperature = cfg.get("temperature", 0.3)
        max_tokens = cfg.get("max_tokens", 4096)
        use_cache = cfg.get("use_cache", True)

        cache_key = self._cache_key(model, messages)
        if use_cache:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        response = self._call_with_retry(provider, model, messages, system_prompt, temperature, max_tokens)

        if use_cache:
            self._write_cache(cache_key, response)
        return response

    def _call_with_retry(self, provider, model, messages, system_prompt, temperature, max_tokens) -> str:
        delays = [1, 2, 4]
        last_error = None
        for i, delay in enumerate(delays):
            try:
                return self._call(provider, model, messages, system_prompt, temperature, max_tokens)
            except Exception as e:
                last_error = e
                if i < len(delays) - 1:
                    time.sleep(delay)
        raise last_error

    def _call(self, provider, model, messages, system_prompt, temperature, max_tokens) -> str:
        if provider == "google_gemini":
            return self._call_google(model, messages, system_prompt, temperature, max_tokens)
        elif provider == "featherless":
            return self._call_openai_compat(
                model, messages, system_prompt, temperature, max_tokens,
                base_url="https://api.featherless.ai/v1",
                api_key=os.environ["FEATHERLESS_API_KEY"],
            )
        elif provider == "aiml_api":
            return self._call_openai_compat(
                model, messages, system_prompt, temperature, max_tokens,
                base_url="https://api.aimlapi.com/v1",
                api_key=os.environ["AIML_API_KEY"],
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def _call_google(self, model, messages, system_prompt, temperature, max_tokens) -> str:
        from google import genai
        from google.genai.types import GenerateContentConfig, ThinkingConfig, ThinkingLevel, Tool, GoogleSearch

        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        last_user_message = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        config_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "thinking_config": ThinkingConfig(thinking_level=ThinkingLevel.HIGH),
            "tools": [Tool(google_search=GoogleSearch())],
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt

        response = client.models.generate_content(
            model=model,
            config=GenerateContentConfig(**config_kwargs),
            contents=last_user_message,
        )
        return response.text

    def _call_openai_compat(self, model, messages, system_prompt, temperature, max_tokens, base_url, api_key) -> str:
        import json as _json
        import re
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0)
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        web_search_tool = {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web for current data, financial reports, market statistics, and news.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"}
                    },
                    "required": ["query"],
                },
            },
        }

        # enable_thinking only works on Qwen3/DeepSeek models, not Gemini
        supports_thinking = not model.startswith("google/")
        extra = {"enable_thinking": True} if supports_thinking else {}

        for _ in range(4):
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=[web_search_tool],
                    **({"extra_body": extra} if extra else {}),
                )
            except Exception:
                response = client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            choice = response.choices[0]
            if choice.finish_reason == "tool_calls" and getattr(choice.message, "tool_calls", None):
                tool_msg = {"role": "assistant", "content": choice.message.content or "", "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in choice.message.tool_calls
                ]}
                full_messages.append(tool_msg)
                for tc in choice.message.tool_calls:
                    if tc.function.name == "web_search":
                        try:
                            args = _json.loads(tc.function.arguments)
                            from agents.shared.search_tools import web_search as do_search
                            results = do_search(args.get("query", ""))
                            result_text = "\n".join(
                                f"- {r.get('title','')}: {r.get('content','')[:300]}"
                                for r in results[:5]
                            )
                        except Exception as e:
                            result_text = f"Search unavailable: {e}"
                        full_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_text,
                        })
            else:
                content = choice.message.content or ""
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                return content

        return response.choices[0].message.content or ""
