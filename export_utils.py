"""Excel-friendly exports for meter reading and billing tables.

XLSX is recommended for Excel. CSV includes an Excel delimiter directive so
Indonesian regional settings open the file in separate columns.
"""
import io

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo


def excel_csv(frame):
    """UTF-8 BOM; Excel recognizes sep=; regardless of locale delimiter."""
    raw = frame.to_csv(index=False, sep=";", decimal=",", lineterminator="\r\n")
    return ("\ufeffsep=;\r\n" + raw).encode("utf-8")


def formatted_xlsx(frame, sheet_name="Data Monitoring"):
    """True Excel workbook, separate columns, frozen header, filters and units."""
    buf = io.BytesIO()
    clean = frame.copy()
    for column in clean.columns:
        if pd.api.types.is_datetime64_any_dtype(clean[column]):
            clean[column] = clean[column].dt.strftime("%Y-%m-%d %H:%M:%S")
    clean = clean.astype(object).where(pd.notna(clean), None)
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        clean.to_excel(writer, sheet_name=sheet_name[:31], index=False)
        ws = writer.sheets[sheet_name[:31]]
        ws.freeze_panes = "A2"
        ws.sheet_view.showGridLines = False
        ws.row_dimensions[1].height = 30
        for col_num, column in enumerate(clean.columns, 1):
            letter = get_column_letter(col_num)
            values = clean[column].head(250).astype(str)
            max_len = max([len(str(column)), *(len(v) for v in values)] or [10])
            ws.column_dimensions[letter].width = min(34, max(15, max_len + 3))
            cell = ws.cell(1, col_num)
            cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for row_num in range(2, len(clean) + 2):
                body = ws.cell(row_num, col_num)
                body.alignment = Alignment(vertical="center")
                if isinstance(body.value, (int, float)) and not isinstance(body.value, bool):
                    body.number_format = '#,##0.000' if any(
                        word in str(column).lower()
                        for word in ("kwh", "kw", "pf", "arus", "tegangan", "rate", "tarif", "pemakaian", "v_", "i_")
                    ) else '#,##0.00'
        if len(clean) > 0 and len(clean.columns) > 0:
            table = Table(displayName="MonitoringData", ref=f"A1:{get_column_letter(len(clean.columns))}{len(clean) + 1}")
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True,
                                                   showFirstColumn=False, showLastColumn=False)
            ws.add_table(table)
        elif len(clean.columns) > 0:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(clean.columns))}1"
    return buf.getvalue()
