"""Context Runtime Interface (CxRI) — Definition 3.5.

The standard adapter between the orchestration layer and context stores.
Every context source implements six operations.
"""

from context_kubernetes.cxri.interface import CxRIConnector, ConnectionConfig, HealthStatus

__all__ = ["CxRIConnector", "ConnectionConfig", "HealthStatus"]
