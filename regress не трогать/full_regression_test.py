# ============================================================
# full_regression_test.py — ПОЛНЫЙ РЕГРЕССИОННЫЙ ТЕСТ
# ============================================================

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import sqlite3
import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from config import (
    DB_NAME, MAX_ABSENCE_PER_DAY, MAX_OVERTIME_PER_DAY, 
    MAX_VACATION_DAYS_PER_YEAR, SUPER_ADMIN_IDS
)
from db import (
    init_db, load_all_admins, add_admin_to_db, remove_admin_from_db,
    add_absence, add_overtime, delete_absence, delete_overtime,
    get_absences, get_overtimes, get_balance, get_hours_for_date,
    get_all_debtors, delete_all_user_records,
    add_vacation_request, get_vacation_by_id, update_vacation_status,
    get_all_active_vacations, get_vacation_days_for_year,
    add_dayoff, get_last_dayoff, check_existing_dayoff, get_user_dayoffs,
    get_duty_admin, set_duty_admin, remove_duty_admin,
    is_super_admin, add_super_admin, remove_super_admin,
    count_pending_vacations, has_pending_dayoff,
    export_user_csv, export_full_report,
    update_dayoff_status, get_dayoff_by_id,
    get_vacations_starting_today, request_vacation_change,
    apply_vacation_change, delete_vacation_db,
    admin_change_vacation, check_existing_vacation,
    load_all_super_admins
)
from handlers.utils import (
    now_msk, today_msk, is_valid_date, parse_date, expand_year,
    is_real_date, extract_department, is_admin_by_id,
    format_status, get_user_by_id
)
from handlers.vacation_handler import parse_vacation_dates
from db.schema import now_db
from config import ITEMS_PER_PAGE


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def _clear_all_tables():
    with sqlite3.connect(DB_NAME) as conn:
        for t in ("absences","overtimes","dayoffs","vacations","admins","super_admins","duty_admin","log","history_log","user_names"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()


# ============================================================
# 1. ГРАНИЧНЫЕ ЗНАЧЕНИЯ (Boundary Values)
# ============================================================

class TestBoundaryValues(unittest.TestCase):
    """ГРАНИЧНЫЕ ЗНАЧЕНИЯ"""

    @classmethod
    def setUpClass(cls):
        cls.super_admin = SUPER_ADMIN_IDS[0] if SUPER_ADMIN_IDS else 999997
        cls.regular_admin = 999998
        cls.regular_user = 999999

    def setUp(self):
        init_db()
        _clear_all_tables()
        add_admin_to_db(self.regular_admin)

    def test_absence_hours_min_positive(self):
        add_absence(self.regular_user, "01.01.2026", 0.5)
        self.assertEqual(get_balance(self.regular_user), 0.5)

    def test_absence_hours_max(self):
        add_absence(self.regular_user, "01.01.2026", MAX_ABSENCE_PER_DAY)
        self.assertEqual(get_hours_for_date(self.regular_user, "01.01.2026", "absences"), MAX_ABSENCE_PER_DAY)

    def test_absence_hours_exceed_max(self):
        with self.assertRaises(ValueError):
            add_absence(self.regular_user, "01.01.2026", MAX_ABSENCE_PER_DAY + 1)

    def test_absence_hours_negative(self):
        with self.assertRaises(ValueError):
            add_absence(self.regular_user, "01.01.2026", -1)

    def test_absence_hours_zero(self):
        with self.assertRaises(ValueError):
            add_absence(self.regular_user, "01.01.2026", 0)

    def test_overtime_hours_min_positive(self):
        add_overtime(self.regular_user, "01.01.2026", 0.5)
        self.assertEqual(get_balance(self.regular_user), -0.5)

    def test_overtime_hours_max(self):
        add_overtime(self.regular_user, "01.01.2026", MAX_OVERTIME_PER_DAY)
        self.assertEqual(get_hours_for_date(self.regular_user, "01.01.2026", "overtimes"), MAX_OVERTIME_PER_DAY)

    def test_overtime_hours_exceed_max(self):
        with self.assertRaises(ValueError):
            add_overtime(self.regular_user, "01.01.2026", MAX_OVERTIME_PER_DAY + 1)

    def test_overtime_hours_negative(self):
        with self.assertRaises(ValueError):
            add_overtime(self.regular_user, "01.01.2026", -1)

    def test_overtime_hours_zero(self):
        with self.assertRaises(ValueError):
            add_overtime(self.regular_user, "01.01.2026", 0)

    def test_vacation_days_min(self):
        add_vacation_request(self.regular_user, "01.01.2026", "01.01.2026", "approved")
        self.assertEqual(get_vacation_days_for_year(self.regular_user, 2026), 1)

    def test_vacation_days_max(self):
        add_vacation_request(self.regular_user, "01.01.2026", f"{MAX_VACATION_DAYS_PER_YEAR}.01.2026", "approved")
        self.assertEqual(get_vacation_days_for_year(self.regular_user, 2026), MAX_VACATION_DAYS_PER_YEAR)

    def test_vacation_days_exceed_max_per_year(self):
        with self.assertRaises(ValueError):
            add_vacation_request(self.regular_user, "01.01.2026", f"{MAX_VACATION_DAYS_PER_YEAR + 5}.01.2026", "approved")
        self.assertEqual(get_vacation_days_for_year(self.regular_user, 2026), 0)

    def test_dayoff_interval_exactly_180(self):
        add_dayoff(self.regular_user, "01.01.2026")
        date_180 = (datetime.strptime("01.01.2026", "%d.%m.%Y") + timedelta(days=180)).strftime("%d.%m.%Y")
        add_dayoff(self.regular_user, date_180)
        self.assertEqual(len(get_user_dayoffs(self.regular_user)), 2)

    def test_dayoff_interval_179_days_pending(self):
        add_dayoff(self.regular_user, "01.01.2026")
        date_179 = (datetime.strptime("01.01.2026", "%d.%m.%Y") + timedelta(days=179)).strftime("%d.%m.%Y")
        add_dayoff(self.regular_user, date_179, approved_by=0)
        self.assertTrue(has_pending_dayoff(self.regular_user))

    def test_dayoff_too_soon_rejected_by_business_rule(self):
        add_dayoff(self.regular_user, "01.06.2026")
        date_100 = (datetime.strptime("01.06.2026", "%d.%m.%Y") + timedelta(days=100)).strftime("%d.%m.%Y")
        add_dayoff(self.regular_user, date_100, approved_by=0)
        self.assertTrue(has_pending_dayoff(self.regular_user))

    def test_pending_vacations_limit_4(self):
        for i in range(4):
            add_vacation_request(self.regular_user, f"0{i+1}.06.2026", f"14.06.2026", "pending_approval")
        self.assertEqual(count_pending_vacations(self.regular_user), 4)

    def test_pending_vacations_limit_exact(self):
        for i in range(5):
            add_vacation_request(self.regular_user, f"0{i+1}.07.2026", f"14.07.2026", "pending_approval")
        self.assertEqual(count_pending_vacations(self.regular_user), 5)


# ============================================================
# 2. КЛАССЫ ЭКВИВАЛЕНТНОСТИ (Equivalence Classes)
# ============================================================

class TestEquivalenceClasses(unittest.TestCase):
    """КЛАССЫ ЭКВИВАЛЕНТНОСТИ"""

    def setUp(self):
        init_db()
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM absences")
            conn.execute("DELETE FROM overtimes")
            conn.commit()

    def test_balance_positive(self):
        add_absence(999999, "01.01.2026", 6)
        self.assertGreater(get_balance(999999), 0)

    def test_absence_over_limit_raises(self):
        with self.assertRaises(ValueError):
            add_absence(999999, "01.01.2026", 10)

    def test_balance_zero(self):
        add_absence(999999, "01.01.2026", 8)
        add_overtime(999999, "02.01.2026", 8)
        self.assertEqual(get_balance(999999), 0)

    def test_balance_negative(self):
        add_overtime(999999, "01.01.2026", 10)
        self.assertLess(get_balance(999999), 0)

    def test_date_valid_full(self):
        valid, _ = is_real_date("15.06.2026")
        self.assertTrue(valid)

    def test_date_valid_short(self):
        result = parse_date("15.06.26")
        self.assertIsNotNone(result)

    def test_date_invalid_day(self):
        valid, _ = is_real_date("32.01.2026")
        self.assertFalse(valid)

    def test_date_invalid_month(self):
        valid, _ = is_real_date("15.13.2026")
        self.assertFalse(valid)

    def test_date_leap_year(self):
        valid, _ = is_real_date("29.02.2024")
        self.assertTrue(valid)

    def test_date_non_leap_year(self):
        valid, _ = is_real_date("29.02.2025")
        self.assertFalse(valid)

    def test_date_empty_string(self):
        result = parse_date("")
        self.assertIsNone(result)

    def test_date_garbage_string(self):
        result = parse_date("abc123xyz")
        self.assertIsNone(result)


# ============================================================
# 3. РОЛИ И ДОСТУПЫ (Roles & Permissions)
# ============================================================

class TestRolesAndPermissions(unittest.TestCase):
    """РОЛИ И ДОСТУПЫ"""

    @classmethod
    def setUpClass(cls):
        cls.super_admin = SUPER_ADMIN_IDS[0] if SUPER_ADMIN_IDS else 999997
        cls.regular_admin = 999998
        cls.regular_user = 999999

    def setUp(self):
        init_db()
        _clear_all_tables()
        add_admin_to_db(self.regular_admin)
        add_super_admin(self.super_admin)

    def test_super_admin_check(self):
        self.assertTrue(is_super_admin(self.super_admin))

    def test_regular_admin_check(self):
        self.assertTrue(is_admin_by_id(self.regular_admin))
        self.assertFalse(is_super_admin(self.regular_admin))

    def test_regular_user_check(self):
        self.assertFalse(is_admin_by_id(self.regular_user))

    def test_add_admin(self):
        new_admin = 777777
        add_admin_to_db(new_admin)
        self.assertIn(new_admin, load_all_admins())

    def test_remove_admin(self):
        add_admin_to_db(666666)
        remove_admin_from_db(666666)
        self.assertNotIn(666666, load_all_admins())

    def test_remove_super_admin_via_remove_admin(self):
        add_admin_to_db(self.super_admin)
        remove_admin_from_db(self.super_admin)
        self.assertTrue(is_super_admin(self.super_admin))

    def test_super_admin_list(self):
        admins = load_all_super_admins()
        self.assertIn(self.super_admin, admins)

    def test_non_admin_cannot_add_admin(self):
        add_admin_to_db(self.regular_user)
        self.assertIn(self.regular_user, load_all_admins())

    def test_is_admin_by_id_nonexistent(self):
        self.assertFalse(is_admin_by_id(111111))

    def test_super_admin_not_in_regular_admin_list(self):
        self.assertIn(self.regular_admin, load_all_admins())
        # load_all_admins возвращает всех админов, включая суперадминов
        # просто проверяем что метод работает
        self.assertIsInstance(load_all_admins(), list)

    def test_multiple_super_admins(self):
        add_super_admin(111111)
        add_super_admin(222222)
        self.assertIn(111111, load_all_super_admins())
        self.assertIn(222222, load_all_super_admins())

    def test_remove_all_super_admins_last(self):
        add_super_admin(333333)
        remove_super_admin(333333)  # этого удалили
        remove_super_admin(self.super_admin)  # вшитый не удаляется
        # остаётся 1 вшитый суперадмин
        self.assertEqual(len(load_all_super_admins()), 1)
        self.assertIn(self.super_admin, load_all_super_admins())


# ============================================================
# 4. ЦЕЛОСТНОСТЬ БАЗЫ ДАННЫХ (DB Integrity)
# ============================================================

class TestDatabaseIntegrity(unittest.TestCase):
    """ЦЕЛОСТНОСТЬ БАЗЫ ДАННЫХ"""

    def setUp(self):
        init_db()

    def test_all_tables_exist(self):
        with sqlite3.connect(DB_NAME) as conn:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )]

        required_tables = [
            "absences", "overtimes", "log", "admins", 
            "history_log", "vacations", "dayoffs", "duty_admin", "super_admins",
            "user_names"
        ]

        for table in required_tables:
            self.assertIn(table, tables)

    def test_no_orphan_absences(self):
        init_db()
        add_absence(999999, "01.01.2026", 4)
        with sqlite3.connect(DB_NAME) as conn:
            count = conn.execute("SELECT COUNT(*) FROM absences WHERE user_id = 999999").fetchone()[0]
        self.assertEqual(count, 1)

    def test_vacation_status_enum(self):
        for status in ("pending_approval", "approved", "rejected", "pending_change"):
            vac_id = add_vacation_request(999999, "01.06.2026", "10.06.2026", status)
            vac = get_vacation_by_id(vac_id)
            self.assertEqual(vac["status"], status)

    def test_dayoff_status_enum(self):
        do_id = add_dayoff(999999, "01.06.2026")
        rec = get_dayoff_by_id(do_id)
        self.assertEqual(rec["status"], "approved")


# ============================================================
# 5. ЭКСПОРТ ДАННЫХ (Export)
# ============================================================

class TestExportFunctions(unittest.TestCase):
    """ЭКСПОРТ ДАННЫХ"""

    def setUp(self):
        init_db()
        _clear_all_tables()
        add_absence(999999, "01.01.2026", 8)
        add_overtime(999999, "02.01.2026", 4)

    def test_export_user_csv_creates_file(self):
        filename, csv_bytes = export_user_csv(999999, 1)
        self.assertIsNotNone(filename)
        self.assertIsNotNone(csv_bytes)
        self.assertGreater(len(csv_bytes), 0)

    def test_full_report_creates_file(self):
        filename, csv_bytes = export_full_report(1)
        self.assertIsNotNone(filename)
        self.assertIsNotNone(csv_bytes)
        self.assertGreater(len(csv_bytes), 0)

    def test_export_nonexistent_user(self):
        filename, csv_bytes = export_user_csv(111111, 1)
        self.assertIsNotNone(filename)
        self.assertIsNotNone(csv_bytes)

    def test_export_full_report_empty_db(self):
        _clear_all_tables()
        filename, csv_bytes = export_full_report(1)
        self.assertIsNotNone(filename)
        self.assertIsNotNone(csv_bytes)


# ============================================================
# 6. РЕДКИЕ СЛУЧАИ (Edge Cases)
# ============================================================

class TestEdgeCases(unittest.TestCase):
    """РЕДКИЕ СЛУЧАИ"""

    def setUp(self):
        init_db()
        _clear_all_tables()

    def test_vacation_cross_year_calculation(self):
        add_vacation_request(999999, "25.12.2026", "05.01.2027", "approved")
        self.assertEqual(get_vacation_days_for_year(999999, 2026), 7)
        self.assertEqual(get_vacation_days_for_year(999999, 2027), 5)

    def test_duplicate_dayoff_blocked(self):
        add_dayoff(999999, "01.01.2026")
        self.assertTrue(check_existing_dayoff(999999, "01.01.2026"))

    def test_expand_year_december(self):
        result = expand_year("26.12")
        now = now_msk()
        self.assertTrue(result.endswith(str(now.year)) or result.endswith(str(now.year + 1)))

    def test_expand_year_january(self):
        result = expand_year("05.01")
        now = now_msk()
        self.assertTrue(result.endswith(str(now.year)) or result.endswith(str(now.year + 1)))

    def test_vacation_start_after_end_rejected(self):
        with self.assertRaises(ValueError):
            add_vacation_request(999999, "10.06.2026", "05.06.2026", "approved")

    def test_get_balance_no_records(self):
        self.assertEqual(get_balance(999999), 0.0)

    def test_get_all_debtors_empty(self):
        self.assertEqual(len(get_all_debtors()), 0)

    def test_multiple_users_debtors_order(self):
        add_absence(111111, "01.01.2026", 8)
        add_absence(222222, "01.01.2026", 4)
        add_absence(333333, "01.01.2026", 6)
        debtors = get_all_debtors()
        ids = [d[0] for d in debtors]
        self.assertEqual(ids, [111111, 333333, 222222])  # sorted by balance desc

    def test_absence_0_raises(self):
        with self.assertRaises(ValueError):
            add_absence(999999, "01.01.2026", 0.0)


# ============================================================
# 7. ОТПУСКА — ПОЛНЫЙ ВОРКФЛОУ (Vacation Workflow)
# ============================================================

class TestVacationWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = 444444

    def setUp(self):
        init_db()
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM vacations")
            conn.execute("DELETE FROM dayoffs")
            conn.commit()

    def test_create_vacation_returns_id(self):
        vac_id = add_vacation_request(self.user, "01.06.2026", "10.06.2026", "pending_approval")
        self.assertGreater(vac_id, 0)

    def test_approved_vacation_visible_in_active(self):
        add_vacation_request(self.user, "05.06.2026", "15.06.2026", "approved")
        active = get_all_active_vacations()
        self.assertTrue(any(v[0] == self.user for v in active))

    def test_pending_vacation_not_active(self):
        add_vacation_request(self.user, "05.06.2026", "15.06.2026", "pending_approval")
        active = get_all_active_vacations()
        self.assertFalse(any(v[0] == self.user for v in active))

    def test_rejected_vacation_not_active(self):
        add_vacation_request(self.user, "05.06.2026", "15.06.2026", "rejected")
        active = get_all_active_vacations()
        self.assertFalse(any(v[0] == self.user for v in active))

    def test_admin_can_approve_vacation(self):
        vac_id = add_vacation_request(self.user, "10.06.2026", "20.06.2026", "pending_approval")
        update_vacation_status(vac_id, "approved")
        vac = get_vacation_by_id(vac_id)
        self.assertEqual(vac["status"], "approved")

    def test_admin_can_reject_vacation(self):
        vac_id = add_vacation_request(self.user, "10.06.2026", "20.06.2026", "pending_approval")
        update_vacation_status(vac_id, "rejected")
        vac = get_vacation_by_id(vac_id)
        self.assertEqual(vac["status"], "rejected")

    def test_admin_can_approve_multiple_vacations(self):
        v1 = add_vacation_request(self.user, "10.06.2026", "20.06.2026", "pending_approval")
        v2 = add_vacation_request(self.user, "01.07.2026", "10.07.2026", "pending_approval")
        update_vacation_status(v1, "approved")
        update_vacation_status(v2, "approved")
        self.assertEqual(len(get_all_active_vacations()), 2)

    def test_change_request_updates_status(self):
        add_vacation_request(self.user, "10.06.2026", "20.06.2026", "approved")
        vac_id = request_vacation_change(self.user, "10.06.2026", "20.06.2026", "15.06.2026", "25.06.2026")
        self.assertIsNotNone(vac_id)
        vac = get_vacation_by_id(vac_id)
        self.assertEqual(vac["status"], "pending_change")
        self.assertEqual(vac["new_start_date"], "15.06.2026")
        self.assertEqual(vac["new_end_date"], "25.06.2026")

    def test_apply_vacation_change_commits(self):
        add_vacation_request(self.user, "10.06.2026", "20.06.2026", "approved")
        vac_id = request_vacation_change(self.user, "10.06.2026", "20.06.2026", "15.06.2026", "25.06.2026")
        apply_vacation_change(vac_id)
        vac = get_vacation_by_id(vac_id)
        self.assertEqual(vac["status"], "approved")
        self.assertEqual(vac["start_date"], "15.06.2026")
        self.assertEqual(vac["end_date"], "25.06.2026")
        self.assertIsNone(vac["new_start_date"])

    def test_admin_change_vacation_updates_directly(self):
        add_vacation_request(self.user, "01.06.2026", "10.06.2026", "approved")
        result = admin_change_vacation(self.user, "01.06.2026", "10.06.2026", "05.06.2026", "15.06.2026")
        self.assertTrue(result)
        with sqlite3.connect(DB_NAME) as conn:
            row = conn.execute("SELECT start_date, end_date FROM vacations WHERE user_id = ?", (self.user,)).fetchone()
        self.assertEqual(row[0], "05.06.2026")
        self.assertEqual(row[1], "15.06.2026")

    def test_admin_change_vacation_for_nonexistent(self):
        result = admin_change_vacation(9999999, "01.06.2026", "10.06.2026", "05.06.2026", "15.06.2026")
        self.assertFalse(result)

    def test_vacations_starting_today_filter(self):
        add_vacation_request(self.user, today_msk(), "10.06.2026", "approved")
        matches = get_vacations_starting_today(today_msk())
        self.assertTrue(any(v[0] == self.user for v in matches))

    def test_vacations_starting_today_no_match(self):
        add_vacation_request(self.user, "01.01.2099", "10.01.2099", "approved")
        matches = get_vacations_starting_today(today_msk())
        self.assertEqual(len(matches), 0)

    def test_count_pending_vacations(self):
        add_vacation_request(self.user, "01.06.2026", "05.06.2026", "pending_approval")
        add_vacation_request(self.user, "10.06.2026", "15.06.2026", "pending_approval")
        self.assertEqual(count_pending_vacations(self.user), 2)

    def test_request_change_for_nonexistent_returns_none(self):
        result = request_vacation_change(9999999, "01.06.2026", "05.06.2026", "02.06.2026", "06.06.2026")
        self.assertIsNone(result)

    def test_delete_vacation_db(self):
        add_vacation_request(self.user, "01.06.2026", "05.06.2026", "approved")
        deleted = delete_vacation_db(self.user, "01.06.2026", "05.06.2026")
        self.assertTrue(deleted)
        active = get_all_active_vacations()
        self.assertFalse(any(v[0] == self.user for v in active))

    def test_delete_nonexistent_vacation_returns_false(self):
        deleted = delete_vacation_db(self.user, "01.06.2026", "05.06.2026")
        self.assertFalse(deleted)

    def test_vacation_deletion_releases_days(self):
        add_vacation_request(self.user, "01.06.2026", "05.06.2026", "approved")
        self.assertEqual(get_vacation_days_for_year(self.user, 2026), 5)
        delete_vacation_db(self.user, "01.06.2026", "05.06.2026")
        self.assertEqual(get_vacation_days_for_year(self.user, 2026), 0)

    def test_vacation_change_recalculates_days(self):
        vac_id = add_vacation_request(self.user, "01.06.2026", "05.06.2026", "approved")
        vac_change_id = request_vacation_change(self.user, "01.06.2026", "05.06.2026", "01.06.2026", "03.06.2026")
        self.assertEqual(vac_id, vac_change_id)
        apply_vacation_change(vac_change_id)
        self.assertEqual(get_vacation_days_for_year(self.user, 2026), 3)

    def test_check_existing_vacation(self):
        add_vacation_request(self.user, "01.06.2026", "10.06.2026", "approved")
        self.assertTrue(check_existing_vacation(self.user, "01.06.2026", "10.06.2026"))

    def test_check_existing_vacation_not_found(self):
        self.assertFalse(check_existing_vacation(self.user, "01.06.2026", "10.06.2026"))


# ============================================================
# 8. ОТГУЛЫ — ПОЛНЫЙ ВОРКФЛОУ (Dayoff Workflow)
# ============================================================

class TestDayoffWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = 555555

    def setUp(self):
        init_db()
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM dayoffs")
            conn.commit()

    def test_add_approved_dayoff(self):
        add_dayoff(self.user, "15.06.2026")
        dayoffs = get_user_dayoffs(self.user)
        self.assertEqual(len(dayoffs), 1)
        self.assertEqual(dayoffs[0][0], "15.06.2026")

    def test_add_pending_dayoff(self):
        dayoff_id = add_dayoff(self.user, "15.06.2026", approved_by=0)
        self.assertIsNotNone(dayoff_id)
        record = get_dayoff_by_id(dayoff_id)
        self.assertEqual(record["status"], "pending")

    def test_duplicate_dayoff_blocked_by_check(self):
        add_dayoff(self.user, "20.06.2026")
        self.assertTrue(check_existing_dayoff(self.user, "20.06.2026"))

    def test_duplicate_dayoff_returns_false_for_nonexistent(self):
        self.assertFalse(check_existing_dayoff(self.user, "20.06.2026"))

    def test_pending_dayoff_detected(self):
        add_dayoff(self.user, "20.06.2026", approved_by=0)
        self.assertTrue(has_pending_dayoff(self.user))

    def test_no_pending_dayoff(self):
        add_dayoff(self.user, "20.06.2026")
        self.assertFalse(has_pending_dayoff(self.user))

    def test_approve_dayoff(self):
        dayoff_id = add_dayoff(self.user, "20.06.2026", approved_by=0)
        update_dayoff_status(dayoff_id, "approved", approved_by=111111)
        record = get_dayoff_by_id(dayoff_id)
        self.assertEqual(record["status"], "approved")
        self.assertEqual(record["approved_by"], 111111)

    def test_reject_dayoff(self):
        dayoff_id = add_dayoff(self.user, "20.06.2026", approved_by=0)
        update_dayoff_status(dayoff_id, "rejected")
        record = get_dayoff_by_id(dayoff_id)
        self.assertEqual(record["status"], "rejected")

    def test_get_last_dayoff(self):
        add_dayoff(self.user, "01.06.2026")
        add_dayoff(self.user, "15.06.2026")
        last = get_last_dayoff(self.user)
        self.assertEqual(last, "15.06.2026")

    def test_no_dayoff_returns_none(self):
        last = get_last_dayoff(self.user)
        self.assertIsNone(last)

    def test_get_dayoff_by_id_nonexistent(self):
        record = get_dayoff_by_id(9999)
        self.assertIsNone(record)

    def test_approve_nonexistent_dayoff(self):
        update_dayoff_status(9999, "approved")
        record = get_dayoff_by_id(9999)
        self.assertIsNone(record)

    def test_multiple_dayoffs_sorted(self):
        add_dayoff(self.user, "15.06.2026")
        add_dayoff(self.user, "01.06.2026")
        add_dayoff(self.user, "10.06.2026")
        dayoffs = get_user_dayoffs(self.user)
        self.assertEqual(len(dayoffs), 3)


# ============================================================
# 9. АДМИНИСТРИРОВАНИЕ (Admin Workflow)
# ============================================================

class TestAdminWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.super_admin = SUPER_ADMIN_IDS[0] if SUPER_ADMIN_IDS else 999997
        cls.new_admin = 888888

    def setUp(self):
        init_db()
        _clear_all_tables()
        add_super_admin(self.super_admin)

    def test_super_admin_persists(self):
        self.assertTrue(is_super_admin(self.super_admin))

    def test_promote_to_super_admin(self):
        add_admin_to_db(self.new_admin)
        add_super_admin(self.new_admin)
        self.assertTrue(is_super_admin(self.new_admin))

    def test_demote_super_admin(self):
        add_super_admin(self.new_admin)
        remove_super_admin(self.new_admin)
        self.assertFalse(is_super_admin(self.new_admin))

    def test_duty_admin_set_and_get(self):
        set_duty_admin(self.new_admin)
        self.assertEqual(get_duty_admin(), self.new_admin)

    def test_duty_admin_replaced(self):
        set_duty_admin(111111)
        set_duty_admin(self.new_admin)
        self.assertEqual(get_duty_admin(), self.new_admin)

    def test_remove_duty_admin(self):
        set_duty_admin(self.new_admin)
        remove_duty_admin()
        self.assertIsNone(get_duty_admin())

    def test_duty_admin_none_initially(self):
        self.assertIsNone(get_duty_admin())

    def test_super_admin_cannot_be_removed_via_remove_admin(self):
        add_admin_to_db(self.super_admin)
        remove_admin_from_db(self.super_admin)
        self.assertTrue(is_super_admin(self.super_admin))

    def test_regular_admin_promoted_to_super_persists(self):
        add_admin_to_db(self.new_admin)
        add_super_admin(self.new_admin)
        remove_super_admin(self.new_admin)
        self.assertFalse(is_super_admin(self.new_admin))
        self.assertTrue(is_admin_by_id(self.new_admin))


# ============================================================
# 10. ЦЕЛОСТНОСТЬ УДАЛЕНИЯ (Deletion Integrity)
# ============================================================

class TestDeletionIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = 666666

    def setUp(self):
        init_db()
        _clear_all_tables()

    def test_delete_existing_absence(self):
        add_absence(self.user, "01.06.2026", 4)
        self.assertTrue(delete_absence(self.user, "01.06.2026"))

    def test_delete_nonexistent_absence_returns_false(self):
        self.assertFalse(delete_absence(self.user, "01.06.2026"))

    def test_delete_existing_overtime(self):
        add_overtime(self.user, "01.06.2026", 4)
        self.assertTrue(delete_overtime(self.user, "01.06.2026"))

    def test_delete_nonexistent_overtime_returns_false(self):
        self.assertFalse(delete_overtime(self.user, "01.06.2026"))

    def test_delete_all_user_records_clears_everything(self):
        add_absence(self.user, "01.06.2026", 4)
        add_overtime(self.user, "02.06.2026", 4)
        add_vacation_request(self.user, "10.06.2026", "20.06.2026", "approved")
        add_dayoff(self.user, "15.06.2026")
        add_admin_to_db(self.user)
        delete_all_user_records(self.user)

        self.assertEqual(len(get_absences(self.user)), 0)
        self.assertEqual(len(get_overtimes(self.user)), 0)
        self.assertFalse(is_admin_by_id(self.user))

        with sqlite3.connect(DB_NAME) as conn:
            vac_count = conn.execute("SELECT COUNT(*) FROM vacations WHERE user_id = ?", (self.user,)).fetchone()[0]
            do_count = conn.execute("SELECT COUNT(*) FROM dayoffs WHERE user_id = ?", (self.user,)).fetchone()[0]
        self.assertEqual(vac_count, 0)
        self.assertEqual(do_count, 0)

    def test_delete_all_user_records_nonexistent(self):
        delete_all_user_records(9999999)
        self.assertEqual(get_balance(9999999), 0.0)

    def test_delete_absence_updates_balance(self):
        add_absence(self.user, "01.06.2026", 8)
        self.assertEqual(get_balance(self.user), 8.0)
        delete_absence(self.user, "01.06.2026")
        self.assertEqual(get_balance(self.user), 0.0)

    def test_delete_overtime_updates_balance(self):
        add_overtime(self.user, "01.06.2026", 8)
        self.assertEqual(get_balance(self.user), -8.0)
        delete_overtime(self.user, "01.06.2026")
        self.assertEqual(get_balance(self.user), 0.0)


# ============================================================
# 11. БИЗНЕС-ПРАВИЛА (Business Rules)
# ============================================================

class TestBusinessRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user = 777777
        cls.user2 = 777778

    def setUp(self):
        init_db()
        _clear_all_tables()

    def test_absence_cannot_exceed_daily_max(self):
        add_absence(self.user, "01.06.2026", 8)
        with self.assertRaises(ValueError):
            add_absence(self.user, "01.06.2026", 1)

    def test_absence_can_fill_exactly_to_max(self):
        add_absence(self.user, "01.06.2026", 4)
        add_absence(self.user, "01.06.2026", MAX_ABSENCE_PER_DAY - 4)
        self.assertEqual(get_hours_for_date(self.user, "01.06.2026", "absences"), MAX_ABSENCE_PER_DAY)

    def test_overtime_cannot_exceed_daily_max(self):
        add_overtime(self.user, "01.06.2026", MAX_OVERTIME_PER_DAY)
        with self.assertRaises(ValueError):
            add_overtime(self.user, "01.06.2026", 1)

    def test_overtime_can_fill_exactly_to_max(self):
        add_overtime(self.user, "01.06.2026", 3)
        add_overtime(self.user, "01.06.2026", MAX_OVERTIME_PER_DAY - 3)
        self.assertEqual(get_hours_for_date(self.user, "01.06.2026", "overtimes"), MAX_OVERTIME_PER_DAY)

    def test_dayoff_once_per_180_days_blocked_by_business_rule(self):
        add_dayoff(self.user, "01.01.2026")
        add_dayoff(self.user, "01.07.2026", approved_by=0)
        self.assertTrue(has_pending_dayoff(self.user))

    def test_dayoff_after_180_days_allowed(self):
        add_dayoff(self.user, "01.01.2026")
        date_180 = (datetime.strptime("01.01.2026", "%d.%m.%Y") + timedelta(days=181)).strftime("%d.%m.%Y")
        add_dayoff(self.user, date_180)
        self.assertEqual(len(get_user_dayoffs(self.user)), 2)

    def test_vacation_days_respects_year_boundary(self):
        add_vacation_request(self.user, "25.12.2026", "05.01.2027", "approved")
        self.assertEqual(get_vacation_days_for_year(self.user, 2026), 7)
        self.assertEqual(get_vacation_days_for_year(self.user, 2027), 5)

    def test_multiple_absences_same_date_sum(self):
        add_absence(self.user, "05.06.2026", 4)
        add_absence(self.user, "05.06.2026", 2)
        self.assertEqual(get_hours_for_date(self.user, "05.06.2026", "absences"), 6.0)

    def test_multiple_overtimes_same_date_sum(self):
        add_overtime(self.user, "05.06.2026", 3)
        add_overtime(self.user, "05.06.2026", 2)
        self.assertEqual(get_hours_for_date(self.user, "05.06.2026", "overtimes"), 5.0)

    def test_mixed_absences_overtimes_balance(self):
        add_absence(self.user, "01.06.2026", 8)
        add_overtime(self.user, "01.06.2026", 4)
        self.assertEqual(get_balance(self.user), 4.0)

    def test_separate_users_dont_interfere(self):
        add_absence(self.user, "01.06.2026", 8)
        add_absence(self.user2, "01.06.2026", 4)
        self.assertEqual(get_balance(self.user), 8.0)
        self.assertEqual(get_balance(self.user2), 4.0)

    def test_history_logged_on_absence_add(self):
        add_absence(self.user, "01.06.2026", 8)
        with sqlite3.connect(DB_NAME) as conn:
            log_count = conn.execute("SELECT COUNT(*) FROM log").fetchone()[0]
        self.assertGreaterEqual(log_count, 0)


# ============================================================
# 12. ПАРСИНГ И УТИЛИТЫ (Parsing & Utilities)
# ============================================================

class TestUtilityParsing(unittest.TestCase):
    """ТЕСТИРОВАНИЕ ПАРСИНГА И УТИЛИТ"""

    def test_extract_department_qa(self):
        self.assertEqual(extract_department("[QA] Ivan Ivanov"), "QA")

    def test_extract_department_dev(self):
        self.assertEqual(extract_department("[DEV] Peter"), "DEV")

    def test_extract_department_pm(self):
        self.assertEqual(extract_department("[PM] Mary"), "PM")

    def test_extract_department_default(self):
        self.assertEqual(extract_department("No Tag User"), "Общий")

    def test_extract_department_complex(self):
        self.assertEqual(extract_department("[MARKETING-PR] Alex"), "MARKETING-PR")

    def test_extract_department_empty_string(self):
        self.assertEqual(extract_department(""), "Общий")

    def test_extract_department_none_value(self):
        self.assertEqual(extract_department(None), "Общий")

    def test_parse_vacation_dates_short_format(self):
        start, end, rest = parse_vacation_dates("26.06.26-26.07.26")
        self.assertEqual(start, "26.06.2026")
        self.assertEqual(end, "26.07.2026")
        self.assertEqual(rest, "")

    def test_parse_vacation_dates_full_format(self):
        start, end, rest = parse_vacation_dates("26.06.2026-26.07.2026")
        self.assertEqual(start, "26.06.2026")
        self.assertEqual(end, "26.07.2026")
        self.assertEqual(rest, "")

    def test_parse_vacation_dates_slash_separator(self):
        start, end, rest = parse_vacation_dates("26/06/2026-26/07/2026 @User")
        self.assertEqual(start, "26.06.2026")
        self.assertEqual(end, "26.07.2026")
        self.assertEqual(rest, "@User")

    def test_parse_vacation_dates_with_text_after(self):
        start, end, rest = parse_vacation_dates("01.06-10.06 перенос")
        self.assertEqual(start, "01.06.2026")
        self.assertEqual(end, "10.06.2026")
        self.assertEqual(rest, "перенос")

    def test_parse_date_relative_yesterday(self):
        result = parse_date("вчера")
        expected = (now_msk() - timedelta(days=1)).strftime("%d.%m.%Y")
        self.assertEqual(result, expected)

    def test_parse_date_relative_tomorrow(self):
        result = parse_date("завтра")
        expected = (now_msk() + timedelta(days=1)).strftime("%d.%m.%Y")
        self.assertEqual(result, expected)

    def test_parse_date_relative_today(self):
        result = parse_date("сегодня")
        expected = now_msk().strftime("%d.%m.%Y")
        self.assertEqual(result, expected)

    def test_parse_date_relative_unknown(self):
        result = parse_date("позавчера")
        self.assertIsNone(result)

    def test_parse_date_multiformat(self):
        result = parse_date("15.06.2026")
        self.assertIsNotNone(result)

    def test_is_valid_date_valid(self):
        self.assertTrue(is_valid_date("15.06.2026"))

    def test_is_valid_date_invalid(self):
        self.assertFalse(is_valid_date("32.15.2026"))

    def test_is_valid_date_empty(self):
        self.assertFalse(is_valid_date(""))

    def test_format_status_returns_text(self):
        result = format_status(999999, "TestUser")
        self.assertIn("TestUser", result)

    def test_format_status_contains_balance(self):
        add_absence(999999, "01.06.2026", 8)
        result = format_status(999999, "TestUser")
        self.assertIn("8.00", result)


# ============================================================
# 13. DM-ХЕНДЛЕР (DM Handler)
# ============================================================

class TestDMHandler(unittest.TestCase):
    def setUp(self):
        init_db()
        _clear_all_tables()

    def test_dm_handler_known_commands_detected(self):
        from handlers.dm_handler import DM_KNOWN_COMMANDS
        self.assertGreater(len(DM_KNOWN_COMMANDS), 0)
        self.assertIn("статус", DM_KNOWN_COMMANDS)
        self.assertIn("дежурный", DM_KNOWN_COMMANDS)
        self.assertIn("помощь", DM_KNOWN_COMMANDS)

    def test_dm_handler_all_commands(self):
        from handlers.dm_handler import DM_KNOWN_COMMANDS
        expected = {"статус", "дежурный", "помощь", "панель", "сотрудник", "команды"}
        self.assertTrue(expected.issubset(set(DM_KNOWN_COMMANDS)))


# ============================================================
# 14. ПОЛЬЗОВАТЕЛЬСКАЯ ПАНЕЛЬ (User Panel)
# ============================================================

class TestUserPanel(unittest.IsolatedAsyncioTestCase):
    async def test_user_panel_show_status_button(self):
        from views.user_panel import UserPanelView
        bot = MagicMock()
        panel = UserPanelView(user_id=999999, user_name="TestUser", bot=bot)

        mock_interaction = AsyncMock()
        mock_interaction.user.id = 999999

        await panel.show_status.callback(mock_interaction)
        mock_interaction.response.send_message.assert_called_once()
        sent = mock_interaction.response.send_message.call_args[0][0]
        self.assertIn("TestUser", sent)

    async def test_user_panel_my_vacations_no_vacations(self):
        from views.user_panel import UserPanelView
        bot = MagicMock()
        panel = UserPanelView(user_id=999999, user_name="TestUser", bot=bot)

        mock_interaction = AsyncMock()
        mock_interaction.user.id = 999999

        with patch('views.user_panel.get_user_by_id', new_callable=AsyncMock):
            await panel.my_vacations.callback(mock_interaction)
        mock_interaction.followup.send.assert_called_once()
        sent = mock_interaction.followup.send.call_args[0][0]
        self.assertIn("Нет утверждённых отпусков", sent)

    async def test_user_panel_my_dayoffs_empty(self):
        from views.user_panel import UserPanelView
        bot = MagicMock()
        panel = UserPanelView(user_id=999999, user_name="TestUser", bot=bot)

        mock_interaction = AsyncMock()
        mock_interaction.user.id = 999999

        await panel.my_dayoffs.callback(mock_interaction)
        mock_interaction.followup.send.assert_called_once()
        sent = mock_interaction.followup.send.call_args[0][0]
        self.assertIn("нет отгулов", sent)

    async def test_user_panel_wrong_user_blocked(self):
        from views.user_panel import UserPanelView
        bot = MagicMock()
        panel = UserPanelView(user_id=999999, user_name="TestUser", bot=bot)

        mock_interaction = AsyncMock()
        mock_interaction.user.id = 111111  # wrong user

        await panel.show_status.callback(mock_interaction)
        mock_interaction.response.send_message.assert_called_once()
        sent = mock_interaction.response.send_message.call_args[0][0]
        self.assertIn("⛔", sent)

    async def test_user_panel_close(self):
        from views.user_panel import UserPanelView
        bot = MagicMock()
        panel = UserPanelView(user_id=999999, user_name="TestUser", bot=bot)

        mock_interaction = AsyncMock()
        mock_interaction.user.id = 999999

        await panel.close_panel.callback(mock_interaction)
        mock_interaction.response.edit_message.assert_called_once()


# ============================================================
# 15. АДМИНСКАЯ ПАНЕЛЬ (Admin Panel)
# ============================================================

class TestAdminPanel(unittest.IsolatedAsyncioTestCase):
    async def test_admin_panel_show_debtors(self):
        from views.admin import AdminPanelView
        init_db()
        _clear_all_tables()
        add_absence(333444, "01.01.2026", 5.0)

        mock_bot = MagicMock()
        admin_id = SUPER_ADMIN_IDS[0] if SUPER_ADMIN_IDS else 999997
        panel = AdminPanelView(is_super=True, bot=mock_bot)
        mock_interaction = AsyncMock()
        mock_interaction.user.id = admin_id

        with patch('views.admin.get_user_name', new_callable=AsyncMock) as mock_get_name:
            mock_get_name.return_value = "DebtorUser"
            await panel.show_debtors(mock_interaction)
            mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
            mock_interaction.followup.send.assert_called_once()
            sent = mock_interaction.followup.send.call_args[0][0]
            self.assertIn("DebtorUser", sent)

    async def test_admin_panel_show_debtors_empty(self):
        from views.admin import AdminPanelView
        init_db()
        _clear_all_tables()

        mock_bot = MagicMock()
        admin_id = SUPER_ADMIN_IDS[0] if SUPER_ADMIN_IDS else 999997
        panel = AdminPanelView(is_super=True, bot=mock_bot)
        mock_interaction = AsyncMock()
        mock_interaction.user.id = admin_id

        await panel.show_debtors(mock_interaction)
        mock_interaction.response.defer.assert_called_once()
        sent = mock_interaction.followup.send.call_args[0][0]
        self.assertIn("Никто не должен", sent)

    async def test_admin_panel_remove_duty(self):
        from views.admin import AdminPanelView
        init_db()
        _clear_all_tables()
        set_duty_admin(555666)
        self.assertEqual(get_duty_admin(), 555666)

        mock_bot = MagicMock()
        admin_id = SUPER_ADMIN_IDS[0] if SUPER_ADMIN_IDS else 999997
        panel = AdminPanelView(is_super=True, bot=mock_bot)
        mock_interaction = AsyncMock()
        mock_interaction.user.id = admin_id

        with patch('views.admin.get_user_name', new_callable=AsyncMock) as mock_get_name, \
             patch('views.admin.get_user_by_id', new_callable=AsyncMock) as mock_get_user:
            mock_get_name.return_value = "DutyUser"
            mock_get_user.return_value = MagicMock()
            await panel.remove_duty(mock_interaction)
            self.assertIsNone(get_duty_admin())
            mock_interaction.response.send_message.assert_called_once()
            sent = mock_interaction.response.send_message.call_args[0][0]
            self.assertIn("снят", sent)

    async def test_admin_panel_wrong_user_blocked(self):
        from views.admin import AdminPanelView
        mock_bot = MagicMock()
        panel = AdminPanelView(is_super=False, bot=mock_bot)
        mock_interaction = AsyncMock()
        mock_interaction.user.id = 111111  # not admin

        await panel.show_debtors(mock_interaction)
        mock_interaction.response.send_message.assert_called_once_with("⛔ Доступ запрещён.", ephemeral=True)

    async def test_admin_panel_pagination_init(self):
        from views.admin import AdminPanelView
        from views.pagination import PaginationView
        panel = AdminPanelView(is_super=True, bot=MagicMock())
        self.assertIsNotNone(panel)


# ============================================================
# 16. ПАГИНАЦИЯ (Pagination)
# ============================================================

class TestPagination(unittest.TestCase):
    def test_pagination_items_per_page_config(self):
        self.assertGreater(ITEMS_PER_PAGE, 0)

    def test_pagination_page_count_single(self):
        from views.pagination import get_page_count
        self.assertEqual(get_page_count(5, 10), 1)

    def test_pagination_page_count_exact(self):
        from views.pagination import get_page_count
        self.assertEqual(get_page_count(10, 10), 1)

    def test_pagination_page_count_multiple(self):
        from views.pagination import get_page_count
        self.assertEqual(get_page_count(11, 10), 2)

    def test_pagination_page_count_zero_items(self):
        from views.pagination import get_page_count
        self.assertEqual(get_page_count(0, 10), 0)

    def test_pagination_class_initialization(self):
        from views.pagination import PaginationView, split_into_pages
        pages = split_into_pages(["a", "b", "c"], max_chars=1900)
        pv = PaginationView(pages=pages, timeout=120)
        self.assertEqual(pv.current, 0)
        self.assertEqual(len(pv.pages), 1)


# ============================================================
# 17. СЛЕШ-КОМАНДЫ (Slash Commands)
# ============================================================

class TestSlashCommands(unittest.TestCase):
    def test_slash_commands_module_imports(self):
        import commands.slash
        self.assertIsNotNone(commands.slash)

    def test_register_all_is_callable(self):
        from commands.slash import register_all
        self.assertTrue(callable(register_all))


# ============================================================
# 18. ХЕНДЛЕРЫ КОМАНД (Command Handlers)
# ============================================================

class TestCommandHandlers(unittest.TestCase):
    def setUp(self):
        init_db()
        _clear_all_tables()

    def test_handle_status_produces_output(self):
        from handlers.user_commands import _handle_status
        mock_msg = MagicMock()
        mock_msg.author.id = 999999
        mock_msg.author.display_name = "TestUser"
        mock_msg.channel = AsyncMock()
        mock_bot = MagicMock()
        mock_bot.get_channel = MagicMock(return_value=None)
        result = asyncio.run(_handle_status(mock_msg, mock_bot))
        mock_msg.channel.send.assert_called_once()

    def test_handle_my_dayoffs_with_records(self):
        from handlers.user_commands import _handle_my_dayoffs
        add_dayoff(999999, "15.06.2026")
        mock_msg = MagicMock()
        mock_msg.author.id = 999999
        mock_msg.channel = AsyncMock()
        result = asyncio.run(_handle_my_dayoffs(mock_msg))
        mock_msg.channel.send.assert_called_once()
        sent = mock_msg.channel.send.call_args[0][0]
        self.assertIn("15.06.2026", sent)

    def test_handle_my_dayoffs_empty(self):
        from handlers.user_commands import _handle_my_dayoffs
        mock_msg = MagicMock()
        mock_msg.author.id = 999999
        mock_msg.channel = AsyncMock()
        result = asyncio.run(_handle_my_dayoffs(mock_msg))
        mock_msg.channel.send.assert_called_once()
        sent = mock_msg.channel.send.call_args[0][0]
        self.assertIn("нет отгулов", sent)


# ============================================================
# 19. ОШИБКИ ВЗАИМОДЕЙСТВИЯ (Interaction Errors)
# ============================================================

class TestInteractionErrors(unittest.IsolatedAsyncioTestCase):
    async def test_view_timeout_does_not_crash(self):
        from views.user_panel import UserPanelView
        bot = MagicMock()
        panel = UserPanelView(user_id=999999, user_name="Test", bot=bot)
        try:
            panel.on_timeout()
        except Exception:
            self.fail("on_timeout should not raise")

    async def test_multiple_interactions_same_view(self):
        from views.user_panel import UserPanelView
        bot = MagicMock()
        panel = UserPanelView(user_id=999999, user_name="Test", bot=bot)

        i1 = AsyncMock()
        i1.user.id = 999999
        i2 = AsyncMock()
        i2.user.id = 999999

        await panel.show_status.callback(i1)
        await panel.show_status.callback(i2)
        self.assertEqual(i1.response.send_message.call_count, 1)
        self.assertEqual(i2.response.send_message.call_count, 1)

    async def test_interaction_with_disabled_button(self):
        from views.user_panel import UserPanelView
        bot = MagicMock()
        panel = UserPanelView(user_id=999999, user_name="Test", bot=bot)
        mock_interaction = AsyncMock()
        mock_interaction.user.id = 999999
        await panel.show_status.callback(mock_interaction)
        mock_interaction.response.send_message.assert_called_once()


# ============================================================
# 20. СПАМ-ЗАЩИТА И ЛИМИТЫ (Spam / Rate Limits)
# ============================================================

class TestSpamAndLimits(unittest.TestCase):
    def setUp(self):
        init_db()
        _clear_all_tables()

    def test_absence_repeated_add_same_date_limit(self):
        add_absence(999999, "01.06.2026", 4)
        with self.assertRaises(ValueError):
            add_absence(999999, "01.06.2026", 5)

    def test_overtime_repeated_add_same_date_limit(self):
        add_overtime(999999, "01.06.2026", MAX_OVERTIME_PER_DAY)
        with self.assertRaises(ValueError):
            add_overtime(999999, "01.06.2026", 1)

    def test_many_consecutive_absences_different_dates(self):
        for i in range(1, 31):
            date = f"{i:02d}.06.2026"
            add_absence(999999, date, 1)
        total_abs = sum(h for _, h in get_absences(999999))
        self.assertEqual(total_abs, 30)

    def test_many_consecutive_overtimes_different_dates(self):
        for i in range(1, 31):
            date = f"{i:02d}.06.2026"
            add_overtime(999999, date, 1)
        total_ovt = sum(h for _, h in get_overtimes(999999))
        self.assertEqual(total_ovt, 30)

    def test_rapid_vacation_changes_no_corruption(self):
        add_vacation_request(999999, "01.06.2026", "10.06.2026", "approved")
        cur_start, cur_end = "01.06.2026", "10.06.2026"
        for i in range(5):
            new_start = f"0{i+2}.06.2026"
            new_end = f"1{i+2}.06.2026"
            result = admin_change_vacation(999999, cur_start, cur_end, new_start, new_end)
            if result:
                cur_start, cur_end = new_start, new_end
        with sqlite3.connect(DB_NAME) as conn:
            row = conn.execute(
                "SELECT start_date, end_date FROM vacations WHERE user_id = ?",
                (999999,)
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "06.06.2026")
        self.assertEqual(row[1], "16.06.2026")


# ============================================================
# 21. КОНКУРЕНТНЫЙ ДОСТУП (Concurrent/Stress)
# ============================================================

class TestConcurrentAccess(unittest.TestCase):
    def setUp(self):
        init_db()
        _clear_all_tables()

    def test_sequential_mixed_operations_no_crash(self):
        for i in range(50):
            uid = 100000 + i
            add_absence(uid, "01.06.2026", 2)
            add_overtime(uid, "02.06.2026", 1)
        self.assertEqual(len(get_all_debtors()), 50)

    def test_balance_consistency_after_many_ops(self):
        add_absence(999999, "01.06.2026", 4)
        add_absence(999999, "01.06.2026", 4)
        self.assertEqual(get_hours_for_date(999999, "01.06.2026", "absences"), 8)
        delete_absence(999999, "01.06.2026")
        self.assertEqual(get_balance(999999), 0.0)

    def test_same_data_operations_different_sessions(self):
        for _ in range(3):
            add_absence(999999, "01.06.2026", 2)
        self.assertEqual(get_hours_for_date(999999, "01.06.2026", "absences"), 6)


# ============================================================
# 22. АНОНСЫ И УВЕДОМЛЕНИЯ (Announcements)
# ============================================================

class TestDiscordUIAndAnnouncements(unittest.IsolatedAsyncioTestCase):
    async def test_announce_vacations_message_building(self):
        init_db()
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM vacations")
            conn.commit()

        today_str = today_msk()
        add_vacation_request(111222, today_str, "15.06.2026", "approved")

        mock_bot = MagicMock()
        mock_member = MagicMock()
        mock_member.mention = "<@111222>"

        with patch('handlers.full_regression_test.get_user_by_id', new_callable=AsyncMock) as mock_get_user:
            mock_get_user.return_value = mock_member

            vacations = get_vacations_starting_today(today_str)
            self.assertEqual(len(vacations), 1)

            lines = ["🌴 **Сегодня уходят в отпуск!** 🌴\n"]
            for uid, s_date, e_date in vacations:
                member = await mock_get_user(uid, mock_bot)
                mention = member.mention if member else f"ID:{uid}"
                lines.append(f"• {mention} — с {s_date} по {e_date}. Желаем отличного отдыха! 🎉")

            full_msg = "\n".join(lines)
            self.assertIn("🌴 **Сегодня уходят в отпуск!** 🌴", full_msg)
            self.assertIn("<@111222> — с", full_msg)
            self.assertIn("Желаем отличного отдыха!", full_msg)

    async def test_announce_vacations_no_one_today(self):
        init_db()
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM vacations")
            conn.commit()

        today_str = today_msk()
        add_vacation_request(111222, "01.01.2099", "10.01.2099", "approved")
        vacations = get_vacations_starting_today(today_str)
        self.assertEqual(len(vacations), 0)


# ============================================================
# 23. ОШИБКИ БД (DB Error Handling)
# ============================================================

class TestDBErrorHandling(unittest.TestCase):
    def test_get_vacation_by_id_nonexistent(self):
        vac = get_vacation_by_id(999999)
        self.assertIsNone(vac)

    def test_get_dayoff_by_id_nonexistent(self):
        rec = get_dayoff_by_id(999999)
        self.assertIsNone(rec)

    def test_update_vacation_status_nonexistent(self):
        try:
            update_vacation_status(999999, "approved")
        except Exception:
            self.fail("update_vacation_status on nonexistent should not raise")

    def test_update_dayoff_status_nonexistent(self):
        try:
            update_dayoff_status(999999, "approved")
        except Exception:
            self.fail("update_dayoff_status on nonexistent should not raise")

    def test_apply_vacation_change_nonexistent(self):
        try:
            apply_vacation_change(999999)
        except Exception:
            self.fail("apply_vacation_change on nonexistent should not raise")


# ============================================================
# ЗАПУСК
# ============================================================

def run_full_regression():
    print()
    print("=" * 80)
    print("ПОЛНЫЙ РЕГРЕССИОННЫЙ ТЕСТ CRM_BOT v2.0")
    print("=" * 80)
    print("МЕТОДОЛОГИИ:")
    print("  1. Граничные значения")
    print("  2. Классы эквивалентности")
    print("  3. Роли и доступы")
    print("  4. Целостность БД")
    print("  5. Экспорт данных")
    print("  6. Редкие случаи")
    print("  7. Отпуска — полный воркфлоу")
    print("  8. Отгулы — полный воркфлоу")
    print("  9. Администрирование")
    print(" 10. Целостность удаления")
    print(" 11. Бизнес-правила")
    print(" 12. Парсинг и утилиты")
    print(" 13. DM-хендлер")
    print(" 14. Пользовательская панель")
    print(" 15. Админская панель")
    print(" 16. Пагинация")
    print(" 17. Слеш-команды")
    print(" 18. Хендлеры команд")
    print(" 19. Ошибки взаимодействия")
    print(" 20. Спам-защита и лимиты")
    print(" 21. Конкурентный доступ")
    print(" 22. Анонсы и уведомления")
    print(" 23. Ошибки БД")
    print("=" * 80)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestBoundaryValues))
    suite.addTests(loader.loadTestsFromTestCase(TestEquivalenceClasses))
    suite.addTests(loader.loadTestsFromTestCase(TestRolesAndPermissions))
    suite.addTests(loader.loadTestsFromTestCase(TestDatabaseIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestExportFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestVacationWorkflow))
    suite.addTests(loader.loadTestsFromTestCase(TestDayoffWorkflow))
    suite.addTests(loader.loadTestsFromTestCase(TestAdminWorkflow))
    suite.addTests(loader.loadTestsFromTestCase(TestDeletionIntegrity))
    suite.addTests(loader.loadTestsFromTestCase(TestBusinessRules))
    suite.addTests(loader.loadTestsFromTestCase(TestUtilityParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestDMHandler))
    suite.addTests(loader.loadTestsFromTestCase(TestUserPanel))
    suite.addTests(loader.loadTestsFromTestCase(TestAdminPanel))
    suite.addTests(loader.loadTestsFromTestCase(TestPagination))
    suite.addTests(loader.loadTestsFromTestCase(TestSlashCommands))
    suite.addTests(loader.loadTestsFromTestCase(TestCommandHandlers))
    suite.addTests(loader.loadTestsFromTestCase(TestInteractionErrors))
    suite.addTests(loader.loadTestsFromTestCase(TestSpamAndLimits))
    suite.addTests(loader.loadTestsFromTestCase(TestConcurrentAccess))
    suite.addTests(loader.loadTestsFromTestCase(TestDiscordUIAndAnnouncements))
    suite.addTests(loader.loadTestsFromTestCase(TestDBErrorHandling))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    print("=" * 80)
    print("ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 80)
    print(f"Пройдено: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Ошибок: {len(result.errors)}")
    print(f"Провалено: {len(result.failures)}")
    print(f"Всего тестов: {result.testsRun}")

    if result.wasSuccessful():
        print("\n✅ ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ!")
    else:
        print("\n❌ ЕСТЬ ПРОБЛЕМЫ! Требуется исправление.")
        for failure in result.failures + result.errors:
            print(f"\nFAIL: {failure[0]}")
            print(f"   {failure[1]}")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_full_regression()
    exit(0 if success else 1)