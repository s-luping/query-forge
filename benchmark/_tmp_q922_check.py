# -*- coding: utf-8 -*-
"""检查 q922 (dog_kennels) 拦截轮的 prompt 注入内容。"""
import sqlite3

con = sqlite3.connect(r"db\logs.db")
tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("tables:", tables)

# llm_prompts / llm_calls: 找最近一次 prompt 里含 Indiana 的调用
for t in ("llm_prompts", "llm_calls"):
    if t not in tables:
        continue
    cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
    print(t, "cols:", cols)

if "llm_prompts" in tables:
    cols = [c[1] for c in con.execute("PRAGMA table_info(llm_prompts)")]
    rows = con.execute(
        "SELECT * FROM llm_prompts ORDER BY id DESC LIMIT 40").fetchall()
    for r in rows:
        d = dict(zip(cols, r))
        blob = json.dumps(d, ensure_ascii=False, default=str)
        if "Indiana" in blob or "indiana" in blob:
            print("---- hit id:", d.get("id"), "call_id:", d.get("call_id"))
            for k, v in d.items():
                s = str(v)
                if k in ("prompt", "content", "request_body", "prompt_text"):
                    print(k, "len:", len(s))
                    # 查关键段
                    import re
                    for kw in ("professionals", "treatments", "dog_kennels", "表结构"):
                        idxs = [m.start() for m in re.finditer(kw, s, re.I)][:3]
                        print("  kw", kw, "hits:", idxs)
                    if "professionals" in s.lower():
                        i = s.lower().find("professionals")
                        print("  ctx:", s[max(0, i-200):i+300].replace("\n", " ")[:500])
                    else:
                        print("  professionals NOT in prompt!")
            break
