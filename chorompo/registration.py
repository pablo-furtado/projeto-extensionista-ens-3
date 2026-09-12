from django.core import signing

from .models import Company

REGISTRATION_SALT = "chorompo.initial-administrator"
REGISTRATION_MAX_AGE = 3600


def registration_token(company):
    return signing.dumps({"company_id": company.pk, "email": company.email}, salt=REGISTRATION_SALT)


def load_registration_company(token):
    data = signing.loads(token, salt=REGISTRATION_SALT, max_age=REGISTRATION_MAX_AGE)
    return Company.objects.filter(pk=data["company_id"], email=data["email"], memberships__isnull=True).first()


def company_from_token(token):
    try:
        return load_registration_company(token)
    except (signing.BadSignature, TypeError):
        return None
