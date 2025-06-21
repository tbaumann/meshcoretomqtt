import unittest
from mctomqtt import MeshCoreBridge

advert_raw_companion = '1100106A641F287C36E515FDA4B8059B0E7AF4A1B4055FFD64D898FB4D90E76C633D25105668F9AAD5F909151B34CA44FF4B7C109B062E53542267A25074785E7C51CBF653E0B5B38DEDCB293B09184CDEB03A0BDA2C6B741CF94D20FA641A41402F8E5C890C91EC62D80277E6BAF8F09F91BD43697369656E21'
advert_raw_repeater = '1200C51DEEC07A23CE758D065FAFB3A79014E75AE0DFD9EECAFF9A9F27E055A84136943456680C071497FB33D9A6BDAB04C8A5E82F94BC0B92C9186EAB48CA92C9C306B92E1E03372FCB6F9711AA79629A0C7F39F4B65487F784454DA8D2949D5E9DA3CF310692C962D80211E7BAF843697369656E2053746174696F6E'

class TestMessageParsing(unittest.TestCase):
    def test_companion_advert(self):
        bridge = MeshCoreBridge(debug=True)
        result = bridge.decode_and_publish_message(advert_raw_companion)

        print(result)

        self.assertEqual(result['payload_type'], 4)
        self.assertEqual(result['route_type'], 1)
        self.assertEqual(result['payload_version'], 0)
        self.assertEqual(result['path'], [])
        self.assertEqual(result['public_key'], '106a641f287c36e515fda4b8059b0e7af4a1b4055ffd64d898fb4d90e76c633d')
        self.assertEqual(result['advert_time'], 1750470693)
        self.assertEqual(result['signature'], 'f9aad5f909151b34ca44ff4b7c109b062e53542267a25074785e7c51cbf653e0b5b38dedcb293b09184cdeb03a0bda2c6b741cf94d20fa641a41402f8e5c890c')
        self.assertEqual(result['mode'], 'COMPANION'), 
        self.assertEqual(result['lat'], 47.74), 
        self.assertEqual(result['lon'], -121.97),
        self.assertEqual(result['name'], '👽Cisien!'),

    def test_repeater_advert(self):
        bridge = MeshCoreBridge(debug=True)
        result = bridge.decode_and_publish_message(advert_raw_repeater)

        print(result)

        self.assertEqual(result['payload_type'], 4)
        self.assertEqual(result['route_type'], 2)
        self.assertEqual(result['payload_version'], 0)
        self.assertEqual(result['path'], [])
        self.assertEqual(result['public_key'], 'c51deec07a23ce758d065fafb3a79014e75ae0dfd9eecaff9a9f27e055a84136')
        self.assertEqual(result['advert_time'], 1750480020)
        self.assertEqual(result['signature'], '0c071497fb33d9a6bdab04c8a5e82f94bc0b92c9186eab48ca92c9c306b92e1e03372fcb6f9711aa79629a0c7f39f4b65487f784454da8d2949d5e9da3cf3106')
        self.assertEqual(result['mode'], 'REPEATER'), 
        self.assertEqual(result['lat'], 47.74), 
        self.assertEqual(result['lon'], -121.97),
        self.assertEqual(result['name'], 'Cisien Station'),

    def test_room_server_advert(self):
        self.assertTrue(True)


if __name__ == '__main__':
    unittest.main()