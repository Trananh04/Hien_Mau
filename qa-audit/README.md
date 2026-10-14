# qa-audit — Bộ kiểm thử & audit có thể chạy lại

Mọi kiểm thử chạy trên **môi trường QA cô lập**: Docker project `hienmau-qa`, DB riêng, cổng `127.0.0.1:8091`, dữ liệu giả do `seed_demo` tạo. Không đụng môi trường dev (8080) hay production. Phạm vi và giới hạn an toàn nằm trong `config/scope.json`. Các script đọc file này và từ chối chạy khi target nằm ngoài phạm vi.

## Cấu trúc
| Thư mục | Nội dung |
|---|---|
| `config/` | `scope.json` (phạm vi, giới hạn, phê duyệt), `docker-compose.qa.yml`, `qa.env.example` (tự tạo `qa.env`, đã gitignore) |
| `inventory/` | `routes.json`: 80 route + vai trò, sinh từ code |
| `scripts/` | `build_inventory.py`, `qa_lib.py` (client HTTP + bằng chứng đã che dữ liệu nhạy cảm), `confirm_live.py` |
| `playwright/` | `ui_smoke.py`: hiển thị 40 trang × 4 vai trò × 2 khung nhìn · `ui_flows.py`: 11 luồng thao tác thật (điền form, hộp thoại xác nhận, bàn phím, mobile) + quét trợ năng axe-core |
| `security/raw/` | Kết quả thô Semgrep / ZAP / Nuclei / check --deploy |
| `evidence/` | Log test, ảnh chụp, request/response đã che thông tin nhạy cảm |
| `reports/` | 6 báo cáo `01`…`06` |
| `gherkin/`, `testcases/` | Dành cho vòng sau (Hercules: Blocked) |

Test hồi quy cho các lỗi đã tìm và đã sửa nằm trong ứng dụng: `backend/bloodbank/tests/test_qa_audit.py` (tag `qa_audit`, chạy cùng bộ test chính).

## Chạy (Windows Git Bash / WSL / Linux, cần Docker)

```bash
# 0. Tạo qa-audit/config/qa.env từ qa.env.example (mật khẩu ngẫu nhiên)
# 1. Dựng môi trường QA
docker compose -p hienmau-qa -f qa-audit/config/docker-compose.qa.yml --env-file qa-audit/config/qa.env up -d --build

# 2. Danh mục route
docker exec -i hienmau-qa-qa-web-1 python manage.py shell < qa-audit/scripts/build_inventory.py > qa-audit/inventory/routes.json

# 3. Test (DB test riêng của Django) — toàn bộ, hoặc chỉ nhóm hồi quy của đợt audit
docker compose exec web python manage.py test
docker compose exec web python manage.py test --tag qa_audit
docker compose exec web python manage.py test --tag concurrency   # race condition, PostgreSQL thật, nhiều luồng

# 4. Xác nhận trên ứng dụng QA đang chạy
PYTHONIOENCODING=utf-8 QA_RUN_ID=confirm-live python qa-audit/scripts/confirm_live.py

# 5. Giao diện (Playwright)
docker run --rm --add-host=host.docker.internal:host-gateway -e QA_BASE_URL=http://host.docker.internal:8091 \
  -e QA_ACCOUNT_PASSWORD=<từ qa.env> -e QA_UI_OUT=/qa/evidence/runs/ui -v "$PWD/qa-audit:/qa" -w /tmp \
  mcr.microsoft.com/playwright/python:v1.48.0-jammy sh -c "pip install -q playwright==1.48.0 axe-playwright-python && python /qa/playwright/ui_smoke.py && python /qa/playwright/ui_flows.py"

# 6. Quét
docker run --rm -v "$PWD:/src" -w /src semgrep/semgrep semgrep scan --config p/django --config p/python \
  --config p/secrets --config p/security-audit --config p/dockerfile --exclude backend/staticfiles \
  --json --output qa-audit/security/raw/semgrep.json --metrics=off backend docker-compose.yml
docker run --rm --add-host=host.docker.internal:host-gateway -v "$PWD/qa-audit/security/raw:/zap/wrk:rw" \
  ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t http://host.docker.internal:8091/ -m 3 -J zap-baseline.json -r zap-baseline.html -I
docker run --rm --entrypoint sh --add-host=host.docker.internal:host-gateway -v "$PWD/qa-audit/security/raw:/out" \
  projectdiscovery/nuclei -c "nuclei -ut -silent; nuclei -u http://host.docker.internal:8091 \
  -tags misconfig,exposure,headers,tech,config,panel -exclude-tags dos,fuzz,intrusive,bruteforce -rl 20 -c 5 -jsonl -o /out/nuclei.jsonl -duc"
docker compose exec web python manage.py check --deploy

# 7. Dọn môi trường QA
docker compose -p hienmau-qa -f qa-audit/config/docker-compose.qa.yml --env-file qa-audit/config/qa.env down -v
```
Trên Git Bash Windows, thêm `MSYS_NO_PATHCONV=1` trước `docker run` và dùng `$(pwd -W)` thay cho `$PWD`.

# 6b. ZAP active scan (đã được chủ dự án cho phép, chỉ nhắm môi trường QA localhost, giới hạn 30 phút)
docker run --rm --add-host=host.docker.internal:host-gateway -v "$PWD/qa-audit/security/raw:/zap/wrk:rw"   ghcr.io/zaproxy/zaproxy:stable zap-full-scan.py -t http://host.docker.internal:8091/ -m 3 -T 30 -J zap-full.json -r zap-full.html -I

## Cần phê duyệt trước khi chạy
Các bước sau ở trạng thái Blocked trong `scope.json` và chỉ chạy khi được chủ dự án cho phép:
- Strix, Shannon (cần API key LLM, có chi phí; Shannon khai thác thật).
- Hercules (cần API key LLM).
