from django.urls import path

from . import bench_views as views

urlpatterns = [
    path("allowed/", views.allowed),
    path("blocked/", views.blocked),
    path("distinct/", views.distinct),
    path("mode/", views.mode),
]
