import os
import random
import time
from datetime import datetime, timedelta, timezone

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from .models import Opportunity


RADAR_PASSWORD = os.getenv("RADAR_PASSWORD", "albusdumbledore")

def _cool_password_error():
    lines = [
        "Erraste a password. Outra vez.",
        "Tentativa fraca.",
        "Quase, mas nem por isso.",
        "Nada feito. Porta fechada.",
        "Falhou redondo. Reagrupa e tenta de novo.",
        "A password certa estava noutro universo.",
        "Isso foi um palpite com excesso de confiança.",
        "Não bateu. Volta com mais rigor.",
        "Hoje estás em modo tentativa livre, estou a ver.",
        "Entrada negada. Continua a brincar que um dia acertas.",
        "A tranca nem pestanejou.",
        "Se isto era um teste de azar, passaste.",
        "Foi bonito de ver. Inútil, mas bonito.",
        "Acertei no diagnóstico: password errada.",
        "Estás perto. Perto de falhar outra vez.",
        "Boa energia, péssima password.",
        "Quiseste entrar à campeão, saíste à estagiário.",
        "Sem drama: erraste. Corrige e volta.",
        "A porta ouviu isso e riu-se.",
        "Entrada recusada com convicção.",
        "Isso foi uma bela porcaria de tentativa.",
        "Que password de merda. Tenta uma a sério.",
        "Parece que atiraste letras ao teclado e rezaste.",
        "Tentativa caótica. Resultado previsível.",
    ]

    return random.choice(lines)


def _empty_password_error():
    lines = [
        "Mandaste um vazio. Password invisível não conta.",
        "Sem password não há milagre. Preenche e volta.",
        "Entrar com nada? Audaz, mas não funciona.",
        "Campo em branco detectado. Tenta com conteúdo real.",
    ]
    return random.choice(lines)


def login_gate(request):
    if request.GET.get("logout") == "1":
        request.session.pop("radar_unlocked", None)

    if request.session.get("radar_unlocked"):
        return redirect("dashboard")

    error = None
    easter_song = None

    if request.method == "POST":
        password = (request.POST.get("password") or "").strip()

        if not password:
            error = _empty_password_error()
        elif password == RADAR_PASSWORD:
            request.session["radar_unlocked"] = True
            return redirect("dashboard")
        elif password.lower() == "joseamorim":
            easter_song = "joseamorim"
            error = "Password errada. Mas desbloqueaste a jukebox secreta."
        else:
            error = _cool_password_error()

    if not request.session.get("login_anim_anchor"):
        request.session["login_anim_anchor"] = time.time()

    elapsed = max(0.0, time.time() - float(request.session.get("login_anim_anchor", time.time())))
    walker_delay_roam = f"-{elapsed % 13:.3f}s"
    walker_delay_hop = f"-{elapsed % 1.15:.3f}s"
    walker_delay_tilt = f"-{elapsed % 1.7:.3f}s"

    return render(
        request,
        "concursos/login.html",
        {
            "error": error,
            "easter_song": easter_song,
            "walker_elapsed": elapsed,
            "walker_delay_roam": walker_delay_roam,
            "walker_delay_hop": walker_delay_hop,
            "walker_delay_tilt": walker_delay_tilt,
        },
    )


def logout_view(request):
    request.session.pop("radar_unlocked", None)
    return redirect("login_gate")


def about(request):
    if not request.session.get("radar_unlocked"):
        return redirect("login_gate")

    return render(request, "concursos/about.html", {"current_year": datetime.now().year})


def dashboard(request):
    if not request.session.get("radar_unlocked"):
        return redirect("login_gate")
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "todas")
    status = request.GET.get("status", "todos")
    min_score = int(request.GET.get("min_score", 20) or 20)
    max_score = int(request.GET.get("max_score", 100) or 100)
    min_score = max(0, min(100, min_score))
    max_score = max(0, min(100, max_score))
    if min_score > max_score:
        min_score, max_score = max_score, min_score

    sort_by = request.GET.get("sort_by", "score")
    sort_order = request.GET.get("sort_order", "desc")

    qs = Opportunity.objects.filter(relevance_score__gte=min_score, relevance_score__lte=max_score)

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

    new_until = datetime.now(timezone.utc) - timedelta(days=7)
    for item in sliced_items:
        item.is_new = False
        raw_seen = getattr(item, "first_seen_at", None)
        if raw_seen:
            try:
                seen_dt = datetime.fromisoformat(str(raw_seen).replace("Z", "+00:00"))
                if seen_dt.tzinfo is None:
                    seen_dt = seen_dt.replace(tzinfo=timezone.utc)
                item.is_new = seen_dt >= new_until
            except Exception:
                item.is_new = False

    return render(
        request,
        "concursos/dashboard.html",
        {
            "items": sliced_items,
            "q": q,
            "selected_category": category,
            "selected_status": status,
            "min_score": min_score,
            "max_score": max_score,
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
