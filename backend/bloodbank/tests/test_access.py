"""Phân quyền theo vai trò: 3 cổng đăng nhập, bảng màn hình (access.py) áp cho MỌI route."""
from django.test import TestCase
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

from bloodbank import access
from bloodbank.models import AuditLog, Campaign

from . import factories as f

PW = "MatKhau!2026"


def all_route_names():
    names = set()

    def walk(patterns, ns=None):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, p.namespace or ns)
            elif isinstance(p, URLPattern) and p.name:
                names.add(f"{ns}:{p.name}" if ns else p.name)

    walk(get_resolver().url_patterns)
    return names


def url_for(name):
    for args in ([], [999999], ["nhap"], ["khong-hop-le"]):
        try:
            return reverse(name, args=args)
        except NoReverseMatch:
            continue
    raise AssertionError(f"Không dựng được URL cho {name}")


class ScreenRegistryTests(TestCase):
    def test_every_route_is_declared_and_every_declared_route_exists(self):
        routes = all_route_names()
        self.assertEqual(sorted(routes - set(access.ROUTE_ROLES)), [], "Route chưa khai báo quyền trong access.py")
        self.assertEqual(sorted(set(access.ROUTE_ROLES) - routes), [], "access.py khai báo route không tồn tại")

    def test_roles_are_known(self):
        known = {access.PUBLIC, *access.ROLE_LABELS}
        for sc in access.SCREENS:
            self.assertTrue(sc.roles and set(sc.roles) <= known, sc.code)


class RoleMatrixTests(TestCase):
    """Mỗi vai trò chỉ mở được màn hình của mình; còn lại 403 (đã đăng nhập) hoặc chuyển về đúng cổng đăng nhập."""

    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.users = {
            access.MEMBER: f.user(),
            access.HOSPITAL: f.staff(cls.h),
            access.ADMIN: f.user(role="admin"),
        }

    def test_every_route_for_every_role(self):
        checked = 0
        for name, roles in access.ROUTE_ROLES.items():
            if access.PUBLIC in roles or name == "accounts:logout":
                continue
            url = url_for(name)
            self.client.logout()
            r = self.client.get(url)
            if url.startswith("/api/"):   # API trả JSON 401 thay vì chuyển trang
                self.assertEqual(r.status_code, 401, f"khách → {name}")
                self.assertEqual(r.json()["error"]["code"], "ERR-AUTH-UNAUTHENTICATED")
            else:
                self.assertEqual(r.status_code, 302, f"khách → {name}")
                self.assertTrue(r["Location"].startswith(reverse(access.login_url_for(roles))), f"{name} → {r['Location']}")
            for role, user in self.users.items():
                self.client.force_login(user)
                r = self.client.get(url)
                if role in roles:
                    self.assertNotEqual(r.status_code, 403, f"{role} phải mở được {name}")
                else:
                    self.assertEqual(r.status_code, 403, f"{role} không được mở {name}")
                checked += 1
        self.assertGreater(checked, 150)
        self.assertTrue(AuditLog.objects.filter(action="access_denied", new_values__reason="screen_role").exists())

    def test_post_is_blocked_too(self):
        self.client.force_login(self.users[access.MEMBER])
        r = self.client.post(reverse("bloodbank:stock_txn", args=["nhap"]), {"blood_group": "O+"})
        self.assertEqual(r.status_code, 403)
        self.client.force_login(self.users[access.HOSPITAL])
        r = self.client.post(reverse("bloodbank:admin_users"), {"action": "lock", "user_id": self.users[access.ADMIN].pk})
        self.assertEqual(r.status_code, 403)
        self.users[access.ADMIN].refresh_from_db()
        self.assertEqual(self.users[access.ADMIN].status, "active")

    def test_non_member_cannot_register_for_campaign(self):
        c = f.campaign(self.h, start_offset_h=24)
        for role in (access.HOSPITAL, access.ADMIN):
            self.client.force_login(self.users[role])
            r = self.client.get(reverse("bloodbank:campaign_detail", args=[c.pk]))
            self.assertContains(r, "chỉ dành cho tài khoản Người dùng")
            r = self.client.post(reverse("bloodbank:campaign_detail", args=[c.pk]), {"donation_type": "whole_blood"})
            self.assertEqual(r.status_code, 403)
        self.assertFalse(Campaign.objects.get(pk=c.pk).registrations.exists())

    def test_menus_only_list_own_screens(self):
        self.client.force_login(self.users[access.HOSPITAL])
        r = self.client.get(reverse("bloodbank:hospital_dashboard"))
        self.assertNotContains(r, reverse("bloodbank:admin_stats"))
        self.assertNotContains(r, reverse("bloodbank:my_history"))
        self.client.force_login(self.users[access.ADMIN])
        r = self.client.get(reverse("bloodbank:admin_stats"))
        self.assertContains(r, reverse("bloodbank:admin_permissions"))
        self.assertNotContains(r, f'href="{reverse("bloodbank:hospital_dashboard")}"')
        self.assertNotContains(r, f'href="{reverse("bloodbank:profile")}"')
        self.client.force_login(self.users[access.MEMBER])
        r = self.client.get(reverse("bloodbank:profile"))
        self.assertNotContains(r, f'href="{reverse("bloodbank:hospital_dashboard")}"')
        self.assertNotContains(r, reverse("bloodbank:admin_stats"))

    def test_permission_screen_shows_matrix(self):
        self.client.force_login(self.users[access.ADMIN])
        r = self.client.get(reverse("bloodbank:admin_permissions"))
        self.assertEqual(len(r.context["rows"]), len(access.SCREENS))
        self.assertContains(r, "Phân quyền màn hình")


class LoginPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.h = f.hospital()
        cls.member = f.user(email="nd@test.vn")
        cls.staff = f.staff(cls.h, f.user(email="nv@test.vn", role="hospital"))
        cls.admin = f.user(email="qt@test.vn", role="admin")

    def login(self, name, email, **extra):
        return self.client.post(reverse(name), {"email": email, "password": PW, **extra})

    def test_each_portal_accepts_only_its_role(self):
        cases = [("accounts:login", self.member, "bloodbank:home"),
                 ("accounts:hospital_login", self.staff, "bloodbank:hospital_dashboard"),
                 ("accounts:admin_login", self.admin, "bloodbank:admin_stats")]
        for portal, owner, home in cases:
            for user in (self.member, self.staff, self.admin):
                self.client.logout()
                r = self.login(portal, user.email)
                if user == owner:
                    self.assertRedirects(r, reverse(home), fetch_redirect_response=False)
                    self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
                else:
                    self.assertEqual(r.status_code, 200, f"{user.email} @ {portal}")
                    self.assertContains(r, "không đăng nhập được tại cổng này")
                    self.assertContains(r, reverse(access.LOGIN_URLS[user.role]))  # gợi ý đúng cổng
                    self.assertNotIn("_auth_user_id", self.client.session)

    def test_wrong_portal_does_not_count_as_failed_attempt(self):
        for _ in range(6):
            self.login("accounts:hospital_login", self.member.email)
        r = self.login("accounts:login", self.member.email)
        self.assertEqual(r.status_code, 302)

    def test_wrong_password_still_generic(self):
        r = self.client.post(reverse("accounts:hospital_login"), {"email": self.member.email, "password": "sai-mat-khau"})
        self.assertContains(r, "Email hoặc mật khẩu không đúng")
        self.assertNotContains(r, "không đăng nhập được tại cổng này")  # không lộ vai trò khi sai mật khẩu

    def test_next_to_other_role_screen_is_ignored(self):
        r = self.login("accounts:hospital_login", self.staff.email, next=reverse("bloodbank:admin_users"))
        self.assertRedirects(r, reverse("bloodbank:hospital_dashboard"), fetch_redirect_response=False)
        self.client.logout()
        r = self.login("accounts:hospital_login", self.staff.email, next=reverse("bloodbank:stock"))
        self.assertRedirects(r, reverse("bloodbank:stock"), fetch_redirect_response=False)

    def test_anonymous_redirected_to_matching_portal(self):
        for url, portal in [(reverse("bloodbank:stock"), "accounts:hospital_login"),
                            (reverse("bloodbank:admin_users"), "accounts:admin_login"),
                            (reverse("bloodbank:my_history"), "accounts:login")]:
            r = self.client.get(url)
            self.assertTrue(r["Location"].startswith(reverse(portal) + "?next="), r["Location"])

    def test_logout_returns_to_own_portal(self):
        self.client.force_login(self.staff)
        r = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(r, reverse("accounts:hospital_login"), fetch_redirect_response=False)
        self.client.force_login(self.admin)
        r = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(r, reverse("accounts:admin_login"), fetch_redirect_response=False)

    def test_hospital_account_without_assignment_is_denied(self):
        orphan = f.user(email="khongpc@test.vn", role="hospital")
        self.client.force_login(orphan)
        self.assertEqual(self.client.get(reverse("bloodbank:hospital_dashboard")).status_code, 403)
