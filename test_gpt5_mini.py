#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GPT-5-mini の動作テスト"""
import os
from openai import OpenAI

# APIキーを環境変数から取得
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("Error: OPENAI_API_KEY not set")
    exit(1)

client = OpenAI(api_key=api_key)

# テスト1: 基本的な呼び出し
print("=== Test 1: Basic call ===")
try:
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "あなたは優秀なライターです。"},
            {"role": "user", "content": "「群馬銀行 やばい」というキーワードで、読者の不安に寄り添うSEOタイトルを1本だけ書いてください。"}
        ],
        max_completion_tokens=300,
        temperature=0.7
    )
    
    print(f"Response object: {response}")
    print(f"\nChoice[0]: {response.choices[0]}")
    print(f"\nMessage: {response.choices[0].message}")
    print(f"\nContent: '{response.choices[0].message.content}'")
    print(f"\nContent length: {len(response.choices[0].message.content or '')}")
    print(f"\nFinish reason: {response.choices[0].finish_reason}")
    
except Exception as e:
    print(f"Error: {e}")

# テスト2: temperature なし
print("\n\n=== Test 2: Without temperature ===")
try:
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "あなたは優秀なライターです。"},
            {"role": "user", "content": "「群馬銀行 やばい」というキーワードで、読者の不安に寄り添うSEOタイトルを1本だけ書いてください。"}
        ],
        max_completion_tokens=300
    )
    
    print(f"Content: '{response.choices[0].message.content}'")
    print(f"Content length: {len(response.choices[0].message.content or '')}")
    print(f"Finish reason: {response.choices[0].finish_reason}")
    
except Exception as e:
    print(f"Error: {e}")

# テスト3: シンプルなプロンプト
print("\n\n=== Test 3: Simple prompt ===")
try:
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "user", "content": "Hello, how are you?"}
        ],
        max_completion_tokens=100
    )
    
    print(f"Content: '{response.choices[0].message.content}'")
    print(f"Content length: {len(response.choices[0].message.content or '')}")
    
except Exception as e:
    print(f"Error: {e}")
