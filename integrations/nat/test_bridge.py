import asyncio
import json
import os
import unittest
import httpx
from insurelens_nat.register import InsureLensConfig, invoke_bridge, register

class BridgeTests(unittest.TestCase):
    def test_actual_nat_registration_and_bridge(self):
        os.environ['INSURELENS_TEST_COOKIE']='session=test'
        calls=[]
        def handle(request):
            calls.append(request)
            if request.method=='POST':
                return httpx.Response(202,json={'jobId':'job1'})
            return httpx.Response(200,json={'state':'completed','result':{'quotes':[{'quote':'원문'}]}})
        config=InsureLensConfig(cookie_env='INSURELENS_TEST_COOKIE')
        result=asyncio.run(invoke_bridge(json.dumps({'caseId':'case1','request':{'query':'독감'}}),config,httpx.MockTransport(handle)))
        self.assertEqual(json.loads(result)['quotes'][0]['quote'],'원문')
        self.assertEqual(calls[0].headers['X-Local-Request'],'1')
        self.assertTrue(callable(register))
    def test_remote_destination_rejected(self):
        with self.assertRaisesRegex(ValueError,'Only local'):
            asyncio.run(invoke_bridge('{"caseId":"case1","request":{}}',InsureLensConfig(base_url='https://example.org')))
    def test_path_injection_rejected(self):
        with self.assertRaisesRegex(ValueError,'Invalid caseId'):
            asyncio.run(invoke_bridge('{"caseId":"../other","request":{}}',InsureLensConfig()))

if __name__=='__main__':unittest.main()
