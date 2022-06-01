#!/usr/bin/env python3.9
import csv
import logging
from datetime import datetime

import dateutil.parser
import yaml

_server: str = ""
_url: str = ""
_uid: str = ""
_passwd: str = ""

_journal_id = 0

logger = logging.getLogger()
with open('config.yaml') as f:
    config = yaml.safe_load(f)


class PayrollBill():
    def __init__(self):
        self.id: int = 0  # Odoo obj id
        self.bill_date: datetime = datetime.now()
        self.ref: str = ''
        self.payroll_lines: list = []

    def load(self, infile) -> None:
        pr_csv = csv.DictReader(infile)

        line = next(pr_csv)

        bd: str = line.get("Period End Date", "").strip()
        self.bill_date: datetime = dateutil.parser.parse(bd)

        dd: str = line.get("Check Date", "").strip()
        due_date: datetime = dateutil.parser.parse(dd)

        self.ref: str = line.get("Paygroup", "").strip() + line.get("Report Year", "").strip() + line.get("Week #",
                                                                                                          "").strip() + \
                        '-' + line.get("Payroll #", "").strip()


class PayrollBillLine():

    def __init__(self, description: str, total: float, department=0, earnings=0.0, fees=0.0,
                 deductions=0.0, retirement=0.0):

        self.description: str = description
        self.total: float = total
        self.department: int = department
        self.earnings: float = earnings
        self.fees: float = fees
        self.deductions: float = deductions
        self.retirement: float = retirement

        # ADP adds client level fees only to the total, we need to classify them as "fees"
        # so we can account for them. E.g. Sales tax
        if (self.fees == "" or self.fees == 0.0 or self.fees is None) and self.total != "" and self.total is not None:
            self.fees = total
            self.is_fee_only = True
        else:
            self.is_fee_only = False

    @property
    def total(self) -> float:
        return self._total

    @total.setter
    def total(self, total) -> None:
        try:
            self._total = round(float(total), 2)
        except ValueError:
            self._total = 0.0

    @property
    def earnings(self) -> float:
        return self._earnings

    @earnings.setter
    def earnings(self, earnings) -> None:
        try:
            self._earnings = round(float(earnings), 2)
        except ValueError:
            self._earnings = 0.0

    @property
    def fees(self) -> float:
        return self._fees

    @fees.setter
    def fees(self, fees) -> None:
        try:
            self._fees = round(float(fees), 2)
        except ValueError:
            self._fees = 0.0

    @property
    def deductions(self) -> float:
        return self._deductions

    @deductions.setter
    def deductions(self, deductions) -> None:
        try:
            self._deductions = round(float(deductions), 2)
        except ValueError:
            self._deductions = 0.0

    @property
    def retirement(self) -> float:
        return self._retirement

    @retirement.setter
    def retirement(self, retirement) -> None:
        try:
            self._retirement = round(float(retirement), 2)
        except ValueError:
            self._retirement = 0.0

    @property
    def department(self) -> int:
        return self._department

    @department.setter
    def department(self, department) -> None:
        try:
            self._department = int(department)
        except ValueError:
            self._department = 0

    @property
    def account_code(self) -> str:
        if self.is_fee_only is False:
            try:
                return config['accounts']['departments'][self.department]
            except KeyError:
                logger.error(f"The department {self.department} does not exist in the config file")
        return "not applicable"

    @property
    def fees_account_code(self) -> str:
        if self.department in config['direct-labor-departments']:
            return config['accounts']['expenses']['direct-labor']
        else:
            return config['accounts']['expenses']['payroll']
