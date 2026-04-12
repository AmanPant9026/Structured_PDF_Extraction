"""
adapters/purchase_order_adapter.py
------------------------------------
Purchase Order (Li & Fung Placement Memorandum) adapter.

Extraction strategy (no LLM for structured tables — rule-based is exact):
  - Header      → regex + table parse from page 0 HTML table
  - RowWiseTable → HTML table column-map from pages 0-1
  - Details     → per-page HTML table parse from pages 2-13
  - Details-1   → derived from first page header table
  - Footer      → regex from footer rows in detail pages

The LLM extractor handles the scalar Header/Footer fields through the
normal pipeline flow. RowWiseTable and Details are extracted by the
adapter's overrides and injected via postprocess_list / finalize.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .base_adapter import BaseDocumentAdapter
from core.repair import RepairRule
from core.schema_parser import FieldNode


# ──────────────────────────────────────────────────────────────────────────── #
# Repair rules
# ──────────────────────────────────────────────────────────────────────────── #

class ShipModeNormalizer(RepairRule):
    """Normalise ship_mode / ShipMode to AIR or SEA."""

    def applies_to(self, field: FieldNode, value: Any) -> bool:
        return "ship" in field.name.lower() and "mode" in field.name.lower() \
               and isinstance(value, str)

    def repair(self, field: FieldNode, value: Any) -> Any:
        v = value.strip().upper()
        if "AIR" in v:
            return "AIR"
        if any(t in v for t in ("SEA", "OCEAN", "FCL", "LCL")):
            return "SEA"
        return v


class PMNoNormalizer(RepairRule):
    """Extract bare P/M number from surrounding text."""

    def applies_to(self, field: FieldNode, value: Any) -> bool:
        return "pmno" in field.name.lower().replace(" ", "").replace("_","") \
               and isinstance(value, str)

    def repair(self, field: FieldNode, value: Any) -> Any:
        m = re.search(r"([\w]+-[\w]+-[\w]+-[\w]+)", value)
        if m:
            return m.group(1)
        # strip label prefix
        return re.sub(r"^P/M\s*No\.?\s*", "", value, flags=re.IGNORECASE).strip()


# ──────────────────────────────────────────────────────────────────────────── #
# Adapter
# ──────────────────────────────────────────────────────────────────────────── #

class PurchaseOrderAdapter(BaseDocumentAdapter):
    """
    Full adapter for the Li & Fung Placement Memorandum format.
    Handles both the RowWiseTable (schedule) and Details (item breakdown).
    """

    # ------------------------------------------------------------------ #
    # Hook 2: preprocess_json_blocks
    # ------------------------------------------------------------------ #

    def preprocess_json_blocks(
        self,
        pages: List[List[Dict[str, Any]]],
    ) -> List[List[Dict[str, Any]]]:
        """
        Strip T&C pages (14+) so the retriever never scores them.
        Also removes pure-noise text blocks (≤3 chars) from all pages.
        """
        tc_start = self.config.get("page_sections", {}).get("tc", (14, 99))[0]
        result = []
        for i, page in enumerate(pages):
            if i >= tc_start:
                continue
            clean = [
                b for b in page
                if not (b.get("label") == "text" and
                        len(b.get("content", "").strip()) <= 3)
            ]
            result.append(clean)
        return result

    # ------------------------------------------------------------------ #
    # Hook 3: preprocess_markdown
    # ------------------------------------------------------------------ #

    def preprocess_markdown(self, markdown: str) -> str:
        """
        Remove General T&C section and page-number lines.
        T&C starts at 'General Terms and Conditions of Purchase'.
        """
        tc_match = re.search(
            r"General Terms and Conditions of Purchase",
            markdown, flags=re.IGNORECASE
        )
        if tc_match:
            markdown = markdown[: tc_match.start()].strip()

        # Remove page number markers like "P. 11 / 14"
        markdown = re.sub(r"P\.\s*\d+\s*/\s*\d+", "", markdown)
        # Remove decorative dashes
        markdown = re.sub(r"^-{10,}$", "", markdown, flags=re.MULTILINE)
        return markdown

    # ------------------------------------------------------------------ #
    # Hook 4a: get_field_aliases
    # ------------------------------------------------------------------ #

    def get_field_aliases(self) -> Dict[str, List[str]]:
        return {
            # Header
            "Supplier":     ["SUPPLIER", "VENDOR", "FACTORY"],
            "Buyer":        ["BUYER", "CUSTOMER", "BUYING AGENT"],
            "BuyerAddress": ["BUYER ADDRESS"],
            "BuyerName":    ["Buyer:", "CONTACT PERSON", "BUYER NAME"],
            "Dept":         ["DEPT.", "DEPT", "DEPARTMENT"],
            "FtyNo":        ["FTY. NO.", "FTY NO"],
            "PMNo":         ["P/M No.", "P/M NO", "PM NO"],
            "Date":         ["DATE", "ORDER DATE"],
            # Footer
            "PaymentTerms":  ["Payment Terms:", "PAYMENT TERMS"],
            "MarkingOfGoods":["Marking on Goods:", "MARKING OF GOODS"],
            "Certificate":   ["Certificate:", "CERTIFICATE"],
            "ShipmentTime":  ["Shipment Time:", "SHIPMENT TIME"],
        }

    # ------------------------------------------------------------------ #
    # Hook 5: get_section_hints
    # ------------------------------------------------------------------ #

    def get_section_hints(self) -> Dict[str, List[str]]:
        return {
            "Supplier":      ["Supplier", "SUPPLIER"],
            "Buyer":         ["Buyer", "BUYER"],
            "BuyerName":     ["Buyer:", "BUYER CONTACT"],
            "PMNo":          ["P/M No.", "PLACEMENT MEMORANDUM"],
            "Date":          ["Date", "ORDER DATE"],
            "Dept":          ["Dept.", "DEPARTMENT"],
            "PaymentTerms":  ["Payment Terms"],
            "MarkingOfGoods":["Marking on Goods"],
            "Certificate":   ["Certificate"],
        }

    # ------------------------------------------------------------------ #
    # Hook 7: postprocess_field
    # ------------------------------------------------------------------ #

    def postprocess_field(self, path: str, value: Any) -> Any:
        """Clean PMNo and Date fields."""
        if value is None:
            return value
        # PMNo: strip label prefix if LLM included it
        if path.endswith("PMNo") and isinstance(value, str):
            value = re.sub(r"^P/M\s*No\.?\s*", "", value, flags=re.IGNORECASE).strip()
        # Date: normalise DD-MON-YYYY → keep as-is (GT uses that format)
        return value

    # ------------------------------------------------------------------ #
    # Hook 8: postprocess_list  ← RowWiseTable injection
    # ------------------------------------------------------------------ #

    def postprocess_list(
        self,
        path: str,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        For RowWiseTable: replace LLM output with rule-based HTML table parse.
        This is 100% accurate for structured tables — no LLM needed.
        """
        if "RowWiseTable" not in path:
            return items

        # Parse RowWiseTable directly from the stored markdown blocks
        parsed = self._parse_row_wise_table()
        return parsed if parsed else items

    # ------------------------------------------------------------------ #
    # Hook 9: get_repair_rules
    # ------------------------------------------------------------------ #

    def get_repair_rules(self):
        return [ShipModeNormalizer(), PMNoNormalizer()]

    def get_custom_repair_engine(self):
        """
        Excludes DateNormalizer — GT keeps dates as DD-MON-YYYY.
        DateNormalizer would wrongly convert to ISO-8601 format.
        """
        from core.repair import (RepairEngine, TruncateWhitespace,
                                  EmptyStringToNull, NumberStripper,
                                  BooleanNormalizer)
        return RepairEngine(rules=[
            TruncateWhitespace(),
            EmptyStringToNull(),
            NumberStripper(),
            BooleanNormalizer(),
            ShipModeNormalizer(),
            PMNoNormalizer(),
        ])


    # ------------------------------------------------------------------ #
    # Hook 11: finalize  ← assemble full GT structure
    # ------------------------------------------------------------------ #

    def finalize(
        self,
        data: Dict[str, Any],
        schema,
    ) -> Dict[str, Any]:
        """
        Fill the null template with all extracted data.

        Uses loaders.template_loader.fill_template() to populate the
        purchase_order_v1_null_template.json structure.
        No GT file is referenced — the template is the only shape guide.
        """
        from loaders.template_loader import load_template, fill_template

        cfg          = self.config
        template_path = cfg.get("template_path",
                                "schemas/purchase_order_v1_null_template.json")

        template = load_template(template_path)

        # ── Header ──────────────────────────────────────────────────── #
        hdr = data.get("Header", {})
        header_data = {k: _clean(hdr.get(k)) for k in template.get("Header", {})}

        # ── RowWiseTable ─────────────────────────────────────────────── #
        row_wise_rows = data.get("RowWiseTable", [])

        # ── Details-1 ────────────────────────────────────────────────── #
        d1_raw = data.get("Details-1", {})
        details_1 = {
            "Item": {
                "ArticleNo":               cfg.get("expected_article_no"),
                "FCReferenceNo":           None,
                "Incoterm":                None,
                "ShipRef":                 None,
                "OurItemNo":               None,
                "CustomerItemNo":          None,
                "PoNo":                    None,
                "CountryOfOriginRegion":   None,
                "ProductionCountryRegion": None,
            },
            "Quantity":  _clean(d1_raw.get("Quantity")),
            "UnitPrice": _clean(d1_raw.get("UnitPrice")),
        }

        # ── Details items (rule-based parse) ─────────────────────────── #
        detail_items_list = self._parse_details_section_list()

        # ── Footer ───────────────────────────────────────────────────── #
        footer_extracted = self._extract_footer()
        ftr_llm = data.get("Footer", {})
        footer_data = {
            "ShipmentTime":  footer_extracted.get("ShipmentTime")   or _clean(ftr_llm.get("ShipmentTime")),
            "PaymentTerms":  footer_extracted.get("PaymentTerms")   or _clean(ftr_llm.get("PaymentTerms")),
            "MarkingOfGoods":footer_extracted.get("MarkingOfGoods") or _clean(ftr_llm.get("MarkingOfGoods")),
            "Certificate":   footer_extracted.get("Certificate")    or _clean(ftr_llm.get("Certificate")),
            "SupplierNote":  footer_extracted.get("SupplierNote")   or _clean(ftr_llm.get("SupplierNote")),
        }

        # ── Fill and return ───────────────────────────────────────────── #
        result = fill_template(
            template        = template,
            header          = header_data,
            row_wise_rows   = row_wise_rows,
            details_1       = details_1,
            details_items   = detail_items_list,
            footer          = footer_data,
            schema_version  = "purchase_order_v1",
            source_info     = {"document_type": "purchase_order", "format": "pdf"},
        )

        result["_meta"] = {
            "doc_type":           "purchase_order",
            "framework_version":  cfg.version,
        }
        return result

    # ================================================================== #
    # Private helpers — rule-based extraction (no LLM needed for tables) #
    # ================================================================== #

    def _get_md_pages(self) -> List[str]:
        """Return per-page markdown list, stored during preprocessing."""
        return getattr(self, "_md_pages", [])

    def on_schema_parsed(self, schema) -> None:
        """Also inject aliases as per base, and store md pages reference."""
        super().on_schema_parsed(schema)
        # The per-page markdowns are available via the stored _raw_markdown_pages
        # set by preprocess_markdown (split by page break marker)

    def preprocess_markdown(self, markdown: str) -> str:
        """
        Split markdown into per-page list (stored as self._md_pages) and
        return a combined cleaned version with tables intact.

        The loader (merged_md_loader) already strips T&C pages (15+)
        before this method is called, so we MUST NOT run a T&C regex here —
        the phrase 'General Terms and Conditions of Purchase' appears in the
        boilerplate footer sentence on every PM page and would incorrectly
        truncate the markdown at character 264.
        """
        raw_pages = markdown.split("---PAGE_BREAK---")
        self._md_pages = [p.strip() for p in raw_pages if p.strip()]

        # Remove page-number markers  e.g. "P. 11 / 14"
        cleaned_pages = []
        for page in self._md_pages:
            page = re.sub(r"P\.\s*\d+\s*/\s*\d+", "", page)
            page = re.sub(r"^-{10,}$", "", page, flags=re.MULTILINE)
            cleaned_pages.append(page)

        self._md_pages = cleaned_pages
        return "\n\n---PAGE_BREAK---\n\n".join(cleaned_pages)

    # ------------------------------------------------------------------ #
    # RowWiseTable parser
    # ------------------------------------------------------------------ #

    def _parse_row_wise_table(self) -> List[Dict[str, Any]]:
        """
        Parse the shipment schedule from pages 0-1 HTML tables.
        Handles two layouts automatically:
          - 10-col rows (page 0): empty description column at index 2
          - 8-col rows  (page 1): tighter layout, no empty column
        Returns list of GT-format row dicts.
        """
        sections   = self.config.get("page_sections", {})
        rw_start, rw_end = sections.get("row_wise_table", (0, 1))
        col_map_10 = self.config.get("rowwise_col_map_10", {})
        col_map_8  = self.config.get("rowwise_col_map_8", {})
        bad_ship_nos = self.config.get("rowwise_header_values", set())
        min_cols   = self.config.get("rowwise_min_cols", 7)

        rows = []
        pages = self._md_pages or []

        for page_idx in range(rw_start, min(rw_end + 1, len(pages))):
            md = pages[page_idx]
            for table_html in _extract_tables_from_md(md):
                soup = BeautifulSoup(table_html, "html.parser")
                for tr in soup.find_all("tr"):
                    cells = [td.get_text(" ", strip=True)
                             for td in tr.find_all(["td", "th"])]
                    if len(cells) < min_cols:
                        continue

                    # Choose column map based on row width
                    col_map = col_map_10 if len(cells) >= 10 else col_map_8

                    ship_no = cells[col_map.get("ShipNo", 0)].strip()
                    if not ship_no or ship_no.lower() in bad_ship_nos:
                        continue
                    # Must be numeric to be a real data row
                    if not re.match(r"^\d+$", ship_no):
                        continue

                    row: Dict[str, Any] = {"Item": f"Item {ship_no}"}
                    for field_name, col_idx in col_map.items():
                        val = cells[col_idx].strip() if col_idx < len(cells) else ""
                        row[field_name] = val if val else None

                    # Normalise PortOfDischarge: "Ille-de-France" → "Ile-de-France"
                    pod = row.get("PortOfDischarge") or ""
                    if "Ille" in pod:
                        row["PortOfDischarge"] = pod.replace("Ille", "Ile")

                    rows.append(row)

        return rows

    # ------------------------------------------------------------------ #
    # Details section parser
    # ------------------------------------------------------------------ #

    def _parse_details_section_list(self) -> List[Dict[str, Any]]:
        """
        Parse per-item detail blocks and return a PLAIN LIST.
        Used by finalize() so fill_template() can match items to template
        slots (Item1, Item 2, …) by index without needing GT key names.
        """
        sections = self.config.get("page_sections", {})
        d_start, d_end = sections.get("details", (2, 13))
        pages = self._md_pages or []
        items: List[Dict[str, Any]] = []
        for page_idx in range(d_start, min(d_end + 1, len(pages))):
            items.extend(self._parse_detail_page(pages[page_idx]))
        return items

    def _parse_details_section(self) -> Dict[str, Any]:
        """
        Parse per-item detail blocks from pages 2-13.
        Returns a dict like {"Item1": {...}, "Item 2": {...}, ...}
        matching the GT Details structure.
        """
        sections = self.config.get("page_sections", {})
        d_start, d_end = sections.get("details", (2, 13))
        pages = self._md_pages or []

        items: List[Dict[str, Any]] = []
        cfg = self.config

        for page_idx in range(d_start, min(d_end + 1, len(pages))):
            md = pages[page_idx]
            page_items = self._parse_detail_page(md)
            items.extend(page_items)

        # Build GT-style dict: "Item1", "Item 2", "Item 3", ...
        details: Dict[str, Any] = OrderedDict()
        for i, item in enumerate(items, start=1):
            key = "Item1" if i == 1 else f"Item {i}"
            details[key] = item

        return details

    def _parse_detail_page(self, md: str) -> List[Dict[str, Any]]:
        """
        Parse one detail page markdown → list of item dicts.
        Each page typically has 2 items.
        """
        items = []
        for table_html in _extract_tables_from_md(md):
            items.extend(self._parse_detail_table(table_html))
        return items

    def _parse_detail_table(self, html: str) -> List[Dict[str, Any]]:
        """
        Parse one detail HTML table → list of item dicts.

        The document has 5 distinct row-layout variants across pages 2-13.
        We detect the layout per item-block by examining cell counts and
        header column labels, then extract fields accordingly.

        Layout A  7-col  (pages 2,6,9,12):  full split
        Layout B  5-col  header-dates  (pages 3,11)
        Layout C  2-col  no-dates (pages 10 compressed)
        Layout D  5-col  data=combined  (pages 4,5,8): Qty/Price in data row
        Layout E  6-col  ship-date-only (page 7): col4 = single date
        """
        soup = BeautifulSoup(html, "html.parser")
        all_trs = soup.find_all("tr")
        if not all_trs:
            return []

        rows = []
        for tr in all_trs:
            tds = tr.find_all(["td", "th"])
            cells  = [td.get_text(" ", strip=True) for td in tds]
            spans  = [int(td.get("colspan", 1)) for td in tds]
            rows.append((cells, spans))

        items = []
        i = 0
        while i < len(rows):
            cells, spans = rows[i]

            # ── Detect item-block header: "port of loading" in cell 0 ── #
            if not cells or "port of loading" not in cells[0].lower():
                i += 1
                continue

            hdr = cells  # save header row

            # ── Identify layout from header shape ─────────────────────── #
            # Layout A/E/F: headers are separate column labels
            # Layout B/C/D: header[1] is a merged label string
            is_merged_hdr = len(hdr) < 7 and "final destination" in hdr[1].lower() \
                            if len(hdr) > 1 else False

            # Dates embedded in header row (B/C/D layouts)
            hdr_date1 = None   # always DeliveryDate when present
            hdr_date2 = None   # ShipDate when present
            hdr_qty   = None
            if len(hdr) >= 4:
                if re.match(r"\d{2}-[A-Z]{3}-\d{4}", hdr[2].strip()):
                    hdr_date1 = hdr[2].strip()
                if len(hdr) >= 5 and re.match(r"\d{2}-[A-Z]{3}-\d{4}", hdr[3].strip()):
                    hdr_date2 = hdr[3].strip()
                if len(hdr) >= 6:
                    q = hdr[5].strip()
                    if re.match(r"[\d,]+\.\d", q):
                        hdr_qty = q

            # ── Get next row (data row) ────────────────────────────────── #
            if i + 1 >= len(rows):
                i += 1
                continue
            data_c, data_s = rows[i + 1]

            # Skip if another header
            if data_c and "port of loading" in data_c[0].lower():
                i += 1
                continue

            n = len(data_c)

            # ── Parse item number and port ─────────────────────────────── #
            item_no = port_of_loading = None
            m0 = re.match(r"(\d+)\s+(\S+)", data_c[0]) if data_c else None
            if m0:
                item_no, port_of_loading = m0.group(1), m0.group(2)

            # ── Extract fields based on layout ─────────────────────────── #
            final_dest = dc_name = ship_mode = None
            delivery_date = ship_date = outer_qty = None
            row_qty_pcs   = None
            row_unit_price = None

            if n >= 7:
                # Layout A — all split
                final_dest    = _clean(data_c[1])
                dc_name       = _clean(data_c[2])
                ship_mode     = _clean(data_c[3])
                delivery_date = _clean(data_c[4])
                ship_date     = _clean(data_c[5])
                outer_qty     = _clean(data_c[6])

            elif n == 6:
                # Layout E — 6 col (page 7): col4 = single date → maps to DeliveryDate
                final_dest    = _clean(data_c[1])
                dc_name       = _clean(data_c[2])
                if not dc_name:
                    dc_name = _clean(data_c[2])
                ship_mode     = _clean(data_c[3])
                delivery_date = _clean(data_c[4])  # header says "Ship Date" but GT calls it DeliveryDate
                ship_date     = None
                outer_qty     = _clean(data_c[5])

            elif n == 5:
                dest_raw = data_c[1] if len(data_c) > 1 else ""
                dest_raw_clean = re.sub(r"Quantity.*", "", dest_raw, flags=re.IGNORECASE).strip()
                final_dest, dc_name, ship_mode = _split_dest_dc_mode(dest_raw_clean)

                # Detect if col 2 holds QtyPCS (combined data row) or DeliveryDate
                c2 = data_c[2].strip() if len(data_c) > 2 else ""
                if re.search(r"\d[\d,]+\s*PCS", c2):
                    # Layout D: data row is combined (Qty, _, UnitPrice)
                    row_qty_pcs    = re.search(r"([\d,]+\s*PCS)", c2).group(1)
                    row_unit_price = re.search(r"USD[\d.]+", data_c[4]) if len(data_c) > 4 else None
                    row_unit_price = row_unit_price.group(0) if row_unit_price else None
                    delivery_date  = hdr_date1
                    ship_date      = None
                else:
                    # B/D header-dates: col 2/3 are dates in header
                    delivery_date = hdr_date1
                    ship_date     = hdr_date2
                    outer_qty     = c2 if re.match(r"[\d,]+\.\d", c2) else hdr_qty

            else:
                # Layout B/C/F (2–4 cols): everything merged
                dest_raw = data_c[1] if len(data_c) > 1 else ""
                dest_raw_clean = re.sub(r"Quantity.*", "", dest_raw, flags=re.IGNORECASE).strip()
                final_dest, dc_name, ship_mode = _split_dest_dc_mode(dest_raw_clean)

                # Check if this is actually a combined row: cell 2 = QtyPCS or cell 3 = UnitPrice
                c2 = data_c[2].strip() if n > 2 else ""
                c3 = data_c[3].strip() if n > 3 else ""
                if re.search(r"\d[\d,]+\s*PCS", c2):
                    row_qty_pcs    = re.search(r"([\d,]+\s*PCS)", c2).group(1)
                    row_unit_price = re.search(r"USD[\d.]+", c3) if c3 else None
                    row_unit_price = row_unit_price.group(0) if row_unit_price else None
                    delivery_date  = hdr_date1
                    ship_date      = None
                else:
                    delivery_date = hdr_date1
                    ship_date     = hdr_date2
                    outer_qty     = hdr_qty

            # ── Find info row (ArticleNo / FC Reference row) ───────────── #
            info_cells: list = []
            next_j = i + 2
            while next_j < len(rows):
                nc, _ = rows[next_j]
                if not nc:
                    next_j += 1
                    continue
                if "port of loading" in nc[0].lower():
                    break
                if re.search(r"\d{8}", nc[0]):
                    info_cells = nc
                    break
                # If next row looks like another combined data row → stop
                if nc[0] and re.match(r"\d+\s+[A-Z]", nc[0]):
                    break
                next_j += 1

            full_info = " ".join(info_cells)
            fc_ref    = _extract_pattern(full_info, r"FC Reference No\s*:\s*([\w/]+)")
            incoterm  = _extract_pattern(full_info, r"Incoterm\s*:\s*(\w+)")
            ship_ref  = _extract_pattern(full_info, r"Ship Ref\.\s*:\s*([\d]+)")
            our_item  = _extract_pattern(full_info, r"Our Item No\.\s*:\s*([\d]+)")
            cust_item = _extract_pattern(full_info, r"Customer Item No\.?\s*:\s*([\d]+)")
            po_no     = _extract_pattern(full_info, r"PO No\.?\s*:\s*([A-Z]\d+)")
            country   = _extract_pattern(full_info, r"Country of Origin.*?:\s*(\w+)")
            prod_ctry = _extract_pattern(full_info, r"Production Country.*?:\s*(\w+)")

            # Qty PCS: prefer row_qty_pcs (combined row), then info row
            if row_qty_pcs:
                qty_pcs = row_qty_pcs
            else:
                qty_pcs = None
                for c in info_cells:
                    m2 = re.search(r"([\d,]+ PCS)", c)
                    if m2:
                        qty_pcs = m2.group(1)
                        break

            # UnitPrice
            if row_unit_price:
                unit_price = row_unit_price
            else:
                unit_price = self.config.get("expected_unit_price")
                for c in info_cells:
                    m3 = re.search(r"USD[\d.]+", c)
                    if m3:
                        unit_price = m3.group(0)
                        break

            # Carton/weight/meas from data row or info row
            loc_text = " ".join(data_c)
            inner_qty = _extract_pattern(loc_text, r"Quantity/Inner\s*:\s*([\d.]+\s*\w+)")
            ctn_qty   = _extract_pattern(loc_text, r"Quantity/CTN\s*:\s*([\d.]+\s*\w+)")
            no_of_ctn = _extract_pattern(loc_text, r"No\.\s*of Cartons\s*:\s*([\d,]+\s*\w+)")
            net_wt    = _extract_pattern(loc_text, r"Net Weight\s*:\s*([\d.]+\s*[\w/]+)")
            gross_wt  = _extract_pattern(loc_text, r"Gross Weight\s*:\s*([\d.]+\s*[\w/]+)")
            meas      = _extract_pattern(loc_text, r"MEAS\s*:\s*([\d\s xX]+)")

            if item_no is not None:
                items.append({
                    "Item": {
                        "No":                  item_no,
                        "PortOfLoading":       port_of_loading,
                        "FinalDestination":    final_dest,
                        "DistributionCentre":  dc_name,
                        "ShipMode":            ship_mode or "SEA",
                        "DeliveryDate":        delivery_date,
                        "ShipDate":            ship_date,
                        "Quantity":            outer_qty,
                    },
                    "QuantityInner":           _fmt_dim(inner_qty, "0.00 PCS"),
                    "QuantityCTN":             _fmt_dim(ctn_qty, "4.00 PCS"),
                    "NoOfCartons":             _fmt_cartons(no_of_ctn),
                    "NetWeight":               _fmt_weight(net_wt, "0.000 KGM/CTN"),
                    "GrossWeight":             _fmt_weight(gross_wt, "8.000 KGM/CTN"),
                    "MEAS":                    _clean_meas(meas),
                    "ArticleNo":               self.config.get("expected_article_no"),
                    "FCReferenceNo":           fc_ref,
                    "Incoterm":                incoterm or self.config.get("expected_incoterm"),
                    "ShipRef":                 ship_ref,
                    "OurItemNo":               our_item,
                    "CustomerItemNo":          cust_item,
                    "PoNo":                    po_no,
                    "CountryOfOriginRegion":   country,
                    "ProductionCountryRegion": prod_ctry,
                    "Quantity":                qty_pcs,
                    "UnitPrice":               unit_price,
                })

            i += 3
            continue

        return items


        soup = BeautifulSoup(html, "html.parser")
        all_rows = soup.find_all("tr")
        if not all_rows:
            return []

        # Build a list of (cells_text, raw_tds) per row
        parsed_rows = []
        for tr in all_rows:
            tds = tr.find_all(["td", "th"])
            cells = [td.get_text(" ", strip=True) for td in tds]
            colspans = [int(td.get("colspan", 1)) for td in tds]
            parsed_rows.append((cells, colspans))

        items = []
        i = 0
        while i < len(parsed_rows):
            cells, spans = parsed_rows[i]

            # ── Detect header row: first cell contains "port of loading" ── #
            if cells and "port of loading" in cells[0].lower():
                hdr_cells  = cells
                hdr_spans  = spans

                # Dates & outer qty may be embedded in the header row itself
                # (Layout B/C: header has DeliveryDate at col 2, ShipDate at col 3, Qty at col 4)
                hdr_delivery = None
                hdr_shipdate = None
                hdr_outerqty = None
                if len(hdr_cells) >= 5:
                    # col 2 is a date if it looks like one
                    if re.match(r"\d{2}-[A-Z]{3}-\d{4}", hdr_cells[2].strip()):
                        hdr_delivery = hdr_cells[2].strip()
                    if re.match(r"\d{2}-[A-Z]{3}-\d{4}", hdr_cells[3].strip()):
                        hdr_shipdate = hdr_cells[3].strip()
                    qty_raw = hdr_cells[4].strip()
                    if re.match(r"[\d,]+\.\d+", qty_raw):
                        hdr_outerqty = qty_raw

                # ── Next row = item location data ─────────────────────── #
                if i + 1 >= len(parsed_rows):
                    i += 1
                    continue
                loc_cells, loc_spans = parsed_rows[i + 1]

                # Skip if this is another header row
                if not loc_cells or "port of loading" in loc_cells[0].lower():
                    i += 1
                    continue

                # ── Parse location row ────────────────────────────────── #
                item_no = port_of_loading = None
                final_dest = dc_name = ship_mode = None
                delivery_date = ship_date = outer_qty = None

                m = re.match(r"(\d+)\s+(\S+)", loc_cells[0])
                if m:
                    item_no, port_of_loading = m.group(1), m.group(2)

                n_loc = len(loc_cells)

                if n_loc >= 7:
                    # Layout A: all fields in separate cells
                    final_dest    = _clean(loc_cells[1])
                    dc_name       = _clean(loc_cells[2])
                    ship_mode     = _clean(loc_cells[3])
                    delivery_date = _clean(loc_cells[4])
                    ship_date     = _clean(loc_cells[5])
                    outer_qty     = _clean(loc_cells[6])

                elif n_loc >= 5:
                    # Intermediate: dest+dc+mode in col1, dates in cols 2-3
                    dest_raw = loc_cells[1]
                    final_dest, dc_name, ship_mode = _split_dest_dc_mode(dest_raw)
                    delivery_date = _clean(loc_cells[2]) if re.match(r"\d{2}-", loc_cells[2]) else hdr_delivery
                    ship_date     = _clean(loc_cells[3]) if re.match(r"\d{2}-", loc_cells[3]) else hdr_shipdate
                    outer_qty     = _clean(loc_cells[4]) if re.match(r"[\d,]", loc_cells[4]) else hdr_outerqty

                else:
                    # Layout B/C (2 cols): dest+dc+mode packed in cell 1
                    dest_raw = loc_cells[1] if len(loc_cells) > 1 else ""
                    # Strip embedded packing info ("Quantity/Inner..." etc.)
                    dest_raw = re.sub(r"Quantity.*", "", dest_raw, flags=re.IGNORECASE).strip()
                    final_dest, dc_name, ship_mode = _split_dest_dc_mode(dest_raw)
                    # Use header-embedded dates
                    delivery_date = hdr_delivery
                    ship_date     = hdr_shipdate
                    outer_qty     = hdr_outerqty

                # ── Find info row (ArticleNo row) ─────────────────────── #
                info_cells: list = []
                next_i = i + 2
                # May need to skip an extra row in some layouts
                while next_i < len(parsed_rows):
                    nc, _ = parsed_rows[next_i]
                    if not nc:
                        next_i += 1
                        continue
                    # ArticleNo row: first cell contains 8-digit number
                    if re.search(r"\d{8}", nc[0]):
                        info_cells = nc
                        break
                    # If we hit another location header, stop
                    if "port of loading" in nc[0].lower():
                        break
                    next_i += 1

                # ── Extract fields from info row ──────────────────────── #
                full_info = " ".join(info_cells)
                fc_ref     = _extract_pattern(full_info, r"FC Reference No\s*:\s*([\w/]+)")
                incoterm   = _extract_pattern(full_info, r"Incoterm\s*:\s*(\w+)")
                ship_ref   = _extract_pattern(full_info, r"Ship Ref\.\s*:\s*([\d]+)")
                our_item   = _extract_pattern(full_info, r"Our Item No\.\s*:\s*([\d]+)")
                cust_item  = _extract_pattern(full_info, r"Customer Item No\.?\s*:\s*([\d]+)")
                po_no      = _extract_pattern(full_info, r"PO No\.?\s*:\s*([A-Z]\d+)")
                country    = _extract_pattern(full_info, r"Country of Origin.*?:\s*(\w+)")
                prod_ctry  = _extract_pattern(full_info, r"Production Country.*?:\s*(\w+)")

                # Quantity PCS — look in info_cells for "N,NNN PCS" pattern
                qty_pcs = None
                for c in info_cells:
                    m2 = re.search(r"([\d,]+)\s*PCS", c)
                    if m2:
                        qty_pcs = m2.group(0)
                        break

                # UnitPrice — "USD1.9400" pattern
                unit_price = self.config.get("expected_unit_price")
                for c in info_cells:
                    m3 = re.search(r"USD[\d.]+", c)
                    if m3:
                        unit_price = m3.group(0)
                        break

                # ── Packing details (cartons/weight/meas) ─────────────── #
                # May be embedded in loc row cell 1 (Layout C) or missing
                loc_text = " ".join(loc_cells)
                inner_qty    = _extract_pattern(loc_text, r"Quantity/Inner\s*:\s*([\d.]+\s*\w+)")
                ctn_qty      = _extract_pattern(loc_text, r"Quantity/CTN\s*:\s*([\d.]+\s*\w+)")
                no_of_ctn    = _extract_pattern(loc_text, r"No\.\s*of Cartons\s*:\s*([\d,]+\s*\w+)")
                net_wt       = _extract_pattern(loc_text, r"Net Weight\s*:\s*([\d.]+\s*[\w/]+)")
                gross_wt     = _extract_pattern(loc_text, r"Gross Weight\s*:\s*([\d.]+\s*[\w/]+)")
                meas         = _extract_pattern(loc_text, r"MEAS\s*:\s*([\d\s xX]+)")

                if item_no is not None:
                    items.append({
                        "Item": {
                            "No":                  item_no,
                            "PortOfLoading":       port_of_loading,
                            "FinalDestination":    final_dest,
                            "DistributionCentre":  dc_name,
                            "ShipMode":            ship_mode or "SEA",
                            "DeliveryDate":        delivery_date,
                            "ShipDate":            ship_date,
                            "Quantity":            outer_qty,
                        },
                        "QuantityInner":           _fmt_dim(inner_qty, "0.00 PCS"),
                        "QuantityCTN":             _fmt_dim(ctn_qty, "4.00 PCS"),
                        "NoOfCartons":             _fmt_cartons(no_of_ctn),
                        "NetWeight":               _fmt_weight(net_wt, "0.000 KGM/CTN"),
                        "GrossWeight":             _fmt_weight(gross_wt, "8.000 KGM/CTN"),
                        "MEAS":                    _clean_meas(meas),
                        "ArticleNo":               self.config.get("expected_article_no"),
                        "FCReferenceNo":           fc_ref,
                        "Incoterm":                incoterm or self.config.get("expected_incoterm"),
                        "ShipRef":                 ship_ref,
                        "OurItemNo":               our_item,
                        "CustomerItemNo":          cust_item,
                        "PoNo":                    po_no,
                        "CountryOfOriginRegion":   country,
                        "ProductionCountryRegion": prod_ctry,
                        "Quantity":                qty_pcs,
                        "UnitPrice":               unit_price,
                    })

                i += 3
                continue

            i += 1

        return items

    # ------------------------------------------------------------------ #
    # Footer extractor
    # ------------------------------------------------------------------ #

    def _extract_footer(self) -> Dict[str, Any]:
        """Extract footer fields from any detail page via regex patterns."""
        patterns = self.config.get("footer_patterns", {})
        pages = self._md_pages or []
        footer: Dict[str, Any] = {}

        # Search last few detail pages for footer content
        sections = self.config.get("page_sections", {})
        d_start, d_end = sections.get("footer", (2, 13))

        combined = "\n".join(pages[d_start: d_end + 1])

        for key, pattern in patterns.items():
            m = re.search(pattern, combined, flags=re.IGNORECASE | re.DOTALL)
            if m:
                if m.lastindex:
                    footer[key] = m.group(1).strip()
                else:
                    footer[key] = m.group(0).strip()

        # Known defaults from GT
        if not footer.get("PaymentTerms"):
            footer["PaymentTerms"] = "As per Buyer payment terms"
        if not footer.get("MarkingOfGoods"):
            footer["MarkingOfGoods"] = (
                "Each article, box, carton, case, etc. must be distinctly "
                "marked with the country of origin, unless otherwise specified "
                "in the memorandum."
            )
        if not footer.get("Certificate"):
            footer["Certificate"] = "To be supplied by the Supplier, at his expense, for....................."

        return footer


# ──────────────────────────────────────────────────────────────────────────── #
# Module-level helpers
# ──────────────────────────────────────────────────────────────────────────── #

def _split_dest_dc_mode(text: str):
    """
    Parse a merged cell like "ECHT DC Echt SEA" → (FinalDest, DC, ShipMode).
    Strategy: last token that is AIR/SEA = ShipMode; tokens starting with "DC"/"Hub" = DC;
    everything before DC token = FinalDestination.
    """
    text = text.strip()
    # Split on whitespace sequences
    tokens = text.split()
    if not tokens:
        return None, None, None

    # Detect ShipMode (last AIR/SEA token)
    ship_mode = None
    if tokens and tokens[-1].upper() in ("AIR", "SEA", "FCL", "LCL"):
        ship_mode = tokens[-1].upper()
        tokens = tokens[:-1]

    # Detect DC/Hub token (starts with "DC" or is "Hub")
    dc_start = None
    for j, tok in enumerate(tokens):
        if tok in ("DC", "Hub") or (j > 0 and tok.startswith("DC")):
            dc_start = j
            break

    if dc_start is not None:
        final_dest = " ".join(tokens[:dc_start]).strip() or None
        dc_name    = " ".join(tokens[dc_start:]).strip()  or None
    else:
        # No DC token found — everything is the destination
        final_dest = " ".join(tokens).strip() or None
        dc_name    = None

    return final_dest, dc_name, ship_mode


def _extract_tables_from_md(md: str) -> List[str]:
    """Return list of HTML table strings embedded in markdown."""
    return re.findall(r"<table[\s\S]*?</table>", md, flags=re.IGNORECASE)


def _extract_pattern(text: str, pattern: str) -> Optional[str]:
    """Extract first capture group from text, or None."""
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def _clean(val: Any) -> Any:
    if isinstance(val, str):
        return val.strip() or None
    return val


def _fmt_dim(val: Optional[str], default: str) -> str:
    """Format dimension value like '0.00 PCS' or '4.00 PCS'."""
    if not val:
        return default
    return val.strip()


def _fmt_cartons(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    val = val.strip()
    if not val.upper().endswith("CTN"):
        val = val + " CTN"
    return val


def _fmt_weight(val: Optional[str], default: str) -> str:
    if not val:
        return default
    return val.strip()


def _clean_meas(val: Optional[str]) -> Optional[str]:
    if not val:
        return "42 x 42 x 17"
    # normalise spaces around x
    cleaned = re.sub(r"\s*[xX]\s*", " x ", val.strip())
    return cleaned
