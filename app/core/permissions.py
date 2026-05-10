from collections.abc import Callable

from app.core.constants import UserRole
from app.core.dependencies import CurrentUser
from app.core.exceptions import PermissionDeniedError
from app.features.users.models import User


def require_roles(*allowed: UserRole) -> Callable[[User], User]:
    allowed_set = set(allowed)

    def _checker(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_set:
            raise PermissionDeniedError()
        return current_user

    return _checker


require_role = require_roles  # backward-compat alias

require_superadmin = require_roles(UserRole.SUPERADMIN)
require_admin_or_above = require_roles(UserRole.SUPERADMIN, UserRole.ADMIN)
require_manager_or_above = require_roles(
    UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.MANAGER
)
require_any_authenticated = require_roles(
    UserRole.SUPERADMIN, UserRole.ADMIN, UserRole.MANAGER, UserRole.VIEWER
)
