"""
IT Office Service - Platform Strategy & Infrastructure

Responsible for:
- Platform integrations and social channel management
- Identity, access control, and security operations
- Infrastructure automation and technical systems
- Credential vault and secure connection management
"""
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any

from fastapi import FastAPI

app = FastAPI(title="IT Office", version="1.0.0")

# ============================================================================
# IT Sub-Agents (Rebel Alliance Infrastructure Team)
# ============================================================================

class ITSubAgent:
    agent_name = "IT Specialist"
    agent_role = "Technician"
    agent_source = "internal"
    description = ""

    def identity(self) -> dict[str, str]:
        return {
            "name": self.agent_name,
            "role": self.agent_role,
            "source": self.agent_source,
            "description": self.description,
        }


class PlatformIntegrationAgent(ITSubAgent):
    agent_name = "Sabine Wren"
    agent_role = "Platform Integration Lead"
    description = "Manages social platform connectors, credential linking, and publishing infrastructure setup."


class SecurityOpsAgent(ITSubAgent):
    agent_name = "Zeb Orrelios"
    agent_role = "Security & Compliance Lead"
    description = "Oversees identity management, access control, and security compliance for all integrated systems."


class InfrastructureAgent(ITSubAgent):
    agent_name = "Chopper"
    agent_role = "Infrastructure Automation"
    description = "Handles automated deployment, system health monitoring, and infrastructure scaling."


class IdentityAccessAgent(ITSubAgent):
    agent_name = "Tristan Wren"
    agent_role = "Identity & Access Manager"
    description = "Manages credential vaults, access policies, and identity verification for all office integrations."


# ============================================================================
# IT Office Director
# ============================================================================

class ITOfficeDirector:
    def __init__(self):
        self.name = "Kanan Jarrus"
        self.role = "IT Director"
        self.teams = ["Platform Integration", "Security Ops", "Infrastructure", "Identity & Access"]
        self._platform_agent = PlatformIntegrationAgent()
        self._security_agent = SecurityOpsAgent()
        self._infrastructure_agent = InfrastructureAgent()
        self._identity_agent = IdentityAccessAgent()

    def roster(self) -> dict[str, Any]:
        return {
            "director": {"name": self.name, "role": self.role},
            "sub_agents": [
                self._platform_agent.identity(),
                self._security_agent.identity(),
                self._infrastructure_agent.identity(),
                self._identity_agent.identity(),
            ],
        }

    def get_status(self):
        return {
            "manager": self.name,
            "role": self.role,
            "teams": self.teams,
            "status": "online",
            "task_director": "enabled",
            "sub_agent_count": 4,
        }

    def automated_task_router(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Director-level automatic delegation to IT sub-agents."""
        if action == "platform_integration":
            return {
                "status": "success",
                "delegated_to": self._platform_agent.identity(),
                "message": "Platform integration request queued for Sabine Wren",
            }

        if action == "security_compliance":
            return {
                "status": "success",
                "delegated_to": self._security_agent.identity(),
                "message": "Security compliance review queued for Zeb Orrelios",
            }

        if action == "infrastructure_automation":
            return {
                "status": "success",
                "delegated_to": self._infrastructure_agent.identity(),
                "message": "Infrastructure automation task queued for Chopper",
            }

        if action == "identity_access":
            return {
                "status": "success",
                "delegated_to": self._identity_agent.identity(),
                "message": "Identity & access request queued for Tristan Wren",
            }

        return {"status": "unknown_action", "action": action}


it_director = ITOfficeDirector()

# ============================================================================
# REST Endpoints - Director & Team
# ============================================================================

@app.get("/status")
async def get_status():
    """Return IT Office status and director info."""
    return it_director.get_status()


@app.get("/team")
async def get_team():
    """Return Kanan Jarrus' full IT team roster."""
    return it_director.roster()


@app.post("/automated-task")
async def automated_task(action: str, payload: dict[str, Any] | None = None):
    """Automated task routing from the orchestrator."""
    return it_director.automated_task_router(action, payload or {})

SOCIAL_SECURE_METHODS = ["oauth2-app", "oauth2-device", "api-token"]
CREATIVE_SECURE_METHODS = ["api-key", "service-account"]
DEFAULT_SECURE_METHOD_BY_CATEGORY = {
    "social-platform": "oauth2-app",
    "creative-api": "api-key",
}
VAULT_REF_PATTERN = re.compile(r"^vault://[a-z0-9][a-z0-9._/-]*$")

# Scopes that MUST be present for a secure link to succeed (enforced server-side).
PLATFORM_REQUIRED_SCOPES: dict[str, list[str]] = {
    "x": ["read", "write"],
    "instagram": ["content.write"],
    "snapchat": ["profile", "content.write"],
    "linkedin": ["w_member_social"],
    "tiktok": ["video.upload"],
    "facebook": ["pages_manage_posts"],
    "meshy": ["model.generate"],
}

INTEGRATION_CATALOG = {
    "x": {
        "name": "X",
        "aliases": ["twitter", "tweet"],
        "category": "social-platform",
        "publish_capable": True,
        "credential_scope": "social",
    },
    "instagram": {
        "name": "Instagram",
        "aliases": ["insta", "ig"],
        "category": "social-platform",
        "publish_capable": True,
        "credential_scope": "social",
    },
    "linkedin": {
        "name": "LinkedIn",
        "aliases": [],
        "category": "social-platform",
        "publish_capable": True,
        "credential_scope": "social",
    },
    "tiktok": {
        "name": "TikTok",
        "aliases": ["tik tok"],
        "category": "social-platform",
        "publish_capable": True,
        "credential_scope": "social",
    },
    "facebook": {
        "name": "Facebook",
        "aliases": ["fb"],
        "category": "social-platform",
        "publish_capable": True,
        "credential_scope": "social",
    },
    "snapchat": {
        "name": "Snapchat",
        "aliases": ["snap", "sc"],
        "category": "social-platform",
        "publish_capable": True,
        "credential_scope": "social",
    },
    "meshy": {
        "name": "Meshy AI API",
        "aliases": ["meshy ai", "meshy api"],
        "category": "creative-api",
        "publish_capable": False,
        "credential_scope": "ai",
    },
}
IT_TASK_CATALOG = [
    {
        "id": "social-media-integration",
        "name": "Social media integration",
        "description": "Validate required publishing platforms, link missing accounts, and confirm secure credential references.",
    },
    {
        "id": "publish-connectors",
        "name": "Publish connector execution",
        "description": "Execute approved posting workflows through linked social connectors and keep audit logs.",
    },
    {
        "id": "integration-audit",
        "name": "Integration audit",
        "description": "List active integrations, review link coverage, and report missing platforms before launch.",
    },
    {
        "id": "token-tracking",
        "name": "Token and credential tracking",
        "description": "Track vault-backed credential references without storing raw secrets in workflow payloads.",
    },
    {
        "id": "meshy-api-integration",
        "name": "Meshy AI API integration",
        "description": "Link Meshy AI API credentials for creative tooling workflows using vault-style secret references.",
    },
    {
        "id": "generate-3d-model",
        "name": "3D model generation workflow",
        "description": "Generate Meshy-backed 3D model job artifacts for downstream review and publishing pipelines.",
    },
    {
        "id": "shenanigans-lab",
        "name": "Shenanigans lab",
        "description": "Run safe experimental, mixed-media automations that require cross-office coordination.",
    },
]


class ITOfficeManager:
    def __init__(self):
        self.name = "IT Manager Agent"
        self.teams = ["Platform Integrations", "Identity", "Security Operations", "Automation"]
        self.output_root = self._resolve_output_root()
        self.integrations_file = self._resolve_integrations_file()
        self.catalog_file = self._resolve_catalog_file()
        self.custom_catalog = self._load_custom_catalog()
        self.integrations = self._load_integrations()

    def _resolve_output_root(self) -> Path:
        configured = os.getenv("IT_OUTPUT_ROOT", "").strip()
        if configured:
            root = Path(configured)
        else:
            root = (Path(__file__).resolve().parent / "../../data-output/it-office").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _resolve_integrations_file(self) -> Path:
        explicit = os.getenv("IT_INTEGRATIONS_FILE", "").strip()
        if explicit:
            path = Path(explicit)
        else:
            path = self.output_root / "integrations.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _resolve_catalog_file(self) -> Path:
        explicit = os.getenv("IT_INTEGRATION_CATALOG_FILE", "").strip()
        if explicit:
            path = Path(explicit)
        else:
            path = self.output_root / "integration-catalog.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _load_integrations(self) -> dict:
        if not self.integrations_file.exists():
            return {}
        try:
            return json.loads(self.integrations_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_integrations(self) -> None:
        self.integrations_file.write_text(json.dumps(self.integrations, indent=2), encoding="utf-8")

    def _load_custom_catalog(self) -> dict:
        if not self.catalog_file.exists():
            return {}
        try:
            payload = json.loads(self.catalog_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(payload, dict):
            return {}

        cleaned = {}
        for integration_id, definition in payload.items():
            if not isinstance(definition, dict):
                continue
            normalized_id = self._normalize_integration_id(integration_id)
            if not normalized_id:
                continue
            cleaned[normalized_id] = {
                "name": (definition.get("name") or normalized_id.replace("-", " ").title()).strip(),
                "aliases": self._normalize_aliases(definition.get("aliases") or []),
                "category": (definition.get("category") or "custom").strip().lower(),
                "publish_capable": bool(definition.get("publish_capable")),
                "credential_scope": (definition.get("credential_scope") or "integrations").strip().lower(),
                "custom": True,
            }
        return cleaned

    def _save_custom_catalog(self) -> None:
        self.catalog_file.write_text(json.dumps(self.custom_catalog, indent=2), encoding="utf-8")

    def _catalog(self) -> dict:
        merged = dict(INTEGRATION_CATALOG)
        merged.update(self.custom_catalog)
        # Annotate each built-in integration with its required scopes so the
        # orchestrator and UI can surface them without a separate call.
        result = {}
        for integration_id, definition in merged.items():
            entry = dict(definition)
            if integration_id in PLATFORM_REQUIRED_SCOPES:
                entry["required_scopes"] = PLATFORM_REQUIRED_SCOPES[integration_id]
            else:
                entry["required_scopes"] = []
            result[integration_id] = entry
        return result

    def _normalize_integration_id(self, integration_id: str) -> str:
        value = re.sub(r"[^a-z0-9_-]+", "-", (integration_id or "").strip().lower())
        return value.strip("-")

    def _normalize_aliases(self, aliases: list) -> list[str]:
        normalized = []
        for alias in aliases:
            value = (alias or "").strip().lower()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    def _default_publish_targets(self) -> list[str]:
        catalog = self._catalog()
        targets = []
        for integration_id, integration in self.integrations.items():
            definition = catalog.get(integration_id) or {}
            if not definition.get("publish_capable"):
                continue
            if definition.get("category") != "social-platform":
                continue
            targets.append(integration_id)
        return sorted(targets)

    def _normalize_platform(self, platform: str) -> str:
        value = (platform or "").strip().lower()
        if not value:
            return value

        catalog = self._catalog()

        if value in catalog:
            return value

        for integration_id, definition in catalog.items():
            aliases = definition.get("aliases") or []
            if value in aliases:
                return integration_id

        return value

    def _get_integration_definition(self, platform: str) -> dict | None:
        normalized = self._normalize_platform(platform)
        return self._catalog().get(normalized)

    def _slugify(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip().lower())
        cleaned = cleaned.strip("-")
        return cleaned or "default"

    def _default_account_name(self, platform: str) -> str:
        normalized = self._normalize_platform(platform)
        return f"agentic-{normalized}-publisher"

    def _default_credential_ref(self, platform: str, account_name: str) -> str:
        normalized = self._normalize_platform(platform)
        definition = self._get_integration_definition(normalized) or {}
        scope = definition.get("credential_scope", "integrations")
        account_slug = self._slugify(account_name)
        return f"vault://{scope}/{normalized}/{account_slug}"

    def _supported_secure_methods(self, integration_id: str) -> list[str]:
        definition = self._get_integration_definition(integration_id) or {}
        category = (definition.get("category") or "").strip().lower()
        if category == "social-platform":
            return list(SOCIAL_SECURE_METHODS)
        if category == "creative-api":
            return list(CREATIVE_SECURE_METHODS)
        return ["api-key"]

    def _default_secure_method(self, integration_id: str) -> str:
        definition = self._get_integration_definition(integration_id) or {}
        category = (definition.get("category") or "").strip().lower()
        return DEFAULT_SECURE_METHOD_BY_CATEGORY.get(category, "api-key")

    def _normalize_scopes(self, scopes: list | None) -> list[str]:
        normalized = []
        for scope in scopes or []:
            value = (scope or "").strip().lower()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    def _validate_credential_ref(self, credential_ref: str) -> tuple[bool, str]:
        value = (credential_ref or "").strip().lower()
        if not value:
            return False, "Credential reference is required"
        if not VAULT_REF_PATTERN.match(value):
            return False, "Credential reference must use vault:// format"
        return True, "ok"

    def _create_output_job_folder(self, prefix: str) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        folder = self.output_root / prefix / timestamp
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _extract_requested_integrations(self, instruction: str, request_data: dict | None = None, workflow_context: dict | None = None) -> list[str]:
        request_data = request_data or {}
        workflow_context = workflow_context or {}
        catalog = self._catalog()

        integrations = []
        explicit_integrations = (
            request_data.get("integrations")
            or request_data.get("platforms")
            or request_data.get("providers")
            or []
        )
        for integration in explicit_integrations:
            normalized = self._normalize_platform(integration)
            if normalized in catalog and normalized not in integrations:
                integrations.append(normalized)

        workflow_steps = workflow_context.get("workflow") or []
        for step in workflow_steps:
            stage_data = ((step or {}).get("stage_response") or {}).get("data") or {}
            for integration in (stage_data.get("recommended_integrations") or stage_data.get("recommended_platforms") or []):
                normalized = self._normalize_platform(integration)
                if normalized in catalog and normalized not in integrations:
                    integrations.append(normalized)

        text = (instruction or "").lower()
        padded_text = f" {text} "
        for integration_id, definition in catalog.items():
            tokens = [integration_id] + list(definition.get("aliases") or [])
            if any(token in padded_text for token in tokens):
                if integration_id not in integrations:
                    integrations.append(integration_id)

        return integrations

    def _extract_requested_platforms(self, instruction: str, request_data: dict | None = None, workflow_context: dict | None = None) -> list[str]:
        requested = self._extract_requested_integrations(instruction, request_data, workflow_context)
        catalog = self._catalog()
        return [
            integration_id
            for integration_id in requested
            if (catalog.get(integration_id) or {}).get("publish_capable")
        ]

    def get_status(self):
        catalog = self._catalog()
        return {
            "manager": self.name,
            "teams": self.teams,
            "linked_platforms": sorted(list(self.integrations.keys())),
            "supported_integrations": sorted(list(catalog.keys())),
            "integrations_file": str(self.integrations_file),
            "catalog_file": str(self.catalog_file),
            "output_root": str(self.output_root),
            "tasks": IT_TASK_CATALOG,
        }

    def list_tasks(self) -> dict:
        return {"status": "success", "tasks": IT_TASK_CATALOG}

    def list_integration_catalog(self) -> dict:
        catalog = self._catalog()
        return {
            "status": "success",
            "catalog": catalog,
            "custom_count": len(self.custom_catalog),
        }

    def add_integration_definition(self, request_data: dict | None = None) -> dict:
        request_data = request_data or {}
        integration_id = self._normalize_integration_id(
            request_data.get("integration") or request_data.get("platform") or request_data.get("id") or ""
        )
        if not integration_id:
            return {"status": "error", "message": "Integration id is required"}

        if integration_id in INTEGRATION_CATALOG:
            return {
                "status": "error",
                "message": f"Integration '{integration_id}' already exists as a built-in provider",
            }

        aliases = self._normalize_aliases(request_data.get("aliases") or [])
        category = (request_data.get("category") or "social-platform").strip().lower()
        credential_scope = (request_data.get("credential_scope") or "social").strip().lower()
        definition = {
            "name": (request_data.get("name") or integration_id.replace("-", " ").title()).strip(),
            "aliases": aliases,
            "category": category,
            "publish_capable": bool(request_data.get("publish_capable", True)),
            "credential_scope": credential_scope,
            "custom": True,
        }
        self.custom_catalog[integration_id] = definition
        self._save_custom_catalog()
        return {
            "status": "success",
            "integration": integration_id,
            "definition": definition,
            "catalog": self._catalog(),
        }

    def link_integration(
        self,
        integration: str,
        account_name: str = "",
        credential_ref: str = "",
        connection_method: str = "",
        security_level: str = "",
        secure_connection: bool = False,
        scopes: list | None = None,
    ) -> dict:
        normalized = self._normalize_platform(integration)
        definition = self._get_integration_definition(normalized)
        if not definition:
            return {"status": "error", "message": f"Unsupported integration: {integration}"}

        resolved_account_name = account_name or self._default_account_name(normalized)
        resolved_credential_ref = credential_ref or self._default_credential_ref(normalized, resolved_account_name)
        ref_ok, ref_message = self._validate_credential_ref(resolved_credential_ref)
        if not ref_ok:
            return {"status": "error", "message": ref_message}

        resolved_method = (connection_method or "").strip().lower()
        if not resolved_method:
            resolved_method = self._default_secure_method(normalized) if secure_connection else "standard-vault-link"

        supported_methods = self._supported_secure_methods(normalized)
        if secure_connection and resolved_method not in supported_methods:
            return {
                "status": "error",
                "message": f"Unsupported secure connection method '{resolved_method}' for {normalized}",
                "supported_methods": supported_methods,
            }

        normalized_scopes = self._normalize_scopes(scopes)
        is_secure = bool(secure_connection or resolved_method != "standard-vault-link")
        self.integrations[normalized] = {
            "account_name": resolved_account_name,
            "credential_ref": resolved_credential_ref,
            "linked_at": datetime.utcnow().isoformat(),
            "status": "linked-secure" if is_secure else "linked",
            "category": definition.get("category"),
            "publish_capable": bool(definition.get("publish_capable")),
            "display_name": definition.get("name", normalized.title()),
            "secure_connection": is_secure,
            "connection_method": resolved_method,
            "security_level": (security_level or ("high" if is_secure else "standard")).strip().lower(),
            "token_strategy": "vault-reference-only",
            "scopes": normalized_scopes,
            "verified_at": datetime.utcnow().isoformat() if is_secure else None,
            "last_security_check": "pass" if is_secure else "not-run",
        }
        self._save_integrations()

        return {
            "status": "success",
            "platform": normalized,
            "integration": self.integrations[normalized],
        }

    def secure_link_integration(
        self,
        integration: str,
        account_name: str = "",
        credential_ref: str = "",
        connection_method: str = "",
        scopes: list | None = None,
    ) -> dict:
        normalized = self._normalize_platform(integration)
        definition = self._get_integration_definition(normalized)
        if not definition:
            return {"status": "error", "message": f"Unsupported integration: {integration}"}

        resolved_method = (connection_method or self._default_secure_method(normalized)).strip().lower()
        supported_methods = self._supported_secure_methods(normalized)
        if resolved_method not in supported_methods:
            return {
                "status": "error",
                "message": f"Unsupported secure connection method '{resolved_method}' for {normalized}",
                "supported_methods": supported_methods,
            }

        # Enforce per-platform required scopes before proceeding.
        provided_scopes = self._normalize_scopes(scopes)
        required_scopes = PLATFORM_REQUIRED_SCOPES.get(normalized, [])
        missing_scopes = [s for s in required_scopes if s not in provided_scopes]
        if missing_scopes:
            return {
                "status": "error",
                "message": f"Missing required scopes for {normalized}: {missing_scopes}",
                "required_scopes": required_scopes,
                "missing_required_scopes": missing_scopes,
                "provided_scopes": provided_scopes,
            }

        result = self.link_integration(
            integration=normalized,
            account_name=account_name,
            credential_ref=credential_ref,
            connection_method=resolved_method,
            security_level="high",
            secure_connection=True,
            scopes=scopes,
        )
        if result.get("status") != "success":
            return result

        return {
            **result,
            "security_profile": {
                "supported_methods": supported_methods,
                "selected_method": resolved_method,
                "vault_only_credentials": True,
                "transport": "tls-required",
            },
        }

    def link_platform(self, platform: str, account_name: str = "", credential_ref: str = "") -> dict:
        return self.secure_link_integration(platform, account_name, credential_ref)

    def unlink_platform(self, platform: str) -> dict:
        normalized = self._normalize_platform(platform)
        if normalized not in self.integrations:
            return {"status": "error", "message": f"Platform not linked: {platform}"}

        removed = self.integrations.pop(normalized)
        self._save_integrations()
        return {"status": "success", "platform": normalized, "removed": removed}

    def list_integrations(self) -> dict:
        return {
            "status": "success",
            "integrations": self.integrations,
            "linked_count": len(self.integrations),
            "catalog": self._catalog(),
            "default_publish_targets": self._default_publish_targets(),
        }

    def validate_integration_request(
        self,
        instruction: str,
        request_data: dict | None = None,
        workflow_context: dict | None = None,
    ) -> dict:
        request_data = request_data or {}
        workflow_context = workflow_context or {}
        requested_integrations = self._extract_requested_integrations(instruction, request_data, workflow_context)
        catalog = self._catalog()
        if not requested_integrations:
            return {
                "status": "error",
                "message": "No supported integrations found. Mention social platforms or Meshy AI API.",
                "data": {"tasks": IT_TASK_CATALOG, "catalog": catalog},
            }

        credential_refs = request_data.get("credential_refs") or {}
        account_names = request_data.get("account_names") or {}

        existing_integrations = []
        newly_linked = []
        link_results = []
        credential_refs_used = {}

        for integration_id in requested_integrations:
            if integration_id in self.integrations:
                existing_integrations.append(integration_id)
                credential_refs_used[integration_id] = self.integrations[integration_id].get("credential_ref", "not-set")
                continue

            account_name = account_names.get(integration_id) or self._default_account_name(integration_id)
            credential_ref = credential_refs.get(integration_id) or self._default_credential_ref(integration_id, account_name)
            link_result = self.secure_link_integration(
                integration=integration_id,
                account_name=account_name,
                credential_ref=credential_ref,
                connection_method=request_data.get("connection_method", ""),
                scopes=request_data.get("scopes") or [],
            )
            link_results.append(link_result)
            if link_result.get("status") == "success":
                newly_linked.append(integration_id)
                credential_refs_used[integration_id] = credential_ref

        ready_integrations = [integration_id for integration_id in requested_integrations if integration_id in self.integrations]
        missing_integrations = [integration_id for integration_id in requested_integrations if integration_id not in ready_integrations]

        return {
            "status": "success" if not missing_integrations else "blocked",
            "data": {
                "requested_integrations": requested_integrations,
                "ready_integrations": ready_integrations,
                "missing_integrations": missing_integrations,
                "existing_integrations": existing_integrations,
                "newly_linked": newly_linked,
                "link_results": link_results,
                "credential_refs_used": credential_refs_used,
                "security_mode": "vault-reference-only",
                "tasks": IT_TASK_CATALOG,
                "catalog": catalog,
            },
        }

    def validate_publish_request(
        self,
        instruction: str,
        request_data: dict | None = None,
        workflow_context: dict | None = None,
    ) -> dict:
        request_data = request_data or {}
        workflow_context = workflow_context or {}
        integration_check = self.validate_integration_request(instruction, request_data, workflow_context)
        if integration_check.get("status") == "error":
            return integration_check

        publish_target_mode = (request_data.get("publish_target_mode") or "").strip().lower()
        requested_platforms = []
        if publish_target_mode == "all-linked-social":
            requested_platforms = self._default_publish_targets()

        if not requested_platforms:
            requested_platforms = self._extract_requested_platforms(instruction, request_data, workflow_context)

        if not requested_platforms:
            return {
                "status": "error",
                "message": "No supported platforms found to validate. Mention X, Instagram, LinkedIn, TikTok, Facebook, or Snapchat.",
                "data": {"tasks": IT_TASK_CATALOG, "catalog": self._catalog()},
            }

        ready_platforms = [platform for platform in requested_platforms if platform in self.integrations]
        missing_platforms = [platform for platform in requested_platforms if platform not in ready_platforms]

        return {
            "status": "success" if not missing_platforms else "blocked",
            "data": {
                "requested_platforms": requested_platforms,
                "ready_platforms": ready_platforms,
                "missing_platforms": missing_platforms,
                "requested_integrations": integration_check["data"].get("requested_integrations", []),
                "ready_integrations": integration_check["data"].get("ready_integrations", []),
                "missing_integrations": integration_check["data"].get("missing_integrations", []),
                "existing_integrations": integration_check["data"].get("existing_integrations", []),
                "newly_linked": integration_check["data"].get("newly_linked", []),
                "link_results": integration_check["data"].get("link_results", []),
                "credential_refs_used": integration_check["data"].get("credential_refs_used", {}),
                "security_mode": "vault-reference-only",
                "tasks": IT_TASK_CATALOG,
                "catalog": self._catalog(),
                "publish_target_mode": publish_target_mode or "explicit-or-inferred",
                "default_publish_targets": self._default_publish_targets(),
            },
        }

    def generate_3d_model_job(
        self,
        instruction: str,
        request_data: dict | None = None,
        workflow_context: dict | None = None,
    ) -> dict:
        request_data = dict(request_data or {})
        workflow_context = workflow_context or {}

        requested_integrations = request_data.get("integrations") or []
        if "meshy" not in [self._normalize_platform(item) for item in requested_integrations]:
            request_data["integrations"] = list(requested_integrations) + ["meshy"]

        integration_check = self.validate_integration_request(
            instruction,
            request_data=request_data,
            workflow_context=workflow_context,
        )
        if integration_check.get("status") != "success":
            return integration_check

        output_format = (request_data.get("output_format") or "glb").strip().lower()
        style = (request_data.get("style") or "stylized").strip().lower()
        poly_budget = int(request_data.get("poly_budget") or 60000)
        model_prompt = (request_data.get("model_prompt") or instruction or "3D asset request").strip()

        job_dir = self._create_output_job_folder("meshy-jobs")
        job_id = f"meshy-job-{job_dir.name}"

        request_payload = {
            "job_id": job_id,
            "engine": "meshy-ai-api",
            "instruction": instruction,
            "model_prompt": model_prompt,
            "style": style,
            "output_format": output_format,
            "poly_budget": poly_budget,
            "requested_at": datetime.utcnow().isoformat(),
            "status": "queued",
            "security_mode": "vault-reference-only",
            "integrations": integration_check["data"].get("ready_integrations", []),
            "credential_refs": integration_check["data"].get("credential_refs_used", {}),
        }

        request_file = job_dir / "model-request.json"
        request_file.write_text(json.dumps(request_payload, indent=2), encoding="utf-8")

        preview_file = job_dir / "preview-instructions.txt"
        preview_file.write_text(
            "Meshy job queued. Generate preview render once upstream worker executes this request.",
            encoding="utf-8",
        )

        return {
            "status": "success",
            "data": {
                "workflow": "it-3d-meshy-generation",
                "job_id": job_id,
                "engine": "meshy-ai-api",
                "artifact_folder": str(job_dir),
                "artifact_files": [request_file.name, preview_file.name],
                "recommended_integrations": ["meshy"],
                "ready_integrations": integration_check["data"].get("ready_integrations", []),
                "credential_refs_used": integration_check["data"].get("credential_refs_used", {}),
                "model_request": {
                    "prompt": model_prompt,
                    "style": style,
                    "output_format": output_format,
                    "poly_budget": poly_budget,
                },
            },
        }

    def publish_posts(self, posts: list[str], platforms: list[str], artifact_folder: str = "") -> dict:
        normalized_platforms = [self._normalize_platform(p) for p in platforms if (p or "").strip()]
        if not normalized_platforms:
            normalized_platforms = self._default_publish_targets()

        catalog = self._catalog()
        unsupported = [
            p
            for p in normalized_platforms
            if p not in catalog or not (catalog.get(p) or {}).get("publish_capable")
        ]
        if unsupported:
            return {"status": "error", "message": f"Unsupported platforms requested: {unsupported}"}

        if not normalized_platforms:
            return {
                "status": "error",
                "message": "No linked publish-capable social integrations are available.",
                "hint": "Link at least one social integration before publishing.",
            }

        missing_links = [p for p in normalized_platforms if p not in self.integrations]
        if missing_links:
            return {
                "status": "blocked",
                "message": "Some platforms are not linked yet",
                "missing_links": missing_links,
                "hint": "Link platforms in IT office before publishing",
            }

        publish_time = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        publish_dir = self.output_root / "publish-logs" / publish_time
        publish_dir.mkdir(parents=True, exist_ok=True)

        records = []
        for idx, post in enumerate(posts, start=1):
            record = {
                "post_number": idx,
                "platforms": normalized_platforms,
                "post_preview": (post or "").strip()[:200],
                "published_at": datetime.utcnow().isoformat(),
                "artifact_folder": artifact_folder,
                "status": "queued",
            }
            records.append(record)

        record_path = publish_dir / "publish-records.json"
        record_path.write_text(json.dumps(records, indent=2), encoding="utf-8")

        return {
            "status": "success",
            "published_count": len(records),
            "platforms": normalized_platforms,
            "publish_log_folder": str(publish_dir),
            "publish_log_file": str(record_path),
        }

    def handle_message(self, instruction: str) -> dict:
        text = (instruction or "").strip().lower()
        integrations = self._extract_requested_integrations(instruction)

        if any(token in text for token in ["link", "connect", "integrate"]):
            if not integrations:
                return {
                    "status": "error",
                    "message": "No supported integration found in instruction. Mention social platforms or Meshy AI API.",
                }
            linked = [self.secure_link_integration(integration_id) for integration_id in integrations]
            return {"status": "success", "action": "link", "results": linked}

        if "list" in text and "integration" in text:
            return self.list_integrations()

        if "catalog" in text or "supported" in text:
            return self.list_integration_catalog()

        if "list" in text and "task" in text:
            return self.list_tasks()

        return {
            "status": "success",
            "message": "IT office ready. Ask to link platforms (for example: link X and Instagram).",
            "integrations": self.integrations,
            "tasks": IT_TASK_CATALOG,
        }


manager = ITOfficeManager()


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "office": "it",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/manager")
async def get_manager():
    return manager.get_status()


@app.get("/tasks")
async def get_tasks():
    return manager.list_tasks()


@app.get("/integrations")
async def get_integrations():
    return manager.list_integrations()


@app.get("/integrations/catalog")
async def get_integration_catalog():
    return manager.list_integration_catalog()


@app.post("/integrations/catalog/add")
async def add_integration_catalog_item(request: dict):
    return manager.add_integration_definition(request)


@app.post("/integrations/link")
async def link_integration(request: dict):
    platform = request.get("platform") or request.get("integration") or request.get("provider") or ""
    account_name = request.get("account_name", "")
    credential_ref = request.get("credential_ref", "")
    return manager.secure_link_integration(
        integration=platform,
        account_name=account_name,
        credential_ref=credential_ref,
        connection_method=request.get("connection_method", ""),
        scopes=request.get("scopes") or [],
    )


@app.post("/integrations/link-secure")
async def secure_link_integration(request: dict):
    platform = request.get("platform") or request.get("integration") or request.get("provider") or ""
    account_name = request.get("account_name", "")
    credential_ref = request.get("credential_ref", "")
    connection_method = request.get("connection_method", "")
    scopes = request.get("scopes") or []
    return manager.secure_link_integration(platform, account_name, credential_ref, connection_method, scopes)


@app.post("/integrations/unlink")
async def unlink_integration(request: dict):
    platform = request.get("platform") or request.get("integration") or request.get("provider") or ""
    return manager.unlink_platform(platform)


@app.post("/publish")
async def publish(request: dict):
    posts = request.get("posts") or []
    platforms = request.get("platforms") or []
    artifact_folder = request.get("artifact_folder", "")
    return manager.publish_posts(posts, platforms, artifact_folder)


@app.post("/handle-request")
async def handle_request(request: dict):
    action = request.get("action")

    if action == "message":
        workflow_role = request.get("workflow_role", "")
        instruction = request.get("instruction", "")
        request_data = request.get("data") or {}
        workflow_context = request.get("workflow_context") or request_data.get("workflow_context") or {}

        if workflow_role == "integration-reviewer":
            if request_data.get("platforms"):
                return manager.validate_publish_request(instruction, request_data, workflow_context)
            return manager.validate_integration_request(instruction, request_data, workflow_context)

        if workflow_role == "creator":
            lower_instruction = (instruction or "").lower()
            if any(token in lower_instruction for token in ["3d", "meshy", "render", "model", ".glb", ".obj"]):
                return manager.generate_3d_model_job(instruction, request_data, workflow_context)

        return {"status": "success", "data": manager.handle_message(instruction)}

    if action == "link_platform":
        return manager.secure_link_integration(
            request.get("platform") or request.get("integration") or request.get("provider") or "",
            request.get("account_name", ""),
            request.get("credential_ref", ""),
            request.get("connection_method", ""),
            request.get("scopes") or [],
        )

    if action == "link_integration":
        return manager.secure_link_integration(
            request.get("platform") or request.get("integration") or request.get("provider") or "",
            request.get("account_name", ""),
            request.get("credential_ref", ""),
            request.get("connection_method", ""),
            request.get("scopes") or [],
        )

    if action == "link_integration_secure":
        return manager.secure_link_integration(
            request.get("platform") or request.get("integration") or request.get("provider") or "",
            request.get("account_name", ""),
            request.get("credential_ref", ""),
            request.get("connection_method", ""),
            request.get("scopes") or [],
        )

    if action == "list_integrations":
        return manager.list_integrations()

    if action == "list_integration_catalog":
        return manager.list_integration_catalog()

    if action == "add_integration":
        return manager.add_integration_definition(request.get("data") or request)

    if action == "list_tasks":
        return manager.list_tasks()

    if action == "validate_publish_ready":
        return manager.validate_publish_request(
            request.get("instruction", ""),
            request.get("data") or {},
            request.get("workflow_context") or {},
        )

    if action == "validate_integration_ready":
        return manager.validate_integration_request(
            request.get("instruction", ""),
            request.get("data") or {},
            request.get("workflow_context") or {},
        )

    if action == "generate_3d_model":
        return manager.generate_3d_model_job(
            request.get("instruction", ""),
            request.get("data") or {},
            request.get("workflow_context") or {},
        )

    if action == "publish_posts":
        return manager.publish_posts(
            request.get("posts") or [],
            request.get("platforms") or [],
            request.get("artifact_folder", ""),
        )

    return {"status": "unknown_action"}


@app.get("/")
async def root():
    return {
        "service": "IT Office",
        "version": "1.0.0",
        "tasks": IT_TASK_CATALOG,
        "catalog": manager._catalog(),
        "description": "Platform integrations, creative APIs, and publishing connectors",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
