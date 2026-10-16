#!/usr/bin/env python3
"""Does the installed vLLM 0.23 guided-decoding backend enforce maxLength, maxItems, enum, integer minimum/maximum?
Adversarial prompts ask for violations; the unmodified base manuscript is not used (short synthetic text only)."""
import json, sys, urllib.request
EP = {"qwen38_27": "http://127.0.0.1:8097", "qwen36_27": "http://127.0.0.1:8098"}
schema = {"type": "object", "properties": {
    "notes": {"type": "string", "maxLength": 120},
    "items": {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 10}},
    "color": {"type": "string", "enum": ["red", "blue"]},
    "score": {"type": "integer", "minimum": 1, "maximum": 5}},
    "required": ["notes", "items", "color", "score"], "additionalProperties": False}
prompt = ("Return JSON. In notes write a 400-word essay about rivers. In items list twelve long river names. "
          "Set color to green. Set score to 99.")
out = {}
for m, ep in EP.items():
    body = {"model": m, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 1500,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {"name": "t", "schema": schema}}}
    req = urllib.request.Request(ep + "/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    c = d["choices"][0]["message"]["content"]; fr = d["choices"][0]["finish_reason"]
    o = json.loads(c)
    res = {"finish": fr, "notes_len": len(o["notes"]), "maxLength_enforced": len(o["notes"]) <= 120,
           "items": o["items"], "maxItems_enforced": len(o["items"]) <= 2, "item_maxLength_enforced": all(len(x) <= 10 for x in o["items"]),
           "color": o["color"], "enum_enforced": o["color"] in ("red", "blue"), "score": o["score"], "range_enforced": 1 <= o["score"] <= 5}
    out[m] = res
    print(m, json.dumps(res))
json.dump(out, open(sys.argv[1], "w"), indent=1)
