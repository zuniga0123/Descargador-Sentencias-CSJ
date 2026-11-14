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



class RedDeCitas(unittest.TestCase):
    TEXTO = ("Como se dijo en la sentencia T-760 de 2008 y en la SU-061/23, reiterada en C-355-06.[[1]](#_ftn1)\n\n"
             "La Sala Laboral (CSJ SL2586-2020 y SL711 de 2021) adoptó el modelo social; véase también CSJ SL, 25 mar. 2003, rad. 20026.\n\n"
             "[[1]](#_ftnref1) Sentencia T-1040 de 2001 y T-999A/05.")

    def test_formas_de_cita(self):
        from app import citas
        encontradas = {(c.corte, c.radicado) for c in citas.extraer(self.TEXTO)}
        for esperada in [("cc", "T-760-08"), ("cc", "SU061-23"), ("cc", "C-355-06"), ("csj", "SL2586-2020"),
                         ("csj", "SL711-2021"), ("csj", "rad:20026"), ("cc", "T-1040-01"), ("cc", "T-999A-05")]:
            with self.subTest(esperada=esperada):
                self.assertIn(esperada, encontradas)

    def test_nota_al_pie(self):
        from app import citas
        por_rad = {c.radicado: c for c in citas.extraer(self.TEXTO)}
        self.assertTrue(por_rad["T-1040-01"].en_nota)
        self.assertFalse(por_rad["T-760-08"].en_nota)

    def test_autocita_excluida(self):
        from app import citas
        self.assertNotIn("T-760-08", {c.radicado for c in citas.extraer(self.TEXTO, propio="T-760-08")})

    def test_votos_particulares(self):
        from app import citas
        texto = ("**SALVAMENTO DE VOTO DE LOS MAGISTRADOS**\n\n**MARCO GERARDO MONROY CABRA Y RODRIGO ESCOBAR GIL**\n\n"
                 "**A LA SENTENCIA C-355/06**\n\n... DIANA FAJARDO RIVERA Magistrada Con aclaración de voto")
        nombres = {(v["tipo"], v["magistrado"]) for v in citas.votos_particulares(texto)}
        self.assertIn(("salvamento", "Marco Gerardo Monroy Cabra"), nombres)
        self.assertIn(("salvamento", "Rodrigo Escobar Gil"), nombres)
        self.assertIn(("aclaracion", "Diana Fajardo Rivera"), nombres)


class LineaJurisprudencial(unittest.TestCase):
    def test_estado(self):
        from app import lineas
        self.assertEqual(lineas.estado_linea([("2015", 1), ("2018", 1), ("2022", 2)])["estado"], "pacífica")
        self.assertEqual(lineas.estado_linea([("2015", 1), ("2023", 1), ("2024", 5)])["estado"], "en tensión")
        self.assertEqual(lineas.estado_linea([("2010", 5), ("2012", 4), ("2023", 1), ("2024", 2)])["estado"], "cambio reciente")
        self.assertEqual(lineas.estado_linea([("2020", 3)])["estado"], "insuficiente")

    def test_peso_de_la_fuente(self):
        from app import lineas
        self.assertEqual(lineas.peso({"corte_clave": "csj", "radicado": "SL1-2020", "sala": "Sala de Descongestión Laboral"})["nivel"], 1)
        self.assertEqual(lineas.peso({"corte_clave": "csj", "radicado": "SL1-2020", "sala": "Sala de Casación Laboral"})["nivel"], 3)
        self.assertEqual(lineas.peso({"corte_clave": "cc", "radicado": "SU061-23", "sala": "Sala Plena"})["nivel"], 3)
        self.assertEqual(lineas.peso({"corte_clave": "cc", "radicado": "T-076-24", "sala": "Sala de Revisión"})["nivel"], 2)

    @unittest.skipUnless(HAY_BASE, "sin base de sentencias")
    def test_resolver_entrada(self):
        from app import lineas
        self.assertEqual(lineas.resolver_entrada("T-076/24"), ("cc", "T-076-24"))
        self.assertEqual(lineas.resolver_entrada("SU-061 de 2023"), ("cc", "SU061-23"))
        self.assertEqual(lineas.resolver_entrada("SL1152-2023"), ("csj", "SL1152-2023"))
        self.assertIsNone(lineas.resolver_entrada("X-1-1"))


if __name__ == "__main__":
    unittest.main()
