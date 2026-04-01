from __future__ import annotations

import unittest

from data_source import _infer_value_unit_scale, parse_filing_cover_metadata


class DataSourceValueTests(unittest.TestCase):
    def test_parse_filing_cover_metadata_extracts_totals(self) -> None:
        xml = """
        <edgarSubmission>
            <formData>
                <coverPage>
                    <tableEntryTotal>110</tableEntryTotal>
                    <tableValueTotal>274160086701</tableValueTotal>
                </coverPage>
            </formData>
        </edgarSubmission>
        """
        metadata = parse_filing_cover_metadata(xml)
        self.assertEqual(metadata["table_entry_total"], 110)
        self.assertEqual(metadata["official_total_value_usd"], 274160086701.0)

    def test_infer_value_unit_scale_detects_usd_values(self) -> None:
        self.assertEqual(_infer_value_unit_scale(274160086701.0, 274160086701.0), 1.0)

    def test_infer_value_unit_scale_detects_thousand_usd_values(self) -> None:
        self.assertEqual(_infer_value_unit_scale(274160086.701, 274160086701.0), 1000.0)


if __name__ == "__main__":
    unittest.main()
