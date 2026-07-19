import unittest

from webapp.routes_user import build_ord_report_rows


class OrdReportRowsTest(unittest.TestCase):
    def test_build_ord_report_rows_uses_real_post_link_and_channel_title(self):
        rows = [
            {
                "erid": "ERID-1",
                "direct_link": "https://t.me/testchannel/123",
                "channel_title": "Мой канал",
                "channel_id": "@testchannel",
                "views_count": 10,
                "published_at": "2026-07-19T10:00:00+00:00",
            },
            {
                "erid": "ERID-2",
                "direct_link": "",
                "channel_title": None,
                "channel_id": "@emptychannel",
                "views_count": 0,
                "published_at": None,
            },
        ]

        result = build_ord_report_rows(rows)

        self.assertEqual(result[0]["post_link"], "https://t.me/testchannel/123")
        self.assertEqual(result[0]["channel_title"], "Мой канал")
        self.assertEqual(result[0]["platform"], "https://t.me/testchannel/123")
        self.assertEqual(result[0]["channel_type"], "Мой канал")
        self.assertEqual(result[1]["post_link"], "")
        self.assertEqual(result[1]["channel_title"], "")
        self.assertEqual(result[1]["channel_type"], "@emptychannel")


if __name__ == "__main__":
    unittest.main()
