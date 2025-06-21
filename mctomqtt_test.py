import unittest
from mctomqtt import MeshCoreBridge

advert_raw = '1100106A641F287C36E515FDA4B8059B0E7AF4A1B4055FFD64D898FB4D90E76C633D25105668F9AAD5F909151B34CA44FF4B7C109B062E53542267A25074785E7C51CBF653E0B5B38DEDCB293B09184CDEB03A0BDA2C6B741CF94D20FA641A41402F8E5C890C91EC62D80277E6BAF8F09F91BD43697369656E21'

class TestMessageParsing(unittest.TestCase):
    def test_advert(self):
        bridge = MeshCoreBridge(debug=True)
        result = bridge.decode_and_publish_message(advert_raw)

        print(result)

        self.assertEqual(result['payload_type'], 4)
        self.assertEqual(result['route_type'], 1)
        self.assertEqual(result['payload_version'], 0)
        self.assertEqual(result['path'], [])
        self.assertEqual(result['public_key'], '106a641f287c36e515fda4b8059b0e7af4a1b4055ffd64d898fb4d90e76c633d')
        self.assertEqual(result['advert_time'], 1750470693)
        self.assertEqual(result['signature'], 'f9aad5f909151b34ca44ff4b7c109b062e53542267a25074785e7c51cbf653e0b5b38dedcb293b09184cdeb03a0bda2c6b741cf94d20fa641a41402f8e5c890c')
        self.assertEqual(result['mode'], 'COMPANION'), 
        self.assertEqual(result['lat'], 47.735532), 
        self.assertEqual(result['lon'], -121.969033),
        self.assertEqual(result['name'], '👽Cisien!'),

if __name__ == '__main__':
    unittest.main()