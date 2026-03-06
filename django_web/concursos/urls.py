from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_gate, name="login_gate"),
    path("logout/", views.logout_view, name="logout_view"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("update/<int:item_id>/", views.update_item, name="update_item"),
]
