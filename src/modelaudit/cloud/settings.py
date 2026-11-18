"""Builds the Azure pipeline pieces from app settings (environment variables).

In the Function App these are set by azure/infra/main.bicep. Secrets are never stored here:
AZURE_OPENAI_API_KEY is a Key Vault reference, @Microsoft.KeyVault(SecretUri=...), which the
platform resolves using the Function's managed identity. Storage and SQL use the managed
identity directly and need no secret at all.

    AUDIT_STORAGE_ACCOUNT_URL   https://<account>.blob.core.windows.net
    AUDIT_SQL_SERVER            <server>.database.windows.net
    AUDIT_SQL_DATABASE          auditdb
    AUDIT_SQL_AUTH              ActiveDirectoryMSI (default) or ActiveDirectoryDefault on your PC
    AZURE_OPENAI_ENDPOINT       https://<resource>.openai.azure.com   (optional)
    AZURE_OPENAI_DEPLOYMENT     gpt-4.1-mini                          (optional)
    AZURE_OPENAI_API_KEY        Key Vault reference                    (optional; Entra ID if empty)
"""

from __future__ import annotations

import os


def _env(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise RuntimeError(f"App setting {name} is not set")
    return value or None


def azure_components():
    from modelaudit.cloud.explain import make_explainer
    from modelaudit.cloud.sinks import AzureSqlSink
    from modelaudit.cloud.store import BlobStore

    store = BlobStore(_env("AUDIT_STORAGE_ACCOUNT_URL"))
    sink = AzureSqlSink(_env("AUDIT_SQL_SERVER"), _env("AUDIT_SQL_DATABASE"),
                        _env("AUDIT_SQL_AUTH", False) or "ActiveDirectoryMSI")
    explainer = make_explainer(_env("AZURE_OPENAI_ENDPOINT", False), _env("AZURE_OPENAI_DEPLOYMENT", False),
                               _env("AZURE_OPENAI_API_KEY", False))
    return store, sink, explainer
