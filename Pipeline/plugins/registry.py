"""
plugins/registry.py
--------------------
DocumentRegistry — the single place you register a document type.

To add a new document type:
    registry.register("commercial_invoice", InvoiceAdapter, InvoiceConfig())

That is it. Nothing else changes.

DocumentRegistry.default() returns a registry pre-loaded with all
built-in document types. It is the standard way to get a ready-to-use registry.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from adapters.base_adapter import BaseDocumentAdapter
    from configs.base_config import ExtractionConfig


class _Entry:
    def __init__(self, adapter_cls, config):
        self.adapter_cls = adapter_cls
        self.config      = config

    def instantiate(self):
        return self.adapter_cls(), self.config


class DocumentRegistry:
    """
    Maps doc_type string → (AdapterClass, Config instance).

    Usage
    -----
        registry = DocumentRegistry.default()
        registry.register("commercial_invoice", InvoiceAdapter, InvoiceConfig())
        adapter, config = registry.get("commercial_invoice")
    """

    def __init__(self):
        self._entries: Dict[str, _Entry] = {}

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def register(
        self,
        doc_type: str,
        adapter_cls: Type["BaseDocumentAdapter"],
        config: Optional["ExtractionConfig"] = None,
        *,
        override: bool = False,
    ) -> "DocumentRegistry":
        """
        Register a document type.

        Args:
            doc_type:    unique key, e.g. "purchase_order"
            adapter_cls: the adapter CLASS (not an instance)
            config:      config instance — if None, uses ExtractionConfig defaults
            override:    set True to replace an existing registration

        Returns:
            self (for fluent chaining)
        """
        if doc_type in self._entries and not override:
            raise ValueError(
                f"'{doc_type}' already registered. "
                f"Pass override=True to replace it."
            )
        from configs.base_config import ExtractionConfig
        self._entries[doc_type] = _Entry(
            adapter_cls,
            config or ExtractionConfig(doc_type=doc_type),
        )
        return self

    # ------------------------------------------------------------------ #
    # Lookup
    # ------------------------------------------------------------------ #

    def get(
        self,
        doc_type: str,
        config_override: Optional["ExtractionConfig"] = None,
    ) -> Tuple["BaseDocumentAdapter", "ExtractionConfig"]:
        """Return a fresh (adapter_instance, config) pair."""
        if doc_type not in self._entries:
            raise KeyError(
                f"'{doc_type}' not registered. "
                f"Available: {self.list()}"
            )
        adapter, config = self._entries[doc_type].instantiate()
        return adapter, (config_override or config)

    def list(self) -> list:
        """Return all registered doc_type keys."""
        return list(self._entries.keys())

    def has(self, doc_type: str) -> bool:
        return doc_type in self._entries

    def unregister(self, doc_type: str) -> None:
        """Remove a registration (useful in tests)."""
        self._entries.pop(doc_type, None)

    # ------------------------------------------------------------------ #
    # Built-in defaults
    # ------------------------------------------------------------------ #

    @classmethod
    def default(cls) -> "DocumentRegistry":
        """
        Return a registry pre-loaded with all built-in document types.
        This is the standard way to create a ready-to-use registry.

        Built-in types:
            purchase_order   — Li & Fung Placement Memorandum
            shipping_bill    — Indian Customs Shipping Bill
        """
        from adapters.purchase_order_adapter import PurchaseOrderAdapter
        from adapters.shipping_bill_adapter  import ShippingBillAdapter
        from configs.purchase_order_config   import PurchaseOrderConfig
        from configs.shipping_bill_config    import ShippingBillConfig

        r = cls()
        r.register("purchase_order", PurchaseOrderAdapter, PurchaseOrderConfig())
        r.register("shipping_bill",  ShippingBillAdapter,  ShippingBillConfig())
        return r

    # Keep backward-compat alias
    with_defaults = default
