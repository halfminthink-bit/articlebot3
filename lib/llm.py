# lib/llm.py
# -*- coding: utf-8 -*-
"""LLMクライアントの統合（GPT-5対応版・temperature削除版）"""
import sys
from typing import Optional
from openai import OpenAI

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

class LLMClient:
    """LLMクライアント（OpenAI/Anthropic統合）"""
    
    # モデルごとの最大出力トークン数
    MAX_OUTPUT_TOKENS = {
        # GPT-5系（推論モデル）
        "gpt-5": 128000,
        "gpt-5-mini": 128000,
        "gpt-5-nano": 128000,
        "gpt-5-chat-latest": 128000,
        "gpt-5-pro": 128000,
        
        # GPT-4o系
        "gpt-4o": 16384,
        "gpt-4o-2024-11-20": 16384,
        "gpt-4o-2024-08-06": 16384,
        "gpt-4o-2024-05-13": 4096,
        "chatgpt-4o-latest": 16384,
        
        # GPT-4o mini系
        "gpt-4o-mini": 16384,
        "gpt-4o-mini-2024-07-18": 16384,
        
        # GPT-4.1系
        "gpt-4.1": 16384,
        "gpt-4.1-mini": 16384,
        "gpt-4.1-nano": 16384,
        
        # GPT-4系
        "gpt-4-turbo": 4096,
        "gpt-4-turbo-2024-04-09": 4096,
        "gpt-4": 8192,
        "gpt-4-0125-preview": 4096,
        "gpt-4-1106-preview": 4096,
        
        # GPT-3.5系
        "gpt-3.5-turbo": 4096,
        "gpt-3.5-turbo-0125": 4096,
        "gpt-3.5-turbo-1106": 4096,
        
        # o系（推論モデル）
        "o1-preview": 32768,
        "o1-mini": 65536,
        "o3-mini": 100000,
        "o3": 100000,
        "o4-mini": 100000,
    }
    
    def __init__(self, provider: str, api_key: str):
        self.provider = provider.lower()
        self.api_key = api_key
        
        if self.provider == "openai":
            self.client = OpenAI(api_key=api_key)
        elif self.provider == "anthropic":
            if Anthropic is None:
                raise RuntimeError("anthropicパッケージが必要です: pip install anthropic")
            self.client = Anthropic(api_key=api_key)
        else:
            raise ValueError(f"未対応のプロバイダー: {provider}")
    
    def _get_max_tokens_for_model(self, model: str) -> int:
        """モデルごとの最大出力トークン数を取得"""
        # 完全一致
        if model in self.MAX_OUTPUT_TOKENS:
            return self.MAX_OUTPUT_TOKENS[model]
        
        # 部分一致（バージョン番号なしでも対応）
        for key, value in self.MAX_OUTPUT_TOKENS.items():
            if model.startswith(key):
                return value
        
        # デフォルト（安全な値）
        return 4096
    
    def _is_reasoning_model(self, model: str) -> bool:
        """推論モデル（max_completion_tokens使用）か判定"""
        # GPT-5系、o1系、o3系、o4系は推論モデル
        reasoning_prefixes = ["gpt-5", "o1", "o3", "o4"]
        return any(model.startswith(prefix) for prefix in reasoning_prefixes)
    
    def generate(self, model: str, system: str, user: str, max_tokens: int = 6000) -> str:
        """テキスト生成（temperatureパラメータを削除）"""
        
        # max_tokensを制限
        if self.provider == "openai":
            model_max = self._get_max_tokens_for_model(model)
            if max_tokens > model_max:
                print(f"[LLM] max_tokens={max_tokens} をモデル上限 {model_max} に調整", 
                      file=sys.stdout, flush=True)
                max_tokens = model_max
        
        print(f"[LLM] {self.provider}/{model} (max={max_tokens})", 
              file=sys.stdout, flush=True)
        
        if self.provider == "anthropic":
            return self._generate_anthropic(model, system, user, max_tokens)
        else:
            return self._generate_openai(model, system, user, max_tokens)
    
    def _generate_anthropic(self, model: str, system: str, user: str, max_tokens: int) -> str:
        """Claude生成（temperatureはデフォルト値を使用）"""
        resp = self.client.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
        )
        text = "".join(
            block.text for block in resp.content 
            if getattr(block, "type", None) == "text"
        ).strip()
        print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
        return text
    
    def _generate_openai(self, model: str, system: str, user: str, max_tokens: int) -> str:
        """OpenAI生成（Chat Completions・temperature削除）"""
        
        # 推論モデルの場合は max_completion_tokens を使用
        if self._is_reasoning_model(model):
            params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "max_completion_tokens": max_tokens,
            }
        else:
            # 通常モデルは max_tokens を使用
            params = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                "max_tokens": max_tokens,
            }
        
        try:
            resp = self.client.chat.completions.create(**params)
            text = (resp.choices[0].message.content or "").strip()
            
            # 空レスポンスの検出
            if not text:
                print("[LLM] 警告: 空のレスポンスが返されました", file=sys.stderr)
                finish_reason = resp.choices[0].finish_reason
                print(f"[LLM] finish_reason: {finish_reason}", file=sys.stderr)
                
                # length制限の場合は最大3回まで再試行
                if finish_reason == "length":
                    model_max = self._get_max_tokens_for_model(model)
                    retry_count = 0
                    max_retries = 3
                    current_max = max_tokens
                    
                    while retry_count < max_retries and not text:
                        # トークン数を増やす（2倍または残り全て）
                        new_max = min(current_max * 2, model_max)
                        if new_max == current_max:
                            print(f"[LLM] max_tokens上限に達しました: {model_max}", file=sys.stderr)
                            break
                        
                        print(f"[LLM] max_tokens不足 → {new_max} で再試行 (試行 {retry_count + 1}/{max_retries})", flush=True)
                        
                        if self._is_reasoning_model(model):
                            params["max_completion_tokens"] = new_max
                        else:
                            params["max_tokens"] = new_max
                        
                        resp = self.client.chat.completions.create(**params)
                        text = (resp.choices[0].message.content or "").strip()
                        
                        if not text:
                            finish_reason = resp.choices[0].finish_reason
                            print(f"[LLM] まだ空: finish_reason={finish_reason}", file=sys.stderr)
                            if finish_reason != "length":
                                break
                        
                        current_max = new_max
                        retry_count += 1
            
            print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
            return text
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # max_tokens が非対応 → max_completion_tokens に切り替え
            if "max_tokens" in error_msg and ("not supported" in error_msg or "unsupported" in error_msg):
                print("[LLM] max_tokens非対応 → max_completion_tokensで再試行", flush=True)
                params.pop("max_tokens", None)
                params["max_completion_tokens"] = max_tokens
                
                resp = self.client.chat.completions.create(**params)
                text = (resp.choices[0].message.content or "").strip()
                print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
                return text
            
            # max_tokensが大きすぎる
            elif "max_tokens is too large" in error_msg or "max_completion_tokens is too large" in error_msg:
                import re
                match = re.search(r"at most (\d+)", error_msg)
                if match:
                    limit = int(match.group(1))
                    print(f"[LLM] トークン数超過 → {limit} に調整して再試行", flush=True)
                    
                    if "max_completion_tokens" in params:
                        params["max_completion_tokens"] = limit
                    else:
                        params["max_tokens"] = limit
                    
                    resp = self.client.chat.completions.create(**params)
                    text = (resp.choices[0].message.content or "").strip()
                    print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
                    return text
            
            # その他のエラー
            raise e