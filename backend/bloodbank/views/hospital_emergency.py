"""Ca khẩn cấp: báo khẩn → kho mình → bệnh viện gần còn dư → người hiến (xem services/emergency.py)."""
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from bloodbank.forms import EmergencyForm
from bloodbank.models import Demand, ProductSpec
from bloodbank.permissions import staff_required
from bloodbank.services import emergency
from bloodbank.services import inventory as inv

from .helpers import attempt, int_or_none


@staff_required
def emergency_new(request):
    """Phiếu báo khẩn. Điền sẵn từ dòng thiếu / yêu cầu cần máu (?blood_group, product, spec, qty, needed_by, patient_request)."""
    g = request.GET
    initial = {"blood_group": g.get("blood_group"), "quantity": int_or_none(g.get("qty"))}
    spec_id = int_or_none(g.get("spec"))
    if not spec_id and int_or_none(g.get("product")):
        d = ProductSpec.objects.filter(product_id=int_or_none(g.get("product")), is_default=True).first()
        spec_id = d.pk if d else None
    initial["product_spec_id"] = spec_id
    needed = parse_datetime(g.get("needed_by") or "")
    if needed:
        initial["needed_by"] = timezone.localtime(needed).strftime("%Y-%m-%dT%H:%M")
    form = EmergencyForm(request.POST or None, initial=initial)
    prq_id = request.POST.get("patient_request_id") or g.get("patient_request")
    if request.method == "POST" and form.is_valid():
        data = {**form.cleaned_data, "patient_request_id": prq_id}
        ok, demand = attempt(request, lambda: emergency.start(request.staff, data, request),
                             "Đã báo khẩn: toàn bệnh viện đã được thông báo, hệ thống đang xin các bệnh viện gần.")
        if ok:
            return redirect("bloodbank:emergency_case", pk=demand.pk)
    return render(request, "hospital/emergency_new.html", {"form": form, "patient_request_id": prq_id})


@staff_required
def emergency_case(request, pk):
    demand = get_object_or_404(Demand.objects.select_related("product_spec__product", "support_request", "patient_request"),
                               pk=pk, hospital=request.hospital, is_emergency=True)
    return render(request, "hospital/emergency_case.html", {"d": demand, "s": emergency.state(demand)})


@staff_required
@require_POST
def emergency_more(request, pk):
    attempt(request, lambda: emergency.ask_more_hospitals(request.staff, pk, request),
            lambda n: f"Đã xin thêm {n} đơn vị từ các bệnh viện khác.")
    return redirect("bloodbank:emergency_case", pk=pk)


@staff_required
@require_POST
def emergency_close(request, pk):
    status = request.POST.get("status")
    attempt(request, lambda: inv.close_demand(request.staff, pk, status, request),
            "Đã đóng ca khẩn." if status == "fulfilled" else "Đã hủy ca khẩn.")
    return redirect(reverse("bloodbank:emergency_case", args=[pk]))
