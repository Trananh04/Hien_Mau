"""Lưu file tĩnh khi chạy thật: nén + tên kèm mã băm (cache trình duyệt 1 năm), bỏ qua chú thích sourcemap.

Thư viện đóng gói sẵn (vd. vendor/maplibre) có dòng `//# sourceMappingURL=…map` trỏ tới file .map không đi kèm — bản
gốc của Django coi đó là lỗi và dừng collectstatic. File .map chỉ dùng khi gỡ lỗi, nên không cần băm tên.
"""
from whitenoise.storage import CompressedManifestStaticFilesStorage


def _no_sourcemap(patterns):
    out = []
    for ext, items in patterns:
        kept = tuple(p for p in items if "sourceMappingURL" not in (p[0] if isinstance(p, tuple) else p))
        out.append((ext, kept))
    return tuple(out)


class StaticStorage(CompressedManifestStaticFilesStorage):
    patterns = _no_sourcemap(CompressedManifestStaticFilesStorage.patterns)
    manifest_strict = False            # template trỏ file không có trong manifest → dùng tên gốc thay vì lỗi 500
