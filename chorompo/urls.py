from django.urls import path
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views

from . import treatment_views, views

app_name = "chorompo"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="chorompo:company_create", permanent=False)),
    path("empresas/cadastro/", views.company_create, name="company_create"),
    path("cadastro/", views.registration_start, name="registration_start"),
    path("cadastro/confirmar/<str:token>/", views.registration_verify, name="registration_verify"),
    path("cadastro/administrador/", views.administrator_create, name="administrator_create"),
    path("entrar/", auth_views.LoginView.as_view(template_name="chorompo/login.html", redirect_authenticated_user=True), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("integracao/", views.onboarding, name="onboarding"),
    path("plataforma/", views.dashboard, name="dashboard"),
    path("plataforma/pacientes/", views.patients, name="patients"),
    path("plataforma/tratamentos/", treatment_views.catalog, name="treatments"),
    path("plataforma/tratamentos/catalogo/<int:pk>/editar/", treatment_views.catalog_edit, name="treatment_company_edit"),
    path("plataforma/tratamentos/pacientes/", treatment_views.purchases, name="treatment_purchases"),
    path("plataforma/tratamentos/pacientes/<int:pk>/", treatment_views.treatment_detail, name="treatment_detail"),
    path("plataforma/tratamentos/sessoes/<int:pk>/", treatment_views.session_detail, name="session_detail"),
    path("plataforma/agenda/", views.appointments, name="appointments"),
    path("plataforma/funcionarios/", views.employees, name="employees"),
]
