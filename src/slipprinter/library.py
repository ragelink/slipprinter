"""Finding templates: the built-ins, plus your own (which override built-ins of the same name).

Personal templates live outside the repo, in $SLIP_TEMPLATES or
~/.config/slipprinter/templates, so real names and account numbers stay private.
"""

import os
from pathlib import Path

from slipprinter.template import Template, TemplateError, load_template

BUILTIN_DIR = Path(__file__).parent / "templates"
USER_DIR_ENV = "SLIP_TEMPLATES"


def user_dir() -> Path:
    return Path(os.environ.get(USER_DIR_ENV) or Path.home() / ".config" / "slipprinter" / "templates")


def template_paths() -> dict[str, Path]:
    """Template name (file stem) → path. User templates win over built-ins."""
    paths = {}
    for directory in (BUILTIN_DIR, user_dir()):
        if directory.is_dir():
            for path in sorted(directory.glob("*.y*ml")):
                paths[path.stem] = path
    return paths


def get_template(name: str) -> Template:
    paths = template_paths()
    if name not in paths:
        raise TemplateError(f"No template named '{name}'. Available: {', '.join(sorted(paths)) or 'none'}")
    template = load_template(paths[name])
    if template.name != name:
        raise TemplateError(f"{paths[name]}: file is named '{name}' but the template says name: {template.name}")
    return template


def all_templates() -> tuple[list[Template], list[str]]:
    """Every loadable template, plus an error message for each one that isn't."""
    templates, errors = [], []
    for name in template_paths():
        try:
            templates.append(get_template(name))
        except TemplateError as e:
            errors.append(str(e))
    return templates, errors
