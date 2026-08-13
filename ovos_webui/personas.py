"""Create and edit personas in the format ovos-persona reads.

``ovos_persona.PersonaService.load_personas`` reads every ``*.json`` file in
``get_xdg_config_save_path("ovos_persona")``. The file name is the persona name
unless the file carries a ``name`` key, which wins.

``ovos_persona.Persona.__init__`` needs ``handlers`` or ``solvers``: an ordered
list of solver plugin names, and it must not be empty. Any other top level key
whose name is a plugin name is that plugin's configuration. ``memory_module``
names a memory plugin, and the key with that name holds its configuration.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ovos_utils.log import LOG

from ovos_webui.fsutils import atomic_write, is_within, validate_skill_id

#: Keys that are part of the persona itself, not a plugin configuration block.
#: A persona test call (often an LLM over the network) is given at most this
#: long before the request gives up, so a hung solver cannot pin a worker.
PERSONA_TIMEOUT = 30.0

RESERVED_KEYS = {"name", "solvers", "handlers", "memory_module", "catch_phrase",
                 "description", "ignore_plugin_personas"}


class PersonaError(ValueError):
    """Raised when a persona definition cannot be used."""


def personas_root() -> Path:
    """Return the directory ovos-persona reads user personas from."""
    from ovos_config.locations import get_xdg_config_save_path

    return Path(get_xdg_config_save_path("ovos_persona"))


def persona_path(persona_id: str) -> Path:
    """Return the file of ``persona_id``. The id is a plain file name."""
    validate_skill_id(persona_id)
    root = personas_root()
    path = root / f"{persona_id}.json"
    if not is_within(root, path.parent):
        raise PersonaError("the resolved path is outside the personas directory")
    return path


def available_solvers() -> list[dict[str, str]]:
    """Return the solver plugins installed on this device.

    ``ovos_persona.solvers.get_utterance_handler_plugins`` is the same call
    ``Persona`` uses to decide which plugins it can load, so this list holds
    exactly the names that will work.
    """
    try:
        from ovos_persona.solvers import get_utterance_handler_plugins
        found = get_utterance_handler_plugins() or {}
    except ImportError:
        # ovos-persona is not installed. Fall back to the plugin manager, so a
        # user can still write a persona for a device that will run it later.
        try:
            from ovos_plugin_manager.solvers import (find_chat_solver_plugins,
                                                     find_question_solver_plugins)
            found = {**(find_question_solver_plugins() or {}),
                     **(find_chat_solver_plugins() or {})}
        except Exception as err:  # noqa: BLE001 - a broken plugin is not fatal
            LOG.warning(f"could not list solver plugins: {err}")
            found = {}
    except Exception as err:  # noqa: BLE001 - a broken plugin is not fatal
        LOG.warning(f"could not list solver plugins: {err}")
        found = {}
    return [{"name": name, "doc": (getattr(clazz, "__doc__", "") or "").strip().split("\n")[0]}
            for name, clazz in sorted(found.items())]


def available_memory_plugins() -> list[str]:
    """Return the memory plugins installed on this device."""
    try:
        from ovos_plugin_manager.utils import PluginTypes, find_plugins
        return sorted(find_plugins(PluginTypes.AGENT_MEMORY) or {})
    except Exception as err:  # noqa: BLE001
        LOG.warning(f"could not list memory plugins: {err}")
        return []


def list_personas() -> list[dict[str, Any]]:
    """Return one entry per persona file, sorted by id."""
    root = personas_root()
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for child in sorted(root.glob("*.json")):
        persona_id = child.stem
        try:
            validate_skill_id(persona_id)
        except ValueError:
            continue
        try:
            data = json.loads(child.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            out.append({"persona_id": persona_id, "name": persona_id,
                        "solvers": [], "broken": True})
            continue
        if not isinstance(data, dict):
            out.append({"persona_id": persona_id, "name": persona_id,
                        "solvers": [], "broken": True})
            continue
        out.append({
            "persona_id": persona_id,
            "name": data.get("name") or persona_id,
            "solvers": data.get("handlers") or data.get("solvers") or [],
            "broken": False,
        })
    return out


def read_persona(persona_id: str) -> dict[str, Any]:
    """Return the persona definition of ``persona_id``."""
    path = persona_path(persona_id)
    if not path.is_file():
        raise LookupError(f"there is no persona called {persona_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise PersonaError(f"the persona file is not valid JSON: {err}") from err
    if not isinstance(data, dict):
        raise PersonaError("a persona must be a mapping")
    return data


def validate(data: Any, strict_solvers: bool = False) -> dict[str, Any]:
    """Check ``data`` is a persona ovos-persona can load.

    ``strict_solvers`` also checks that every named solver is installed. That
    is a warning by default, because a user may write a persona for plugins
    they are about to install.
    """
    if not isinstance(data, dict):
        raise PersonaError("a persona must be a mapping")
    solvers = data.get("handlers") or data.get("solvers") or []
    if not isinstance(solvers, list) or not solvers:
        raise PersonaError("a persona must name at least one solver")
    if not all(isinstance(s, str) and s for s in solvers):
        raise PersonaError("every solver must be a name")
    if len(set(solvers)) != len(solvers):
        raise PersonaError("the same solver is named more than once")
    name = data.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise PersonaError("the persona name must not be empty")
    memory = data.get("memory_module")
    if memory is not None and not (isinstance(memory, str) or memory is False):
        raise PersonaError("memory_module must be a plugin name")
    for key, value in data.items():
        if key in RESERVED_KEYS:
            continue
        if not isinstance(value, dict):
            raise PersonaError(
                f"'{key}' should hold the configuration of a plugin, so it must be a mapping")
    if strict_solvers:
        have = {s["name"] for s in available_solvers()}
        missing = [s for s in solvers if s not in have]
        if missing:
            raise PersonaError(f"these solvers are not installed: {', '.join(missing)}")
    return data


def missing_solvers(data: dict[str, Any]) -> list[str]:
    """Return the solvers named in ``data`` that are not installed."""
    have = {s["name"] for s in available_solvers()}
    solvers = data.get("handlers") or data.get("solvers") or []
    return [s for s in solvers if s not in have]


def write_persona(persona_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Write a persona, after checking it. Keeps a backup of the old file."""
    validate(data)
    path = persona_path(persona_id)
    backup = atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))
    return {
        "path": str(path),
        "backup": str(backup) if backup else None,
        "missing_solvers": missing_solvers(data),
    }


def delete_persona(persona_id: str) -> dict[str, Any]:
    """Remove a persona. A backup is kept, so the delete can be undone."""
    from ovos_webui.fsutils import make_backup

    path = persona_path(persona_id)
    if not path.is_file():
        raise LookupError(f"there is no persona called {persona_id}")
    backup = make_backup(path)
    path.unlink(missing_ok=True)
    return {"deleted": str(path), "backup": str(backup) if backup else None}


def try_persona(persona_id: str, question: str) -> dict[str, Any]:
    """Ask one question through a persona, in this process.

    Returns a skipped result when ovos-persona is not installed, so the page
    works on a device that only writes the file for another device to run.
    """
    if not isinstance(question, str) or not question.strip():
        raise PersonaError("write a question first")
    if len(question) > 2000:
        raise PersonaError("the question is too long")
    data = read_persona(persona_id)
    validate(data)
    missing = missing_solvers(data)
    if missing:
        return {"skipped": True,
                "reason": f"these solvers are not installed: {', '.join(missing)}"}
    try:
        from ovos_persona import Persona
    except ImportError:
        return {"skipped": True,
                "reason": "ovos-persona is not installed on this device"}
    try:
        persona = Persona(data.get("name") or persona_id, data)
    except Exception as err:  # noqa: BLE001 - any plugin can fail to load
        raise PersonaError(f"the persona did not load: {err}") from err
    try:
        from ovos_bus_client.session import Session
        from ovos_webui.deadline import run_with_deadline

        def ask():
            session = Session()
            messages = persona.get_messages(question, session)
            return persona.chat(messages, session)

        # A solver (often an LLM over the network) has no timeout of its own;
        # bound it so a hung backend fails the request instead of parking a
        # worker forever.
        answer = run_with_deadline(ask, PERSONA_TIMEOUT, what="the persona")
    except Exception as err:  # noqa: BLE001 - a solver can fail at run time
        raise PersonaError(f"the persona did not answer: {err}") from err
    return {"skipped": False, "answer": answer}
