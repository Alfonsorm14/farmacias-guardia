"""Fixtures reales; las alteraciones de robustez se crean explícitamente en cada test."""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch, Mock

from ingesta.asturias_download import Client, NoRedirect, ORIGIN, USER_AGENT, download, robots_policy
from ingesta.common import TZ
from ingesta.parsers.asturias import POST_URL, inspect_html, parse_dir, parse_html
from scripts import actualizar_todo, run_asturias

FIXTURES = Path(__file__).parent / "fixtures/asturias"
DAY = date(2026, 11, 7)
HTML = (FIXTURES / "2026-11-07.html").read_bytes()


class AsturiasTests(unittest.TestCase):
    def test_capturas_no_alteradas_y_limite_real(self):
        for name, digest in json.loads((FIXTURES / "sha256.json").read_text()).items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest)
        for day in (DAY, date(2026, 11, 8), date(2027, 12, 31)):
            self.assertGreater(len(parse_html((FIXTURES / f"{day}.html").read_bytes(), day).shifts), 80)
        empty = parse_html((FIXTURES / "2028-01-01.html").read_bytes(), date(2028, 1, 1))
        self.assertFalse(empty.pharmacies)
        self.assertFalse(empty.shifts)
        self.assertIn("SIN_DATOS", empty.warnings[0])

    def test_identidad_campos_tildes_y_localizada(self):
        result = parse_html(HTML, DAY)
        pharmacy = result.pharmacies["AS:183"]
        self.assertEqual((pharmacy.region, pharmacy.holder, pharmacy.phone, pharmacy.postal_code),
            ("03", "RODRIGUEZ-PELAEZ PEÑA, ANA MARIA", "985807047", "33880"))
        self.assertEqual(result.pharmacies["AS:205"].locality, "CABAÑAQUINTA")
        self.assertEqual(result.pharmacies["AS:113"].duty_phone, "652276947")
        self.assertEqual(next(s for s in result.shifts if s.pharmacy_id == "AS:183").kind, "localizada")
        self.assertIn("pendiente", result.source.license)

    def test_noche_ayer_manana_y_24h(self):
        shifts = parse_html(HTML, DAY).shifts
        previous = next(s for s in shifts if s.pharmacy_id == "AS:280")
        self.assertEqual(previous.start, datetime(2026, 11, 6, 22, tzinfo=TZ))
        self.assertEqual(previous.end, datetime(2026, 11, 7, 9, 30, tzinfo=TZ))
        overnight = next(s for s in shifts if s.pharmacy_id == "AS:265")
        self.assertEqual(overnight.start, datetime(2026, 11, 7, 22, tzinfo=TZ))
        self.assertEqual(overnight.end, datetime(2026, 11, 8, 9, 30, tzinfo=TZ))
        self.assertEqual(overnight.kind, "nocturna")
        full = next(s for s in shifts if s.pharmacy_id == "AS:94")
        self.assertEqual(full.kind, "24h")
        self.assertEqual(full.end, datetime(2026, 11, 8, 9, 30, tzinfo=TZ))

    def test_sin_telefono_y_concejo_son_mutaciones_no_capturas(self):
        changed = HTML.replace(b'985807047', b'').replace(b'>ALLANDE</h4>', '>Concejo de Peñamellera</h4>'.encode())
        parsed = parse_html(changed, DAY, filename="mutacion.html")
        self.assertIsNone(parsed.pharmacies["AS:183"].phone)
        self.assertEqual(next(s for s in parsed.shifts if s.pharmacy_id == "AS:183").zone, "Concejo de Peñamellera")
        self.assertTrue(any("mutacion.html:página 1:línea" in w and "teléfono" in w for w in parsed.warnings))

    def test_no_proyecta_semana_ni_festivos(self):
        parsed = parse_html(HTML, DAY)
        self.assertTrue(any("semanal" in w for w in parsed.warnings))
        self.assertTrue(any("festivos" in w for w in parsed.warnings))
        self.assertFalse(any("viernes siguiente" in s.raw_label for s in parsed.shifts))
        unknown = HTML.replace('De 9,30 horas a 10 de la noche'.encode(), b'Duracion semanal desconocida')
        parsed = parse_html(unknown, DAY)
        self.assertTrue(any('horario nuevo sin inspeccionar' in w for w in parsed.warnings))
        self.assertFalse(any('Duracion semanal desconocida' in s.raw_label for s in parsed.shifts))

    def test_domingo_publicado_no_necesita_inferir_festivos(self):
        day = date(2026,11,8)
        parsed = parse_html((FIXTURES / f'{day}.html').read_bytes(), day)
        shift = next(s for s in parsed.shifts if s.pharmacy_id == 'AS:379')
        self.assertEqual(shift.zone, 'CORVERA DE ASTURIAS')
        self.assertEqual(shift.start, datetime(2026,11,8,10,tzinfo=TZ))
        self.assertEqual(shift.end, datetime(2026,11,8,22,tzinfo=TZ))

    def test_cambios_de_estructura_fecha_y_paginacion_fallan(self):
        for changed, day in [(HTML[:2000], DAY), (HTML, date(2026, 11, 8)),
            (HTML.replace(b'</form>', b'<a href="?intPagina=2">2</a></form>'), DAY)]:
            with self.assertRaises(ValueError):
                parse_html(changed, day)
        changed = HTML.replace(b'N&ordm; Farmacia:&nbsp;183', b'N&ordm; Farmacia:&nbsp;')
        self.assertTrue(any("número de farmacia" in w for w in parse_html(changed, DAY).warnings))
        changed = HTML.replace(b'<h5 class="HorarioGuardias"><a name=\'09:30 - 22:00\'>',
                               b'<h5 class="HorarioCambiado"><a name=\'09:30 - 22:00\'>')
        parsed = parse_html(changed, DAY)
        self.assertFalse(any(s.pharmacy_id == 'AS:275' for s in parsed.shifts))
        self.assertTrue(any('horario sin intervalo legible' in w for w in parsed.warnings))

    def test_recarga_del_dia_reemplaza_farmacia_intercambiada(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / f"{DAY}.html"
            path.write_bytes(HTML)
            before = parse_dir(temp)
            path.write_bytes(HTML.replace(b'N&ordm; Farmacia:&nbsp;183', b'N&ordm; Farmacia:&nbsp;999'))
            after = parse_dir(temp)
            self.assertIn("AS:183", before.pharmacies)
            self.assertNotIn("AS:183", after.pharmacies)
            self.assertIn("AS:999", after.pharmacies)

    def test_noche_repetida_prefiere_asignacion_mas_reciente(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / '2026-11-07.html').write_bytes(HTML)
            next_day = (FIXTURES / '2026-11-08.html').read_bytes()
            changed = next_day.replace(b'N&ordm; Farmacia:&nbsp;265', b'N&ordm; Farmacia:&nbsp;999')
            (Path(temp) / '2026-11-08.html').write_bytes(changed)
            result = parse_dir(temp)
            interval = [s for s in result.shifts if s.zone == 'AVILÉS' and s.start == datetime(2026,11,7,22,tzinfo=TZ)]
            self.assertEqual({s.pharmacy_id for s in interval}, {'AS:999'})

    def test_robots_real_y_reglas_mas_especificas(self):
        robots = (FIXTURES / "robots.txt").read_text()
        self.assertTrue(robots_policy(robots, POST_URL)[0])
        self.assertFalse(robots_policy(robots, ORIGIN + "/GESCOF/index.asp?idMenu=111&fechatratada=20261107")[0])
        self.assertFalse(robots_policy("User-agent: *\nDisallow: /", POST_URL)[0])
        self.assertEqual(robots_policy("User-agent: *\nDisallow: /\nAllow: /GESCOF/\nCrawl-delay: 3", POST_URL), (True, 3))

    def test_post_real_cache_y_frecuencia(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.side_effect = [(FIXTURES / "robots.txt").read_bytes(), HTML]
        opener = Mock()
        opener.open.return_value = response
        with tempfile.TemporaryDirectory() as temp, patch('ingesta.asturias_download.urllib.request.build_opener', return_value=opener), patch('ingesta.asturias_download.time.sleep') as sleep:
            client = Client(temp)
            client.day(DAY)
            client.day(DAY)
            self.assertEqual(opener.open.call_count, 2)
            req = opener.open.call_args.args[0]
            self.assertEqual(req.full_url, POST_URL)
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(req.data, b'busqueda=1&Fecha=07%2F11%2F2026&txtMunicipio=&txtLocalidad=&btnBuscar=Buscar')
            self.assertIn("https://github.com/Alfonsorm14/farmacias-guardia", USER_AGENT)
            self.assertGreater(sleep.call_args.args[0], 1)

    def test_robots_denegado_y_redireccion_no_hacen_busquedas(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Client, '_request', return_value=b'User-agent: *\nDisallow: /') as request:
            client = Client(temp)
            with self.assertRaises(PermissionError):
                client.day(DAY)
            self.assertEqual(request.call_count, 1)
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, 302, '', {}, 'http://otro.example/')

    def test_error_de_red_indica_peticion_sin_reintentar(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Client, '_request', side_effect=[b'User-agent: *', OSError('fallo de red')]) as request:
            client = Client(temp)
            with self.assertRaisesRegex(RuntimeError, '2026-11-07: POST') as exc:
                client.day(DAY)
            self.assertIn('Fecha=07%2F11%2F2026', str(exc.exception))
            self.assertEqual(request.call_count, 2)

    def test_descubrimiento_se_detiene_en_vacio_sin_rellenar(self):
        def response(day):
            if day == date(2027,12,31):
                return (FIXTURES / '2027-12-31.html').read_bytes()
            # Mutación explícita de la fecha del formulario vacío para simular el bloque.
            return (FIXTURES / '2028-01-01.html').read_bytes().replace(b'01/01/2028', day.strftime('%d/%m/%Y').encode())
        with tempfile.TemporaryDirectory() as temp, patch.object(Client, '__init__', return_value=None), patch.object(Client, 'day', side_effect=response):
            report = download(temp, start=date(2027,12,31))
            self.assertEqual(report['dates'], ['2027-12-31'])
            self.assertEqual(report['empty_dates'], ['2028-01-01'])
            self.assertEqual(len(list(Path(temp).glob('*.html'))), 2)
            self.assertTrue(parse_dir(temp).shifts)

    def test_flag_por_defecto_no_toca_snapshot_ni_red(self):
        snapshot = Path(actualizar_todo.BASE_DIR) / "app/assets/snapshot.json"
        before = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(run_asturias.enabled())
        with patch.dict(os.environ, {"ENABLE_ASTURIAS": "false"}), patch('sys.argv', ['run_asturias.py']), patch.object(run_asturias, 'download') as net:
            self.assertEqual(run_asturias.main(), 0)
            net.assert_not_called()
        with patch.dict(os.environ, {"ENABLE_ASTURIAS": "false"}), patch('sys.argv', ['actualizar_todo.py', '--sin-descargas']), patch.object(actualizar_todo, '_run') as run:
            actualizar_todo.main()
            self.assertEqual([c.args[0] for c in run.call_args_list],
                ['scripts/run_navarra.py', 'scripts/run_madrid.py', 'scripts/run_zaragoza.py',
                 '-m', '-m', 'scripts/export_snapshot.py', 'scripts/generar_paridad.py'])
        self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), before)

    def test_activacion_local_genera_y_ci_rechaza(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"ENABLE_ASTURIAS": "true", "GITHUB_ACTIONS": "false"}), patch.object(run_asturias, 'BASE_DIR', Path(temp)), patch('sys.argv', ['run_asturias.py', '--sin-descargas', '--raw', str(FIXTURES)]):
                self.assertEqual(run_asturias.main(), 0)
                output = json.loads((Path(temp) / 'data/propuestas/asturias/asturias.json').read_text(encoding='utf-8'))
                self.assertGreater(len(output['shifts']), 200)
                self.assertFalse((Path(temp) / 'data/out').exists())
            with patch.dict(os.environ, {"ENABLE_ASTURIAS": "true", "GITHUB_ACTIONS": "true"}), patch('sys.argv', ['run_asturias.py']):
                with self.assertRaises(RuntimeError):
                    run_asturias.main()

    def test_fallo_opcional_no_impide_actualizar_las_fuentes_actuales(self):
        def run(*args):
            if args[0] == 'scripts/run_asturias.py':
                raise subprocess.CalledProcessError(1, args)
        with patch.dict(os.environ, {"ENABLE_ASTURIAS": "true"}), patch('sys.argv', ['actualizar_todo.py', '--sin-descargas']), patch.object(actualizar_todo, '_run', side_effect=run) as calls:
            actualizar_todo.main()
            self.assertEqual(calls.call_count, 8)
            self.assertEqual(calls.call_args_list[-1].args, ('scripts/generar_paridad.py',))
