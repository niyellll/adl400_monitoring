"""Validate Excel downloads use separate, readable columns and proper CSV delimiter."""
import io
import unittest
import pandas as pd
from openpyxl import load_workbook

from export_utils import excel_csv, formatted_xlsx


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({
            "ts": pd.to_datetime(["2026-11-08 04:43:00", "2026-11-08 04:44:00"]),
            "slave": [1, 1],
            "Tenant": ["Uniqlo", "Uniqlo"],
            "kw": [8.177, 8.743],
            "v_a": [227.5, 227.7],
            "i_a": [13.74, 14.75],
        })

    def test_excel_has_separate_columns_and_formatting(self):
        data = formatted_xlsx(self.df, "Pembacaan Per Menit")
        wb = load_workbook(io.BytesIO(data), read_only=False)
        sheet = wb["Pembacaan Per Menit"]
        self.assertEqual(sheet["A1"].value, "ts")
        self.assertEqual(sheet["B1"].value, "slave")
        self.assertEqual(sheet["C1"].value, "Tenant")
        self.assertEqual(sheet["C2"].value, "Uniqlo")
        self.assertAlmostEqual(sheet["D2"].value, 8.177)
        self.assertEqual(sheet["A2"].value, "2026-11-08 04:43:00")
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertGreater(sheet.column_dimensions["A"].width, 15)
        self.assertGreater(sheet.column_dimensions["C"].width, 10)
        self.assertTrue(sheet.tables)

    def test_csv_delimiter_and_bom(self):
        result = excel_csv(self.df).decode("utf-8-sig")
        self.assertTrue(result.startswith("sep=;\r\n"))
        self.assertIn("ts;slave;Tenant;kw;v_a;i_a", result)
        self.assertIn("8,177", result)

    def test_empty_rows_still_have_headers(self):
        result = formatted_xlsx(self.df.iloc[:0], "Empty")
        ws = load_workbook(io.BytesIO(result))["Empty"]
        self.assertEqual(ws["C1"].value, "Tenant")


if __name__ == "__main__":
    unittest.main()
