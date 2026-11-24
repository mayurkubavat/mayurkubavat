import json
from pathlib import Path
import tempfile
import unittest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_latest_post as ulp  # noqa: E402


SAMPLE_FEED = {
    "feed": {
        "entry": [
            {
                "title": {
                    "$t": "Building svlang: A Pure-Rust SystemVerilog Front End for DV, Formal and AI Tools"
                },
                "published": {"$t": "2026-11-14T11:30:32.000-08:00"},
                "category": [
                    {"term": "AI"},
                    {"term": "Formal Verification"},
                    {"term": "Software Engineering"},
                    {"term": "SystemVerilog"},
                    {"term": "Tools"},
                    {"term": "UVM"},
                ],
                "link": [
                    {
                        "rel": "replies",
                        "href": "https://dvhandbook.blogspot.com/feeds/123/comments/default",
                    },
                    {
                        "rel": "alternate",
                        "href": "https://dvhandbook.blogspot.com/2026/11/building-svlang-pure-rust-systemverilog.html",
                    },
                ],
                "content": {
                    "$t": (
                        "<p>Every DV tool that reads SystemVerilog needs a front end: something that takes "
                        "file lists, macros and source text and returns a design the tool can reason about. "
                        '<a href="https://github.com/mayurkubavat/svlang">svlang</a> is my pure-Rust '
                        "IEEE 1800-2023 front end.</p><p>Second paragraph.</p>"
                    )
                },
            }
        ]
    }
}


class UpdateLatestPostTests(unittest.TestCase):
    def test_parse_latest_entry_matches_dvhandbook_card(self) -> None:
        post = ulp.parse_latest_entry(SAMPLE_FEED)
        self.assertEqual(
            post["title"],
            "Building svlang: A Pure-Rust SystemVerilog Front End for DV, Formal and AI Tools",
        )
        self.assertEqual(
            post["url"],
            "https://dvhandbook.blogspot.com/2026/11/building-svlang-pure-rust-systemverilog.html",
        )
        self.assertEqual(post["date"], "Nov 14, 2026")
        self.assertEqual(
            post["excerpt"],
            "Every DV tool that reads SystemVerilog needs a front end: something that takes "
            "file lists, macros and source text and returns a design the tool can reason about.",
        )
        self.assertEqual(post["label"], "UVM")
        self.assertEqual(post["label_url"], "https://dvhandbook.blogspot.com/p/uvm.html")

    def test_single_digit_day_and_decimal_versions_in_excerpt(self) -> None:
        self.assertEqual(ulp.format_date("2026-09-06T08:00:00-07:00"), "Sep 6, 2026")
        html_body = (
            "<p>IEEE 1800.2 UVM and SystemC 3.0.3 e.g. TLM-2.0 sockets compile cleanly in CI. "
            "Next sentence starts here.</p>"
        )
        self.assertEqual(
            ulp.extract_excerpt(html_body),
            "IEEE 1800.2 UVM and SystemC 3.0.3 e.g. TLM-2.0 sockets compile cleanly in CI.",
        )

    def test_non_hub_label_falls_back_to_blogger_label_search(self) -> None:
        label, url = ulp.select_primary_label(["Formal Verification", "AI"]) or ("", "")
        self.assertEqual(label, "Formal Verification")
        self.assertEqual(
            url,
            "https://dvhandbook.blogspot.com/search/label/Formal%20Verification",
        )

    def test_cli_writes_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            feed_file = tmp_dir / "feed.json"
            readme_file = tmp_dir / "README.md"
            feed_file.write_text(json.dumps(SAMPLE_FEED), encoding="utf-8")

            rc = ulp.main(["--feed-file", str(feed_file), "--readme", str(readme_file)])
            self.assertEqual(rc, 0)
            content = readme_file.read_text(encoding="utf-8")
            self.assertIn("<!-- BLOG-POST-START -->", content)
            self.assertIn("### [Building svlang:", content)
            self.assertIn("Nov 14, 2026", content)
            self.assertIn(">UVM</a>", content)

            # Second run should keep exact byte-identical output
            rc2 = ulp.main(["--feed-file", str(feed_file), "--readme", str(readme_file)])
            self.assertEqual(rc2, 0)
            self.assertEqual(readme_file.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
