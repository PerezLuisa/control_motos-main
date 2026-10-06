// Pantalla de una carga en proceso: consulta el estado cada 2 s. Todo lo registra la cámara.
;(() => {
  const raiz = document.getElementById('carga')
  if (!raiz) return
  const id = raiz.dataset.id
  const enCarga = raiz.dataset.estado === 'EN_CARGA'

  const $ = (sel) => document.querySelector(sel)
  const NOMBRES = { VALIDA: 'VÁLIDA', DUPLICADA: 'QR YA USADO', SOBRANTE: 'SOBRANTE', OTRA_CARGA: 'OTRA CARGA', NO_PERTENECE: 'NO PERTENECE' }
  let ultimaLectura = Number(raiz.dataset.ultimaLectura || 0)
  let primera = true

  function pintarResumen(d) {
    $('#n-cargadas').textContent = d.cargadas
    $('#n-faltantes').textContent = d.faltantes
    $('#n-total').textContent = d.total
    const pct = d.total ? Math.round((d.cargadas / d.total) * 100) : 0
    $('#barra-progreso').style.width = pct + '%'
    $('#pct').textContent = pct + '%'

    for (const [motoId, m] of Object.entries(d.motos_cargadas)) {
      const fila = document.querySelector(`tr[data-moto="${motoId}"]`)
      if (fila && !fila.classList.contains('CARGADA')) {
        fila.classList.add('CARGADA')
        if (!primera) fila.classList.add('recien')
        fila.querySelector('.estado').innerHTML = '<span class="etiqueta e-CARGADA">CARGADA</span>'
        fila.querySelector('.hora').textContent = m.hora
        const por = fila.querySelector('.por')
        por.textContent = 'QR ✓'
        if (m.track) por.insertAdjacentHTML('beforeend', ' <span class="etiqueta e-EN_CARGA" title="Confirmada visualmente por YOLO">YOLO ✓</span>')
      }
    }

    const y = d.yolo || {}
    $('#n-yolo').textContent = y.detectadas ?? 0
    $('#n-sin-id').textContent = y.sin_identificar ?? 0
    $('#kpi-sin-id').classList.toggle('rojo', (y.sin_identificar || 0) > 0)
  }

  function pintarLecturas(lecturas) {
    const lista = $('#lista-lecturas')
    if (!lista) return
    lista.innerHTML = lecturas.length
      ? ''
      : '<li class="suave">Aún no hay lecturas.</li>'
    for (const l of lecturas) {
      const li = document.createElement('li')
      const detalle = l.descripcion ? `${l.descripcion} · ${l.articulo}` : l.contenido
      li.innerHTML = `
        <span class="hora"></span>
        <span class="etiqueta e-${l.resultado}"></span>
        <span class="texto mono" title=""></span>
        ${l.evidencia ? `<a class="btn btn-chico" target="_blank" href="${l.evidencia}">Foto</a>` : ''}
        ${l.track_id ? '<span class="suave" style="font-size:.75rem">YOLO</span>' : ''}`
      li.querySelector('.hora').textContent = l.leida_en
      li.querySelector('.etiqueta').textContent = NOMBRES[l.resultado] || l.resultado
      li.querySelector('.texto').textContent = detalle
      li.querySelector('.texto').title = l.contenido
      lista.appendChild(li)
    }

    // Aviso sonoro/visual de lo que leyó la cámara desde la última consulta
    const nuevas = lecturas.filter((l) => l.id > ultimaLectura)
    if (lecturas.length) ultimaLectura = Math.max(ultimaLectura, lecturas[0].id)
    if (!primera && nuevas.length) {
      const peor = nuevas.find((l) => ['OTRA_CARGA', 'SOBRANTE', 'NO_PERTENECE', 'DUPLICADA'].includes(l.resultado))
      const l = peor || nuevas[0]
      const textos = {
        VALIDA: `✔ Cargada: ${l.descripcion || ''} · ${l.articulo || ''}`,
        DUPLICADA: `⚠ QR ya usado y moto ya cargada en el camión${l.descripcion ? ': ' + l.descripcion : ''}`,
        OTRA_CARGA: '✖ ¡NO SUBIR! Esta moto pertenece a otra carga',
        SOBRANTE: '✖ ¡SOBRA UNA MOTO! Ya se cargaron todas las unidades de esa referencia',
        NO_PERTENECE: '✖ QR desconocido: no es de esta carga',
      }
      mostrarResultado(l.resultado, `Cámara — ${textos[l.resultado] || l.resultado}`)
    }
  }

  function pintarCamara(c) {
    const el = $('#estado-camara')
    if (!el || !c) return
    el.className = 'estado-camara ' + c.estado
    const yolo = c.yolo && c.yolo.estado === 'ACTIVO' ? ` · YOLO ${c.yolo.dispositivo}` : ''
    el.textContent = c.estado === 'CONECTADA' ? `EN VIVO · QR${yolo}` : c.error || c.estado
  }

  async function refrescar() {
    try {
      const { ok, datos } = await api(`/api/cargas/${id}/estado`)
      if (!ok) return
      if (datos.estado !== raiz.dataset.estado) return window.location.reload()
      pintarResumen(datos)
      pintarLecturas(datos.lecturas)
      pintarCamara(datos.camara)
      primera = false
    } catch (_) {
      /* reintenta en la siguiente vuelta */
    }
  }

  // -- resultado grande para el operador ---------------------------------
  let temporizador
  function mostrarResultado(tipo, texto) {
    const el = $('#resultado')
    if (!el) return
    el.className = `resultado visible ${tipo}`
    el.textContent = texto
    ;(tipo === 'VALIDA' ? Sonido.ok : tipo === 'DUPLICADA' ? Sonido.aviso : Sonido.error)()
    clearTimeout(temporizador)
    temporizador = setTimeout(() => el.classList.remove('visible'), 6000)
  }


  // -- filtro de la tabla de motos --------------------------------------
  const buscar = $('#buscar-moto')
  const filtro = $('#filtro-moto')
  function filtrar() {
    const q = (buscar.value || '').trim().toUpperCase()
    const f = filtro.value
    document.querySelectorAll('tr[data-moto]').forEach((tr) => {
      const coincide = !q || tr.textContent.toUpperCase().includes(q)
      const estado = tr.classList.contains('CARGADA') ? 'CARGADA' : 'PENDIENTE'
      tr.hidden = !(coincide && (!f || f === estado))
    })
  }
  buscar?.addEventListener('input', filtrar)
  filtro?.addEventListener('change', filtrar)

  // -- confirmar finalización mostrando cuántas faltan ------------------
  $('#form-finalizar')?.addEventListener('submit', (e) => {
    const faltan = Number($('#n-faltantes').textContent)
    const msg = faltan
      ? `ATENCIÓN: faltan ${faltan} motos por subir.\n\nSi finaliza ahora la carga quedará INCOMPLETA y se enviará una alerta al administrador.\n\n¿Finalizar de todas formas?`
      : '¿Finalizar la carga? Todas las motos están verificadas.'
    if (!confirm(msg)) e.preventDefault()
  })

  refrescar()
  if (enCarga) setInterval(refrescar, 2000)
})()
