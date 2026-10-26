"""Kiểm thử tích hợp + benchmark với Ollama THẬT (bỏ qua khi không đặt OLLAMA_LIVE_URL).

    docker compose exec -e OLLAMA_LIVE_URL=http://ollama:11434 -e OLLAMA_LIVE_MODEL=qwen3:4b-instruct-2507-q4_K_M web \
        python manage.py test bloodbank.tests.test_ollama_live

Chạy toàn bộ bộ câu hỏi mẫu (assistant_eval.json) qua đúng đường đi của trợ lý: chặn trước → tài liệu → tra sẵn dữ
liệu → mô hình → kiểm tra. Đo thời gian ra chữ đầu tiên, tổng thời gian, tỷ lệ dùng đúng công cụ dữ liệu, tỷ lệ phải
dùng chế độ dự phòng, độ chính xác theo `contains` / `not_contains`. Ghi báo cáo JSON ra OLLAMA_LIVE_REPORT (nếu đặt).
"""
import json
import os
import statistics
import time
from pathlib import Path

from django.core.cache import cache
from django.test import override_settings, tag
from unittest import skipUnless

from bloodbank.assistant import guard, knowledge, llm, rules, verify
from bloodbank.assistant.tools import Ctx

from .test_assistant import AssistantData

LIVE_URL = os.environ.get("OLLAMA_LIVE_URL", "")
LIVE_MODEL = os.environ.get("OLLAMA_LIVE_MODEL", "qwen3:4b-instruct-2507-q4_K_M")
# Ý định của bộ câu hỏi mẫu → công cụ dữ liệu phải được dùng (tra sẵn hoặc mô hình tự gọi)
INTENT_TOOL = {"campaigns": "suggest_campaigns", "eligibility": "my_eligibility", "history": "my_donation_history",
               "my_registrations": "my_registrations", "my_patient_requests": "my_patient_requests",
               "precheck": "preliminary_check"}


@tag("live")
@skipUnless(LIVE_URL, "Đặt OLLAMA_LIVE_URL để chạy với Ollama thật")
@override_settings(OLLAMA_BASE_URL=LIVE_URL, OLLAMA_MODEL=LIVE_MODEL, CHATBOT_USE_LLM=True)
class LiveOllamaEval(AssistantData):
    def test_eval_set(self):
        cases = json.loads((Path(__file__).parent / "assistant_eval.json").read_text(encoding="utf-8"))
        users = {"anon": None, "donor": self.donor, "newbie": self.newbie}
        rows = []
        # Làm nóng: lần đầu nạp mô hình vào GPU (không tính vào thời gian trả lời)
        t0 = time.monotonic()
        llm.ask("xin chào", Ctx(), docs=[])
        load_s = time.monotonic() - t0
        for case in cases:
            cache.clear()
            ctx = Ctx(user=users[case.get("as", "anon")])
            row = {"q": case["q"], "intent": case["intent"], "as": case.get("as", "anon")}
            blocked = guard.check(case["q"])
            if blocked:
                row.update(mode="guard", answer=blocked["answer"], cards=[], ok=True, tool_ok=None)
                rows.append(row)
                continue
            docs = knowledge.search(case["q"])
            pre = rules.prefetch(case["q"], ctx)
            if pre and pre[2].get("login_required"):
                res = rules.answer(case["q"], ctx, docs=docs, pre=pre)
                row.update(mode="rules-login", answer=res["answer"], cards=res.get("cards", []), tool_ok=None)
            else:
                start, first = time.monotonic(), None
                try:
                    res = None
                    for kind, payload in llm.stream(case["q"], ctx, docs=docs, prefetched=pre[1:] if pre else None):
                        if kind == "delta" and first is None:
                            first = time.monotonic() - start
                        if kind == "result":
                            res = payload
                    res["answer"] = verify.check(res["answer"], res["evidence"])
                    want = INTENT_TOOL.get(case["intent"])
                    row.update(mode="llm", answer=res["answer"], cards=res["cards"], tools=res["tools_used"],
                               tool_ok=(want in res["tools_used"]) if want else None)
                except (llm.LLMUnavailable, verify.Unverified) as exc:
                    res = rules.answer(case["q"], ctx, docs=docs, pre=pre)
                    row.update(mode="fallback", reason=str(exc)[:160], answer=res["answer"],
                               cards=res.get("cards", []), tool_ok=None)
                row.update(first_s=round(first, 2) if first is not None else None,
                           total_s=round(time.monotonic() - start, 2))
            text_all = (row["answer"] + " " + " ".join(c["name"] for c in row["cards"])).lower()
            missing = [m for m in case.get("contains", []) if m.lower() not in text_all]
            bad = [b for b in case.get("not_contains", []) if b.lower() in text_all]
            row.update(ok=not missing and not bad, missing=missing, bad=bad)
            rows.append(row)

        ai = [r for r in rows if r["mode"] in ("llm", "fallback")]
        timed = [r for r in ai if r.get("total_s") is not None]
        firsts = [r["first_s"] for r in timed if r.get("first_s") is not None]
        tool_rows = [r for r in rows if r.get("tool_ok") is not None]
        summary = {
            "model": LIVE_MODEL, "cases": len(rows), "load_s": round(load_s, 1),
            "correct": sum(r["ok"] for r in rows),
            "ai_answered": sum(r["mode"] == "llm" for r in rows), "fallback": sum(r["mode"] == "fallback" for r in rows),
            "guard": sum(r["mode"] == "guard" for r in rows),
            "tool_success": f"{sum(r['tool_ok'] for r in tool_rows)}/{len(tool_rows)}",
            "first_token_median_s": round(statistics.median(firsts), 2) if firsts else None,
            "total_median_s": round(statistics.median([r["total_s"] for r in timed]), 2) if timed else None,
            "total_max_s": max((r["total_s"] for r in timed), default=None),
        }
        report = os.environ.get("OLLAMA_LIVE_REPORT")
        if report:
            Path(report).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1,
                                               default=str), encoding="utf-8")
        print("\n" + json.dumps(summary, ensure_ascii=False))
        # Kiểm tra chặt những gì quan trọng: không câu nào chứa nội dung cấm, câu hỏi dữ liệu luôn dùng đúng công cụ,
        # không câu nào phải rơi về dự phòng vì lỗi. Khớp từ khóa (`contains`, viết cho chế độ từ khóa) chỉ cần ≥ 70%:
        # mô hình diễn đạt khác nhau mỗi lần nên tỷ lệ này dao động vài câu giữa các lần chạy.
        self.assertEqual([r["q"] for r in rows if r.get("bad")], [], "Có câu trả lời chứa nội dung cấm")
        self.assertTrue(all(r["tool_ok"] for r in tool_rows), summary)
        self.assertEqual(summary["fallback"], 0, summary)
        self.assertGreaterEqual(summary["correct"], int(0.7 * len(rows)), summary)
