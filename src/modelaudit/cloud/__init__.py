"""Cloud pipeline for the audit engine.

The audit logic in modelaudit.checks is unchanged. This package wraps it so the same code runs:
- locally (LocalStore + SqliteSink + RuleExplainer), with no Azure account, for development and tests;
- in Azure (BlobStore + AzureSqlSink + AzureOpenAIExplainer), inside an Azure Function.

Azure SDKs are imported lazily, so the local path needs only the base dependencies.
"""

from modelaudit.cloud.pipeline import BatchOutcome, process_batch

__all__ = ["BatchOutcome", "process_batch"]
