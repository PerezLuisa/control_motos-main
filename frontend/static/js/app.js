// Utilidades comunes: petición con CSRF y "latido" que mantiene viva la sesión.
const CSRF = document.querySelector('meta[name="csrf-token"]')?.content || ''

async function api(url, opciones = {}) {
  const resp = await fetch(url, {
    ...opciones,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF, ...(opciones.headers || {}) },
  })
  if (resp.status === 401) {
    // La sesión se cerró (expiró, la cerró el administrador o se abrió en otro lado)
    window.location.href = '/login'
    throw new Error('sesion')
  }
  const datos = await resp.json().catch(() => ({}))
  return { ok: resp.ok, status: resp.status, datos }
}

function actualizarContadorAlertas(n) {
  const el = document.getElementById('contador-alertas')
  if (el) {
    el.textContent = n > 0 ? n : ''
    el.dataset.n = n
  }
}

async function latido() {
  try {
    const { datos } = await api('/api/latido', { method: 'POST' })
    actualizarContadorAlertas(datos.alertas_pendientes || 0)
  } catch (_) {
    /* sin conexión: se reintenta en el siguiente latido */
  }
}

if (document.body.dataset.sesion === '1') {
  latido()
  setInterval(latido, 30000)
}

// Formularios que piden confirmación: <form data-confirmar="¿Seguro?">
document.addEventListener('submit', (e) => {
  const msg = e.target.dataset.confirmar
  if (msg && !confirm(msg)) e.preventDefault()
})

// Sonidos cortos para el operador (sin archivos de audio)
const Sonido = (() => {
  let ctx
  function tono(frec, dur, inicio = 0, tipo = 'sine') {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)()
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    o.type = tipo
    o.frequency.value = frec
    g.gain.setValueAtTime(0.15, ctx.currentTime + inicio)
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + inicio + dur)
    o.connect(g).connect(ctx.destination)
    o.start(ctx.currentTime + inicio)
    o.stop(ctx.currentTime + inicio + dur)
  }
  return {
    ok: () => { tono(880, 0.12); tono(1320, 0.18, 0.12) },
    error: () => { tono(300, 0.25, 0, 'square'); tono(300, 0.25, 0.3, 'square') },
    aviso: () => { tono(660, 0.15); tono(660, 0.15, 0.2) },
  }
})()
