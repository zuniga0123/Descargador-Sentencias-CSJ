"""Pruebas de la app de búsqueda. Ejecutar desde la raíz del repositorio:

    python -m unittest tests.test_app

Las que consultan la base se omiten si datos/jurisprudencia.sqlite no existe.
"""

import unittest

from app import busqueda, config, fichas, precedentes

HAY_BASE = config.DB_PATH.exists()


class TraduccionDeConsultas(unittest.TestCase):
    CASOS = {
        "estabilidad laboral": '"estabilidad" AND "laboral"',
        '"contrato realidad" -tutela': '"contrato realidad" NOT "tutela"',
        "fuero O estabilidad despido": '("fuero" OR "estabilidad") AND "despido"',
        '"fuero sindical" "permiso judicial" O "calificación judicial"':
            '"fuero sindical" AND ("permiso judicial" OR "calificación judicial")',
        "pensiona*": '"pensiona"*',
        "T-760/08": '"T 760 08"',
        "despido O": '"despido"',
        "-solo": None,
        "": None,
    }

    def test_traduccion(self):
        for entrada, esperado in self.CASOS.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(busqueda.a_consulta_fts(entrada), esperado)

    @unittest.skipUnless(HAY_BASE, "sin base de sentencias")
    def test_todas_las_formas_se_ejecutan(self):
        formas = list(self.CASOS) + [
            '"fuero de maternidad" O "estado de embarazo" reintegr*', "a O b O c -d", '"a b" O c O "d e" f -g',
            "reintegr* O reinstal* \"fuero sindical\"", "x -y -z", "c++ (a) AND", 'consulta (rota) AND OR "',
        ]
        conn = busqueda.conexion()
        for q in formas:
            fts = busqueda.a_consulta_fts(q)
            if fts:
                with self.subTest(q=q):
                    conn.execute("SELECT count(*) FROM fts WHERE fts MATCH ?", (fts,)).fetchone()


class VerificacionDeCitas(unittest.TestCase):
    TEXTO = ("Primero.- Confirmar el fallo proferido por la Corte Suprema de Justicia - Sala de Casación Laboral, "
             "de fecha 8 de junio de 2004, por el cual denegó el amparo solicitado por el señor, pero por las razones "
             "expuestas en esta sentencia.")

    def test_cita_literal_y_variantes(self):
        v = fichas.Verificador(self.TEXTO)
        self.assertTrue(v.verificar("Confirmar el fallo proferido por la Corte Suprema de Justicia - Sala de Casación Laboral"))
        self.assertTrue(v.verificar("confirmar el fallo proferido por la corte suprema de justicia sala de casacion laboral"))
        self.assertTrue(v.verificar("Confirmar el fallo proferido por la Corte Suprema … por el cual denegó el amparo solicitado"))

    def test_cita_inventada_o_corta(self):
        v = fichas.Verificador(self.TEXTO)
        self.assertFalse(v.verificar("el término de prescripción no corre mientras no se configure el despido"))
        self.assertFalse(v.verificar("Confirmar el fallo"))
        self.assertFalse(v.verificar(""))


class ValidacionesDelAnalisis(unittest.TestCase):
    def test_citas_ajenas_se_marcan(self):
        texto, ajenas = precedentes._marcar_citas("Regla [SL1-2020]; matiz [T-800-99]; norma [art. 26].", {"SL1-2020"})
        self.assertIn("[SL1-2020]", texto)
        self.assertIn("T-800-99 — no está entre", texto)
        self.assertEqual(ajenas, ["T-800-99"])

    def test_similitud_calculada(self):
        comp = [{"relacion": "coincide"}, {"relacion": "coincide"}, {"relacion": "difiere"}, {"relacion": "no_consta"}]
        self.assertEqual(precedentes._similitud(comp, 4), 4)
        self.assertEqual(precedentes._similitud([], 0), 0)

    def test_prioridad_reciente(self):
        self.assertAlmostEqual(precedentes.factor_reciente(precedentes.ANO_ACTUAL), 1.0)
        self.assertAlmostEqual(precedentes.factor_reciente(precedentes.ANO_ACTUAL - 10), 0.5)
        self.assertGreater(precedentes.factor_reciente(2024), precedentes.factor_reciente(2004))


if __name__ == "__main__":
    unittest.main()
