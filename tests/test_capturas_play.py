"""Regresiones del validador de recursos, sin descargar ni generar datos."""
import struct
import unittest
import zlib

from scripts.verificar_capturas import expected_files, png_dimensions


def chunk(tag, payload):
    return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', zlib.crc32(tag + payload))


def png(width=2, height=3):
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\x00' + b'\xff\xff\xff' * width) * height))
            + chunk(b'IEND', b''))


class PlayResourcesTest(unittest.TestCase):
    def test_rgb_dimensions(self):
        self.assertEqual(png_dimensions(png()), (2, 3))

    def test_corruption_and_truncation_rejected(self):
        data = png()
        for invalid in (b'no PNG', data[:-1], data[:40], data + b'extra', data[:42] + b'X' + data[43:]):
            with self.subTest(invalid=invalid[:16]), self.assertRaises(ValueError):
                png_dimensions(invalid)

    def test_resource_matrix_and_play_sizes(self):
        resources = expected_files()
        self.assertEqual(len(resources), 44)
        for device in ('telefono', 'tablet_7', 'tablet_10'):
            self.assertEqual(sum(name.startswith(device + '/') for name in resources), 14)
        for name, (width, height) in resources.items():
            self.assertGreaterEqual(min(width, height), 320)
            self.assertLessEqual(max(width, height), 3840)
            if '/' in name:
                self.assertLessEqual(max(width, height), min(width, height) * 2)
