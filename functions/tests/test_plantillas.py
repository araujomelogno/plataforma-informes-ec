from portal import plantillas as p


def test_bienvenida_sin_enlace_no_se_puede_guardar():
    errores = p.validar(p.BIENVENIDA, "Hola", "Entrá al portal: {{url_portal}}")
    assert any("{{enlace}}" in e for e in errores)


def test_variable_desconocida_se_marca():
    errores = p.validar(p.NUEVO_INFORME, "Nuevo: {{nombre_informe}}", "{{informe}}")
    assert any("nombre_informe" in e for e in errores)


def test_variable_de_otra_plantilla_se_marca():
    # {{enlace}} no existe en "Nuevo informe"; {{informe}} no existe en "Bienvenida".
    assert p.validar(p.NUEVO_INFORME, "x", "{{enlace}}")
    assert p.validar(p.BIENVENIDA, "x", "{{enlace}} {{informe}}")


def test_plantillas_por_defecto_son_validas():
    for clave in p.CLAVES:
        d = p.POR_DEFECTO[clave]
        assert p.validar(clave, d["asunto"], d["cuerpo"]) == [], clave


def test_sin_editar_usa_el_texto_del_codigo():
    efectiva = p.plantilla_efectiva({}, p.BIENVENIDA)
    assert efectiva["asunto"] == p.POR_DEFECTO[p.BIENVENIDA]["asunto"]
    editada = p.plantilla_efectiva(
        {"plantillas": {p.BIENVENIDA: {"asunto": "Otro", "cuerpo": "{{enlace}}"}}},
        p.BIENVENIDA)
    assert editada["asunto"] == "Otro"


def test_armar_reemplaza_y_agrega_firma():
    asunto, texto = p.armar({}, p.BIENVENIDA, {
        "email": "a@b.com", "enlace": "https://x/y", "url_portal": "https://p",
        "admin": "admin@e.com"})
    assert "https://x/y" in texto
    assert "admin@e.com" in texto
    assert texto.endswith(p.FIRMA)
    assert "{{" not in texto


def test_linea_con_variables_vacias_se_omite():
    _, texto = p.armar({}, p.NUEVO_INFORME, {
        "email": "a@b.com", "url_portal": "https://p", "admin": "x@e.com",
        "informe": "Informe A", "carpeta": "", "vence": ""})
    assert "Carpeta:" not in texto
    assert "Disponible hasta" not in texto
    assert "Informe A" in texto


def test_variable_desconocida_queda_vacia_al_enviar():
    cfg = {"plantillas": {p.NUEVO_INFORME: {"asunto": "Hola {{informe}}",
                                            "cuerpo": "Ver {{informe}} {{otra}}"}}}
    _, texto = p.armar(cfg, p.NUEVO_INFORME, {"informe": "A", "otra": "NO"})
    assert "NO" not in texto and "{{otra}}" not in texto


def test_agrupado_lista_en_cuerpo_y_comas_en_asunto():
    asunto, texto = p.armar({}, p.NUEVO_INFORME, {
        "informe": ["A", "B", "C"], "url_portal": "https://p"})
    assert "\n" not in asunto
    assert "A, B, C" in asunto
    assert "• A\n• B\n• C" in texto


def test_remitente_configurable_y_saneado():
    assert p.remitente({}) == ("Equipos Consultores", None)
    assert p.remitente({"remitenteNombre": "Equipos\nX", "replyTo": "no-valido"}) == ("Equipos X", None)
    assert p.remitente({"replyTo": "equipo@equipos.com.uy"})[1] == "equipo@equipos.com.uy"
