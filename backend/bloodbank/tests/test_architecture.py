"""Giữ đúng phân lớp MVT + service: view không ghi DB, template không có script/style inline, CSP không nới lỏng."""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from bloodbank.middleware import SecurityHeadersMiddleware

BACKEND = Path(settings.BASE_DIR)
VIEW_FILES = sorted((BACKEND / "bloodbank" / "views").glob("*.py")) + [BACKEND / "accounts" / "views.py"]
TEMPLATES = sorted((BACKEND / "templates").rglob("*.html"))


class ArchitectureTests(SimpleTestCase):
    def test_views_do_not_write_to_database(self):
        """Ghi DB (save/create/delete/update…) phải đi qua tầng service — view chỉ đọc, gọi form/service, render."""
        write = re.compile(r"\.(save|delete|bulk_create|bulk_update|get_or_create|update_or_create)\(|"
                           r"objects\.create\(|\b(qs|queryset)\.update\(")
        offenders = [f"{p.name}:{i}: {line.strip()}" for p in VIEW_FILES
                     for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if write.search(line)]
        self.assertEqual(offenders, [])

    def test_views_do_not_import_private_names(self):
        private = re.compile(r"^\s*from \S+ import .*\b_[a-z]\w*", re.M)
        offenders = [p.name for p in VIEW_FILES if private.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])

    def test_templates_have_no_inline_script_or_style(self):
        bad = re.compile(r'\sstyle=|<style\b|<script(?![^>]*\bsrc=)|\son[a-z]+="')
        offenders = [f"{p.relative_to(BACKEND)}:{i}" for p in TEMPLATES
                     for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if bad.search(line)]
        self.assertEqual(offenders, [])

    def test_template_comments_are_single_line(self):
        """{# … #} của Django chỉ có tác dụng trên 1 dòng; viết nhiều dòng sẽ in nguyên văn ra trang → dùng {% comment %}."""
        offenders = [f"{p.relative_to(BACKEND)}:{i}" for p in TEMPLATES
                     for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                     if "{#" in line and "#}" not in line.split("{#", 1)[1]]
        self.assertEqual(offenders, [])

    def test_csp_has_no_unsafe_directives(self):
        self.assertNotIn("unsafe-inline", SecurityHeadersMiddleware.CSP)
        self.assertNotIn("unsafe-eval", SecurityHeadersMiddleware.CSP)
