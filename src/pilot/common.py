from __future__ import annotations
import json, re, time, urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_MODEL_CACHE: dict[str, str] = {}

def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())

def save_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")

def append_jsonl(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def read_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out

def extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        pass

    starts = [(text.find("{"), "{", "}"), (text.find("["), "[", "]")]
    starts = [x for x in starts if x[0] >= 0]

    for start, op, cl in sorted(starts):
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]

            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue

            if ch == '"':
                in_str = True
                continue

            if ch == op:
                depth += 1
            elif ch == cl:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start:i + 1])

    raise ValueError("No parseable JSON found")

def endpoint_model(base_url: str, timeout: int = 30) -> str:
    if base_url in _MODEL_CACHE:
        return _MODEL_CACHE[base_url]

    req = urllib.request.Request(base_url.rstrip("/") + "/v1/models")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())

    model = data["data"][0]["id"]
    _MODEL_CACHE[base_url] = model
    return model

def chat(
    base_url: str,
    messages: list[dict],
    *,
    temperature: float = 0.1,
    max_tokens: int = 2200,
    seed: int = 1,
    timeout: int = 1200,
    response_format: dict | None = None,
    chat_template_kwargs: dict | None = None,
    extra_body: dict | None = None,
    use_reasoning_as_content: bool = False,
    return_diagnostics: bool = False,
) -> tuple[str, dict] | tuple[str, dict, dict]:

    model = endpoint_model(base_url)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "seed": seed,
    }
    if response_format is not None:
        payload["response_format"] = response_format
    if chat_template_kwargs is not None:
        payload["chat_template_kwargs"] = chat_template_kwargs
    if extra_body:
        payload.update(extra_body)

    req = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())

            choice = data["choices"][0]
            msg = choice["message"]
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning")
            reasoning_content = msg.get("reasoning_content")

            if use_reasoning_as_content and not content.strip():
                content = reasoning_content or reasoning or ""

            diagnostics = {
                "message_keys": sorted(msg.keys()),
                "finish_reason": choice.get("finish_reason"),
                "usage": data.get("usage"),
                "content_length": len(msg.get("content") or ""),
                "reasoning_length": len(reasoning or ""),
                "reasoning_content_length": len(reasoning_content or ""),
                "has_content": bool((msg.get("content") or "").strip()),
                "has_reasoning": bool((reasoning or "").strip()),
                "has_reasoning_content": bool((reasoning_content or "").strip()),
            }
            data["_diagnostics"] = diagnostics

            if return_diagnostics:
                return content, data, diagnostics
            return content, data

        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"chat failed: {last}")
