"""
run_shipping_bill.py
---------------------
End-to-end Shipping Bill extraction.
Same framework, different adapter + config + template.

Usage
-----
python run_shipping_bill.py \
    --input-md   data/sample/merged_shipping_bill.md \
    --input-json data/sample/merged_shipping_pages.json \
    --template   schemas/shipping_bill_v1_null_template.json \
    --output     output/shipping_bill_result.json

python run_shipping_bill.py --input-md data/sample/merged_shipping_bill.md --dry-run
python run_shipping_bill.py --input-md data/sample/merged_shipping_bill.md --inspect
"""

from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from loaders.merged_pages_loader import load_merged_pages, inspect_merged_pages
from loaders.merged_md_loader    import load_merged_md, inspect_merged_md
from loaders.template_loader     import load_template, introspect_template
from configs.shipping_bill_config import ShippingBillConfig
from adapters.shipping_bill_adapter import ShippingBillAdapter
from plugins.registry import DocumentRegistry
from core.pipeline import ExtractionPipeline
from core.ollama_extractor import OllamaExtractor
from core.cache import CacheManager
from core.evidence import build_evidence_store
from core.schema_parser import parse_schema_dict


def _parser():
    p = argparse.ArgumentParser(description="Shipping Bill extractor — Template-driven")
    p.add_argument("--input-md",   default=None)
    p.add_argument("--input-json", default=None)
    p.add_argument("--template",   default=None)
    p.add_argument("--output",     default=None)
    p.add_argument("--model",      default="qwen2.5:32b")
    p.add_argument("--ollama-url", default="http://localhost:11434")
    p.add_argument("--no-cache",   action="store_true")
    p.add_argument("--dry-run",    action="store_true")
    p.add_argument("--inspect",    action="store_true")
    p.add_argument("--log-dir",    default="logs/")
    return p


def main() -> int:
    args = _parser().parse_args()
    base = Path(__file__).parent

    if not args.input_md and not args.input_json:
        print("[ERROR] Provide --input-md or --input-json", file=sys.stderr)
        return 1

    template_path = Path(args.template) if args.template else (
                        base / "schemas" / "shipping_bill_v1_null_template.json")
    output_path = args.output or str(base / "output" / "shipping_bill_result.json")

    if not template_path.exists():
        print(f"[ERROR] Template not found: {template_path}", file=sys.stderr)
        return 1

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

    # Load inputs
    json_pages, markdown = _load_inputs(args)
    print(f"[INFO] Pages loaded        : {len(json_pages)}")
    print(f"[INFO] Markdown length     : {len(markdown):,} chars")
    print(f"[INFO] Template            : {template_path.name}")

    # Minimal schema from template
    schema = _schema_from_sb_template(load_template(str(template_path)))

    if args.dry_run:
        store = build_evidence_store(json_pages, markdown)
        parsed = parse_schema_dict(schema)
        print(f"\n[DRY-RUN] EvidenceStore blocks : {len(store)}")
        print(f"[DRY-RUN] Would use model      : {args.model}  @  {args.ollama_url}")
        print("[DRY-RUN] No LLM calls made.")
        return 0

    extractor = OllamaExtractor(
        base_url=args.ollama_url, model=args.model,
        temperature=0.0, max_tokens=1024,
        cache=CacheManager(enabled=not args.no_cache),
    )

    cfg = ShippingBillConfig()
    cfg.extra["template_path"] = str(template_path)

    registry = DocumentRegistry()
    registry.register("shipping_bill", ShippingBillAdapter, cfg)

    pipeline = ExtractionPipeline(registry=registry, extractor=extractor,
                                   log_dir=args.log_dir)
    print(f"[INFO] Model               : {args.model}  @  {args.ollama_url}")
    print("[INFO] Running extraction pipeline …\n")

    result = pipeline.run(
        doc_type="shipping_bill", json_pages=json_pages,
        markdown=markdown, schema=schema, output_path=output_path,
    )

    print(f"\n{'='*60}")
    print(f"  Extraction complete")
    print(f"  Valid     : {result.is_valid}")
    print(f"  Elapsed   : {result.elapsed_seconds}s")
    print(f"  Saved to  : {output_path}")
    if result.warnings:
        for w in result.warnings[:4]:
            print(f"  WARN: {w}")
    print(f"{'='*60}\n")
    return 0 if result.is_valid else 2


def _load_inputs(args):
    if args.input_md and args.input_json:
        jp, _ = load_merged_pages(args.input_json, md_separator="\n\n---PAGE_BREAK---\n\n")
        _, md = load_merged_md(args.input_md, tc_page=99)  # no T&C in SB
        return jp, md
    elif args.input_md:
        return load_merged_md(args.input_md, tc_page=99)
    else:
        return load_merged_pages(args.input_json, md_separator="\n\n---PAGE_BREAK---\n\n")


def _schema_from_sb_template(template: dict) -> dict:
    """Minimal pipeline-compatible schema for shipping bill LLM fields."""
    return {
        "document_type": "shipping_bill",
        "version": "1.0",
        "fields": {
            "sb_no":    {"type": "string", "required": True,  "description": "Shipping Bill Number"},
            "sb_date":  {"type": "string", "required": True,  "description": "Shipping Bill Date"},
            "port_code":{"type": "string", "required": False, "description": "Port Code"},
            "exporter": {"type": "string", "required": False, "description": "Exporter Name"},
        }
    }


if __name__ == "__main__":
    sys.exit(main())
