# Restricted Python Analysis Tool

Status: **implemented** for deterministic structured incident analysis. The implementation is
written in Python but deliberately exposes no Python interpreter, source code, expression,
callable, import, path, URL, filesystem, network, environment, or process-execution interface.

## Architecture and authorization

`PythonAnalysisTool` accepts an immutable `AnalysisRequest` whose operation is an enum and whose
filters and parameters are bounded typed fields. Authorization uses the central
`AuthorizationService` and requires `python_analysis` before dataset construction and again before
execution. Viewers are denied; analysts and administrators may run allowlisted operations. Server
policy—not request parameters or token claims—determines permission.

The service loads only incident entries listed in `data/sample_documents/manifest.json` whose path
is directly under `data/sample_documents/incidents`. It rejects traversal, symlinks, malformed
front matter, hash disagreement, and invalid timestamp ranges. Safe YAML parsing is used. Corpus
authorization is applied before a row is constructed, so inaccessible records never enter the
engine. Security fixtures and arbitrary caller files cannot be selected.

## Operations and rows

Schema version `1.0` supports count, grouped count, top values, severity/status/department/document
distributions, date histograms, duration statistics, recurring root causes, corrective-action
summaries, group comparison, and missing-value summaries. The initial engine uses standard-library
collections, statistics, dates, and immutable Pydantic rows. Work is linear in authorized rows plus
bounded deterministic group sorting. There is no mutable calculation state.

Incident rows contain attribution and structured metadata only: incident/document IDs, title,
classification, roles, department, status, dates, severity, duration, services, root-cause
category, and corrective-action status. Public results never contain document bodies or root-cause
paragraphs.

## Taxonomy, provenance, and limits

Taxonomy version `1.0` centrally maps documented phrase families to connection pools,
certificates, queue backlog, provider timeout, configuration drift, retry storms, database locks,
DNS/service discovery, capacity planning, monitoring gaps, deployment regression, manual error,
other, or unknown. It claims only deterministic rule matching.

Every result records row counts, filters, source document IDs, supporting incident IDs, formula,
algorithm version, taxonomy version where applicable, warnings, and correlation IDs. Defaults cap
rows at 1,000, groups at 100, result items at 50, filter values at 50, distinct values at 500, text
at 2,000 characters, and execution at five seconds. Cancellation propagates.

## Graph, events, memory, and limitations

Deterministic query rules plan supported operations. The executable graph route emits tool
authorization/start/completion events, writes a typed result, creates only a deterministic summary,
then follows ordinary output validation and bounded session memory. Memory stores the safe summary
and supporting public context, never the incident dataset or calculation structures.

Unknown plans and validation/integrity/limit failures fail safely through `handle_failure`; no
fallback widens data scope. There is no LLM planner, recursive research, MCP, human approval, or
general-purpose sandbox. If arbitrary code execution is ever required, it must be a separately
hardened, isolated service with network/filesystem/process controls—not an extension of this tool.
