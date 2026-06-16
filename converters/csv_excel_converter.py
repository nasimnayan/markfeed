"""Convert CSV / Excel (.xls, .xlsx) files to Markdown tables via pandas.

Pure tabular conversion — no OCR, no subprocess crash risk. Each Excel sheet (or
the single CSV) becomes a section with a heading and a Markdown pipe table, mirroring
the {markdown, sections} contract used by converters/docx_converter.py.
"""

import io

import pandas as pd

from converters.stats import count_formulas, count_images, count_md_tables, text_stats


def convert_csv_excel(file_bytes: bytes, file_type: str) -> dict:
    """Convert a .csv/.xls/.xlsx file to Markdown tables.

    Returns a dict with keys: markdown (str), sections (list of per-section stat dicts).
    Each sheet (or the single CSV) becomes a section with a heading and a table.
    """
    frames = _read_frames(file_bytes, file_type)

    parts = []
    sections = []
    multi = len(frames) > 1 or file_type != "csv"
    for name, df in frames.items():
        body = _frame_to_markdown(df)
        # A single CSV needs no heading; workbooks label each sheet.
        section_md = f"## {name}\n\n{body}" if multi else body
        parts.append(section_md)
        sections.append(_build_section_row(name, section_md, file_type))

    markdown = "\n\n".join(parts).strip()
    return {"markdown": markdown, "sections": sections}


def _read_frames(file_bytes: bytes, file_type: str) -> dict:
    """Return an ordered {sheet_name: DataFrame} mapping for the given file."""
    buf = io.BytesIO(file_bytes)
    if file_type == "csv":
        return {"Sheet 1": pd.read_csv(buf)}
    engine = "openpyxl" if file_type == "xlsx" else "xlrd"
    # sheet_name=None returns a dict of every sheet, preserving workbook order.
    return pd.read_excel(buf, sheet_name=None, engine=engine)


def _frame_to_markdown(df: pd.DataFrame) -> str:
    """Render a DataFrame as a Markdown table, with clean empty cells."""
    if df.empty:
        return "*No data*"
    # fillna keeps NaN out of the table; index is dropped (row data only).
    return df.fillna("").to_markdown(index=False)


def _build_section_row(label: str, markdown: str, source: str) -> dict:
    row = {"label": label, "source": source}
    row.update(text_stats(markdown))
    row["image_count"] = count_images(markdown)
    row["table_count"] = count_md_tables(markdown)
    row["formula_count"] = count_formulas(markdown)
    return row
