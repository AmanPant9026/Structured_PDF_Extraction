"""
run_purchase_order.py
----------------------
End-to-end Purchase Order extraction.

Inputs (what the user provides — nothing else is needed or accepted):
  --input-json  merged_pages.json                    (OCR JSON)
  --input-md    merged_purchase_order.md             (Markdown)
  --template    purchase_order_v1_null_template.json (output shape)

That is it. No GT file. No schema file. No API keys.
LLM: Qwen2.5:32b via Ollama (Apache 2.0, runs locally).

Usage
-----
python run_purchase_order.py \\
    --input-md   data/sample/merged_purchase_order.md \\
    --input-json data/sample/merged_pages.json \\
    --template   schemas/purchase_order_v1_null_template.json \\
    --output     output/purchase_order_result.json

# MD only:
python run_purchase_order.py \\
    --input-md data/sample/merged_purchase_order.md

# Validate inputs (no LLM, no cost):
python run_purchase_order.py \\
    --input-md data/sample/merged_purchase_order.md --dry-run

# See page structure:
python run_purchase_order.py \\
    --input-md data/sample/merged_purchase_order.md --inspect

# Smaller model:
python run_purchase_order.py \\
    --input-md data/sample/merged_purchase_order.md --model qwen2.5:14b
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loaders.merged_pages_loader import load_merged_pages, inspect_merged_pages
from loaders.merged_md_loader    import load_merged_md, inspect_merged_md
from loaders.template_loader     import load_template, introspect_template
from helpers.schema_helpers       import fill_rate_report
from configs.purchase_order_config import PurchaseOrderConfig
from adapters.purchase_order_adapter import PurchaseOrderAdapter
from plugins.registry import DocumentRegistry
from core.pipeline import ExtractionPipeline
from core.ollama_extractor import OllamaExtractor
from core.cache import CacheManager
from core.evidence import build_evidence_store
from core.schema_parser import parse_schema_dict


# ──────────────────────────────────────────────────────────────────────────── #
# CLI
# ──────────────────────────────────────────────────────────────────────────── #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Purchase Order extractor\n"
            "Inputs: pred JSON + pred MD + null template  →  filled JSON\n"
            "Model:  Qwen2.5:32b via Ollama (Apache 2.0, local, no API key)"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--input-md",   default=None,
                   help="merged_purchase_order.md  (<!-- PAGE N --> format)")
    p.add_argument("--input-json", default=None,
                   help="merged_pages.json  (glmocr_pages_merge_v1 format)")
    p.add_argument("--template",   default=None,
                   help="Null output template  "
                        "(default: schemas/purchase_order_v1_null_template.json)")
    p.add_argument("--output",     default=None,
                   help="Output JSON path  (default: output/purchase_order_result.json)")
    p.add_argument("--model",      default="qwen2.5:32b",
                   help="Ollama model tag  (default: qwen2.5:32b, Apache 2.0)")
    p.add_argument("--ollama-url", default="http://localhost:11434",
                   help="Ollama server URL  (default: http://localhost:11434)")
    p.add_argument("--no-cache",   action="store_true",
                   help="Disable LLM response cache")
    p.add_argument("--dry-run",    action="store_true",
                   help="Build evidence store only — no LLM calls")
    p.add_argument("--inspect",    action="store_true",
                   help="Print page + template structure and exit")
    p.add_argument("--log-dir",    default="logs/",
                   help="Log directory  (default: logs/)")
    return p


# ──────────────────────────────────────────────────────────────────────────── #
# Main
# ──────────────────────────────────────────────────────────────────────────── #

def main() -> int:
    args = _build_parser().parse_args()
    base = Path(__file__).parent

    if not args.input_md and not args.input_json:
        print("[ERROR] Provide --input-md or --input-json (or both)", file=sys.stderr)
        return 1

    # ── Resolve template path ─────────────────────────────────────────── #
    template_path = Path(args.template) if args.template else (
                        base / "schemas" / "purchase_order_v1_null_template.json")
    if not template_path.exists():
        print(f"[ERROR] Template not found: {template_path}", file=sys.stderr)
        return 1

    output_path = args.output or str(base / "output" / "purchase_order_result.json")

    # ── --inspect ─────────────────────────────────────────────────────── #
    if args.inspect:
        if args.input_md:
            print("=== MD file ===")
            inspect_merged_md(args.input_md)
        if args.input_json:
            print("\n=== JSON file ===")
            inspect_merged_pages(args.input_json)
        print("\n=== Template ===")
        introspect_template(load_template(str(template_path)))
        return 0

    # ── Load inputs ───────────────────────────────────────────────────── #
    json_pages, markdown = _load_inputs(args)
    print(f"[INFO] Pages loaded        : {len(json_pages)}")
    print(f"[INFO] Total OCR blocks    : {sum(len(p) for p in json_pages)}")
    print(f"[INFO] Markdown length     : {len(markdown):,} chars")

    template = load_template(str(template_path))
    print(f"[INFO] Template            : {template_path.name}")
    print(f"[INFO] Template sections   : {[k for k in template if not k.startswith('_')]}")

    schema = _schema_from_template(template)

    # ── --dry-run ─────────────────────────────────────────────────────── #
    if args.dry_run:
        store  = build_evidence_store(json_pages, markdown)
        parsed = parse_schema_dict(schema)
        print(f"\n[DRY-RUN] Evidence blocks  : {len(store)}")
        print(f"[DRY-RUN] Schema leaves    : {sum(1 for _ in parsed.all_leaves())}")
        print(f"[DRY-RUN] Model            : {args.model}  @  {args.ollama_url}")
        print("[DRY-RUN] No LLM calls made.")
        return 0

    # ── Build extractor ───────────────────────────────────────────────── #
    cache = CacheManager(
        cache_dir=str(base / ".cache" / "extractions"),
        enabled=not args.no_cache,
    )
    extractor = OllamaExtractor(
        base_url    = args.ollama_url,
        model       = args.model,
        temperature = 0.0,
        max_tokens  = 1024,
        cache       = cache,
    )

    # ── Build registry ────────────────────────────────────────────────── #
    config = PurchaseOrderConfig()
    config.extra["template_path"] = str(template_path)
    if args.no_cache:
        config.enable_cache = False

    registry = DocumentRegistry()
    registry.register("purchase_order", PurchaseOrderAdapter, config)

    # ── Run pipeline ──────────────────────────────────────────────────── #
    pipeline = ExtractionPipeline(
        registry  = registry,
        extractor = extractor,
        log_dir   = args.log_dir,
    )

    print(f"[INFO] Model               : {args.model}  @  {args.ollama_url}")
    print(f"[INFO] Running extraction …\n")

    result = pipeline.run(
        doc_type    = "purchase_order",
        json_pages  = json_pages,
        markdown    = markdown,
        schema      = schema,
        output_path = output_path,
    )

    # ── Report ────────────────────────────────────────────────────────── #
    _print_report(result, output_path, template)
    return 0 if result.is_valid else 2


# ──────────────────────────────────────────────────────────────────────────── #
# Helpers
# ──────────────────────────────────────────────────────────────────────────── #

def _load_inputs(args) -> tuple:
    """Load and merge json_pages + markdown from provided inputs."""
    if args.input_md and args.input_json:
        print(f"[INFO] Loading JSON  : {args.input_json}")
        json_pages, _ = load_merged_pages(
            args.input_json,
            md_separator="\n\n---PAGE_BREAK---\n\n",
        )
        print(f"[INFO] Loading MD    : {args.input_md}")
        _, markdown = load_merged_md(args.input_md, tc_page=15)
        return json_pages, markdown
    elif args.input_md:
        print(f"[INFO] Loading MD    : {args.input_md}")
        return load_merged_md(args.input_md, tc_page=15)
    else:
        print(f"[INFO] Loading JSON  : {args.input_json}")
        return load_merged_pages(
            args.input_json,
            md_separator="\n\n---PAGE_BREAK---\n\n",
        )


def _schema_from_template(template: dict) -> dict:
    """
    Derive a minimal pipeline-compatible schema directly from the null template.
    The template is the single source of truth for output shape.
    No GT or external schema file is used.
    """
    header_fields = {
        k: {"type": "string",
            "required": k in ("Supplier", "Buyer", "PMNo", "Date"),
            "description": k}
        for k in template.get("Header", {})
    }
    footer_fields = {
        k: {"type": "string", "required": False, "description": k}
        for k in template.get("Footer", {})
    }
    rw_proto = (template.get("RowWiseTable") or [{}])[0]
    rw_item_fields = {
        k: {"type": "string", "required": k == "ShipNo"}
        for k in rw_proto
    }
    return {
        "document_type": "purchase_order",
        "version": "2.0",
        "fields": {
            "Header":       {"type": "object", "fields": header_fields},
            "Footer":       {"type": "object", "fields": footer_fields},
            "RowWiseTable": {
                "type": "list",
                "list_root": True,
                "description": "Shipment schedule rows",
                "items": rw_item_fields,
            },
        },
    }


def _print_report(result, output_path: str, template: dict) -> None:
    data = result.data
    print(f"\n{'='*60}")
    print(f"  Extraction complete")
    print(f"  Valid        : {result.is_valid}")
    print(f"  Validation   : {result.validation_summary}")
    print(f"  Elapsed      : {result.elapsed_seconds}s")
    print(f"  Saved to     : {output_path}")
    print()

    # Fill-rate report (template-driven, no GT)
    report = fill_rate_report(data, template)
    for section, info in report.items():
        if section == "RowWiseTable":
            print(f"  RowWiseTable : {info['rows']} rows extracted")
        elif section == "overall":
            print(f"  Overall fill : {info['filled']}/{info['total']} fields "
                  f"({info['pct']}%)")
        else:
            print(f"  {section:<13}: {info['filled']}/{info['total']} fields filled "
                  f"({info['pct']}%)")

    if result.warnings:
        print(f"\n  Warnings ({len(result.warnings)}):")
        for w in result.warnings[:6]:
            print(f"    • {w}")
        if len(result.warnings) > 6:
            print(f"    … and {len(result.warnings)-6} more (see logs/)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    sys.exit(main())
