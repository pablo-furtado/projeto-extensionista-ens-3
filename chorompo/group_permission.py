ROLE_PERMISSIONS = {

    "ADMIN": {"patients", "treatments", "appointments", "employees", "finance"},

    "RECEPTION": {"patients", "appointments"},

    "FINANCIAL": {"finance"},

    "PROFESSIONAL": {"patients", "treatments", "appointments"},
}

def has_permission(membership, permission):
    permissions = ROLE_PERMISSIONS.get(
        membership.role,
        set()
    )

    return membership.is_active and membership.user.is_active and permission in permissions
