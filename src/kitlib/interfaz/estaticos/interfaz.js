/* Interfaz visual local del kit. Este archivo solo pinta el JSON que entrega el puente (Python) y envía
   acciones. No calcula, no valida ni interpreta datos: cada texto y cada número vienen del puente.
   Todas las peticiones van a la misma dirección local (127.0.0.1) que sirvió esta página. */
(function () {
  "use strict";

  var token = new URLSearchParams(location.search).get("token") || "";
  var estado = { archivo: null, receta: null, ejecucion: null, ocupado: false, pestana: null, resultado: null };
  var $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------------ peticiones
  function api(ruta, parametros) {
    var url = ruta;
    if (parametros) { url += "?" + new URLSearchParams(parametros).toString(); }
    return fetch(url, { headers: { "X-Kit-Token": token }, cache: "no-store" }).then(leer);
  }
  function enviar(ruta, cuerpo) {
    return fetch(ruta, {
      method: "POST",
      headers: { "X-Kit-Token": token, "Content-Type": "application/json" },
      body: JSON.stringify(cuerpo)
    }).then(leer);
  }
  function leer(respuesta) {
    return respuesta.json().then(function (datos) {
      if (!respuesta.ok) { throw new Error(datos.error || ("Error " + respuesta.status)); }
      return datos;
    });
  }

  // ------------------------------------------------------------------ utilidades de pintado
  function el(etiqueta, atributos, hijos) {
    var nodo = document.createElement(etiqueta);
    Object.keys(atributos || {}).forEach(function (k) {
      if (k === "texto") { nodo.textContent = atributos[k]; }
      else if (k === "clase") { nodo.className = atributos[k]; }
      else if (k === "style") { nodo.style.cssText = atributos[k]; }  // CSSOM: compatible con la política de contenido
      else { nodo.setAttribute(k, atributos[k]); }
    });
    (hijos || []).forEach(function (h) { if (h) { nodo.appendChild(typeof h === "string" ? document.createTextNode(h) : h); } });
    return nodo;
  }
  function vaciar(nodo) { while (nodo.firstChild) { nodo.removeChild(nodo.firstChild); } }
  function bytes(n) {
    if (n == null) { return ""; }
    if (n < 1024) { return n + " B"; }
    if (n < 1024 * 1024) { return (n / 1024).toFixed(1) + " KiB"; }
    return (n / (1024 * 1024)).toFixed(1) + " MiB";
  }

  // ------------------------------------------------------------------ pantalla 1: archivo
  function cargarArchivos() {
    return api("/api/archivos").then(function (datos) {
      var lista = $("lista-archivos");
      vaciar(lista);
      if (!datos.archivos.length) {
        lista.appendChild(el("li", { clase: "secundario pequeno", texto: "No hay archivos en data/ ni examples/. Sube uno." }));
      }
      datos.archivos.forEach(function (a) {
        var boton = el("button", { type: "button", clase: "opcion" + (estado.archivo === a.ruta ? " elegida" : ""), "data-ruta": a.ruta,
          "aria-pressed": estado.archivo === a.ruta ? "true" : "false" }, [
          el("span", {}, [el("span", { clase: "nombre", texto: a.nombre }),
            el("span", { clase: "meta", texto: a.ruta + (a.subida ? " · copia subida" : "") + " · " + bytes(a.bytes) })]),
          el("span", { clase: "visto", texto: "✓", "aria-hidden": "true" })
        ]);
        boton.addEventListener("click", function () { elegirArchivo(a.ruta); });
        lista.appendChild(el("li", {}, [boton]));
      });
    });
  }

  function elegirArchivo(ruta) {
    estado.archivo = ruta;
    Array.prototype.forEach.call($("lista-archivos").querySelectorAll(".opcion"), function (b) {
      var elegida = b.getAttribute("data-ruta") === ruta;
      b.classList.toggle("elegida", elegida);
      b.setAttribute("aria-pressed", elegida ? "true" : "false");
    });
    var detalle = $("detalle-archivo");
    detalle.hidden = false;
    vaciar(detalle);
    detalle.appendChild(el("span", { texto: "Leyendo con «inspeccionar»…" }));
    actualizarBotones();
    api("/api/inspeccionar", { ruta: ruta }).then(function (d) {
      vaciar(detalle);
      detalle.appendChild(el("div", {}, [el("strong", { texto: d.nombre })]));
      if (d.estado === "error") {
        detalle.appendChild(el("div", { texto: d.error || "El kit no pudo leer el archivo" }));
        return;
      }
      (d.tablas || []).forEach(function (t) {
        var filas = t.filas == null ? "total desconocido" : t.filas + " filas";
        detalle.appendChild(el("div", { texto: (t.hoja ? "Hoja " + t.hoja + ": " : "") + filas + " · " + t.columnas.length + " columnas" }));
        detalle.appendChild(el("div", { clase: "columnas" }, t.columnas.map(function (c) { return el("span", { texto: c }); })));
      });
      if (d.incidencias || d.advertencias) {
        detalle.appendChild(el("div", { texto: "Al leer: " + d.incidencias + " incidencias, " + d.advertencias + " advertencias" }));
      }
      detalle.appendChild(el("div", { clase: "pequeno", texto: d.nota }));
    }).catch(function (e) { vaciar(detalle); detalle.appendChild(el("span", { texto: e.message })); });
  }

  function subir(archivo) {
    if (!archivo) { return; }
    var aviso = $("aviso-subida");
    aviso.textContent = "Subiendo " + archivo.name + "…";
    var lector = new FileReader();
    lector.onload = function () {
      var base64 = String(lector.result).split(",")[1] || "";
      enviar("/api/subir", { nombre: archivo.name, contenido_base64: base64 }).then(function (r) {
        aviso.textContent = r.aviso;
        return cargarArchivos().then(function () { elegirArchivo(r.ruta); });
      }).catch(function (e) { aviso.textContent = "No se subió: " + e.message; });
    };
    lector.readAsDataURL(archivo);
  }

  // ------------------------------------------------------------------ pantalla 2: receta
  function cargarRecetas() {
    return api("/api/recetas").then(function (datos) {
      var lista = $("lista-recetas");
      vaciar(lista);
      if (!datos.recetas.length) {
        lista.appendChild(el("li", { clase: "secundario pequeno", texto: "No hay recetas en recetas/." }));
      }
      datos.recetas.forEach(function (r) {
        var boton = el("button", { type: "button", clase: "opcion", "data-ruta": r.ruta, "aria-pressed": "false" }, [
          el("span", { clase: "cabeza" }, [el("span", { clase: "nombre", texto: r.titulo }), el("span", { clase: "visto", texto: "✓", "aria-hidden": "true" })]),
          el("span", { clase: "descripcion", texto: r.error || r.descripcion || (r.pasos.length + " pasos") })
        ]);
        boton.addEventListener("click", function () { elegirReceta(r); });
        lista.appendChild(el("li", {}, [boton]));
      });
    });
  }

  function elegirReceta(r) {
    estado.receta = r.ruta;
    Array.prototype.forEach.call($("lista-recetas").querySelectorAll(".opcion"), function (b) {
      var elegida = b.getAttribute("data-ruta") === r.ruta;
      b.classList.toggle("elegida", elegida);
      b.setAttribute("aria-pressed", elegida ? "true" : "false");
    });
    $("otras-entradas").textContent = r.otras_entradas || "";
    actualizarBotones();
  }

  // ------------------------------------------------------------------ pantalla 3: ejecutar
  function actualizarBotones() {
    var listo = Boolean(estado.archivo && estado.receta) && !estado.ocupado;
    $("boton-vista").disabled = !listo;
    $("boton-ejecutar").disabled = !listo;
    $("resumen-eleccion").textContent = estado.archivo && estado.receta
      ? estado.archivo + " → " + estado.receta.replace(/^recetas\//, "")
      : "Elige un archivo y una receta.";
  }

  function vistaPrevia() {
    var panel = $("vista-previa");
    panel.hidden = false;
    vaciar(panel);
    panel.appendChild(el("h3", { texto: "Pidiendo la vista previa al kit…" }));
    api("/api/vista_previa", { archivo: estado.archivo, receta: estado.receta }).then(function (v) {
      vaciar(panel);
      panel.appendChild(el("h3", { texto: v.titulo }));
      if (v.alcance) { panel.appendChild(el("p", { clase: "alcance", texto: v.alcance })); }
      var lista = el("ul", {});
      (v.entradas || []).forEach(function (e) {
        lista.appendChild(el("li", {}, [el("strong", { texto: "Entrada " + e.nombre + ": " }),
          (e.ruta || "") + " · encabezado " + (e.encabezado || "?") + (e.columnas != null ? " (" + e.columnas + " columnas)" : "") + (e.motivo ? " · " + e.motivo : "")]));
      });
      (v.pasos || []).forEach(function (p) {
        var extra = p.incidencias_previstas && p.incidencias_previstas.length ? " · incidencias previstas: " + p.incidencias_previstas.join(", ") : "";
        lista.appendChild(el("li", {}, [el("strong", { texto: p.numero + " " + p.nombre + " " }), el("span", { clase: "op", texto: "(" + p.op + ") → " + (p.produce.length ? p.produce.join(", ") : "solo informe") + " · columnas " + (p.columnas || "?") + (p.motivo ? ": " + p.motivo : "") + extra })]));
      });
      panel.appendChild(lista);
      pintarErrores(panel, (v.errores || []).concat(v.avisos || []));
      if (v.destino) { panel.appendChild(el("p", { clase: "secundario pequeno", texto: v.destino })); }
    }).catch(function (e) { vaciar(panel); panel.appendChild(el("h3", { texto: "Vista previa no disponible: " + e.message })); });
  }

  function ejecutar() {
    estado.ocupado = true;
    actualizarBotones();
    $("estado-ejecucion").textContent = "Ejecutando…";
    $("vista-previa").hidden = true;
    enviar("/api/ejecutar", { archivo: estado.archivo, receta: estado.receta }).then(function (r) {
      estado.ejecucion = r.ejecucion;
      vigilar();
    }).catch(function (e) {
      estado.ocupado = false;
      actualizarBotones();
      $("estado-ejecucion").textContent = e.message;
    });
  }

  function vigilar() {
    api("/api/resultado", { ejecucion: estado.ejecucion }).then(function (r) {
      pintarResultado(r);
      if (r.estado === "en_curso" && r.en_marcha !== false) {
        setTimeout(vigilar, 600);
        return;
      }
      estado.ocupado = false;
      actualizarBotones();
      $("estado-ejecucion").textContent = "Terminado: " + (r.franja ? r.franja.titulo : r.estado);
    }).catch(function (e) {
      estado.ocupado = false;
      actualizarBotones();
      $("estado-ejecucion").textContent = e.message;
    });
  }

  // ------------------------------------------------------------------ pantalla 4: resultado
  function pintarErrores(contenedor, errores) {
    if (!errores || !errores.length) { return; }
    var lista = el("ul", { clase: "errores" });
    errores.forEach(function (e) {
      var donde = [e.paso ? "paso " + e.paso : "", e.campo ? "campo " + e.campo : ""].filter(Boolean).join(", ");
      lista.appendChild(el("li", {}, [el("code", { texto: e.codigo || "?" }), donde ? " (" + donde + "): " : ": ", e.mensaje || "",
        e.sugerencia ? el("div", { clase: "secundario", texto: "Sugerencia: " + e.sugerencia }) : null]));
    });
    contenedor.appendChild(lista);
  }

  function pintarResultado(r) {
    estado.resultado = r;
    var franja = $("franja");
    franja.className = "franja " + (r.franja.tipo || "neutro");
    $("franja-titulo").textContent = r.franja.titulo || "";
    $("franja-detalle").textContent = r.franja.detalle || "";
    var errores = $("franja-errores");
    vaciar(errores);
    errores.hidden = !(r.franja.errores && r.franja.errores.length);
    (r.franja.errores || []).forEach(function (e) {
      var donde = [e.paso ? "paso " + e.paso : "", e.campo ? "campo " + e.campo : ""].filter(Boolean).join(", ");
      errores.appendChild(el("li", {}, [el("code", { texto: e.codigo || "?" }), donde ? " (" + donde + "): " : ": ", e.mensaje || "",
        e.sugerencia ? el("div", { clase: "secundario", texto: "Sugerencia: " + e.sugerencia }) : null]));
    });

    var contadores = $("contadores");
    vaciar(contadores);
    (r.contadores || []).forEach(function (c) {
      contadores.appendChild(el("div", { clase: "tarjeta contador " + c.tipo }, [
        el("div", { clase: "etiqueta", texto: c.etiqueta }),
        el("div", { clase: "valor", texto: c.valor == null ? "—" : String(c.valor) })
      ]));
    });

    var barra = $("barra");
    var conservacion = $("conservacion");
    vaciar(barra);
    if (r.conservacion && r.conservacion.mostrar) {
      barra.hidden = false;
      barra.setAttribute("aria-label", r.conservacion.frase);
      r.conservacion.partes.forEach(function (p) {
        barra.appendChild(el("span", { clase: p.tipo, style: "width:" + p.porcentaje + "%", title: p.nombre + ": " + p.valor }));
      });
      conservacion.hidden = false;
      conservacion.textContent = r.conservacion.frase;
    } else {
      barra.hidden = true;
      conservacion.hidden = true;
    }

    var pestanas = $("pestanas");
    vaciar(pestanas);
    pestanas.hidden = !(r.pestanas && r.pestanas.length);
    $("panel").hidden = pestanas.hidden;
    if (!pestanas.hidden) {
      var ids = r.pestanas.map(function (p) { return p.id; });
      if (ids.indexOf(estado.pestana) < 0) { estado.pestana = ids[0]; }
      r.pestanas.forEach(function (p) {
        var boton = el("button", { type: "button", clase: "pestana", role: "tab", id: "pestana-" + p.id,
          "aria-selected": p.id === estado.pestana ? "true" : "false", "aria-controls": "panel" }, [
          p.titulo, el("span", { clase: "conteo", texto: String(p.conteo) })]);
        boton.addEventListener("click", function () { estado.pestana = p.id; pintarResultado(estado.resultado); });
        pestanas.appendChild(boton);
      });
      pintarPestana(r.pestanas.filter(function (p) { return p.id === estado.pestana; })[0]);
    }

    var pie = $("pie");
    pie.hidden = !r.pie || !r.pie.carpeta;
    if (!pie.hidden) {
      $("pie-original").textContent = r.pie.original_sin_cambios ? r.pie.frase_original : "";
      $("boton-excel").hidden = !r.pie.excel;
    }
  }

  function pintarPestana(p) {
    var tabla = $("tabla");
    var aviso = $("aviso-tope");
    vaciar(tabla);
    $("panel").setAttribute("aria-labelledby", "pestana-" + p.id);
    aviso.hidden = !p.aviso_tope;
    aviso.textContent = p.aviso_tope || "";
    if (p.id === "incidencias") { return pintarIncidencias(p); }
    if (!p.filas || !p.filas.length) {
      tabla.appendChild(el("caption", { clase: "vacio-panel", texto: "Sin filas en " + p.titulo.toLowerCase() + "." }));
      return;
    }
    var conMotivos = p.apartadas === true;
    var cabecera = el("tr", {});
    if (p.filas[0].fila_original !== undefined) { cabecera.appendChild(el("th", { scope: "col", texto: "Fila original" })); }
    p.columnas.forEach(function (c) { cabecera.appendChild(el("th", { scope: "col", texto: c })); });
    if (conMotivos) { cabecera.appendChild(el("th", { scope: "col", texto: "Motivo" })); }
    tabla.appendChild(el("thead", {}, [cabecera]));
    var cuerpo = el("tbody", {});
    p.filas.forEach(function (f, indice) {
      var fila = el("tr", {});
      if (f.fila_original !== undefined) { fila.appendChild(el("td", { clase: "fila-original", texto: f.fila_original == null ? "—" : String(f.fila_original) })); }
      p.columnas.forEach(function (c) {
        var valor = f.celdas[c];
        var marcada = (f.marcadas || []).indexOf(c) >= 0;
        var celda = el("td", {});
        if (marcada) {
          var motivos = (f.motivos || []).filter(function (m) { return m.columna === c; }).map(function (m) { return m.etiqueta; }).join(", ");
          celda.appendChild(el("strong", { clase: "culpable", texto: valor == null || valor === "" ? "(vacío)" : String(valor), "aria-label": (valor == null ? "vacío" : valor) + ", " + motivos }));
        } else if (valor == null || valor === "") {
          celda.className = "vacio";
          celda.textContent = "—";
        } else {
          celda.textContent = String(valor);
        }
        fila.appendChild(celda);
      });
      if (conMotivos) {
        var tdMotivo = el("td", {});
        (f.motivos || []).forEach(function (m, j) {
          var idExp = "exp-" + p.id + "-" + indice + "-" + j;
          var boton = el("button", { type: "button", clase: "motivo", "aria-expanded": "false", "aria-controls": idExp }, [
            m.etiqueta, el("span", { clase: "flecha", "aria-hidden": "true", texto: "▾" })]);
          var explicacion = el("tr", { clase: "fila-explicacion", id: idExp, hidden: "" }, [
            el("td", { colspan: String(p.columnas.length + 2) }, [el("div", { clase: "explicacion" }, [
              el("div", { clase: "primera", texto: m.que_paso }), el("div", { clase: "segunda", texto: m.que_hacer })])])]);
          boton.addEventListener("click", function () {
            var abierto = boton.getAttribute("aria-expanded") === "true";
            boton.setAttribute("aria-expanded", abierto ? "false" : "true");
            explicacion.hidden = abierto;
          });
          tdMotivo.appendChild(boton);
          fila.explicaciones = (fila.explicaciones || []).concat([explicacion]);
        });
        if (!(f.motivos || []).length && f.motivo_procedencia) { tdMotivo.appendChild(el("span", { clase: "secundario pequeno", texto: f.motivo_procedencia })); }
        fila.appendChild(tdMotivo);
      }
      cuerpo.appendChild(fila);
      (fila.explicaciones || []).forEach(function (x) { cuerpo.appendChild(x); });
    });
    tabla.appendChild(cuerpo);
  }

  function pintarIncidencias(p) {
    var tabla = $("tabla");
    var cuerpo = el("tbody", {});
    if (!p.grupos.length) {
      tabla.appendChild(el("caption", { clase: "vacio-panel", texto: "Sin incidencias." }));
      return;
    }
    p.grupos.forEach(function (g, i) {
      var idExp = "exp-inc-" + i;
      var boton = el("button", { type: "button", clase: "motivo", "aria-expanded": "false", "aria-controls": idExp }, [
        g.etiqueta, el("span", { clase: "flecha", "aria-hidden": "true", texto: "▾" })]);
      var explicacion = el("div", { clase: "explicacion", id: idExp, hidden: "" }, [
        el("div", { clase: "primera", texto: g.que_paso }), el("div", { clase: "segunda", texto: g.que_hacer })]);
      boton.addEventListener("click", function () {
        var abierto = boton.getAttribute("aria-expanded") === "true";
        boton.setAttribute("aria-expanded", abierto ? "false" : "true");
        explicacion.hidden = abierto;
      });
      var filas = g.filas.map(function (f) { return "fila " + (f.fila == null ? "?" : f.fila) + (f.columna ? " · " + f.columna : "") + (f.detalle ? " (" + f.detalle + ")" : ""); }).join("; ");
      if (g.mostradas < g.cantidad) { filas += " … (mostrando " + g.mostradas + " de " + g.cantidad + ")"; }
      var grupo = el("div", { clase: "grupo" }, [
        el("h3", {}, [boton, el("code", { texto: g.codigo }), el("span", { clase: "cantidad", texto: g.cantidad + (g.cantidad === 1 ? " fila" : " filas") + (g.columnas.length ? " · columna " + g.columnas.join(", ") : "") })]),
        explicacion,
        el("div", { clase: "filas", texto: filas })
      ]);
      cuerpo.appendChild(el("tr", {}, [el("td", { style: "padding:0;height:auto" }, [grupo])]));
    });
    tabla.appendChild(cuerpo);
  }

  function abrir(archivo) {
    if (!estado.resultado || !estado.resultado.ejecucion) { return; }
    var cuerpo = { ejecucion: estado.resultado.ejecucion };
    if (archivo) { cuerpo.archivo = archivo; }
    enviar("/api/abrir", cuerpo).catch(function (e) { $("estado-ejecucion").textContent = e.message; });
  }

  // ------------------------------------------------------------------ arranque
  function arrancar() {
    api("/api/estado").then(function (e) {
      $("version").textContent = e.version;
      $("local-texto").textContent = e.local;
      $("aviso-subida").textContent = "La subida guarda una copia dentro de data/interfaz-subidas/ (hasta "
        + bytes(e.limites.subida_bytes) + "). Tu archivo original no se toca.";
    }).catch(function (e) { $("franja-titulo").textContent = e.message; });
    cargarArchivos().catch(function (e) { $("franja-titulo").textContent = e.message; });
    cargarRecetas().catch(function (e) { $("franja-titulo").textContent = e.message; });
    api("/api/resultado").then(pintarResultado).catch(function (e) { $("franja-titulo").textContent = e.message; });

    $("boton-vista").addEventListener("click", vistaPrevia);
    $("boton-ejecutar").addEventListener("click", ejecutar);
    $("boton-carpeta").addEventListener("click", function () { abrir(null); });
    $("boton-excel").addEventListener("click", function () { abrir(estado.resultado.pie.excel); });
    $("entrada-archivo").addEventListener("change", function (ev) { subir(ev.target.files[0]); ev.target.value = ""; });
    var zona = $("zona-subida");
    zona.addEventListener("click", function (ev) { if (ev.target.tagName !== "LABEL") { $("entrada-archivo").click(); } });
    zona.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); $("entrada-archivo").click(); } });
    ["dragenter", "dragover"].forEach(function (n) { zona.addEventListener(n, function (ev) { ev.preventDefault(); zona.classList.add("activa"); }); });
    ["dragleave", "drop"].forEach(function (n) { zona.addEventListener(n, function (ev) { ev.preventDefault(); zona.classList.remove("activa"); }); });
    zona.addEventListener("drop", function (ev) { subir(ev.dataTransfer.files[0]); });
  }

  arrancar();
})();
