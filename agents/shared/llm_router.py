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
        from google.genai.types import GenerateContentConfig

        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        last_user_message = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        config_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
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
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        response = client.chat.completions.create(
            model=model,
            messages=full_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
