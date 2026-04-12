#!/usr/bin/env python3
"""
run.py  —  Universal PDF Extraction Framework Runner
=====================================================

ONE script for ALL document types.
Swap doc type with --doc-type. Everything else stays the same.

Quick start
-----------
  python run.py --doc-type purchase_order \\
                --md   data/sample/merged_purchase_order.md \\
                --json data/sample/merged_pages.json

  python run.py --doc-type shipping_bill \\
                --md   data/sample/merged_shipping_bill.md \\
                --json data/sample/merged_shipping_pages.json

Common flags
------------
  --doc-type   purchase_order | shipping_bill | <any registered type>
  --md         path to merged markdown file  (<!-- PAGE N --> format)
  --json       path to merged_pages.json     (glmocr_pages_merge_v1)
  --template   null-template JSON            (auto-resolved if omitted)
  --output     output JSON path              (auto-resolved if omitted)
  --model      Ollama model tag              (default: qwen2.5:32b)
  --ollama-url Ollama server URL             (default: http://localhost:11434)
  --no-cache   disable LLM response cache
  --dry-run    validate inputs, no LLM calls
  --inspect    show page structure and template shape, then exit
  --list       show all registered document types, then exit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ── bootstrap ────────────────────────────────────────────────────────────── #
_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))


# ──────────────────────────────────────────────────────────────────────────── #
# CLI definition
# ──────────────────────────────────────────────────────────────────────────── #

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python run.py",
        description="PDF Extraction Framework — single runner for all document types",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run.py --doc-type purchase_order "
            "--md data/sample/merged_purchase_order.md\n"
            "  python run.py --doc-type shipping_bill  "
            "--md data/sample/merged_shipping_bill.md --dry-run\n"
            "  python run.py --list\n"
        ),
    )

    # ── What to process ──────────────────────────────────────────────── #
    p.add_argument(
        "--doc-type", "-d",
        default=None,
        metavar="TYPE",
        help="Document type to extract  (e.g. purchase_order, shipping_bill)",
    )

    # ── Inputs ───────────────────────────────────────────────────────── #
    inp = p.add_argument_group("inputs")
    inp.add_argument(
        "--md", "-m",
        default=None,
        dest="md_path",
        metavar="FILE",
        help="Markdown file  (<!-- PAGE N --> format)",
    )
    inp.add_argument(
        "--json", "-j",
        default=None,
        dest="json_path",
        metavar="FILE",
        help="OCR JSON file  (glmocr_pages_merge_v1 format)",
    )
    inp.add_argument(
        "--template", "-t",
        default=None,
        metavar="FILE",
        help="Null-template JSON  (auto-resolved from doc_type if omitted)",
    )

    # ── Output ───────────────────────────────────────────────────────── #
    out = p.add_argument_group("output")
    out.add_argument(
        "--output", "-o",
        default=None,
        metavar="FILE",
        help="Output JSON path  (default: output/<doc_type>_result.json)",
    )

    # ── Model ────────────────────────────────────────────────────────── #
    model = p.add_argument_group("model (Ollama / Qwen2.5 — Apache 2.0)")
    model.add_argument(
        "--model",
        default="qwen2.5:32b",
        metavar="TAG",
        help="Ollama model tag  (default: qwen2.5:32b)\n"
             "Alternatives: qwen2.5:14b  qwen2.5:7b",
    )
    model.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        metavar="URL",
        help="Ollama server URL  (default: http://localhost:11434)",
    )
    model.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable LLM response cache (force fresh calls)",
    )

    # ── Modes ────────────────────────────────────────────────────────── #
    mode = p.add_argument_group("run modes")
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Load + validate inputs, build evidence — no LLM calls made",
    )
    mode.add_argument(
        "--inspect",
        action="store_true",
        help="Print page structure and template shape, then exit",
    )
    mode.add_argument(
        "--list",
        action="store_true",
        help="Print all registered document types and exit",
    )

    # ── Misc ─────────────────────────────────────────────────────────── #
    p.add_argument("--log-dir", default="logs/", metavar="DIR",
                   help="Log directory  (default: logs/)")

    return p


# ──────────────────────────────────────────────────────────────────────────── #
# Main
# ──────────────────────────────────────────────────────────────────────────── #

def main() -> int:
    args = _build_parser().parse_args()

    # ── Lazy imports (faster --help / --list) ─────────────────────────── #
    from plugins.registry import DocumentRegistry
    registry = DocumentRegistry.default()

    # ── --list ────────────────────────────────────────────────────────── #
    if args.list:
        _print_registered(registry)
        return 0

    # ── Validate doc-type ─────────────────────────────────────────────── #
    if not args.doc_type:
        print("[ERROR] --doc-type is required.\n")
        _print_registered(registry)
        return 1

    if not registry.has(args.doc_type):
        print(f"[ERROR] '{args.doc_type}' is not registered.\n")
        _print_registered(registry)
        return 1

    # ── Validate inputs ───────────────────────────────────────────────── #
    if not args.md_path and not args.json_path:
        print("[ERROR] Provide at least --md or --json (or both).")
        return 1

    # ── Resolve paths ─────────────────────────────────────────────────── #
    template_path = _resolve_template(args, registry)
    output_path   = _resolve_output(args)

    if not template_path.exists():
        print(f"[ERROR] Template not found: {template_path}")
        return 1

    # ── --inspect ─────────────────────────────────────────────────────── #
    if args.inspect:
        _run_inspect(args, template_path)
        return 0

    # ── Load inputs ───────────────────────────────────────────────────── #
    json_pages, markdown = _load_inputs(args)
    template = _load_json(template_path)

    _print_banner(args, json_pages, markdown, template_path)

    # ── --dry-run ─────────────────────────────────────────────────────── #
    if args.dry_run:
        return _run_dry(json_pages, markdown, template, args)

    # ── Build extractor ───────────────────────────────────────────────── #
    from core.ollama_extractor import OllamaExtractor
    from core.cache import CacheManager

    extractor = OllamaExtractor(
        base_url    = args.ollama_url,
        model       = args.model,
        temperature = 0.0,
        max_tokens  = 1024,
        cache       = CacheManager(
            cache_dir = str(_HERE / ".cache" / "extractions"),
            enabled   = not args.no_cache,
        ),
    )

    # ── Apply config overrides ────────────────────────────────────────── #
    _, config = registry.get(args.doc_type)
    config.extra["template_path"] = str(template_path)
    if args.no_cache:
        config.enable_cache = False
    registry.register(
        args.doc_type,
        registry._entries[args.doc_type].adapter_cls,
        config,
        override=True,
    )

    # ── Run pipeline ──────────────────────────────────────────────────── #
    from core.pipeline import ExtractionPipeline

    pipeline = ExtractionPipeline(
        registry  = registry,
        extractor = extractor,
        log_dir   = args.log_dir,
    )

    schema = _schema_from_template(template)
    result = pipeline.run(
        doc_type    = args.doc_type,
        json_pages  = json_pages,
        markdown    = markdown,
        schema      = schema,
        output_path = str(output_path),
    )

    _print_result(result, output_path)
    return 0 if result.is_valid else 2


# ──────────────────────────────────────────────────────────────────────────── #
# Input loading
# ──────────────────────────────────────────────────────────────────────────── #

def _load_inputs(args):
    """Load markdown and/or JSON inputs. Combine when both provided."""
    from loaders.merged_md_loader    import load_merged_md
    from loaders.merged_pages_loader import load_merged_pages

    # TC page cutoff: shipping_bill has no T&C pages; purchase_order strips at 15
    tc_page = _tc_page_for(args.doc_type)

    if args.md_path and args.json_path:
        print(f"[INFO] Loading OCR JSON : {args.json_path}")
        jp, _ = load_merged_pages(
            args.json_path,
            md_separator="\n\n---PAGE_BREAK---\n\n",
        )
        print(f"[INFO] Loading Markdown : {args.md_path}")
        _, md = load_merged_md(args.md_path, tc_page=tc_page)
        return jp, md

    elif args.md_path:
        print(f"[INFO] Loading Markdown : {args.md_path}")
        return load_merged_md(args.md_path, tc_page=tc_page)

    else:
        print(f"[INFO] Loading OCR JSON : {args.json_path}")
        return load_merged_pages(
            args.json_path,
            md_separator="\n\n---PAGE_BREAK---\n\n",
        )


def _tc_page_for(doc_type: str) -> int:
    """Return tc_page cutoff for merged_md_loader."""
    # T&C pages by doc type:
    _TC = {
        "purchase_order": 15,   # pages 15+ are General T&C
        "shipping_bill":  99,   # no T&C pages
    }
    return _TC.get(doc_type, 99)


# ──────────────────────────────────────────────────────────────────────────── #
# Path resolution
# ──────────────────────────────────────────────────────────────────────────── #

def _resolve_template(args, registry) -> Path:
    """
    Template resolution order:
      1. --template flag (explicit path)
      2. config.extra["template_path"]
      3. schemas/<doc_type>_v1_null_template.json
    """
    if args.template:
        return Path(args.template)

    _, config = registry.get(args.doc_type)
    if config.get("template_path"):
        return _HERE / config.get("template_path")

    return _HERE / "schemas" / f"{args.doc_type}_v1_null_template.json"


def _resolve_output(args) -> Path:
    if args.output:
        return Path(args.output)
    out_dir = _HERE / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{args.doc_type}_result.json"


# ──────────────────────────────────────────────────────────────────────────── #
# Schema derivation (no GT needed)
# ──────────────────────────────────────────────────────────────────────────── #

def _schema_from_template(template: dict) -> dict:
    """
    Build a minimal pipeline-compatible schema from the null template.

    The schema only tells the pipeline which scalar fields to ask the LLM for.
    The output SHAPE is entirely determined by the template + adapter.finalize().
    """
    doc_type = (template.get("schema_version") or "unknown").replace("_v1", "")

    # Collect top-level scalar leaf keys as LLM targets
    fields: dict = {}

    def _walk(obj: dict, prefix: str = "") -> None:
        for k, v in obj.items():
            if k.startswith("_") or k in ("schema_version", "source"):
                continue
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _walk(v, path)
            elif isinstance(v, list):
                pass  # lists are handled rule-based by adapter
            else:
                # leaf scalar — register as LLM extraction target
                fields[k] = {"type": "string", "required": False,
                              "description": k}

    _walk(template)

    return {
        "document_type": doc_type,
        "version": "1.0",
        "fields": fields if fields else {
            "doc_id": {"type": "string", "required": False}
        },
    }


# ──────────────────────────────────────────────────────────────────────────── #
# Inspect mode
# ──────────────────────────────────────────────────────────────────────────── #

def _run_inspect(args, template_path: Path) -> None:
    from loaders.merged_md_loader    import inspect_merged_md
    from loaders.merged_pages_loader import inspect_merged_pages
    from loaders.template_loader     import introspect_template, load_template

    if args.md_path:
        print(f"\n{'─'*50}")
        print(f"  Markdown: {args.md_path}")
        print(f"{'─'*50}")
        inspect_merged_md(args.md_path)

    if args.json_path:
        print(f"\n{'─'*50}")
        print(f"  OCR JSON: {args.json_path}")
        print(f"{'─'*50}")
        inspect_merged_pages(args.json_path)

    print(f"\n{'─'*50}")
    print(f"  Template: {template_path.name}")
    print(f"{'─'*50}")
    introspect_template(load_template(str(template_path)))


# ──────────────────────────────────────────────────────────────────────────── #
# Dry run
# ──────────────────────────────────────────────────────────────────────────── #

def _run_dry(json_pages, markdown, template, args) -> int:
    from core.evidence    import build_evidence_store
    from core.schema_parser import parse_schema_dict

    store  = build_evidence_store(json_pages, markdown)
    schema = _schema_from_template(template)
    parsed = parse_schema_dict(schema)

    print(f"\n{'─'*50}")
    print(f"  DRY-RUN — no LLM calls made")
    print(f"{'─'*50}")
    print(f"  Evidence blocks : {len(store)}")
    print(f"  Schema fields   : {sum(1 for _ in parsed.all_leaves())}")
    print(f"  List roots      : {[lr.name for lr in parsed.list_roots]}")
    print(f"  Model (unused)  : {args.model}  @  {args.ollama_url}")
    print(f"{'─'*50}\n")
    print("  Inputs are valid. Ready to run.")
    return 0


# ──────────────────────────────────────────────────────────────────────────── #
# Print helpers
# ──────────────────────────────────────────────────────────────────────────── #

def _print_banner(args, json_pages, markdown, template_path: Path) -> None:
    print(f"\n{'═'*56}")
    print(f"  PDF Extraction Framework")
    print(f"  Document type  : {args.doc_type}")
    print(f"  Model          : {args.model}  @  {args.ollama_url}")
    print(f"  Pages loaded   : {len(json_pages)}")
    print(f"  Markdown       : {len(markdown):,} chars")
    print(f"  Template       : {template_path.name}")
    print(f"{'═'*56}\n")


def _print_result(result, output_path: Path) -> None:
    data = result.data
    print(f"\n{'═'*56}")
    print(f"  Extraction complete")
    print(f"  Valid          : {result.is_valid}")
    print(f"  Validation     : {result.validation_summary}")
    print(f"  Elapsed        : {result.elapsed_seconds}s")
    print(f"  Output         : {output_path}")

    # Quick fill summary — works for any template shape
    filled = _count_filled(data)
    total  = _count_all(data)
    pct    = 100 * filled / total if total else 0
    print(f"  Fields filled  : {filled}/{total} ({pct:.0f}%)")

    if result.warnings:
        print(f"\n  Warnings ({len(result.warnings)}):")
        for w in result.warnings[:5]:
            print(f"    • {w}")
        if len(result.warnings) > 5:
            print(f"    … and {len(result.warnings)-5} more (see logs/)")
    print(f"{'═'*56}\n")


def _print_registered(registry) -> None:
    types = registry.list()
    print(f"\nRegistered document types ({len(types)}):\n")
    for t in types:
        print(f"    {t}")
    print(f"\nUsage:  python run.py --doc-type <TYPE> --md <FILE>\n")


def _count_filled(obj, _depth=0) -> int:
    if _depth > 8:
        return 0
    if isinstance(obj, dict):
        return sum(_count_filled(v, _depth+1) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_filled(i, _depth+1) for i in obj)
    return 0 if obj is None else 1


def _count_all(obj, _depth=0) -> int:
    if _depth > 8:
        return 0
    if isinstance(obj, dict):
        return sum(_count_all(v, _depth+1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return 1
        return sum(_count_all(i, _depth+1) for i in obj)
    return 1


# ──────────────────────────────────────────────────────────────────────────── #
# Utility
# ──────────────────────────────────────────────────────────────────────────── #

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────────────────── #
# Entry point
# ──────────────────────────────────────────────────────────────────────────── #

if __name__ == "__main__":
    sys.exit(main())
