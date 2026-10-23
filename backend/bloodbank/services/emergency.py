"""Ca khẩn cấp (nút "Khẩn cấp"): cần máu trong vài giờ.

Thứ tự xử lý — nguồn có sẵn và đã xét nghiệm trước, người hiến sau cùng:
  1. KHO MÌNH: phần đang khả dụng → xuất ngay cho người bệnh.
  2. BỆNH VIỆN GẦN CÒN DƯ: phần còn thiếu tự chia cho các bệnh viện gần nhất có khai số chia sẻ, gửi đề nghị KHẨN
     (bên kia nhận email; không phản hồi sau `offer_response_ttl_urgent_minutes` thì tự hủy).
  3. NGƯỜI HIẾN: chỉ khi bệnh viện không đủ (không ai còn dư, từ chối, quá hạn) mới kêu gọi khẩn, đúng phần còn thiếu.
     Máu hiến mới còn phải xét nghiệm → bước này chủ yếu để bù lại kho, trừ nhóm máu hiếm.

Mỗi ca là một Demand (is_emergency) — nhờ vậy phần thiếu tự hiện ở "Cần xử lý" và tự giảm khi kho được bổ sung.
"""
from datetime import timedelta

from django.utils import timezone

from accounts.models import BLOOD_GROUP_VALUES
from bloodbank.models import Demand, PatientRequest, ProductSpec, RequestOffer, Stock

from . import transfers as trf
from .common import (
    BusinessError, alert, as_id, audit, business_transaction, hospital_staff_users, positive_int, require, snapshot,
)

O = RequestOffer.Status
DEFAULT_HOURS = 6


def _stock(hospital, blood_group, spec):
    return Stock.objects.filter(hospital=hospital, blood_group=blood_group, product_spec=spec).first()


def start(staff, data, request=None):
    """Tạo ca khẩn: nhu cầu mức khẩn + báo toàn bệnh viện + tự xin bệnh viện gần cho phần kho không đủ."""
    h = staff.hospital
    bg = data.get("blood_group")
    require(bg in BLOOD_GROUP_VALUES, "ERR-VALIDATION", "Chọn nhóm máu.")
    spec = ProductSpec.objects.select_related("product").filter(
        pk=as_id(data.get("product_spec_id")), is_active=True, product__is_active=True).first()
    require(spec is not None, "ERR-CAT-INACTIVE", "Chọn chế phẩm / quy cách.")
    qty = positive_int(data.get("quantity"))
    needed_by = data.get("needed_by") or timezone.now() + timedelta(hours=DEFAULT_HOURS)
    require(needed_by > timezone.now(), "ERR-VALIDATION", "Thời điểm cần phải ở tương lai.")
    prq = None
    if data.get("patient_request_id"):
        prq = PatientRequest.objects.filter(pk=as_id(data["patient_request_id"]), hospital=h).first()
        require(prq is not None, "ERR-PRQ-WRONG-HOSPITAL")
    note = (data.get("note") or "").strip()[:500] or None

    with business_transaction():
        demand = Demand.objects.create(hospital=h, blood_group=bg, product_spec=spec, required_quantity=qty,
                                       needed_by=needed_by, note=note, is_emergency=True, patient_request=prq)
        audit(staff.user, demand, "emergency_start", new=snapshot(demand), hospital=h, request=request)
        alert(hospital_staff_users(h), "emergency_started",
              f"[Khẩn] Cần {qty} đơn vị {bg} trước {timezone.localtime(needed_by):%H:%M %d/%m}",
              f"{spec.product.name} — {spec.name}. Do {staff.user.full_name} tạo. Mở ca khẩn để xử lý.", entity=demand)
        _ask_hospitals(staff, demand, request)
    return demand


def _ask_hospitals(staff, demand, request=None):
    """Bước 2: chia phần thiếu cho bệnh viện gần còn dư (chưa được mời trong ca này), gửi đề nghị khẩn."""
    st = state(demand)
    need = st["donors_needed"]       # phần chưa có nguồn nào lo (kho, đang chuyển, đang chờ trả lời)
    if need <= 0:
        return 0
    asked = set()
    if demand.support_request_id:
        asked = set(demand.support_request.offers.values_list("supplier_hospital_id", flat=True))
    rows = [r for r in trf.search_sources(demand.hospital, demand.blood_group, demand.product_spec.product_id,
                                          demand.product_spec_id) if r["hospital"].pk not in asked]
    plan = trf.suggest_allocation(rows, need, demand.product_spec_id)
    if not plan:
        return 0
    if demand.support_request_id and not demand.support_request.is_final and demand.support_request.closed_at is None:
        req = demand.support_request
        # Phiếu đã có: số cần = phần đã có nguồn lo (nhận, đang chuyển, chấp thuận, chờ trả lời) + phần mới xin
        n = trf.request_numbers(req)
        pending = sum(o.quantity_requested or 0 for o in req.offers.filter(status=O.PENDING))
        req.quantity_needed = n["received"] + n["transit"] + n["committed"] + pending + sum(plan.values())
        req.save(update_fields=["quantity_needed", "updated_at"])
        for hid, q in plan.items():
            trf.invite_more(staff, req.pk, hid, q, request)
    else:
        req = trf.create_request(staff, {
            "blood_group": demand.blood_group, "product_spec_id": demand.product_spec_id,
            "quantity_needed": sum(plan.values()), "priority": "urgent", "needed_by": demand.needed_by,
            "note": f"Ca khẩn cấp #{demand.pk}" + (f" — {demand.note}" if demand.note else ""),
        }, list(plan.items()),
            patient_request_id=demand.patient_request_id if demand.patient_request_id and demand.patient_request.status in (
                PatientRequest.Status.VERIFIED, PatientRequest.Status.PROCESSING) else None,
            request=request)
        Demand.objects.filter(pk=demand.pk).update(support_request=req)
        demand.support_request = req
    return sum(plan.values())


def ask_more_hospitals(staff, demand_id, request=None):
    """Bệnh viện từ chối / quá hạn → thử xin thêm bệnh viện khác còn dư (chưa mời trong ca này)."""
    demand = _get(staff, demand_id)
    with business_transaction():
        n = _ask_hospitals(staff, demand, request)
    if not n:
        raise BusinessError("ERR-NOT-FOUND", "Không còn bệnh viện nào khác đang chia sẻ chế phẩm này. Hãy kêu gọi người hiến.")
    return n


def _get(staff, demand_id):
    d = (Demand.objects.select_related("product_spec__product", "support_request", "patient_request")
         .filter(pk=as_id(demand_id), hospital=staff.hospital, is_emergency=True).first())
    if d is None:
        raise BusinessError("ERR-NOT-FOUND")
    return d


def state(demand):
    """Tình trạng 3 bước của ca khẩn (chỉ đọc).

    - kho: khả dụng hiện tại của đúng nhóm máu + quy cách (đã gồm phần bệnh viện khác giao tới);
    - bệnh viện: đã nhận / đang chuyển / đã chấp thuận / đang chờ trả lời;
    - người hiến cần lo = thiếu hiện tại − (đang chuyển + đã chấp thuận + đang chờ trả lời).
    """
    stock = _stock(demand.hospital, demand.blood_group, demand.product_spec)
    available = stock.available if stock else 0
    short_now = max(0, demand.required_quantity - available) if demand.status == Demand.Status.ACTIVE else 0
    hosp = {"received": 0, "transit": 0, "committed": 0, "waiting": 0, "offers": [], "request": None}
    req = demand.support_request
    if req is not None:
        n = trf.request_numbers(req)
        offers = list(req.offers.select_related("supplier_hospital").order_by("pk"))
        for o in offers:
            o.distance_km = trf.distance_km(demand.hospital, o.supplier_hospital)
        hosp.update(received=n["received"], transit=n["transit"], committed=n["committed"], offers=offers, request=req,
                    waiting=sum(o.quantity_requested or 0 for o in offers if o.status == O.PENDING))
    incoming = hosp["transit"] + hosp["committed"] + hosp["waiting"]
    donors_needed = max(0, short_now - incoming)
    if demand.status != Demand.Status.ACTIVE:
        step = "done"
    elif short_now == 0:
        step = "issue"            # kho đã đủ (ban đầu hoặc nhờ bệnh viện khác giao tới): xuất cho người bệnh
    elif donors_needed == 0:
        step = "hospitals"        # đang chờ bệnh viện trả lời / giao hàng
    else:
        step = "donors"           # bệnh viện không đủ → kêu gọi người hiến
    return {"available": available, "stock_id": stock.pk if stock else None, "short_now": short_now, "hosp": hosp, "incoming": incoming,
            "donors_needed": donors_needed, "step": step,
            "can_issue": min(available, demand.required_quantity) if demand.status == Demand.Status.ACTIVE else 0}


def active_cases(hospital):
    return (Demand.objects.filter(hospital=hospital, is_emergency=True, status=Demand.Status.ACTIVE)
            .select_related("product_spec__product").order_by("needed_by"))
