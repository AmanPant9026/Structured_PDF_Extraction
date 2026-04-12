"""
adapters/shipping_bill_adapter.py
----------------------------------
Shipping Bill adapter — precision row-index extraction.

Every section uses exact row-index + column-index maps derived from
inspecting the actual HTML table structure. No guessing, no regex sprawl.

Page structure (confirmed from real document):
  Page 1 (36 rows) → PART-I SUMMARY sections A-J
  Page 2 (19 rows) → PART-II INVOICE sections A-D
  Page 3 (3 tables)→ PART-III ITEM DETAILS
  Page 4           → PART-IV SCHEME DETAILS A-M
  Page 5           → PART-V REEXPORT section N
  Page 6           → PART-V DECLARATIONS section B
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .base_adapter import BaseDocumentAdapter
from core.repair import RepairRule
from core.schema_parser import FieldNode


class SBDateKeep(RepairRule):
    """Shipping Bill dates stay as DD-MON-YY — no ISO normalisation."""
    def applies_to(self, f, v): return False
    def repair(self, f, v): return v


class ShippingBillAdapter(BaseDocumentAdapter):

    # ------------------------------------------------------------------ #
    # preprocess_markdown — split pages, store list, return combined
    # ------------------------------------------------------------------ #
    def preprocess_markdown(self, markdown: str) -> str:
        raw = markdown.split("---PAGE_BREAK---")
        self._md_pages = [p.strip() for p in raw if p.strip()]
        return "\n\n---PAGE_BREAK---\n\n".join(self._md_pages)

    def get_field_aliases(self):
        return {
            "sb_no":    ["SB No", "SB NO"],
            "sb_date":  ["SB Date", "SB DATE"],
            "port_code":["Port Code", "PORT CODE"],
        }

    def get_section_hints(self):
        return {"sb_no": ["SB No"], "sb_date": ["SB Date"]}

    def get_repair_rules(self):
        return [SBDateKeep()]

    def get_custom_repair_engine(self):
        from core.repair import (RepairEngine, TruncateWhitespace,
                                  EmptyStringToNull, NumberStripper)
        return RepairEngine(rules=[TruncateWhitespace(), EmptyStringToNull(),
                                    NumberStripper()])

    # ------------------------------------------------------------------ #
    # finalize — template-driven
    # ------------------------------------------------------------------ #
    def finalize(self, data: Dict[str, Any], schema) -> Dict[str, Any]:
        from loaders.template_loader import load_template
        cfg  = self.config
        tmpl = load_template(cfg.get("template_path",
                             "schemas/shipping_bill_v1_null_template.json"))
        pages = self._md_pages or []

        return {
            "schema_version": "shipping_bill_v1",
            "source": {
                "pdf_filename":  None,
                "document_type": "shipping_bill",
                "page_count":    len(pages),
            },
            "shipping_bill": {
                "common": self._common(pages),
                "pages":  self._all_pages(pages),
            },
            "_meta": {"doc_type": "shipping_bill",
                      "framework_version": cfg.version},
        }

    # ================================================================== #
    # Shared helpers
    # ================================================================== #
    @staticmethod
    def _tables(md: str) -> List[str]:
        return re.findall(r"<table[\s\S]*?</table>", md, re.IGNORECASE)

    @staticmethod
    def _rows(html: str) -> List[List[str]]:
        soup = BeautifulSoup(html, "html.parser")
        return [[td.get_text(" ", strip=True)
                 for td in tr.find_all(["td", "th"])]
                for tr in soup.find_all("tr")]

    @staticmethod
    def _v(rows: List[List[str]], r: int, c: int) -> Optional[str]:
        """Safe value accessor."""
        try:
            val = rows[r][c].strip()
            return val or None
        except IndexError:
            return None

    # ================================================================== #
    # COMMON — header table (identical on every page, parse from page 0)
    # Row layout confirmed:
    #   [0] Port Code | SB No | (colspan)SB Date
    #   [1] INHZA1   | (colspan)56515593 | 15-DEC-24
    #   [2] IEC/Br   | (colspan)3LW...   | 91
    #   [3] GSTIN/TYPE| (colspan)30FRB... GST
    #   [4] CB CODE  | (colspan)TYWHG...
    #   [5] TYPE     | INV | ITEM | (colspan)CONT
    #   [6] Nos      | 8   | (colspan)1 | 8
    #   [7] PKG      | 26  | G.WT | KGS | 99.32
    # ================================================================== #
    def _common(self, pages: List[str]) -> Dict[str, Any]:
        if not pages:
            return {}
        tables = self._tables(pages[0])
        rows   = self._rows(tables[0]) if tables else []

        # Watermark: INV... code in page text before tables
        wm = None
        m = re.search(r"(INV\d{14,})", pages[0])
        if m:
            wm = m.group(1)

        # port_name from section heading line
        port_name = None
        for line in pages[0].split("\n"):
            if "SHIPPING BILL SUMMARY" in line.upper():
                port_name = line.strip().lstrip("#").strip()
                break

        # G.WT — scan row 7 for G.WT label then take next two cells
        gwt_unit = gwt_val = None
        for row in rows:
            for i, cell in enumerate(row):
                if "G.WT" in cell and i + 2 < len(row):
                    gwt_unit = row[i + 1].strip() or None
                    gwt_val  = row[i + 2].strip() or None
                    break

        return {
            "Heading-1":   "SHIPPING BILL",
            "Sub-Heading-1": port_name,
            "port_name":   None,
            "header_ids": {
                "port_code":  self._v(rows, 1, 0),
                "sb_no":      self._v(rows, 1, 1),
                "sb_date":    self._v(rows, 1, 2),
                "IEC":        self._v(rows, 2, 1),
                "Br":         self._v(rows, 2, 2),
                "GSTIN/TYPE": self._v(rows, 3, 1),
                "CB_CODE":    self._v(rows, 4, 1),
                "TYPE": {
                    "NosINV":  self._v(rows, 6, 1),
                    "NosITEM": self._v(rows, 6, 2),
                    "NosCONT": self._v(rows, 6, 3),
                },
                "PKGINV":      self._v(rows, 7, 1),
                "G.WT":       {"unit": gwt_unit, "value": gwt_val},
                "CODE BELOW QR": wm,
            },
            "HEADING-4": None,
            "watermark":  wm,
        }

    # ================================================================== #
    # All 6 pages
    # ================================================================== #
    def _all_pages(self, pages: List[str]) -> List[Dict[str, Any]]:
        fns = [self._p1, self._p2, self._p3, self._p4, self._p5, self._p6]
        return [fn(pages[i] if i < len(pages) else "")
                for i, fn in enumerate(fns)]

    # ================================================================== #
    # Page 1 — PART-I SUMMARY
    # Confirmed 36-row structure (see audit above)
    # ================================================================== #
    def _p1(self, md: str) -> Dict[str, Any]:
        tables = self._tables(md)
        rows   = self._rows(tables[1]) if len(tables) > 1 else []

        v = self._v  # shortcut

        # ── A STATUS (rows 0-4) ─────────────────────────────────────── #
        # row[0] = labels, row[1] = values
        a = {
            "1.MODE":    v(rows, 1, 0),
            "2.ASSESS":  v(rows, 1, 1),
            "3.EXMN":    v(rows, 1, 2),
            "4.JOBBING": v(rows, 1, 3),
            "5.MEIS":    v(rows, 1, 4),
            "6.DBK":     v(rows, 1, 5),
            "7.RODTP":   v(rows, 1, 6),
            "8.LICENCE": v(rows, 1, 7),
            "9.DFRC":    v(rows, 1, 8),
            "10.RE-EXP": v(rows, 1, 9),
            "11.LUT":    v(rows, 1, 10),
            # row[2]: ["12.PORT OF LOADING", "13.COUNTRY OF FINALDESTINATION ..."]
            # row[3]: ["14.STATE OF ORIGIN VERMONT", "15.PORT OF FINAL DESTINATION ..."]
            # row[4]: ["16.PORT OF DISCHARGE ...", "17.COUNTRY OF DISCHARGE ..."]
        }
        # Port/country fields — values are embedded with label in same cell
        for row_i, label_prefix, key in [
            (2, "12.PORT OF LOADING",               "12.PORT OF LOADING"),
            (2, "13.COUNTRY OF FINALDESTINATION",    "13.COUNTRY OF FINALDESTINATIO"),
            (3, "14.STATE OF ORIGIN",                "14.STATE OF ORIGIN"),
            (3, "15.PORT OF FINAL DESTINATION",      "15.PORT OF FINAL DESTINATION"),
            (4, "16.PORT OF DISCHARGE",              "16.PORT OF DISCHARGE"),
            (4, "17.COUNTRY OF DISCHARGE",           "17.COUNTRY OF DISCHARGE"),
        ]:
            if row_i < len(rows):
                for cell in rows[row_i]:
                    if cell.upper().startswith(label_prefix.upper()):
                        val = cell[len(label_prefix):].strip()
                        a[key] = val or None
                        break

        # ── B DECLARAN (rows 6-13) ───────────────────────────────────── #
        # row[6]: B DECLARAN DETAILS | EXPORTER_NAME | CONSIGNEE_NAME
        # row[7]: EXPORTER_LINE2 | CONSIGNEE_LINE2
        # row[8]: EXPORTER_LINE3 | CONSIGNEE_LINE3
        # row[9]: EXPORTER_CITY  | TYPE "Public" | CONSIGNEE_POSTCODE
        # row[10]: "3. AD CODE:" | AD_CODE | "8.GSTIN / TYPE ..."
        # row[11]: "4.RBI WAIVER.." | "" | "9.FOREX BANK A/C NO. ..."
        # row[12]: "5.CB NAME ..."  | ""  | "10.DBK BANK A/C NO. ..."
        # row[13]: "6.AEO" | "" | "11. IFSC NO. ..."
        exp_parts = []
        con_parts = []
        for ri in [6, 7, 8, 9]:
            if ri < len(rows):
                row = rows[ri]
                if ri == 6:
                    # col 1 = exporter name, col 2 = consignee name
                    if len(row) > 1 and row[1].strip():
                        exp_parts.append(row[1].strip())
                    if len(row) > 2 and row[2].strip():
                        con_parts.append(row[2].strip())
                else:
                    if len(row) > 0 and row[0].strip():
                        exp_parts.append(row[0].strip())
                    if len(row) > 1 and row[1].strip():
                        con_parts.append(row[1].strip())

        def _after(cell: str, label: str) -> Optional[str]:
            if label.upper() in cell.upper():
                return cell[cell.upper().index(label.upper()) + len(label):].strip() or None
            return None

        ad_code  = v(rows, 10, 1)
        gstin_cell = v(rows, 10, 2) or ""
        gstin_val  = _after(gstin_cell, "8.GSTIN / TYPE") or _after(gstin_cell, "GSTIN")
        forex_cell = v(rows, 11, 2) or ""
        forex_val  = _after(forex_cell, "9.FOREX BANK A/C NO.")
        dbk_cell   = v(rows, 12, 3) or "" if len(rows) > 12 else ""
        dbk_val    = _after(dbk_cell, "10.DBK BANK A/C NO.")
        cb_cell    = v(rows, 12, 1) or "" if len(rows) > 12 else ""
        cb_name    = _after(cb_cell, "5.CB NAME")
        ifsc_cell  = v(rows, 13, 2) or "" if len(rows) > 13 else ""
        ifsc_val   = _after(ifsc_cell, "11. IFSC NO.")

        b = {
            "1.EXPORTER'S NAME & ADDRESS": "\n".join(exp_parts) or None,
            "2.Type":         v(rows, 9, 2),
            "3. AD CODE:":    ad_code,
            "4.RBI WAIVER NO.& DT": None,
            "5.CB NAME":      cb_name,
            "6.AEO":          None,
            "7.CONSIGNEE NAME & ADDRESS": "\n".join(con_parts) or None,
            "8. GSTIN / TYPE":  gstin_val,
            "9.FOREX BANK A/C NO.": forex_val,
            "10.DBK BANK A/C NO.":  dbk_val,
            "11. IFSC NO.":         ifsc_val,
        }

        # ── C VALUE SUMMARY (rows 14-17) ────────────────────────────── #
        # row[14]: 1.FOB VALUE | 2.FREIGHT | 3.INSURANC | 4.DISCOU | 5.COM | D.EX.PR. | ...
        # row[15]: 265852.58   | 0.0       | ""         | ""       | 0.0   | 4692.44   | 16166.07 | 0.0
        # row[16]: 6.DEDUCTIONS | 7.P/C | "" | 8.DUTY | 9.CESS | 4.IGST VALUE | 5.RODTEP | 6.ROSCTL
        # row[17]: 0.0 | 0.0 | 0.0 | 0.0 | 134717.27 | 1616.61 | 0.0
        c = {
            "1.FOB VALUE":  v(rows, 15, 0),
            "2.FREIGHT":    v(rows, 15, 1),
            "3.INSURANC":   v(rows, 15, 2),
            "4.DISCOU":     v(rows, 15, 3),
            "5.COM":        v(rows, 15, 4),
            "6.DEDUCTIONS": v(rows, 17, 0),
            "7.P/C":        v(rows, 17, 1),
            "8.DUTY":       v(rows, 17, 3),
            "9.CESS":       v(rows, 17, 4),
        }
        d = {
            "1.DBK CLAIM":  v(rows, 15, 5),
            "2.IGST AMT":   v(rows, 15, 6),
            "3.CESS AMT":   v(rows, 15, 7),
            "4.IGST VALUE": v(rows, 17, 5),
            "5.RODTEP AMT": v(rows, 17, 6),
            "6.ROSCTL AMT": v(rows, 17, 7) if len(rows) > 17 and len(rows[17]) > 7 else None,
        }

        # ── E MANIFEST (rows 18-21) ─────────────────────────────────── #
        # row[18]: E MANIFEST | 1.MAWB | 2.MAWB DT | 3.HAWB | 4.HAWB DT | N.O.C. | F.INVOICE | ...
        # row[19]: ""         | ""     | ""         | ""     | ""         | 1 | MI-2351-6827 | 569.4 | EUR
        # row[20]: 4.CIN NO. | 5.CIN DT. | 6.CIN SITE ID | ...
        # row[21]: 34ETCA... | 02-DEC-23 | INHZA1 | ...
        e = {
            "1.MAWB NO.":  v(rows, 19, 0),
            "2.MAWB DT":   v(rows, 19, 1),
            "3.HAWB NO.":  v(rows, 19, 2),
            "4.HAWB DT":   v(rows, 19, 3),
            "N.O.C.":      v(rows, 19, 4),
            "4. CIN NO.":  v(rows, 21, 0),
            "5. CIN DT.":  v(rows, 21, 1),
            "6. CIN SITE ID": v(rows, 21, 2),
        }
        f = {
            "1.SNO":      v(rows, 19, 5),
            "2.INV NO.":  v(rows, 19, 6),
            "3.INV AMT.": v(rows, 19, 7),
            "4.CURRENC":  v(rows, 19, 8),
        }

        # ── I ANNEX (rows 26-28) ─────────────────────────────────────── #
        # row[26]: I.ANNEX | 1.SEAL TYPE | 2.NATURE | 3.NO.PACKETS | 4.CONTAINERS | 5.LOOSE
        # row[27]: FACTORY SEALED | CONTAINERISED | 26 | 0 | 4
        # row[28]: 6.MARKS & NUMBERS | AEO NO ...
        i_sec = {
            "1.SEAL TYPE":       v(rows, 27, 0),
            "2.NATURE OF CARGO": v(rows, 27, 1),
            "3.NO. OF PACKETS":  v(rows, 27, 2),
            "4.NO. OF CONTAINERS": v(rows, 27, 3),
            "5.LOOSE PACKETS":   v(rows, 27, 4),
            "6.MARKS & NUMBERS": v(rows, 28, 1),
        }

        # ── J PROCESS (rows 30-35) ──────────────────────────────────── #
        # row[30]: J.PROCESS | 1.EVENT | 2.DATE | 3.TIME | 4.LEO NO. | 76/260
        # row[31]: 5.Submission | 28-NOV-25 | 00:00 | 6.LEO Date. | 29-NOV-25
        # row[32]: 5.Assessment | ""        | ""    | 8.BRC Realisation Date | 18-SEP-26
        # row[33]: 7.Examination | 29-NOV-25 | 00:00 | "" | ""
        # row[34]: 9.LEO | 29-NOV-25 | 00:00 | "" | ""
        # row[35]: 10.SEZ UNIT Details | ""
        j = {
            "1.EVENT": {
                "5.Submission":  {"DATE": v(rows, 31, 1), "TIME": v(rows, 31, 2)},
                "6.Assessment":  {"DATE": v(rows, 32, 1), "TIME": v(rows, 32, 2)},
                "7.Examination": {"DATE": v(rows, 33, 1), "TIME": v(rows, 33, 2)},
                "9.LEO":         {"DATE": v(rows, 34, 1), "TIME": v(rows, 34, 2)},
            },
            "4.LEO NO.":             v(rows, 30, 5),
            "6.LEO Date.":           v(rows, 31, 4),
            "8.BRC Realisation Date":v(rows, 32, 4),
            "10. SEZ UNIT Details":  v(rows, 35, 1),
        }

        # ── Signature (text, not table) ─────────────────────────────── #
        sig_date = sig_time = sig_reason = sig_loc = None
        for line in md.split("\n"):
            if "Date:" in line and re.search(r"\d{4}\.\d{2}\.\d{2}", line):
                m = re.search(r"(\d{4})\.(\d{2})\.(\d{2}) (\d{2}:\d{2}:\d{2})", line)
                if m:
                    sig_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                    sig_time = m.group(4)
            if line.strip().startswith("Reason:"):
                sig_reason = line.replace("Reason:", "").strip()
            if "Location" in line:
                sig_loc = line.split(":", 1)[-1].strip() or None

        return {
            "page_number": 1,
            "page_label": "PART-I-SHIPPING BILL SUMMARY",
            "HEADING-2": {
                "Title": "PART-I-SHIPPING BILL SUMMARY",
                "SUBHEADINg-2": {
                    "A STATUS": a,
                    "B DECLARAN DETAILS": b,
                    "C VALU SUMMA": c,
                    "D. EX.PR.": d,
                    "E MANIFEST DETAILS": e,
                    "F INVOICE SUMMARY": f,
                    "G. EQUIPMENT DETAILS": {"1.CONTAINER": None, "2.SEAL": None,
                                              "3.DATE": None, "4.S No": None},
                    "H CHALLAN DETAILS":   {"1SR.NO": None, "2.CHALLAN NO": None,
                                              "3.PAYMT DT": None, "4.AMOUNT": None},
                    "I ANNEX DETAILS": i_sec,
                    "J PROCESS DETAILS": j,
                },
            },
            "Signature": {
                "Raw-Text": "Digitally signed by DS CENTRAL BOARD" if sig_reason else None,
                "Date": sig_date, "Time": sig_time,
                "Reason": sig_reason, "Location": sig_loc,
            },
            "HEADING-3": {"Glossary": None},
        }

    # ================================================================== #
    # Page 2 — PART-II INVOICE
    # Confirmed 19-row structure
    # ================================================================== #
    def _p2(self, md: str) -> Dict[str, Any]:
        tables = self._tables(md)
        rows   = self._rows(tables[-1]) if tables else []
        v      = self._v

        # A REF row[1]: sno | inv_no dt | po | loc | contract | ad_code | invterm
        ref = {
            "1.S.No":            v(rows, 1, 0),
            "2.INVOICE No. & Dt.": v(rows, 1, 1),
            "3.P.O.No. & Dt.":   v(rows, 1, 2),
            "4.LoC No. & Dt":    v(rows, 1, 3),
            "5.Contract No.&Dt": v(rows, 1, 4),
            "6.AD code":         v(rows, 1, 5),
            "7.INVTERM":         v(rows, 1, 6),
        }

        # B TRANSACTION rows[3-11]
        # rows[3]: EXPORTER_NAME | BUYER_NAME
        # rows[4]: EXPORTER_LINE2 | BUYER_LINE2
        # rows[5]: EXPORTER_LINE3 | BUYER_LINE3
        # rows[6]: EXPORTER_POST  | BUYER_COUNTRY_POST
        # rows[7]: "" | ""
        # rows[9]: THIRD_PARTY_NAME | ""
        # rows[10]: THIRD_LINE2 | ""
        # rows[11]: THIRD_LINE3 | ""
        def _party(col: int, start: int, end: int) -> Optional[str]:
            parts = []
            for ri in range(start, min(end, len(rows))):
                c = v(rows, ri, col)
                if c:
                    parts.append(c)
            return "\n".join(parts) or None

        b = {
            "1.EXPORTER'S NAME & ADDRESS": _party(0, 3, 8),
            "2.BUYER'S NAME & ADDRESS":    _party(1, 3, 8),
            "3.THIRD PARTY NAME & ADDRESS": _party(0, 9, 12),
            "4.BUYER AEO STATUS": v(rows, 9, 1),
        }

        # C VAL row[12]=labels row[13]=values row[14]=currencies
        c_val = {
            "1.INVOICE VALUE": {"value": v(rows, 13, 0), "currency": v(rows, 14, 0)},
            "2.FOB VALUE":     {"value": v(rows, 13, 1), "currency": v(rows, 14, 1)},
            "3FREIGHT":        {"value": v(rows, 13, 2), "currency": v(rows, 14, 2)},
            "4.INSURANCE":     {"value": v(rows, 13, 3), "currency": v(rows, 14, 3)},
            "5DISCOUNT":       v(rows, 13, 4),
            "6.COMMISON":      v(rows, 13, 5),
            "7.DEDUCT":        v(rows, 13, 6),
            "8.P/C":           v(rows, 13, 7),
            "9.EXCHANGE RATE": v(rows, 13, 8) if len(rows) > 13 and len(rows[13]) > 8 else None,
        }

        # D ITEM row[16]=data
        col_map = self.config.get("item_detail_cols", {
            "1.ItemSNo": 0, "2.HS CD": 1, "3.DESCRIPTION": 2,
            "4.QUANTITY": 3, "5.UQC": 4, "6.RATE": 5, "7.VALUE(F/C)": 6,
        })
        items = []
        if len(rows) > 16 and rows[16] and re.match(r"^\d+$", rows[16][0].strip()):
            items.append({k: v(rows, 16, c) for k, c in col_map.items()})

        return {
            "page_number": 2,
            "page_label": "PART-II-INVOICE DETAILS",
            "HEADING-2": {
                "Title": "PART - II - INVOICE DETAILS",
                "SUBHEADINg-2": {
                    "A. REF": [ref],
                    "B. TRANSACTION PARTIES": b,
                    "C. VAL DTLS": c_val,
                    "D. ITEM DETAILS": items or [{}],
                },
            },
            "HEADING-3": {"Glossary": None},
        }

    # ================================================================== #
    # Page 3 — PART-III ITEM DETAILS
    # table[0]=header, table[1]=items (8 rows), table[2]=glossary
    # row[0]=col headers, row[1]=data, row[2]=extra field names,
    # row[3]=extra values, row[4]=scheme names, row[5]=scheme values,
    # row[6]=pt/comp names, row[7]=pt/comp values
    # ================================================================== #
    def _p3(self, md: str) -> Dict[str, Any]:
        tables = self._tables(md)
        rows   = self._rows(tables[1]) if len(tables) > 1 else []
        v      = self._v

        if not rows or len(rows) < 2:
            return {"page_number": 3, "page_label": "PART-III-ITEM DETAILS",
                    "HEADING-2": {"Title": "PART - III - ITEM DETAILS",
                                  "SUBHEADINg-2": {"Invoice(1/1)": [{}]}},
                    "HEADING-3": {"Glossary": None}}

        # row[0]: headers  row[1]: main data values
        item = {
            "1INVSN":       v(rows, 1, 0),
            "2ITEMSN":      v(rows, 1, 1),
            "3.HS CD":      v(rows, 1, 2),
            "4.DESCRIPTION":v(rows, 1, 3),
            "5.QUANTITY":   v(rows, 1, 4),
            "6UQC":         v(rows, 1, 5),
            "7.RATE":       v(rows, 1, 6),
            "8VALUE(F/C)":  v(rows, 1, 7),
            "9.FOB (INR)":  v(rows, 1, 8),
            "10.PMV":       v(rows, 1, 9),
        }
        # row[2]: extra col headers  row[3]: extra values
        extra_hdrs = rows[2] if len(rows) > 2 else []
        extra_vals = rows[3] if len(rows) > 3 else []
        for i, hdr in enumerate(extra_hdrs):
            if hdr.strip():
                item[hdr.strip()] = extra_vals[i].strip() if i < len(extra_vals) else None

        # row[4]: scheme/origin headers  row[5]: values
        scheme_hdrs = rows[4] if len(rows) > 4 else []
        scheme_vals = rows[5] if len(rows) > 5 else []
        for i, hdr in enumerate(scheme_hdrs):
            if hdr.strip():
                item[hdr.strip()] = scheme_vals[i].strip() if i < len(scheme_vals) else None

        # row[6]: pt/comp headers  row[7]: values
        pt_hdrs = rows[6] if len(rows) > 6 else []
        pt_vals = rows[7] if len(rows) > 7 else []
        for i, hdr in enumerate(pt_hdrs):
            if hdr.strip():
                item[hdr.strip()] = pt_vals[i].strip() if i < len(pt_vals) else None

        return {
            "page_number": 3,
            "page_label": "PART-III-ITEM DETAILS",
            "HEADING-2": {
                "Title": "PART - III - ITEM DETAILS",
                "SUBHEADINg-2": {"Invoice(1/1)": [item]},
            },
            "HEADING-3": {"Glossary": None},
        }

    # ================================================================== #
    # Page 4 — PART-IV SCHEME DETAILS
    # ================================================================== #
    def _p4(self, md: str) -> Dict[str, Any]:
        tables = self._tables(md)
        rows   = self._rows(tables[-1]) if tables else []
        v      = self._v

        def _section(trigger: str) -> List[List[str]]:
            """Return data rows under a section header (trigger text)."""
            capturing, result = False, []
            for row in rows:
                txt = " ".join(row).upper()
                if trigger.upper() in txt:
                    capturing = True
                    continue
                if capturing:
                    # Stop at next section header
                    if any(t in txt for t in [
                        "A. DRAWBACK","B. AA","C. JOBBING","D. SINGLE",
                        "E. SINGLE","F. SINGLE","G. SUPPORTING","H. INVOICE",
                        "I. CONTAINER","J.AR4","K. THIRD","L. ITEM","M. RODTEP"
                    ]) and trigger.upper() not in txt:
                        break
                    if any(cell.strip() for cell in row):
                        result.append(row)
            return result

        def _parse_rows(rows_in, field_map):
            """Turn data rows into list of dicts using field_map {name: col_idx}."""
            result = []
            for row in rows_in:
                if row and re.match(r"^\d+$", row[0].strip()):
                    result.append({k: v(row, None, c) if False else
                                   (row[c].strip() if c < len(row) else None)
                                   for k, c in field_map.items()})
            return result

        # A DRAWBACK
        dbk = _parse_rows(_section("A. DRAWBACK"), {
            "1.INV SNO":0,"2.ITEM SNO":1,"3.DBK SNO.":2,"4.QTY/WT":3,
            "5.VALUE":4,"6.RATE":5,"7.DBK AMT":6,"8.STALEV":7,
            "9.CENLEV":8,"10.ROSCTL AMT":9})

        # D SINGLE WINDOW
        swd = _parse_rows(_section("D. SINGLE WINDOW DECLARATION"), {
            "1.INVSN":0,"2.ITMSN":1,"3.INFO":2,"4.QUALIFIER":3,
            "5.INFO CD":4,"6.INFO TEXT":5,"7.INFO MSR":6,"8.UQC":7})
        # Remove header-like rows
        swd = [r for r in swd if r.get("1.INVSN") not in (None,"1.INVSN")]

        # G SUPPORTING DOCUMENTS
        g = _parse_rows(_section("G.SUPPORTING"), {
            "1.INVSN":0,"2.ITMSNO":1,"3 DOCTYPCD":2,"4. ICEGATE ID":3,
            "5. IRN":4,"6.PARTY CD":5,"7.ISSUE PLA":6,"8.ISS DT":7,"9.EXP DT":8})

        # H INVOICE
        h = _parse_rows(_section("H. INVOICE"), {
            "1.SNO":0,"2.INVOICE NO":1,"3.INVOICE AMOUNT":2,"4.CURRENCY":3})

        # M RODTEP
        rod = _parse_rows(_section("M. RODTEP"), {
            "1.INVSN":0,"2.ITMSN":1,"3. QUANTITY":2,"4. UQC":3,
            "5. NO. OF  UNITS":4,"6. VALUE":5})

        return {
            "page_number": 4,
            "page_label": "PART-IV-EXPORT SCHEME DETAILS",
            "HEADING-2": {
                "Title": "PART - IV - EXPORT SCHEME DETAILS",
                "SUBHEADINg-2": {
                    "OTHER ADDIIONAL INFORMATION": [{
                        "A. DRAWBACK & ROSL CLAIM":  dbk or [{}],
                        "B. AA / DFIA LICENCE DETAILS": [{}],
                        "C. JOBBING DETAILS":         [{}],
                        "D. SINGLE WINDOW DECLARATION": swd or [{}],
                        "E. SINGLE WINDOW DECLARATION - CONSTITUENTS": [{}],
                        "F. SINGLE WINDOW DECLARATION - CONTROL": [{}],
                        "G. SUPPORTING DOCUMENTS":   g or [{}],
                        "H. INVOICE DETAILS":        h or [{}],
                        "I. CONTAINER DETAILS":      [{}],
                        "J.AR4 DETAILS":             [{}],
                        "K. THIRD PARTY DETAILS":    [{}],
                        "L. ITEM MANUFACTURER/PRODUCER/GROWER DETAILS": [{}],
                        "M. RODTEP DETAILS":         rod or [{}],
                    }],
                },
            },
            "HEADING-3": {"Glossary": None},
        }

    # ================================================================== #
    # Page 5 — PART-V REEXPORT
    # ================================================================== #
    def _p5(self, md: str) -> Dict[str, Any]:
        tables = self._tables(md)
        # Find the re-export table (has N. REEXPORT header)
        reexp = []
        for t in tables:
            if "REEXPORT" in t.upper():
                rows = self._rows(t)
                for row in rows:
                    if row and re.match(r"^\d+$", row[0].strip()):
                        reexp.append({
                            "1.INVS": row[0].strip(),
                            "2.ITMSN": row[1] if len(row)>1 else None,
                            "3.BE SITE ID": row[2] if len(row)>2 else None,
                            "4.BE NUMBER":  row[3] if len(row)>3 else None,
                            "5.BE DATE":    row[4] if len(row)>4 else None,
                            "6.BE INV SNO": row[5] if len(row)>5 else None,
                            "7.BE ITEM S":  row[6] if len(row)>6 else None,
                            "8. BE QTY":    row[7] if len(row)>7 else None,
                            "9. BE UQC":    row[8] if len(row)>8 else None,
                        })
        return {
            "page_number": 5, "page_label": "PART-V-REEXPORT",
            "HEADING-2": {"Title": "PART - V",
                          "SUBHEADINg-2": {"N. REEXPORT DETAILS": reexp or [{}]}},
            "HEADING-3": {"Glossary": None},
        }

    # ================================================================== #
    # Page 6 — PART-V DECLARATIONS
    # ================================================================== #
    def _p6(self, md: str) -> Dict[str, Any]:
        tables = self._tables(md)
        rows   = self._rows(tables[-1]) if tables else []
        v      = self._v

        date_ = place = cha = None
        for row in rows:
            txt = " ".join(row)
            m = re.search(r"CHA NAME[：:]\s*(\S+)", txt)
            if m:
                cha = m.group(1)

        return {
            "page_number": 6, "page_label": "PART-V-DECLARATIONS",
            "HEADING-2": {
                "Title": "PART - V - DECLARATIONS",
                "SUBHEADINg-2": {
                    "A. DECLARATION STATEMENT": None,
                    "B. AUTHORIZED SIGNATORY": {
                        "DATE": v(rows, 1, 0),
                        "PLACE": v(rows, 2, 0),
                        "AUTHORIZED SIGNATORY": v(rows, 1, 1),
                        "CHA NAME": cha,
                    },
                },
            },
        }
