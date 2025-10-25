# lib/llm.py
# -*- coding: utf-8 -*-
"""LLMクライアントの統合"""
import sys
from typing import Optional
from openai import OpenAI

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

class LLMClient:
    """LLMクライアント（OpenAI/Anthropic統合）"""
    
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
    
    def generate(self, model: str, system: str, user: str, 
                 temperature: float = 0.5, max_tokens: int = 6000) -> str:
        """テキスト生成"""
        print(f"[LLM] {self.provider}/{model} (temp={temperature}, max={max_tokens})", 
              file=sys.stdout, flush=True)
        
        if self.provider == "anthropic":
            return self._generate_anthropic(model, system, user, temperature, max_tokens)
        else:
            return self._generate_openai(model, system, user, temperature, max_tokens)
    
    def _generate_anthropic(self, model: str, system: str, user: str,
                           temperature: float, max_tokens: int) -> str:
        """Claude生成"""
        resp = self.client.messages.create(
            model=model,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = "".join(
            block.text for block in resp.content 
            if getattr(block, "type", None) == "text"
        ).strip()
        print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
        return text
    
    def _generate_openai(self, model: str, system: str, user: str,
                        temperature: float, max_tokens: int) -> str:
        """OpenAI生成（フォールバック処理含む）"""
        params = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        # 試行1: デフォルト
        try:
            resp = self.client.chat.completions.create(**params)
            text = (resp.choices[0].message.content or "").strip()
            print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
            return text
        except Exception as e:
            error_msg = str(e).lower()
            
            # max_tokens非対応 → max_completion_tokens
            if "max_tokens" in error_msg and "not supported" in error_msg:
                print("[LLM] max_tokens非対応 → max_completion_tokensで再試行")
                params.pop("max_tokens", None)
                params["max_completion_tokens"] = max_tokens
                
                try:
                    resp = self.client.chat.completions.create(**params)
                    text = (resp.choices[0].message.content or "").strip()
                    print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
                    return text
                except Exception as e2:
                    error_msg2 = str(e2).lower()
                    
                    # temperature非対応
                    if "temperature" in error_msg2 and "unsupported" in error_msg2:
                        print("[LLM] temperature非対応 → 削除して再試行")
                        params.pop("temperature", None)
                        resp = self.client.chat.completions.create(**params)
                        text = (resp.choices[0].message.content or "").strip()
                        print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
                        return text
                    raise e2
            
            # temperature非対応（最初から）
            elif "temperature" in error_msg and "unsupported" in error_msg:
                print("[LLM] temperature非対応 → 削除して再試行")
                params.pop("temperature", None)
                
                try:
                    resp = self.client.chat.completions.create(**params)
                    text = (resp.choices[0].message.content or "").strip()
                    print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
                    return text
                except Exception as e2:
                    # max_tokens問題が後から
                    error_msg2 = str(e2).lower()
                    if "max_tokens" in error_msg2 and "not supported" in error_msg2:
                        print("[LLM] max_tokens非対応 → max_completion_tokensで再試行")
                        params.pop("max_tokens", None)
                        params["max_completion_tokens"] = max_tokens
                        resp = self.client.chat.completions.create(**params)
                        text = (resp.choices[0].message.content or "").strip()
                        print(f"[LLM] 完了 ({len(text)}文字)", flush=True)
                        return text
                    raise e2
            else:
                raise e