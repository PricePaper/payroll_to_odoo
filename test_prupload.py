#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from csv import DictReader
from datetime import date
from unittest import TestCase

from prupload import PayrollBill, PayrollBillLine, _clean_file, XLPayrollFile


class TestPayrollBill(TestCase):

    def setUp(self) -> None:
        with open('test_data.csv', newline='') as f:
            self.csvfile = _clean_file(f)

    def test_construction(self):
        assert PayrollBill()
        self.assertEqual(PayrollBill().invoice_total, 0)

    def test_load(self):
        test_bill = PayrollBill.load(self.csvfile)

        self.assertEqual(test_bill.date, date(2022, 5, 13))
        self.assertEqual(test_bill.ref, '1QR-2022-W20-1')
        self.assertEqual(len(test_bill.payroll_lines), 8)
        self.assertEqual(test_bill.invoice_total, 28356.58)

    def test_save(self):
        bill = PayrollBill.load(self.csvfile)

        PayrollBill.save(bill)

        assert bill.id > 0
        print(f"Vendor Bill id = {bill.id}")


class TestPayrollBillLine(TestCase):
    def setUp(self) -> None:
        with open('test_data.csv', newline='') as f:
            lines = DictReader(_clean_file(f))

            # slurp all lines to make life easy
            self.payroll_lines: list = [x for x in lines]

    def _get_new_payroll_line(self, line) -> PayrollBillLine:
        test_payroll_line = PayrollBillLine(
            description=line['Dept Descr'],
            total=line['Total Payroll Bill'],
            department=line['Worked Department #'],
            earnings=line['Gross Earnings'],
            fees=line['Total Fee'],
            deductions=line['Deduct Adjust'],
            retirement=line['Employer Contrib (401k)']
        )
        return test_payroll_line

    def _calculate_total(self, payroll_line):
        return round(payroll_line.earnings + payroll_line.fees +
                     payroll_line.deductions + payroll_line.retirement, 2)

    def test_construction(self):
        """Test first payroll line"""
        payroll_line = self._get_new_payroll_line(self.payroll_lines[0])

        assert payroll_line.department == 10
        assert payroll_line.description == "Office"
        assert payroll_line.earnings == 2386.93
        assert payroll_line.fees == 253.77
        assert payroll_line.deductions == -257.02
        assert payroll_line.retirement == 26.34
        assert payroll_line.total == 2410.02

        self.assertEqual(payroll_line.total, self._calculate_total(payroll_line),
                         "Line values do not equal line total")
        self.assertEqual(payroll_line.get_account_code("earnings"), "70200")
        self.assertEqual(payroll_line.get_account_code("fees"), "70550")
        self.assertEqual(payroll_line.get_account_code("deductions"), "73000")
        self.assertEqual(payroll_line.get_account_code("retirement"), "75900")
        self.assertFalse(payroll_line.is_fee_only)

    def test_fee_only_payroll_line(self):
        """Test line with sales tax only"""
        payroll_line = self._get_new_payroll_line(self.payroll_lines[6])

        assert payroll_line.description == "(NY) SALES TAX"
        assert payroll_line.fees == 24.16
        assert payroll_line.total == 24.16
        self.assertEqual(payroll_line.total, self._calculate_total(payroll_line),
                         "Line values do not equal line total")
        self.assertTrue(payroll_line.is_fee_only)
        self.assertEqual(payroll_line.get_account_code("earnings"), "not applicable")
        self.assertEqual(payroll_line.get_account_code("fees"), "70550")

    def test_direct_labor_payroll_line(self):
        """Test direct labor payroll line"""
        payroll_line = self._get_new_payroll_line(self.payroll_lines[1])

        assert payroll_line.department == 30
        assert payroll_line.description == "Warehouse"
        assert payroll_line.earnings == 6868.68
        assert payroll_line.fees == 1180.77
        assert payroll_line.deductions == -210.92
        assert payroll_line.retirement == 43
        assert payroll_line.total == 7881.53

        self.assertEqual(payroll_line.total, self._calculate_total(payroll_line),
                         "Line values do not equal line total")
        self.assertEqual(payroll_line.get_account_code("earnings"), "50350")
        self.assertEqual(payroll_line.get_account_code("fees"), "50370")
        self.assertEqual(payroll_line.get_account_code("deductions"), "73000")
        self.assertEqual(payroll_line.get_account_code("retirement"), "75900")
        self.assertFalse(payroll_line.is_fee_only)

    def test_to_odoo_values_regular_line(self):
        """Test direct labor payroll line"""
        payroll_line = self._get_new_payroll_line(self.payroll_lines[1])

        entries = payroll_line.to_odoo_values(1234)

        self.assertEqual(len(entries), 4)

    def test_to_odoo_values_fees_line(self):
        """Test direct labor payroll line"""
        payroll_line = self._get_new_payroll_line(self.payroll_lines[7])

        entries = payroll_line.to_odoo_values(1234)

        self.assertEqual(len(entries), 1)


class TestXLPayrollFile(TestCase):

    def test_constructor(self):
        payroll_file = XLPayrollFile('new_test_data.xls')
        self.assertIsInstance(payroll_file, XLPayrollFile)
        self.assertEqual('new_test_data.xls', payroll_file.filename)

    def setUp(self) -> None:
        self.reader = XLPayrollFile('new_test_data.xls')

    def test_read_xl_file(self):
        self.reader.read_xl_file()

        # check file header info
        test_header_data = {
            "paygroup": "6RZ",
            "reference": "NCTS-6RZ20231301",
            "total": 13173.11,
            "due_date": date(2023, 3, 30),
            "end_date": date(2023, 3, 24)
        }

        self.assertDictEqual(test_header_data, self.reader.header_data)

        # Check that payroll lines exist
        self.assertEqual(4, len(self.reader.pay_data.keys()))
