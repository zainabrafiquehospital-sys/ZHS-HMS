"""Fixed configuration-as-code for the Authentication module: password
policy thresholds and a bundled common-password denylist.

The denylist is intentionally a small, hardcoded set of the most
frequently breached/guessed passwords rather than an external API call
(e.g. HaveIBeenPwned) or a large bundled wordlist dependency — a
security-critical login path in a healthcare system should not depend on
a third-party network call succeeding, and a few hundred entries catches
the overwhelming majority of trivially guessable passwords that satisfy
the length/character-class rules below."""

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
PASSWORD_REQUIRED_CHARACTER_CLASSES = 3  # of: upper, lower, digit, symbol

# A representative sample of the most common passwords/patterns found in
# real-world breach corpora, normalized to lowercase for comparison.
COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password123",
        "123456789012",
        "1234567890123",
        "qwertyuiop12",
        "letmein12345",
        "welcome12345",
        "admin1234567",
        "administrator",
        "changeme12345",
        "iloveyou1234",
        "sunshine1234",
        "princess1234",
        "football1234",
        "baseball1234",
        "dragon123456",
        "monkey123456",
        "master123456",
        "superman1234",
        "trustno1trust",
        "hospital12345",
        "hospital123",
        "healthcare123",
        "gynecology123",
        "p@ssw0rd12345",
        "p@ssword1234",
        "passw0rd12345",
        "qwerty1234567",
        "abc123456789",
        "letmein123456",
        "welcome123456",
        "zxcvbnm123456",
        "123456abcdef",
        "abcdef123456",
        "aaaaaaaaaaaa",
        "111111111111",
        "000000000000",
    }
)

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

# User Management (Phase 5 Step 2) — permission codes, following the
# `<group>:<action>` convention app/modules/auth/models.py's `Permission`
# docstring already establishes (e.g. `patients:create`). Centralized here
# rather than as string literals in user_router.py so every call site
# (router, tests) references the same constant instead of a
# hand-typed string that could silently drift out of sync.
PERMISSION_USERS_CREATE = "users:create"
PERMISSION_USERS_READ = "users:read"
PERMISSION_USERS_UPDATE = "users:update"
PERMISSION_USERS_DELETE = "users:delete"
PERMISSION_USERS_MANAGE_STATUS = "users:manage_status"
PERMISSION_USERS_MANAGE_PASSWORD = "users:manage_password"
PERMISSION_USERS_MANAGE_ROLES = "users:manage_roles"

# Role Management (Phase 5 Step 3) — same convention as PERMISSION_USERS_*.
PERMISSION_ROLES_CREATE = "roles:create"
PERMISSION_ROLES_READ = "roles:read"
PERMISSION_ROLES_UPDATE = "roles:update"
PERMISSION_ROLES_DELETE = "roles:delete"

# Role <-> Permission Assignment (Phase 5 Step 5) — a dedicated code,
# separate from PERMISSION_ROLES_UPDATE, mirroring how
# PERMISSION_USERS_MANAGE_ROLES (Phase 5 Step 2) is dedicated and
# separate from PERMISSION_USERS_UPDATE. This is the single most
# security-sensitive permission code in the system: holding it lets an
# actor grant any permission to any role, then (via the existing
# users:manage_roles-gated endpoints) assign that role to any user — a
# full privilege-escalation chain in two API calls. It should be held
# only by a super-admin-equivalent role in any real deployment.
PERMISSION_ROLES_MANAGE_PERMISSIONS = "roles:manage_permissions"

# Permission Management (Phase 5 Step 4) — same convention as PERMISSION_USERS_*.
PERMISSION_PERMISSIONS_CREATE = "permissions:create"
PERMISSION_PERMISSIONS_READ = "permissions:read"
PERMISSION_PERMISSIONS_UPDATE = "permissions:update"
PERMISSION_PERMISSIONS_DELETE = "permissions:delete"

# Matches Permission.group's column length (String(50)) — a permission
# code's group prefix (the text before its `:`) can never exceed this,
# since `group` is always derived directly from `code`; see
# validators.validate_permission_code / derive_permission_group.
PERMISSION_GROUP_MAX_LENGTH = 50

# Length of a system-generated temporary password (Create User, Admin
# Reset Password) — comfortably above PASSWORD_MIN_LENGTH so the
# character-class-diversity retry loop in
# PasswordService.generate_temporary_password virtually never needs more
# than one attempt.
TEMPORARY_PASSWORD_LENGTH = 20
