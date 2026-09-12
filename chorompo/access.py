from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

from .group_permission import has_permission
from .models import CompanyMembership


def clinic_required(permission=None, *, onboarding=False):
    def decorator(view):
        @never_cache
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            memberships = CompanyMembership.objects.select_related("company", "user").filter(
                user=request.user, is_active=True, user__is_active=True,
            )
            company_id = request.session.get("active_company_id")
            membership = memberships.filter(company_id=company_id).first() if company_id else memberships.order_by("pk").first()
            if membership is None:
                raise PermissionDenied("Sua conta não possui acesso ativo a esta clínica.")
            request.membership = membership
            request.company = membership.company
            request.session["active_company_id"] = membership.company_id
            if permission and not has_permission(membership, permission):
                raise PermissionDenied("Seu perfil não tem acesso a este módulo.")
            if not onboarding and not request.company.onboarding_completed:
                return redirect("chorompo:onboarding")
            return view(request, *args, **kwargs)
        return wrapped
    return decorator
