#!/usr/bin/env python3.10
import argparse
import csv
import re
import ssl
import sys
import xmlrpc.client
from datetime import date

import math

try:
    import yaml
except ImportError:
    print("The Py-YAML module is not installed.", sys.stderr)
    sys.exit(1)

try:
    import dateutil.parser
except ImportError:
    print("The python-dateutil module is not installed.", sys.stderr)
    sys.exit(1)

if sys.platform == "darwin":
    try:
        import macos_tags
    except ImportError:
        print("If you would like to tag files as done, install the macos-tags library via pip")

## NOTE global vars are here for test suite - they are overridden in main()
try:
    with open('config.yaml') as f:
        config = yaml.safe_load(f)

    # Set default server config to test server
    server = "odoo-dev"

    # get login info from the config file
    url = config[server]['url']
    db = config[server]['database']
    username = config[server]['username']
    password = config[server]['password']

    # get uid of user
    with xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True,
                                   context=ssl._create_unverified_context()) as common:
        uid = common.authenticate(db, username, password, {})

    with xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True,
                                   context=ssl._create_unverified_context()) as models:
        code_ids = models.execute_kw(db, uid, password, 'account.account', 'search_read',
                                     [[['deprecated', '=', False]]],
                                     {'fields': ['code', 'id']}
                                     )
    code_ids = {rec['code']: rec['id'] for rec in code_ids}

    # Cleanup
    del (common)
    del (models)

except FileNotFoundError:
    # if we're here, the test config file can not be found, which is okay
    pass


# END test global variables

def _clean_file(infile) -> list[str]:
    """Remove extra spaces from the ADP file that make csv.DictReader sad"""

    # The file is formatted like "text text"   ,"more text"   ,
    # and the extra white space after the quote causes problems
    # we find/remove all white space following a quote and before the comma

    junk = re.compile(r'"\s+,')
    return [junk.sub(r'",', line) for line in infile]


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
    def load(cls, infile) -> object:
        """:returns PayrollBill object from file with data loaded"""

        infile = _clean_file(infile)
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
    def save(cls, bill: object) -> int:
        """Creates vendor bill in Odoo.
        :type bill: PayrollBill
        :returns object id: int"""

        # Values needed to create vendor bill in Odoo
        vals = {
            'move_type': 'in_invoice',
            'partner_id': config[server]['partner-id'],
            'date': bill.date.isoformat(),
            'invoice_date': bill.date.isoformat(),
            'invoice_date_due': bill.due_date.isoformat(),
            'ref': bill.ref,
            'journal_id': config[server]['journal-id'],
        }

        # Create vendor bill in Odoo
        with xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True,
                                       context=ssl._create_unverified_context()) as models:
            bill.id = models.execute_kw(db, uid, password, 'account.move', 'create', [vals])

            # Iterate through payroll lines, creating a list of dicts for easy loading in Odoo
            vals = []
            total: float = 0.0
            for pr_line in bill.payroll_lines:
                vals.extend(pr_line.to_odoo_values(bill.id))
                total += pr_line.total

            # Add offsetting journal item for A/P
            vals.append(
                {
                    'move_id': bill.id,
                    'account_id': code_ids["20100"],
                    'credit': total,
                    'exclude_from_invoice_tab': True
                }
            )
            models.execute_kw(db, uid, password, 'account.move.line', 'create', [vals])
        return bill.id


class PayrollBillLine:

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
                        print(f"The department {self.department} does not exist in the config file", sys.stderr)
                        sys.exit(1)
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

    def to_odoo_values(self, bill_id: int) -> list[dict]:
        """Convert an ADP payroll line to Odoo dict format for creating journal items"""

        # Create a line for fees
        fees = {
            'move_id': bill_id,
            'account_id': code_ids[self.get_account_code("fees")],
            'name': f"{self.department} {self.description.title()} Payroll Fees",
            'quantity': 1,
            'price_unit': self.fees,
            'exclude_from_invoice_tab': False
        }
        # If this line is only fees, we short circuit and return now
        if self.is_fee_only:
            return [fees, ]

        # Create line for earnings
        earnings = {
            'move_id': bill_id,
            'account_id': code_ids[self.get_account_code("earnings")],
            'name': f"{self.department} {self.description.title()} Earnings",
            'quantity': 1,
            'price_unit': self.earnings,
            'exclude_from_invoice_tab': False
        }

        # Create a line for health deductions
        deductions = {
            'move_id': bill_id,
            'account_id': code_ids[self.get_account_code("deductions")],
            'name': f"{self.department} {self.description.title()} Health Deductions",
            'quantity': 1,
            'price_unit': self.deductions,
            'exclude_from_invoice_tab': False
        }

        # Create a line for 401k retirement
        retirement = {
            'move_id': bill_id,
            'account_id': code_ids[self.get_account_code("retirement")],
            'name': f"{self.department} {self.description.title()} 401k Retirement",
            'quantity': 1,
            'price_unit': self.retirement,
            'exclude_from_invoice_tab': False
        }

        return [earnings, fees, deductions, retirement]


class XLPayrollFile:

    def __init__(self, filename: str):
        self.header_data: dict = {}

        self.filename: str = filename

    def read_xl_file(self) -> None:
        with open(self.filename, 'rb') as xl_file:
            pass


def main():
    parser = argparse.ArgumentParser(conflict_handler='resolve',
                                     description='Import ADP payroll csv files into Odoo as vendor bills'
                                     )
    parser.add_argument('-c', '--config', dest='configfile', type=str, required=False,
                        default='/usr/local/etc/prupload.conf',
                        help='specify a different config file (default "/usr/local/etc/prupload.conf")')
    parser.add_argument('-s', '--server', dest='server', type=str, required=False, default='odoo',
                        help='specify a different server config to use from config file (default "odoo")')
    parser.add_argument('input', metavar='input', type=str, help='payroll cvs filename')

    args = parser.parse_args()

    global server
    server = args.server

    with open(args.configfile) as f:
        global config, url, db, username, password, uid, code_ids

        config = yaml.safe_load(f)

        # get login info from the config file and store in globals
        url = config[server]['url']
        db = config[server]['database']
        username = config[server]['username']
        password = config[server]['password']

    # get uid of user
    with xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True,
                                   context=ssl._create_unverified_context()) as common:
        # uid is global
        uid = common.authenticate(db, username, password, {})

    # Get ids of account codes
    with xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True,
                                   context=ssl._create_unverified_context()) as models:
        codes = models.execute_kw(db, uid, password, 'account.account', 'search_read',
                                  [[['deprecated', '=', False]]],
                                  {'fields': ['code', 'id']}
                                  )
    # code_ids are global
    code_ids = {rec['code']: rec['id'] for rec in codes}

    with open(args.input, newline='') as infile:
        bill = PayrollBill.load(infile)
        bill_id = PayrollBill.save(bill)
        print(f"\n{url}/web#id={bill_id}&cids=1&menu_id=240&action=1237&model=account.move&view_type=form\n")

        # See if we can tag the file on MacOS
        try:
            tag = macos_tags.Tag("Done", color=macos_tags.Color.GRAY)
            macos_tags.add(tag, file=infile)
        except ModuleNotFoundError:
            pass


if __name__ == '__main__':
    main()
