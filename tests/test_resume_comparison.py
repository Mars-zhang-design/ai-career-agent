"""Actual resume comparison stays complete and safe without model calls."""
from html.parser import HTMLParser
import unittest
from unittest.mock import patch

from resume_comparison import compare_resume


class HighlightReader(HTMLParser):
    """Read rendered content without treating escaped user markup as elements."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.tags = []
        self.attributes = []
        self.feed(text)
        self.close()

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_endtag(self, tag):
        self.tags.append(tag)


class ResumeComparisonTests(unittest.TestCase):
    def assert_lossless(self, before, after):
        blocks = compare_resume(before, after)
        for side, expected in (("before", before), ("after", after)):
            self.assertEqual("".join(block[side] for block in blocks), expected)
            rendered = HighlightReader("".join(block[side + "_html"] for block in blocks))
            self.assertEqual("".join(rendered.text), expected)
            self.assertTrue(set(rendered.tags).issubset({"del", "ins"}))
            self.assertEqual(rendered.attributes, [])
        return blocks

    def test_multiline_chinese_blank_lines_and_trailing_newlines_are_preserved(self):
        before = "姓名：测试\r\n\r\n项目经验\n使用 Python 开发接口。\n\n教育经历\r\n本科\r\n"
        after = "姓名：测试\r\n\r\n项目经验\n基于 Python 实现接口与参数校验。\n\n教育经历\r\n本科\r\n"
        blocks = self.assert_lossless(before, after)
        self.assertTrue(any(block["kind"] == "equal" for block in blocks))
        self.assertTrue(any(block["kind"] == "replace" for block in blocks))

    def test_literal_html_scripts_and_entities_cannot_become_markup(self):
        before = '<script>alert("private")</script>\n<img src=x onerror=alert(1)> & &#x41;\n'
        after = '</div><iframe src="https://invalid.example"></iframe>\n<ins>本人文字</ins> &amp;\n'
        blocks = self.assert_lossless(before, after)
        rendered = "".join(block[side] for block in blocks for side in ("before_html", "after_html"))
        self.assertNotIn("<script", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("<iframe", rendered)
        self.assertIn("&lt;", rendered)
        self.assertIn("&amp;", rendered)

    def test_inserted_content_has_empty_original_and_only_addition_markup(self):
        blocks = self.assert_lossless("个人简介\n教育经历\n", "个人简介\n新增项目经历\n教育经历\n")
        changes = [block for block in blocks if block["kind"] != "equal"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "insert")
        self.assertEqual(changes[0]["before_html"], "")
        self.assertIn("<ins>", changes[0]["after_html"])

    def test_deleted_content_has_empty_result_and_only_deletion_markup(self):
        blocks = self.assert_lossless("个人简介\n重复自评\n教育经历\n", "个人简介\n教育经历\n")
        changes = [block for block in blocks if block["kind"] != "equal"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "delete")
        self.assertEqual(changes[0]["after_html"], "")
        self.assertIn("<del>", changes[0]["before_html"])

    def test_identical_text_has_no_change_markup(self):
        original = "Python <基础> & SQL\n\n原样保留。\n"
        blocks = self.assert_lossless(original, original)
        self.assertTrue(all(block["kind"] == "equal" for block in blocks))
        for block in blocks:
            self.assertEqual(HighlightReader(block["before_html"]).tags, [])
            self.assertEqual(HighlightReader(block["after_html"]).tags, [])

    def test_empty_and_entire_resume_replacements_are_lossless(self):
        for before, after in (("", ""), ("", "新简历\n"), ("原简历\n", ""),
                              ("原简历没有换行", "不同版本没有换行")):
            with self.subTest(before=before, after=after):
                self.assert_lossless(before, after)

    def test_whitespace_only_changes_and_unicode_line_breaks_are_preserved(self):
        self.assert_lossless("标题\u2028正文\n\n  缩进\t结束\n", "标题\u2028正文\n\n 缩进  结束")

    def test_long_repetitive_paragraph_uses_bounded_lossless_highlighting(self):
        from difflib import SequenceMatcher
        before = "原文：" + "重复经历<&>" * 1000
        after = "新文：" + "重复经历<&>" * 1000 + "实际表达优化"
        # One line-level comparison is enough; expensive character matching
        # must not run on a long paragraph with heavily repeated characters.
        with patch("resume_comparison.SequenceMatcher", wraps=SequenceMatcher) as matching:
            blocks = self.assert_lossless(before, after)
        self.assertEqual(matching.call_count, 1)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(HighlightReader(blocks[0]["before_html"]).tags, ["del", "del"])
        self.assertEqual(HighlightReader(blocks[0]["after_html"]).tags, ["ins", "ins"])


class ComparisonViewTests(unittest.TestCase):
    def test_switch_to_full_comparison_shows_untouched_resume_sections(self):
        from streamlit.testing.v1 import AppTest
        original = "教育经历保持不变\n原项目说明\n"
        polished = "教育经历保持不变\n改写后的项目说明\n"
        app = AppTest.from_string(
            "from resume_comparison import render_resume_comparison\n"
            f"render_resume_comparison({original!a}, {polished!a})\n"
        ).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="resume_compare").value, "只看改动")
        self.assertFalse(any("教育经历保持不变" in item.value for item in app.markdown))
        app.radio(key="resume_compare").set_value("完整对照").run()
        self.assertFalse(app.exception)
        panels = [item.value for item in app.markdown if '<div class="resume-comparison">' in item.value]
        self.assertEqual(len(panels), 2)
        self.assertTrue(all("教育经历保持不变" in panel for panel in panels))
        self.assertTrue(any(item.value == "你输入的简历" for item in app.caption))
        self.assertTrue(any(item.value == "美化后的简历" for item in app.caption))


if __name__ == "__main__":
    unittest.main()
