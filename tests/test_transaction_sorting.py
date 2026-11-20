import unittest
from transactions import transaction_sql,SORT_COLUMNS

class TransactionSortingTests(unittest.TestCase):
    def test_sort_whitelist_and_stable_order_before_pagination(self):
        for column in SORT_COLUMNS:
            for direction in ('asc','desc'):
                with self.subTest(column=column,direction=direction):
                    sql=transaction_sql({'sort':[column],'direction':[direction],'page':['2']})
                    self.assertIn(', j.id DESC LIMIT 100 OFFSET 100',sql)
                    self.assertIn(direction.upper(),sql)
        for params in ({'sort':['j.id; DELETE']},{'direction':['DESC; SELECT 1']}):
            with self.assertRaises(ValueError):transaction_sql(params)

    def test_numeric_price_and_vendor_values_and_export_sort(self):
        sql=transaction_sql({'sort':['vendor'],'direction':['desc']},export=True)
        self.assertIn('j.quantity*COALESCE(t.SellPrice,0)',sql)
        self.assertIn('IS NULL ASC',sql)
        self.assertNotIn('LIMIT 100',sql)
        sql=transaction_sql({'sort':['price'],'direction':['asc']})
        self.assertIn("WHEN 'mail_sent_observed' THEN j.mail_postage",sql)
        self.assertIn("WHEN 'listing_observed' THEN j.start_bid",sql)
