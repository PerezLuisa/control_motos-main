// Monitoreo en vivo: enciende la cámara (si hace falta) y consulta su estado cada segundo.
;(() => {
  const raiz = document.getElementById('monitor')
  if (!raiz) return
  const camara = raiz.dataset.camara
  const $ = (id) => document.getElementById(id)
  const video = $('video')

  async function encender() {
    await api(`/api/camaras/${camara}/monitoreo`, { method: 'POST' })
    video.src = `/camaras/${camara}/vivo?t=${Date.now()}` // evita que el navegador reuse un flujo cerrado
  }

  function texto(el, valor) {
    el.textContent = valor
  }

  function pintar(r) {
    const estado = $('estado-camara')
    estado.className = 'estado-camara ' + r.estado
    texto(estado, r.estado === 'CONECTADA' ? 'EN VIVO' : r.error || r.estado)

    const modo = $('modo')
    modo.className = 'etiqueta ' + (r.carga_id ? 'e-EN_CARGA' : 'e-PENDIENTE')
    texto(modo, r.carga_id ? 'MODO CARGA · registrando' : 'MODO MONITOREO · no registra')

    const y = r.yolo || {}
    const yolo = $('yolo-estado')
    yolo.className = 'yolo-estado ' + (y.estado || '')
    texto(yolo, y.estado === 'ACTIVO'
      ? `● Activo en ${y.dispositivo} · ${y.fps} análisis/s · ${y.ms} ms cada uno`
      : y.estado === 'CARGANDO' ? 'Cargando el modelo…' : `○ ${y.detalle || 'No disponible'}`)

    const c = r.contadores || {}
    texto($('k-vistas'), c.motos_vistas ?? 0)
    texto($('k-identificadas'), c.identificadas ?? 0)
    texto($('k-sin'), c.sin_identificar ?? 0)
    texto($('k-qr'), c.qr_leidos ?? 0)

    const panelCarga = $('panel-carga')
    panelCarga.hidden = !r.carga
    if (r.carga) {
      const pct = r.carga.total_motos ? Math.round((r.carga.motos_cargadas / r.carga.total_motos) * 100) : 0
      const enlace = $('carga-enlace')
      enlace.href = `/cargas/${r.carga.id}`
      texto(enlace, r.carga.codigo_contrato)
      $('carga-barra').style.width = pct + '%'
      texto($('carga-texto'), `${r.carga.motos_cargadas} de ${r.carga.total_motos} motos cargadas · faltan ${r.carga.motos_faltantes}`)
    }

    const lista = $('motos-ahora')
    lista.innerHTML = ''
    const motos = r.motos_en_imagen || []
    if (!motos.length) lista.innerHTML = '<li class="suave">Ninguna moto a la vista.</li>'
    for (const m of motos) {
      const li = document.createElement('li')
      li.className = m.identificada ? 'identificada' : ''
      li.innerHTML = '<b></b><span class="suave"></span><span class="etiqueta"></span>'
      texto(li.children[0], `Moto #${m.numero}`)
      texto(li.children[1], `${Math.round(m.confianza * 100)}%`)
      li.children[2].className = 'etiqueta ' + (m.identificada ? 'e-VALIDA' : 'e-NO_PERTENECE')
      texto(li.children[2], m.identificada ? 'Identificada' : 'Esperando QR')
      if (m.qr) li.title = m.qr
      lista.appendChild(li)
    }

    const bitacora = $('bitacora')
    bitacora.innerHTML = ''
    const eventos = r.eventos || []
    if (!eventos.length) bitacora.innerHTML = '<li class="suave">Sin eventos todavía.</li>'
    for (const e of eventos) {
      const li = document.createElement('li')
      li.className = 'ev-' + e.tipo
      li.innerHTML = '<span class="hora"></span><span></span>'
      texto(li.children[0], e.hora)
      texto(li.children[1], e.texto)
      bitacora.appendChild(li)
    }
  }

  async function refrescar() {
    try {
      const { ok, datos } = await api(`/api/camaras/${camara}/monitoreo`)
      if (!ok) return
      if (datos.estado === 'APAGADA') return encender() // se apagó por inactividad o terminó la carga
      pintar(datos)
    } catch (_) {
      /* reintenta en la siguiente vuelta */
    }
  }

  encender().then(refrescar)
  setInterval(refrescar, 1000)
})()
