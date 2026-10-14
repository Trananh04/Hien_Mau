"""Chạy tác vụ định kỳ. Một lần: `python manage.py run_jobs`; lặp: `python manage.py run_jobs --loop 300`."""
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from bloodbank.services import jobs


class Command(BaseCommand):
    help = "Hết hạn yêu cầu liên viện, tự hủy đề nghị quá hạn phản hồi, nhắc yêu cầu cần máu chưa xác minh."

    def add_arguments(self, parser):
        parser.add_argument("--loop", type=int, default=0, help="Lặp lại sau mỗi N giây (0 = chạy một lần).")

    def handle(self, *args, loop=0, **options):
        while True:
            try:
                result = jobs.run_all()
                self.stdout.write(f"[{timezone.localtime():%Y-%m-%d %H:%M:%S}] {result}")
            except Exception as exc:  # một lần lỗi không được dừng vòng lặp
                self.stderr.write(f"[{timezone.localtime():%Y-%m-%d %H:%M:%S}] Lỗi tác vụ định kỳ: {exc!r}")
                if not loop:
                    raise
            if not loop:
                return
            self.stdout.flush()
            time.sleep(loop)
            close_old_connections()  # kết nối DB mới cho vòng sau (DB khởi động lại không làm chết tiến trình)
