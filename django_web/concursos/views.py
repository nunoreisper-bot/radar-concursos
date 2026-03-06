import os
from datetime import datetime

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from .models import Opportunity


RADAR_PASSWORD = os.getenv("RADAR_PASSWORD", "albusdumbledore")


def login_gate(request):
    if request.GET.get("logout") == "1":
        request.session.pop("radar_unlocked", None)

    if request.session.get("radar_unlocked"):
        return redirect("dashboard")

    error = None
    if request.method == "POST":
        password = (request.POST.get("password") or "").strip()
        if password == RADAR_PASSWORD:
            request.session["radar_unlocked"] = True
            return redirect("dashboard")
        error = "Password inválida. Tenta outra vez."

    return render(request, "concursos/login.html", {"error": error})


def logout_view(request):
    request.session.pop("radar_unlocked", None)
    return redirect("login_gate")


def dashboard(request):
    if not request.session.get("radar_unlocked"):
        return redirect("login_gate")
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "todas")
    status = request.GET.get("status", "todos")
    min_score = int(request.GET.get("min_score", 20) or 20)
    sort_by = request.GET.get("sort_by", "score")
    sort_order = request.GET.get("sort_order", "desc")

    qs = Opportunity.objects.filter(relevance_score__gte=min_score)

    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(cpv__icontains=q)
            | Q(location__icontains=q)
            | Q(notice_number__icontains=q)
        )
    if category != "todas":
        qs = qs.filter(category=category)
    if status != "todos":
        qs = qs.filter(status=status)

    # Sorting
    if sort_by == "category_priority":
        priority = {"arquitetura": 0, "fiscalização": 1, "engenharia": 2, "misto": 3}
        items = list(qs[:4000])
        reverse = sort_order == "desc"
        items.sort(key=lambda x: (priority.get((x.category or "").lower(), 99), -(x.relevance_score or 0)))
        if reverse:
            items.reverse()
        sliced_items = items[:1200]
    else:
        order_prefix = "-" if sort_order == "desc" else ""
        field_map = {
            "score": "relevance_score",
            "data_entrega": "deadline_at",
            "data_aviso": "published_at",
            "categoria": "category",
            "recentes": "first_seen_at",
        }
        order_field = field_map.get(sort_by, "relevance_score")
        sliced_items = qs.order_by(f"{order_prefix}{order_field}")[:1200]

    categories = Opportunity.objects.values_list("category", flat=True).distinct().order_by("category")

    return render(
        request,
        "concursos/dashboard.html",
        {
            "items": sliced_items,
            "q": q,
            "selected_category": category,
            "selected_status": status,
            "min_score": min_score,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "categories": [c for c in categories if c],
            "status_options": ["todos", "new", "favorite", "irrelevant", "review"],
            "row_status_options": ["new", "favorite", "irrelevant", "review"],
            "current_year": datetime.now().year,
        },
    )


@require_POST
def update_item(request, item_id):
    item = get_object_or_404(Opportunity, id=item_id)
    status = request.POST.get("status", "new")
    note = (request.POST.get("feedback_note", "") or "").strip() or None

    if status not in {"new", "favorite", "irrelevant", "review"}:
        return JsonResponse({"ok": False, "error": "invalid status"}, status=400)

    Opportunity.objects.filter(id=item.id).update(status=status, feedback_note=note)
    return JsonResponse({"ok": True})
