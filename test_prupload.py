#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from csv import DictReader
from datetime import datetime
from unittest import TestCase

from prupload import PayrollBill, PayrollBillLine


class TestPayrollBill(TestCase):

    def test_construction(self):
        assert PayrollBill()

    def test_load(self):
        with open('test_data.csv') as f:
            test_bill = PayrollBill()
            test_bill.load(f)

            self.assertEqual(test_bill.bill_date, datetime(2022, 5, 13))
            self.assertEqual(test_bill.ref, '1QR2220-1')

    def test__add_line(self):
        pass


class TestPayrollBillLine(TestCase):
    def setUp(self) -> None:
        with open('test_data.csv', newline='') as f:
            lines = DictReader(f)

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
        return payroll_line.earnings + payroll_line.fees + \
               payroll_line.deductions + payroll_line.retirement

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
        self.assertEqual(payroll_line.account_code, "70200")
        self.assertEqual(payroll_line.fees_account_code, "70550")
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
        self.assertEqual(payroll_line.account_code, "not applicable")
        self.assertEqual(payroll_line.fees_account_code, "70550")
