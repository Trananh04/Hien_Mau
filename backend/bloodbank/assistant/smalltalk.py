"""Câu giao tiếp thường ngày (chào, cảm ơn, tạm biệt, hỏi thăm, "bạn là ai", "ok") — đáp lại tự nhiên như người thật.

Dùng ở chế độ từ khóa (không có AI) và khi AI lỗi; chế độ AI tự trả lời các câu này theo hướng dẫn trong llm.RULES.
Chỉ nhận câu NGẮN chỉ gồm lời giao tiếp — "chào bạn, tôi muốn hiến máu ở Đà Nẵng" vẫn đi tiếp tới phần tra cứu.
"""
import random
import re

from bloodbank.content import _norm

HELP = ("tìm đợt hiến máu gần bạn, xem khi nào bạn hiến lại được, giải đáp về quy trình và chuẩn bị trước khi hiến, "
        "hoặc hướng dẫn gửi yêu cầu khi người nhà cần máu")

PATTERNS = [
    ("greeting", re.compile(r"^(xin )?(chao|hi|hello|helo|hey|alo|a lo|yo|chao ban|chao em|chao ad|chao admin|"
                            r"chao tro ly|hi ban|hello ban|good morning|chao buoi (sang|trua|chieu|toi))"
                            r"( ban| em| ad| shop| ca nha| moi nguoi)?$")),
    ("how_are_you", re.compile(r"^(ban )?(khoe khong|co khoe khong|the nao roi|dang lam gi( do| the)?|"
                               r"how are you)$")),
    ("who", re.compile(r"^(ban|em|day) (la ai|la gi|ten (la )?gi|lam duoc gi|giup duoc gi|biet lam gi)$|"
                       r"^(ban|em) co the (lam|giup) (duoc )?gi( cho (toi|minh))?$|^(giup|tro giup|help)( toi| minh)?$")),
    ("thanks", re.compile(r"^(cam on|cam on ban|cam on nhieu|cam on nhe|cam on em|thank|thanks|thank you|tks|thanks ban|"
                          r"ok cam on|ok thanks|cam on ban nhieu)( nhieu| nhe| nha| a)?$")),
    ("bye", re.compile(r"^(tam biet|bye|bye bye|bai|hen gap lai|chao nhe|di day|toi di day)( ban| nhe| nha)?$")),
    ("ack", re.compile(r"^(ok|oke|okay|okela|uh|u|uhm|um|vang|da|duoc|duoc roi|hieu roi|toi hieu roi|ro roi|"
                       r"tot|hay|hay qua|tuyet)( nhe| nha| a| roi)?$")),
]

REPLIES = {
    "greeting": [
        "Chào {name}! Mình là trợ lý hiến máu của Giọt Hồng. Mình có thể giúp bạn {help}. Bạn đang cần gì nè?",
        "Chào {name}, rất vui được nói chuyện với bạn. Bạn muốn tìm đợt hiến máu, hỏi về quy trình hiến, "
        "hay đang cần máu cho người nhà?",
    ],
    "how_are_you": [
        "Mình vẫn ổn và sẵn sàng giúp bạn nè. Hôm nay bạn muốn tìm đợt hiến máu hay hỏi gì về hiến máu?",
    ],
    "who": [
        "Mình là trợ lý hiến máu của Giọt Hồng. Mình có thể giúp bạn {help}. Bạn cứ hỏi tự nhiên, "
        "ví dụ: \"Cuối tuần này có đợt hiến nào ở Đà Nẵng?\" hoặc \"Trước khi hiến máu cần chuẩn bị gì?\"",
    ],
    "thanks": [
        "Không có gì đâu {name}! Cảm ơn bạn đã quan tâm đến hiến máu. Cần gì thêm cứ hỏi mình nhé.",
        "Rất vui vì giúp được bạn. Nếu cần tìm đợt hiến hay hỏi thêm, mình luôn ở đây.",
    ],
    "bye": [
        "Tạm biệt {name}, chúc bạn một ngày tốt lành! Khi cần, cứ quay lại hỏi mình nhé.",
    ],
    "ack": [
        "Dạ vâng. Bạn còn muốn hỏi thêm gì không? Mình có thể tìm đợt hiến gần bạn hoặc giải đáp về quy trình hiến.",
    ],
}


def kind(question):
    q = re.sub(r"[^\w\s]", " ", _norm(question or ""))
    q = re.sub(r"\s+", " ", q).strip()
    if not q or len(q) > 40:
        return None
    for name, pattern in PATTERNS:
        if pattern.match(q):
            return name
    return None


def reply(question, user=None):
    """Câu đáp tự nhiên, hoặc None nếu không phải câu giao tiếp thường ngày."""
    k = kind(question)
    if k is None:
        return None
    name = getattr(user, "short_name", None) if getattr(user, "is_authenticated", False) else None
    text = random.choice(REPLIES[k]).format(name=name or "bạn", help=HELP)
    return {"answer": text, "source": None, "intent": "smalltalk", "links": []}
