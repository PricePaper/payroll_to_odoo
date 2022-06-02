#!/usr/bin/env python3.10
import csv
import logging
import re
import ssl
import xmlrpc.client
from datetime import datetime, date

import dateutil.parser
import math
import yaml

logger = logging.getLogger()
with open('config.yaml') as f:
    config = yaml.safe_load(f)


class PayrollBill():
    def __init__(self):
        self.id: int = 0  # Odoo obj id
        self.date: date = date.today()
        self.due_date: date = date.today()
        self.ref: str = ''
        self.payroll_lines: list = []

    @property
    def invoice_total(self) -> float:
        if len(self.payroll_lines) > 0:
            return round(math.fsum([l.total for l in self.payroll_lines]), 2)
        else:
            return 0.0

    @classmethod
    def _clean_file(cls, infile) -> list[str]:
        """Remove extra spaces from the ADP file that make csv.DictReader sad"""

        # The file is formatted like "text text"   ,"more text"   ,
        # and the extra white space after the quote causes problems
        # so we find/remove all white space following a quote and before the comma
        junk = re.compile(r'"\s+,')
        cleanfile: list[str] = [junk.sub(r'",', line) for line in infile]

        return cleanfile

    @classmethod
    def load(cls, infile) -> object:
        """:returns PayrollBill object from file with data loaded"""

        infile = cls._clean_file(infile)
        pr_csv = csv.DictReader(infile, dialect='unix', quoting=csv.QUOTE_ALL)

        # slurp all lines to make life easy
        payroll_lines: list[dict] = [x for x in pr_csv]
        line: dict = payroll_lines[0]

        # Create a new PayrollBill object
        bill = PayrollBill()

        bd: str = line.get("Period End Date", "")
        bill.date = dateutil.parser.parse(bd).date()

        dd: str = line.get("Check Date", "")
        bill.due_date = dateutil.parser.parse(dd).date()

        bill.ref = line.get("Paygroup", "") + '-20' + line.get("Report Year", "") + "-W" + \
                   line.get("Week #", "") + '-' + line.get("Payroll #", "")

        # Add payroll lines to payroll bill
        for line in payroll_lines:
            bill.payroll_lines.append(
                PayrollBillLine(
                    description=line['Dept Descr'],
                    total=line['Total Payroll Bill'],
                    department=line['Worked Department #'],
                    earnings=line['Gross Earnings'],
                    fees=line['Total Fee'],
                    deductions=line['Deduct Adjust'],
                    retirement=line['Employer Contrib (401k)']
                )
            )
        return bill

    @classmethod
    def save_to(cls, server: str, bill: object) -> int:
        """Creates vendor bill in Odoo.
        :returns object id: int"""

        # get login info from the config file
        url = config[server]['url']
        db = config[server]['database']
        username = config[server]['username']
        password = config[server]['password']

        # get uid of user
        with xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True,context=ssl._create_unverified_context()) as common:
            uid = common.authenticate(db, username, password, {})

        vals = {
            'move_type': 'in_invoice',
            'partner_id': config[server]['partner-id'],
            'date': bill.date.isoformat(),
            'invoice_date': bill.date.isoformat(),
            'invoice_date_due': bill.due_date.isoformat(),
            'ref': bill.ref,
            'journal_id': config[server]['journal-id'],
        }
        with xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True,context=ssl._create_unverified_context()) as models:
            bill.id = models.execute_kw(db, uid, password, 'account.move', 'create', [vals])

        vals = []

        for pr_line in bill.payroll_lines:
            vals.append(
                {
                    'move_id': bill.id,


                }
            )

        return bill.id


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
        return round(self._total, 2)

    @total.setter
    def total(self, total) -> None:
        try:
            self._total = round(float(total), 2)
        except ValueError:
            self._total = 0.0

    @property
    def earnings(self) -> float:
        return round(self._earnings, 2)

    @earnings.setter
    def earnings(self, earnings) -> None:
        try:
            self._earnings = round(float(earnings), 2)
        except ValueError:
            self._earnings = 0.0

    @property
    def fees(self) -> float:
        return round(self._fees, 2)

    @fees.setter
    def fees(self, fees) -> None:
        try:
            self._fees = round(float(fees), 2)
        except ValueError:
            self._fees = 0.0

    @property
    def deductions(self) -> float:
        return round(self._deductions, 2)

    @deductions.setter
    def deductions(self, deductions) -> None:
        try:
            self._deductions = round(float(deductions), 2)
        except ValueError:
            self._deductions = 0.0

    @property
    def retirement(self) -> float:
        return round(self._retirement, 2)

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

    def get_account_code(self, prop: str) -> str:
        match prop:
            case "earnings":
                if self.is_fee_only is False:
                    try:
                        return config['accounts']['departments'][self.department]
                    except KeyError:
                        logger.error(f"The department {self.department} does not exist in the config file")
                return "not applicable"
            case "fees":
                if self.department in config['direct-labor-departments']:
                    return config['accounts']['expenses']['direct-labor']
                else:
                    return config['accounts']['expenses']['payroll']
            case "deductions":
                return config['accounts']['expenses']['health']
            case "retirement":
                return config['accounts']['expenses']['pension']
        return ""
