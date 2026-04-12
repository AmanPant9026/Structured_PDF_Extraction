from pathlib import Path
import re
import argparse


def page_sort_key(path: Path):
    """
    Extract page number from names like:
    page_0001.md
    page_0001/page_0001.md
    """
    matches = re.findall(r"page_(\d+)", str(path))
    if matches:
        return int(matches[-1])
    return float("inf")


def collect_md_files(doc_dir: Path):
    """
    Collect only page-wise markdown files.
    Example matches:
    .../page_0001/page_0001/page_0001.md
    .../page_0002/page_0002/page_0002.md
    """
    md_files = list(doc_dir.rglob("*.md"))

    filtered = []
    for f in md_files:
        if re.search(r"page_\d+\.md$", f.name):
            filtered.append(f)

    filtered = sorted(filtered, key=page_sort_key)
    return filtered


def merge_markdown_files(doc_dir: str, output_file: str = None, add_page_separators: bool = True):
    doc_path = Path(doc_dir)

    if not doc_path.exists():
        raise FileNotFoundError(f"Directory not found: {doc_path}")

    md_files = collect_md_files(doc_path)

    if not md_files:
        raise FileNotFoundError(f"No page markdown files found inside: {doc_path}")

    if output_file is None:
        output_file = doc_path / "merged_output.md"
    else:
        output_file = Path(output_file)

    merged_parts = []

    for i, md_file in enumerate(md_files, start=1):
        content = md_file.read_text(encoding="utf-8").strip()

        if add_page_separators:
            merged_parts.append(f"\n\n<!-- PAGE {i}: {md_file.name} -->\n\n")

        merged_parts.append(content)

    final_text = "\n\n".join(merged_parts).strip() + "\n"
    output_file.write_text(final_text, encoding="utf-8")

    print(f"Found {len(md_files)} markdown files.")
    print(f"Merged file saved to: {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge page-wise markdown files into one markdown file.")
    parser.add_argument(
        "--doc_dir",
        type=str,
        required=True,
        help="Document folder containing page_* markdown outputs"
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Path for merged markdown output file"
    )
    parser.add_argument(
        "--no_page_separators",
        action="store_true",
        help="Do not add page separator comments"
    )

    args = parser.parse_args()

    merge_markdown_files(
        doc_dir=args.doc_dir,
        output_file=args.output_file,
        add_page_separators=not args.no_page_separators
    )