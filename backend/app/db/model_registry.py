"""Centralized model registry.

This is the single place every feature module's models must be imported so
they register on `Base.metadata` before anything reads it — Alembic
autogenerate (app/db/migrations/env.py imports this module, not
app/db/base.py directly) and the application runtime both rely on that
side effect. Adding a new feature module therefore requires exactly ONE
line here, and nothing else: env.py never needs to change again.

This was originally `app/db/base.py` itself (the `Base` class definition
and this import list lived in the same file), which worked by accident
with exactly one feature module (auth) registered. It breaks with two or
more: `app/shared/base_entity.py` imports `Base` FROM this file's home;
every feature module's `models.py` imports `BaseEntity` FROM
`base_entity`. Whichever feature module happens to be the *first* thing
anything imports (e.g. a test importing `app.modules.auth.models`
directly, or FastAPI's router wiring reaching `auth.models` before
anything else touches the database layer) becomes the entry point into
that cycle — and when `base_entity` is still mid-import (paused on its
own `from app.db.base import Base` line) and this file's import list
reaches a *second* feature module, that module's own
`from app.shared.base_entity import BaseEntity` fails outright: Python
finds `base_entity` already in `sys.modules` (partially initialized, not
yet reached its class definitions) and raises `ImportError` rather than
re-running it. A single-module list never exposed this because
`app/db/base.py`'s own `from app.modules.auth.models import *`
(re-)import of the very module already driving the whole chain is a
no-op-shaped partial star-import that Python tolerates without erroring
— pure accident, not something a second module can also rely on.

Splitting `Base` (zero imports beyond SQLAlchemy) from this list (which
imports every feature module) breaks the cycle structurally: `base_entity`
importing `Base` from `app/db/base.py` never transitively reaches back
into this file, regardless of which feature module happens to be the
first thing imported anywhere in the process.

Each import is `noqa`-marked because the module is imported purely for its
side effect of registering models on Base.metadata — the name is unused.
"""

from app.db.base import Base  # noqa: F401
from app.modules.auth.models import *  # noqa: E402,F401,F403
from app.modules.billing.models import *  # noqa: E402,F401,F403
from app.modules.consultation.models import *  # noqa: E402,F401,F403
from app.modules.inventory.models import *  # noqa: E402,F401,F403
from app.modules.lab.models import *  # noqa: E402,F401,F403
from app.modules.patients.models import *  # noqa: E402,F401,F403
from app.modules.pharmacy.models import *  # noqa: E402,F401,F403
from app.modules.queue.models import *  # noqa: E402,F401,F403
from app.modules.visits.models import *  # noqa: E402,F401,F403
from app.modules.vitals.models import *  # noqa: E402,F401,F403
from app.shared.audit.models import *  # noqa: E402,F401,F403
