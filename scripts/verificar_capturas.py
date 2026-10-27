#!/usr/bin/env python3
"""Comprueba integridad PNG, dimensiones y SHA-256 sin dependencias externas."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]
SCREENS = (
    '01_ahora_lista', '02_mapa', '03_manana', '04_detalle',
    '05_selector_lugar', '06_fuentes', '07_privacidad',
)
DEVICES = {'telefono': (1080, 1920), 'tablet_7': (1280, 1920), 'tablet_10': (1600, 2560)}


def expected_files():
    files = {
        f'{device}/{theme}_{screen}.png': dimensions
        for device, dimensions in DEVICES.items()
        for theme in ('claro', 'oscuro') for screen in SCREENS
    }
    files.update({'grafico_funciones_1024x500.png': (1024, 500), 'icono_512x512.png': (512, 512)})
    return files


def png_dimensions(data):
    """Rechaza PNG truncado/corrupto y formatos distintos de RGB/RGBA de 8 bits."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Firma PNG inválida')
    offset, dimensions, image_data, ended = 8, None, bytearray(), False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError('PNG truncado')
        size = struct.unpack_from('>I', data, offset)[0]
        tag = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        end = offset + 12 + size
        if end > len(data) or zlib.crc32(tag + payload) != struct.unpack_from('>I', data, end - 4)[0]:
            raise ValueError('Bloque PNG corrupto')
        if dimensions is None and tag != b'IHDR':
            raise ValueError('Falta IHDR al inicio')
        if tag == b'IHDR':
            if dimensions is not None or size != 13:
                raise ValueError('IHDR inválido')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            if not width or not height or depth != 8 or color not in (2, 6) or (compression, filtering, interlace) != (0, 0, 0):
                raise ValueError('Se requiere PNG RGB/RGBA de 8 bits sin entrelazar')
            dimensions = width, height
            channels = 3 if color == 2 else 4
        elif tag == b'IDAT':
            image_data.extend(payload)
        elif tag == b'IEND':
            if size or end != len(data):
                raise ValueError('Final PNG inválido')
            ended = True
            break
        offset = end
    if not ended or dimensions is None:
        raise ValueError('PNG incompleto')
    decoded = zlib.decompress(image_data)
    if len(decoded) != (width * channels + 1) * height:
        raise ValueError('Datos de píxeles incompletos')
    return dimensions


def build_manifest(folder):
    expected = expected_files()
    found = {p.relative_to(folder).as_posix() for p in folder.rglob('*.png')}
    if found != set(expected):
        raise ValueError(f'PNG ausentes: {sorted(set(expected) - found)}; sobrantes: {sorted(found - set(expected))}')
    manifest = {}
    for name, size in sorted(expected.items()):
        data = (folder / name).read_bytes()
        if png_dimensions(data) != size:
            raise ValueError(f'Dimensiones incorrectas: {name}, se esperaba {size}')
        manifest[name] = {'ancho': size[0], 'alto': size[1], 'sha256': hashlib.sha256(data).hexdigest()}
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actualizar-manifiesto', action='store_true')
    args = parser.parse_args()
    folder = ROOT / 'play/capturas'
    manifest = build_manifest(folder)
    destination = folder / 'manifiesto.json'
    if args.actualizar_manifiesto:
        destination.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    elif json.loads(destination.read_text(encoding='utf-8')) != manifest:
        raise ValueError('El manifiesto no coincide con los PNG; regenera los recursos')
    print(f'{len(manifest)} PNG válidos; dimensiones y SHA-256 correctos.')


if __name__ == '__main__':
    main()
