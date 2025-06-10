import unittest,alertExchange

class TestParse(unittest.TestCase):

    def test_basics(self):
        with open("test.xml") as f:
            data = alertExchange.parse_cap_for_alert_exchange(f.read())
            self.assertIn('event',data)

    def test_find(self):
        with open("test.xml") as f:
            data = alertExchange.parse_cap_for_alert_exchange(f.read())
            self.assertIn('Alert_Name',data)
            self.assertNotEqual(data["Alert_Name"],data['event'].replace("_", " "))
            print(data['Alert_Name'])
    
    def test_route(self):
        self.assertEqual(alertExchange.build_routing_key({
            "event":"TEST",
            "urgency":"urgency",
            "certainty":"high"
        }),"alerts.TEST.urgency.high")

if __name__ == '__main__':
    unittest.main()