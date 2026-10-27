"""Importador genérico: solo documentos y personas totalmente inventados."""
from __future__ import annotations

import copy
import io
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml
from ingesta.common import TZ
from ingesta.export import to_json
from ingesta.generico import main
from ingesta.parsers._tabular import read_tables
from ingesta.parsers.generico import MappingError, coverage_report, load_mapping, parse_file, validate_mapping

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/generico'
BUILD = runpy.run_path(str(FIXTURES / 'build_fixtures.py'))
NOW = datetime(2026, 10, 27, tzinfo=TZ)
HEADER = ['Nombre', 'Direccion', 'Municipio', 'CP', 'Telefono', 'Codigo', 'Zona', 'Fecha', 'Inicio', 'Fin', 'Tipo']
ROW = ['Farmacia Inventada Aurora', 'Calle Imaginaria Uno, 1', 'Villa Ficticia', '01001', '900000001', '001', 'Zona Inventada Norte', '01/11/2026', '09:00', '21:00', 'diurna']


class GenericTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.mapping = load_mapping(FIXTURES / 'xlsx.yaml')
        self.mapping['file'] = {'type': 'csv', 'header_row': 1}
        self.mapping.pop('coverage')

    def csv(self, rows, headers=HEADER):
        import csv
        path = self.work / 'inventado.csv'
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream, delimiter=';')
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    def parse(self, rows, mapping=None, headers=HEADER):
        return parse_file(self.csv(rows, headers), mapping or self.mapping, retrieved_at=NOW)

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_four_invented_sources_and_errors(self):
        for kind, filename, count, reason in [
            ('xlsx', 'filas.xlsx', 3, 'fila 6: ERROR: Fecha'),
            ('csv', 'franjas.csv', 2, 'fila 5: ERROR: Franja'),
            ('ods', 'calendario.ods', 3, 'fila 3, columna 02/11/2026'),
            ('pdf', 'tabla.pdf', 2, 'página 1, fila 4: ERROR: Fecha'),
        ]:
            with self.subTest(kind=kind):
                result = parse_file(FIXTURES / filename, FIXTURES / f'{kind}.yaml', NOW)
                self.assertEqual(len(result.shifts), count)
                self.assertTrue(any(reason in w for w in result.warnings), result.warnings)
                data = to_json(result)
                self.assertEqual(data['source']['retrieved_at'], NOW.isoformat())
                self.assertTrue(all(s['times_exact'] for s in data['shifts']))
                self.assertTrue(all('Inventada' in p.holder for p in result.pharmacies.values()))

    def test_xlsx_native_values_sparse_cells_and_leading_zeros(self):
        result = parse_file(FIXTURES / 'filas.xlsx', FIXTURES / 'xlsx.yaml', NOW)
        pharmacy = result.pharmacies['FICTICIO-XLSX:001']
        self.assertEqual(pharmacy.holder, 'Farmacia Inventada Aurora')
        self.assertEqual(pharmacy.postal_code, '01001')
        self.assertEqual(pharmacy.phone, '900000001')
        self.assertEqual(result.shifts[0].start.hour, 9)
        self.assertEqual(result.shifts[1].end.day, 3)
        self.assertTrue(any('fila 7: AVISO: phone' in w for w in result.warnings))
        self.assertIsNone(result.pharmacies['FICTICIO-XLSX:003'].phone)
        self.assertEqual(len([w for w in result.warnings if 'duplicado' in w]), 1)

    def test_native_excel_epoch_and_formula_failure(self):
        mapping = copy.deepcopy(self.mapping)
        mapping['file'] = {'type': 'xlsx', 'header_row': 1, 'sheet': 1}
        path = self.work / 'inventado.xlsx'
        row = ROW.copy()
        row[7:10] = [datetime(2026, 11, 1), ('serial', 9 / 24), ('serial', 21 / 24)]
        BUILD['xlsx'](path, [(1, HEADER), (2, row)], date1904=True)
        result = parse_file(path, mapping, NOW)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.shifts[0].start, datetime(2026, 11, 1, 9, tzinfo=TZ))
        row[7] = ('iso', '2026-11-01')
        BUILD['xlsx'](path, [(1, HEADER), (2, row)])
        self.assertEqual(parse_file(path, mapping, NOW).warnings, [])
        row[7] = ('formula', 'TODAY()')
        BUILD['xlsx'](path, [(1, HEADER), (2, row)])
        self.assertTrue(any('fórmula sin resultado' in w for w in parse_file(path, mapping, NOW).warnings))
        row[7] = ('serial', 60)
        BUILD['xlsx'](path, [(1, HEADER), (2, row)])
        self.assertTrue(any('29/02/1900' in w for w in parse_file(path, mapping, NOW).warnings))

    def test_xlsx_missing_sheet_and_header(self):
        mapping = load_mapping(FIXTURES / 'xlsx.yaml')
        mapping['file']['sheet'] = 'Inexistente'
        with self.assertRaisesRegex(ValueError, 'Hoja no encontrada'):
            parse_file(FIXTURES / 'filas.xlsx', mapping, NOW)
        mapping['file'].update(sheet=1, header_row=99)
        result = parse_file(FIXTURES / 'filas.xlsx', mapping, NOW)
        self.assertIn('fila 99', result.warnings[0])

    def test_ods_matrix_blank_cells_not_shifts_and_coverage(self):
        mapping = load_mapping(FIXTURES / 'ods.yaml')
        result = parse_file(FIXTURES / 'calendario.ods', mapping, NOW)
        report = coverage_report(result, mapping)
        self.assertEqual(report['gaps'], [{'date': '2026-11-02', 'zone': 'Zona Inventada Calendario'}])
        self.assertEqual(len(result.shifts), 3)
        self.assertEqual(result.shifts[-1].start.day, 1)
        self.assertTrue(any(s.end.day == 4 for s in result.shifts))
        self.assertTrue(all(p.phone is None for p in result.pharmacies.values()))

    def test_ods_repeats_native_dates_times_and_spaces(self):
        ns = 'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
        xml = f'<office:document-content {ns}><office:body><office:spreadsheet><table:table table:name="Hoja ficticia"><table:table-row table:number-rows-repeated="2"><table:table-cell office:value-type="date" office:date-value="2026-11-01"/><table:table-cell office:value-type="time" office:time-value="PT9H30M"/><table:table-cell table:number-columns-repeated="2" office:value-type="string"><text:p>A<text:s text:c="2"/>B</text:p></table:table-cell><table:table-cell office:value-type="float" office:value="12"/></table:table-row></table:table></office:spreadsheet></office:body></office:document-content>'
        path = self.work / 'native.ods'
        BUILD['archive'](path, {'content.xml': xml})
        table = read_tables(path, {'type': 'ods', 'sheet': 'Hoja ficticia'})[0]
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(table.rows[1][0], 2)
        self.assertEqual(table.rows[0][1], [datetime(2026, 11, 1), timedelta(hours=9, minutes=30), 'A  B', 'A  B', '12'])

    def test_pdf_page_selection_duplicates_and_no_text(self):
        mapping = load_mapping(FIXTURES / 'pdf.yaml')
        mapping['file']['pages'] = [2]
        result = parse_file(FIXTURES / 'tabla.pdf', mapping, NOW)
        self.assertEqual(len(result.shifts), 1)
        self.assertEqual(result.warnings, [])
        mapping['file'].pop('pages')
        result = parse_file(FIXTURES / 'tabla.pdf', mapping, NOW)
        self.assertTrue(any('página 2, fila 2' in w and 'duplicado' in w for w in result.warnings))
        mapping['file']['pages'] = [3]
        with self.assertRaisesRegex(ValueError, 'Página inexistente'):
            parse_file(FIXTURES / 'tabla.pdf', mapping, NOW)
        with patch('ingesta.parsers._tabular.pdf_to_text', return_value=None):
            with self.assertRaisesRegex(ValueError, 'PDF sin texto'):
                parse_file(FIXTURES / 'tabla.pdf', mapping, NOW)

    def test_defaults_normalization_replacements_and_original_slot_label(self):
        mapping = load_mapping(FIXTURES / 'csv.yaml')
        mapping.pop('coverage')
        mapping['values'] = {'slot': {'Servicio diurno': 'D'}}
        mapping['defaults'] = {'zone': 'Zona Inventada Sur'}
        path = self.work / 'franjas.csv'
        path.write_text((FIXTURES / 'franjas.csv').read_text().splitlines()[0] + '\n' + (FIXTURES / 'franjas.csv').read_text().splitlines()[1].replace(';D;', ';Servicio diurno;').replace(';Zona Inventada Sur;', ';;') + '\n')
        result = parse_file(path, mapping, NOW)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.shifts[0].raw_label, 'Servicio diurno')
        self.assertEqual(result.shifts[0].zone, 'Zona Inventada Sur')
        self.assertIn('FICTICIO-CSV:FICTICIO-A', result.pharmacies)

    def test_invalid_rows_fields_and_pharmacy_conflicts(self):
        rows = []
        for index, value in [(0, ''), (1, ''), (6, ''), (7, '31/11/2026'), (8, '25:00'), (9, '24:01'), (10, 'inventado')]:
            row = ROW.copy(); row[index] = value; rows.append(row)
        rows.append(ROW + ['celda inesperada'])
        result = self.parse(rows)
        self.assertEqual(result.shifts, [])
        self.assertEqual(len(result.warnings), 9)
        self.assertTrue(all('fila' in w for w in result.warnings[:-1]))
        row = ROW.copy(); row[1] = 'Otra Calle Inventada, 9'; row[7] = '02/11/2026'
        result = self.parse([ROW, row])
        self.assertEqual(len(result.shifts), 1)
        self.assertIn('Datos contradictorios', result.warnings[0])
        self.assertEqual(next(iter(result.pharmacies.values())).address, ROW[1])

    def test_bad_optional_values_are_absent_with_warnings(self):
        row = ROW.copy(); row[3] = 'ABCDE'; row[4] = 'sin teléfono'
        result = self.parse([row])
        self.assertEqual(len(result.shifts), 1)
        pharmacy = next(iter(result.pharmacies.values()))
        self.assertIsNone(pharmacy.phone)
        self.assertIsNone(pharmacy.postal_code)
        self.assertEqual(len(result.warnings), 2)

    def test_derived_identity_is_stable_without_official_code(self):
        mapping = copy.deepcopy(self.mapping)
        mapping['columns'].pop('code')
        a = self.parse([ROW], mapping)
        row = ROW.copy(); row[7] = '02/11/2026'
        b = self.parse([row], mapping)
        self.assertEqual(set(a.pharmacies), set(b.pharmacies))
        self.assertIn(':derived-', next(iter(a.pharmacies)))

    def test_columns_by_position_and_duplicate_headers(self):
        mapping = copy.deepcopy(self.mapping)
        mapping['columns'] = {field: HEADER.index(name) + 1 for field, name in mapping['columns'].items()}
        mapping.pop('ignore')
        self.assertEqual(self.parse([ROW], mapping).warnings, [])
        result = self.parse([ROW], headers=['Repetido'] * len(HEADER))
        self.assertIn('Columna ausente', result.warnings[0])
        headers = HEADER + ['Nombre']
        self.assertIn('repetida', self.parse([ROW], headers=headers).warnings[0])

    def test_blank_ignored_and_incomplete_rows(self):
        mapping = copy.deepcopy(self.mapping)
        mapping['ignore']['rows'] = [4]
        result = self.parse([[], ['TOTAL'], ['ruido que se ignora'], ROW, ['incompleta']], mapping)
        self.assertEqual(len(result.shifts), 1)
        self.assertEqual(len(result.warnings), 1)
        self.assertIn('fila 6', result.warnings[0])

    def test_duplicate_and_conflicting_end(self):
        row = ROW.copy(); row[9] = '20:00'
        result = self.parse([ROW, ROW, row])
        self.assertEqual(len(result.shifts), 1)
        self.assertIn('duplicado', result.warnings[0])
        self.assertIn('contradictorios', result.warnings[1])

    def test_midnight_24h_and_native_times(self):
        for start, end, expected in [('22:00','08:00',2), ('09:00','09:00',2), ('09:00','24:00',2)]:
            with self.subTest(start=start,end=end):
                row = ROW.copy(); row[8:10] = [start,end]
                result = self.parse([row])
                self.assertEqual(result.warnings, [])
                self.assertEqual(result.shifts[0].end.day, expected)
        from ingesta.parsers.generico import _clock
        self.assertEqual(_clock(time(9, 30), self.mapping, False), (time(9, 30),0))
        self.assertEqual(_clock(timedelta(days=1), self.mapping, True), (time(),1))
        with self.assertRaises(ValueError): _clock(timedelta(days=2), self.mapping, True)

    def test_dst_nonexistent_and_ambiguous_are_rejected(self):
        for day in ['29/03/2026','25/10/2026']:
            row = ROW.copy(); row[7:10] = [day,'02:30','08:00']
            result = self.parse([row])
            self.assertEqual(result.shifts, [])
            self.assertIn('inexistente o ambigua', result.warnings[0])
        row = ROW.copy(); row[7:10] = ['24/10/2026','22:00','08:00']
        shift = self.parse([row]).shifts[0]
        self.assertEqual((shift.end.astimezone(timezone.utc)-shift.start.astimezone(timezone.utc)).total_seconds(), 11*3600)

    def test_canary_timezone(self):
        mapping = copy.deepcopy(self.mapping); mapping['source']['timezone'] = 'Atlantic/Canary'
        result = self.parse([ROW], mapping)
        self.assertEqual(result.shifts[0].start.utcoffset(), timedelta())
        with self.assertRaisesRegex(ValueError, 'retrieved_at'):
            parse_file(self.csv([ROW]), mapping, datetime(2026,1,1))

    def test_coverage_declared_observed_and_daily_gaps(self):
        row = ROW.copy(); row[7] = '03/11/2026'
        result = self.parse([ROW,row])
        report = coverage_report(result, self.mapping)
        self.assertEqual(report['scope'],'observed')
        self.assertEqual(report['gaps'],[{'date':'2026-11-02','zone':ROW[6]}])
        mapping = copy.deepcopy(self.mapping)
        mapping['coverage']={'start':'01/11/2026','end':'01/11/2026','zones':[ROW[6],'Zona Ausente'],'daily_start':'08:00','daily_end':'22:00'}
        report = coverage_report(result,mapping)
        self.assertEqual(report['scope'],'declared')
        gaps = [g for g in report['gaps'] if g['zone']==ROW[6]]
        self.assertEqual(len(gaps),2)
        self.assertTrue(gaps[0]['start'].endswith('08:00:00+01:00'))
        self.assertEqual(len([g for g in report['gaps'] if g['zone']=='Zona Ausente']),1)
        self.assertEqual(len(result.shifts),2)

    def test_coverage_empty_and_overnight_continuation(self):
        result = self.parse([])
        self.assertEqual(coverage_report(result,self.mapping)['daily'],[])
        row = ROW.copy(); row[8:10]=['22:00','08:00']
        result = self.parse([row])
        report = coverage_report(result,self.mapping)
        self.assertEqual(len(report['daily']),2)
        self.assertEqual(report['gaps'],[])

    def test_yaml_safe_unique_keys_and_complete_syntax(self):
        path = self.work/'mapping.yaml'
        for text in ['version: 1\nversion: 2\n', '!!python/object/apply:os.system ["false"]', '{broken']:
            path.write_text(text)
            with self.assertRaises(MappingError): load_mapping(path)
        path.write_text(yaml.safe_dump(self.mapping,allow_unicode=True))
        self.assertEqual(load_mapping(path),self.mapping)
        path.write_text(yaml.safe_dump(self.mapping,allow_unicode=True).replace('header_row: 1', '<<: &defaults {header_row: 2}\n  header_row: 1'))
        self.assertEqual(load_mapping(path)['file']['header_row'],1)

    def test_mapping_rejects_unknown_types_and_contradictions(self):
        changes = [
            ('version', 2), ('file.type','xls'), ('file.header_row',0), ('file.header_row',True),
            ('file.sheet',1), ('file.delimiter',';;'), ('file.pages',[0]),
            ('source.region',1), ('source.region','99'), ('source.timezone','Inventada/Falsa'),
            ('columns.holder',0), ('columns.typo','Nombre'), ('defaults.zone',None),
            ('normalization.holder',['magic']), ('values.kind',[]), ('date_formats',[]),
            ('date_formats',['%d/%m']), ('time_formats',['%M']), ('time_formats',['%I:%M']),
            ('ignore.rows',[-1]), ('ignore.equals',[{'column':'Nombre','value':None}]),
            ('coverage.start','01/11/2026'), ('coverage.zones',[]), ('source.publisher',''),
            ('coverage',{'start':'03/11/2026','end':'01/11/2026'}),
            ('coverage',{'daily_start':'25:00','daily_end':'08:00'}),
            ('columns.slot','Franja'), ('unknown','x'),
        ]
        for dotted,value in changes:
            with self.subTest(change=dotted,value=value):
                mapping=copy.deepcopy(self.mapping); target=mapping; keys=dotted.split('.')
                for key in keys[:-1]: target=target.setdefault(key,{})
                target[keys[-1]]=value
                with self.assertRaises(MappingError): validate_mapping(mapping)
        mapping=load_mapping(FIXTURES/'ods.yaml')
        mapping['matrix']['markers']['D']='UNKNOWN'
        with self.assertRaises(MappingError): validate_mapping(mapping)
        mapping=load_mapping(FIXTURES/'csv.yaml')
        mapping['slots']['D']['start']='25:00'
        with self.assertRaises(MappingError): validate_mapping(mapping)

    def test_declared_normalization_preserves_identity_and_phone_rules(self):
        mapping=copy.deepcopy(self.mapping)
        mapping['normalization'].update(holder=['spaces','title'],address=['upper'],locality=['normalize'],zone=['lower'],code=['strip'])
        row=ROW.copy(); row[0]=' FARMACIA   INVENTADA AURORA '; row[2]='Villa Fictícia'
        result=self.parse([row],mapping)
        pharmacy=next(iter(result.pharmacies.values()))
        self.assertEqual(pharmacy.holder,'Farmacia Inventada Aurora')
        self.assertEqual(pharmacy.address,ROW[1].upper())
        self.assertEqual(pharmacy.locality,'VILLA FICTICIA')
        self.assertEqual(result.shifts[0].zone,ROW[6].lower())

    def test_blank_defaults_and_native_type_errors(self):
        mapping=copy.deepcopy(self.mapping); mapping['defaults']={'zone':ROW[6]}
        row=ROW.copy(); row[6]='   '
        self.assertEqual(self.parse([row],mapping).warnings,[])
        mapping['file']={'type':'xlsx','header_row':1}
        row=ROW.copy(); row[0]=datetime(2026,11,1)
        path=self.work/'wrong-type.xlsx'; BUILD['xlsx'](path,[(1,HEADER),(2,row)])
        result=parse_file(path,mapping,NOW)
        self.assertIn('Tipo de celda nativo incompatible con holder',result.warnings[0])
        row=ROW.copy(); row[7]=datetime(2026,11,1,9)
        BUILD['xlsx'](path,[(1,HEADER),(2,row)])
        self.assertTrue(any('contiene una hora' in w for w in parse_file(path,mapping,NOW).warnings))

    def test_cli_gaps_and_failed_atomic_write_preserve_output(self):
        mapping=copy.deepcopy(self.mapping)
        mapping['coverage']={'start':'01/11/2026','end':'02/11/2026','zones':[ROW[6]]}
        path=self.work/'mapping.yaml'; path.write_text(yaml.safe_dump(mapping))
        output=self.work/'out.json'; output.write_text('contenido anterior')
        args=['--mapeo',str(path),'--entrada',str(self.csv([ROW])),'--salida',str(output)]
        code,_,error=self.cli(*args)
        self.assertEqual(code,1); self.assertIn('HUECO',error)
        self.assertEqual(output.read_text(),'contenido anterior')
        mapping.pop('coverage'); path.write_text(yaml.safe_dump(mapping))
        before=set(self.work.iterdir())
        with patch('ingesta.generico.json.dump',side_effect=OSError('disco lleno ficticio')):
            code,_,error=self.cli(*args)
        self.assertEqual(code,2); self.assertIn('disco lleno',error)
        self.assertEqual(output.read_text(),'contenido anterior')
        self.assertEqual(set(self.work.iterdir()),before)

    def test_cli_validate_write_atomic_and_refuse_bad_rows(self):
        path=self.csv([ROW]); mapping_path=self.work/'mapping.yaml'
        mapping_path.write_text(yaml.safe_dump(self.mapping,allow_unicode=True))
        output=self.work/'new'/'out.json'
        args=['--mapeo',str(mapping_path),'--entrada',str(path),'--salida',str(output)]
        self.assertEqual(self.cli(*args,'--solo-validar')[0],0)
        self.assertFalse(output.parent.exists())
        self.assertEqual(self.cli(*args)[0],0)
        data=json.loads(output.read_text())
        self.assertEqual(len(data['shifts']),1)
        original=output.read_bytes()
        self.csv([ROW,ROW])
        code,_,error=self.cli(*args)
        self.assertEqual(code,1); self.assertIn('duplicado',error)
        self.assertEqual(output.read_bytes(),original)
        self.csv([ROW]); self.assertEqual(self.cli(*args,'--solo-validar')[0],0)
        self.assertEqual(output.read_bytes(),original)
        self.assertEqual(self.cli('--mapeo',str(mapping_path),'--entrada',str(path),'--solo-validar')[0],0)
        self.assertEqual(self.cli('--mapeo',str(mapping_path),'--entrada',str(path),'--salida',str(path))[0],2)

    def test_cli_missing_corrupt_input_and_mapping(self):
        path=self.work/'bad.yaml'; path.write_text('version: 7')
        code,_,error=self.cli('--mapeo',str(path),'--entrada',str(self.work/'missing.csv'),'--solo-validar')
        self.assertEqual(code,2); self.assertIn('ERROR',error)
        path.write_text(yaml.safe_dump(self.mapping))
        self.assertEqual(self.cli('--mapeo',str(path),'--entrada',str(self.work/'missing.csv'),'--solo-validar')[0],2)
        mapping=load_mapping(FIXTURES/'xlsx.yaml'); path.write_text(yaml.safe_dump(mapping))
        broken=self.work/'broken.xlsx'; broken.write_text('no es zip')
        self.assertEqual(self.cli('--mapeo',str(path),'--entrada',str(broken),'--solo-validar')[0],2)

    def test_module_cli_and_required_output(self):
        mapping=self.work/'mapping.yaml'; mapping.write_text(yaml.safe_dump(self.mapping))
        cmd=[sys.executable,'-m','ingesta.generico','--mapeo',str(mapping),'--entrada',str(self.csv([ROW]))]
        process=subprocess.run(cmd+['--solo-validar'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(json.loads(process.stdout)['shifts'],1)
        process=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(process.returncode,2)
        self.assertIn('--salida',process.stderr)


if __name__ == '__main__':
    unittest.main()
